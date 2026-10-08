"""API SPEI simulada: se comporta como el sandbox de un proveedor de pagos.

POST /sim-spei/v1/transferencias  (Bearer API key + Idempotency-Key)
  -> 202 Accepted con folio y clave de rastreo.
Después de SPEI_DEMORA_S segundos la orden se liquida y el banco envía un webhook firmado
(HMAC-SHA256) a la URL indicada en la orden, con reintentos y retroceso exponencial.
"""
import hashlib
import hmac
import json
import secrets
import uuid
from decimal import Decimal, InvalidOperation

from flask import Blueprint, current_app, jsonify, request

from . import clabe as clabe_mod
from . import eventos, transporte
from .db import ahora_iso, conectar, local, siguiente_numero, transaccion
from .firma import firmar
from .metricas import pesos

bp = Blueprint("spei", __name__, url_prefix="/sim-spei")

MONTO_MAXIMO = Decimal("50000")
MAX_INTENTOS = 6


def _error(http, codigo, mensaje):
    return jsonify({"error": codigo, "mensaje": mensaje}), http


@bp.post("/v1/transferencias")
def crear_transferencia():
    cfg = current_app.config
    esperado = f"Bearer {cfg['SPEI_API_KEY']}".encode()
    if not hmac.compare_digest(request.headers.get("Authorization", "").encode(), esperado):
        return _error(401, "no_autorizado", "API key inválida o ausente")
    idem = request.headers.get("Idempotency-Key", "").strip()
    if not idem or len(idem) > 80:
        return _error(400, "falta_idempotencia", "Falta la cabecera Idempotency-Key")
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return _error(400, "json_invalido", "El cuerpo debe ser un objeto JSON")
    try:
        monto = Decimal(str(datos.get("monto"))).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return _error(422, "monto_invalido", "El monto no es un número")
    if not monto.is_finite() or monto <= 0 or monto > MONTO_MAXIMO:
        return _error(422, "monto_invalido", "El monto debe ser mayor que 0 y menor que 50,000 MXN")
    clabe = str(datos.get("clabe_destino") or "")
    if not clabe_mod.es_valida(clabe):
        return _error(422, "clabe_invalida", "La CLABE no es válida: el dígito de control no coincide")
    referencia = str(datos.get("referencia") or "")[:40]
    if not referencia:
        return _error(422, "referencia", "Falta la referencia")
    webhook_url = str(datos.get("webhook_url") or "")
    if not webhook_url.startswith(("http://", "https://")):
        return _error(422, "webhook_url", "Falta una webhook_url http(s)")

    huella = hashlib.sha256(
        json.dumps({"monto": str(monto), "clabe": clabe, "referencia": referencia}, sort_keys=True).encode()
    ).hexdigest()
    conn = conectar(cfg["DB_PATH"])
    try:
        with transaccion(conn):
            previa = conn.execute("SELECT * FROM spei_orden WHERE idempotency_key = ?", (idem,)).fetchone()
            if previa is not None:
                if previa["huella"] != huella:
                    return _error(409, "idempotencia_conflicto", "La llave ya se usó con otros datos")
                respuesta = jsonify(json.loads(previa["respuesta"]))
                respuesta.status_code = 200
                respuesta.headers["Idempotent-Replayed"] = "true"
                return respuesta
            ahora = ahora_iso()
            numero = siguiente_numero(conn, "spei_orden")
            hora = local(ahora)
            folio = f"SIM{hora:%y%m%d}{numero:06d}"
            clave = f"RAC{hora:%Y%m%d%H%M%S}{secrets.randbelow(10000):04d}"
            cuerpo = {
                "folio": folio,
                "clave_rastreo": clave,
                "estatus": "RECIBIDA",
                "monto": str(monto),
                "moneda": "MXN",
                "recibida": hora.isoformat(timespec="seconds"),
            }
            conn.execute(
                "INSERT INTO spei_orden(id, idempotency_key, huella, folio, clave_rastreo, monto_cent, clabe, "
                "beneficiario, referencia, concepto, webhook_url, estatus, liquidar_en, respuesta, creado) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'RECIBIDA', ?, ?, ?)",
                (numero, idem, huella, folio, clave, int(monto * 100), clabe,
                 str(datos.get("beneficiario") or "")[:60], referencia, str(datos.get("concepto") or "")[:120],
                 webhook_url, ahora_iso(cfg["SPEI_DEMORA_S"]), json.dumps(cuerpo), ahora),
            )
            eventos.registrar(
                conn, "banco.orden_recibida",
                f"Banco simulado: orden {folio} por ${monto} aceptada; se liquida en {cfg['SPEI_DEMORA_S']:g} s",
                ref=referencia, detalle=cuerpo,
            )
    finally:
        conn.close()
    despachador = current_app.extensions.get("despachador")
    if despachador:
        despachador.despertar()
    return jsonify(cuerpo), 202


def procesar(app, conn):
    """Liquida las órdenes vencidas y entrega sus webhooks. Devuelve cuántas acciones hizo."""
    cfg = app.config
    hechas = 0
    ahora = ahora_iso()
    for fila in conn.execute(
            "SELECT id, folio, referencia, monto_cent FROM spei_orden WHERE estatus = 'RECIBIDA' AND liquidar_en <= ?",
            (ahora,)).fetchall():
        with transaccion(conn):
            cur = conn.execute(
                "UPDATE spei_orden SET estatus = 'LIQUIDADA', liquidado = ?, webhook_estado = 'PENDIENTE', "
                "webhook_proximo = ? WHERE id = ? AND estatus = 'RECIBIDA'",
                (ahora_iso(), ahora_iso(), fila["id"]),
            )
            if cur.rowcount:
                eventos.registrar(
                    conn, "banco.liquidada",
                    f"Banco simulado: {fila['folio']} liquidada por ${pesos(fila['monto_cent'])}; enviando webhook",
                    ref=fila["referencia"],
                )
        hechas += 1

    for fila in conn.execute(
            "SELECT * FROM spei_orden WHERE webhook_estado = 'PENDIENTE' AND webhook_proximo <= ?",
            (ahora_iso(),)).fetchall():
        cur = conn.execute(
            "UPDATE spei_orden SET webhook_estado = 'PROCESANDO' WHERE id = ? AND webhook_estado = 'PENDIENTE'",
            (fila["id"],),
        )
        if not cur.rowcount:
            continue
        hechas += 1
        cuerpo = json.dumps({
            "evento": "transferencia.liquidada",
            "folio": fila["folio"],
            "clave_rastreo": fila["clave_rastreo"],
            "referencia": fila["referencia"],
            "monto": pesos(fila["monto_cent"]),
            "moneda": "MXN",
            "clabe_destino": fila["clabe"],
            "fecha_liquidacion": local(fila["liquidado"]).isoformat(timespec="seconds"),
        }, ensure_ascii=False).encode()
        cabeceras = {
            "Content-Type": "application/json",
            "User-Agent": "SPEI-Simulado/1.0",
            "X-Spei-Evento": "transferencia.liquidada",
            "X-Spei-Entrega": uuid.uuid4().hex,
            "X-Spei-Firma": firmar(cfg["WEBHOOK_SECRET"], cuerpo),
        }
        try:
            r = transporte.enviar(app, "POST", fila["webhook_url"], cuerpo, cabeceras)
            status, ms, motivo = r.status, r.ms, f"HTTP {r.status}"
        except Exception as e:  # red caída, DNS, tiempo agotado
            status, ms, motivo = None, 0.0, f"{type(e).__name__}"
        intentos = fila["webhook_intentos"] + 1
        with transaccion(conn):
            if status is not None and 200 <= status < 300:
                conn.execute(
                    "UPDATE spei_orden SET webhook_estado = 'ENTREGADO', webhook_http = ?, webhook_intentos = ? "
                    "WHERE id = ?", (status, intentos, fila["id"]))
                eventos.registrar(
                    conn, "banco.webhook_entregado",
                    f"Banco simulado: webhook de {fila['folio']} entregado ({status}) en {ms:.0f} ms",
                    ref=fila["referencia"],
                )
            else:
                final = intentos >= MAX_INTENTOS
                espera = min(60, 2 ** intentos)
                conn.execute(
                    "UPDATE spei_orden SET webhook_estado = ?, webhook_http = ?, webhook_intentos = ?, "
                    "webhook_proximo = ? WHERE id = ?",
                    ("FALLIDO" if final else "PENDIENTE", status, intentos, ahora_iso(espera), fila["id"]))
                eventos.registrar(
                    conn, "banco.webhook_fallido",
                    f"Banco simulado: el webhook de {fila['folio']} falló ({motivo}); "
                    + ("se abandonó tras 6 intentos" if final else f"reintento {intentos + 1} en {espera} s"),
                    ref=fila["referencia"],
                )
    return hechas


def hay_pendientes(conn):
    return conn.execute(
        "SELECT EXISTS(SELECT 1 FROM spei_orden WHERE estatus = 'RECIBIDA' OR webhook_estado = 'PENDIENTE')"
    ).fetchone()[0] == 1
