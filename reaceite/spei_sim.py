"""Pasarela de pagos simulada: se comporta como el sandbox de un proveedor de pagos con SPEI.

POST /sim-spei/v1/transferencias  (Bearer API key + Idempotency-Key)
  -> 202 Accepted con folio y clave de rastreo. El monto se carga en ese momento a la cuenta
     de origen (el Fondo de Garantía de Dispersión de ReAceite); si no alcanza, 409 fondos_insuficientes.
Después de SPEI_DEMORA_S segundos la orden se liquida: el monto se abona a la cuenta destino
(la billetera del comercio, ligada a su celular) y el banco envía un webhook firmado
(HMAC-SHA256) a la URL indicada en la orden, con reintentos y retroceso exponencial.

POST /sim-spei/v1/cuentas                      alta de una billetera (idempotente por CLABE)
GET  /sim-spei/v1/cuentas/<clabe>              saldo de una cuenta
GET  /sim-spei/v1/cuentas/<clabe>/movimientos  últimos movimientos

Todo es simulado: ningún peso real se mueve y todas las CLABE son del banco ficticio 999.
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

# Cuentas propias de la operación (CLABE simuladas del banco 999).
FONDO_CLABE = clabe_mod.simulada(90_000_000_001)
PLANTA_CLABE = clabe_mod.simulada(80_000_000_001)


class SaldoInsuficiente(Exception):
    pass


def _error(http, codigo, mensaje):
    return jsonify({"error": codigo, "mensaje": mensaje}), http


def _autorizado():
    esperado = f"Bearer {current_app.config['SPEI_API_KEY']}".encode()
    return hmac.compare_digest(request.headers.get("Authorization", "").encode(), esperado)


# ---------------------------------------------------------------- cuentas y movimientos
def cuenta_por_clabe(conn, clabe):
    return conn.execute("SELECT * FROM cuenta WHERE clabe = ?", (clabe,)).fetchone()


def asegurar_cuenta(conn, clabe, titular, tipo, celular=None, creado=None):
    fila = cuenta_por_clabe(conn, clabe)
    if fila is None:
        conn.execute(
            "INSERT INTO cuenta(clabe, titular, tipo, celular, saldo_cent, creado) VALUES (?, ?, ?, ?, 0, ?)",
            (clabe, titular[:60], tipo, celular, creado or ahora_iso()),
        )
        fila = cuenta_por_clabe(conn, clabe)
    return fila


def mover(conn, cuenta_id, tipo, monto_cent, concepto, referencia=None, orden=None, creado=None):
    """Abono o cargo con saldo resultante. Un cargo sin saldo suficiente lanza SaldoInsuficiente."""
    monto_cent = int(monto_cent)
    if monto_cent <= 0:
        raise ValueError("monto")
    saldo = conn.execute("SELECT saldo_cent FROM cuenta WHERE id = ?", (cuenta_id,)).fetchone()[0]
    nuevo = saldo + monto_cent if tipo == "ABONO" else saldo - monto_cent
    if nuevo < 0:
        raise SaldoInsuficiente(saldo)
    conn.execute("UPDATE cuenta SET saldo_cent = ? WHERE id = ?", (nuevo, cuenta_id))
    conn.execute(
        "INSERT INTO movimiento(cuenta_id, tipo, monto_cent, saldo_cent, concepto, referencia, orden, creado) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (cuenta_id, tipo, monto_cent, nuevo, concepto[:120], referencia, orden, creado or ahora_iso()),
    )
    return nuevo


def transferencia_interna(conn, clabe_origen, clabe_destino, monto_cent, concepto, referencia, creado=None):
    """Movimiento entre dos cuentas del mismo banco simulado (se aplica al instante, sin SPEI)."""
    origen = cuenta_por_clabe(conn, clabe_origen)
    destino = cuenta_por_clabe(conn, clabe_destino)
    mover(conn, origen["id"], "CARGO", monto_cent, concepto, referencia, creado=creado)
    return mover(conn, destino["id"], "ABONO", monto_cent, concepto, referencia, creado=creado)


def _cuenta_json(fila):
    return {
        "clabe": fila["clabe"],
        "titular": fila["titular"],
        "tipo": fila["tipo"],
        "celular": fila["celular"],
        "saldo": pesos(fila["saldo_cent"]),
        "moneda": "MXN",
        "consultado": local(ahora_iso()).isoformat(timespec="seconds"),
    }


@bp.post("/v1/cuentas")
def abrir_cuenta():
    """Alta de una billetera ligada a un celular. Idempotente: la misma CLABE devuelve la cuenta existente."""
    if not _autorizado():
        return _error(401, "no_autorizado", "API key inválida o ausente")
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return _error(400, "json_invalido", "El cuerpo debe ser un objeto JSON")
    clabe = str(datos.get("clabe") or "")
    if not clabe_mod.es_valida(clabe):
        return _error(422, "clabe_invalida", "La CLABE no es válida: el dígito de control no coincide")
    celular = str(datos.get("celular") or "")
    if celular and not (celular.isdigit() and len(celular) == 10):
        return _error(422, "celular_invalido", "El celular debe tener 10 dígitos")
    conn = conectar(current_app.config["DB_PATH"])
    try:
        with transaccion(conn):
            previa = cuenta_por_clabe(conn, clabe)
            if previa is not None:
                if celular and not previa["celular"]:
                    conn.execute("UPDATE cuenta SET celular = ? WHERE id = ?", (celular, previa["id"]))
                return jsonify(_cuenta_json(cuenta_por_clabe(conn, clabe))), 200
            fila = asegurar_cuenta(conn, clabe, str(datos.get("titular") or "Billetera")[:60], "BILLETERA",
                                   celular or None)
            eventos.registrar(conn, "banco.billetera_abierta",
                              f"Pasarela simulada: billetera {clabe_mod.enmascarar(clabe)} abierta para "
                              f"{fila['titular']}", ref=str(datos.get("referencia") or "")[:40] or None)
            return jsonify(_cuenta_json(fila)), 201
    finally:
        conn.close()


@bp.get("/v1/cuentas/<clabe>")
def consultar_cuenta(clabe):
    if not _autorizado():
        return _error(401, "no_autorizado", "API key inválida o ausente")
    conn = conectar(current_app.config["DB_PATH"])
    try:
        fila = cuenta_por_clabe(conn, clabe)
        if fila is None:
            return _error(404, "cuenta_desconocida", "No existe una cuenta con esa CLABE")
        return jsonify(_cuenta_json(fila))
    finally:
        conn.close()


@bp.get("/v1/cuentas/<clabe>/movimientos")
def consultar_movimientos(clabe):
    if not _autorizado():
        return _error(401, "no_autorizado", "API key inválida o ausente")
    try:
        limite = max(1, min(50, int(request.args.get("limite", "10"))))
    except ValueError:
        limite = 10
    conn = conectar(current_app.config["DB_PATH"])
    try:
        fila = cuenta_por_clabe(conn, clabe)
        if fila is None:
            return _error(404, "cuenta_desconocida", "No existe una cuenta con esa CLABE")
        movimientos = [
            {"tipo": m["tipo"], "monto": pesos(m["monto_cent"]), "saldo": pesos(m["saldo_cent"]),
             "concepto": m["concepto"], "referencia": m["referencia"], "orden": m["orden"],
             "fecha": local(m["creado"]).isoformat(timespec="seconds")}
            for m in conn.execute("SELECT * FROM movimiento WHERE cuenta_id = ? ORDER BY id DESC LIMIT ?",
                                  (fila["id"], limite))
        ]
        return jsonify({"clabe": clabe, "saldo": pesos(fila["saldo_cent"]), "movimientos": movimientos})
    finally:
        conn.close()


# ---------------------------------------------------------------- transferencias SPEI
@bp.post("/v1/transferencias")
def crear_transferencia():
    cfg = current_app.config
    if not _autorizado():
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
            # El monto sale del Fondo de Garantía de Dispersión en el momento en que se acepta la orden.
            fondo = cuenta_por_clabe(conn, FONDO_CLABE)
            beneficiario = str(datos.get("beneficiario") or "")[:60]
            try:
                if fondo is None:
                    raise SaldoInsuficiente(0)
                saldo_fondo = mover(conn, fondo["id"], "CARGO", int(monto * 100),
                                    f"SPEI enviado a {beneficiario or clabe_mod.enmascarar(clabe)}", referencia, folio)
            except SaldoInsuficiente as e:
                disponible = pesos(e.args[0] if e.args else 0)
                return _error(409, "fondos_insuficientes",
                              f"Saldo insuficiente en la cuenta de origen: disponible ${disponible}, orden ${monto}")
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
                 beneficiario, referencia, str(datos.get("concepto") or "")[:120],
                 webhook_url, ahora_iso(cfg["SPEI_DEMORA_S"]), json.dumps(cuerpo), ahora),
            )
            conn.execute("UPDATE spei_orden SET clabe_origen = ? WHERE id = ?", (FONDO_CLABE, numero))
            eventos.registrar(
                conn, "banco.orden_recibida",
                f"Pasarela simulada: orden {folio} por ${monto} aceptada y cargada al Fondo de Garantía "
                f"(saldo ${saldo_fondo / 100:,.2f}); se liquida en {cfg['SPEI_DEMORA_S']:g} s",
                ref=referencia, detalle={**cuerpo, "saldo_fondo": pesos(saldo_fondo)},
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
            "SELECT id, folio, referencia, monto_cent, clabe, beneficiario, concepto FROM spei_orden "
            "WHERE estatus = 'RECIBIDA' AND liquidar_en <= ?", (ahora,)).fetchall():
        with transaccion(conn):
            cur = conn.execute(
                "UPDATE spei_orden SET estatus = 'LIQUIDADA', liquidado = ?, webhook_estado = 'PENDIENTE', "
                "webhook_proximo = ? WHERE id = ? AND estatus = 'RECIBIDA'",
                (ahora_iso(), ahora_iso(), fila["id"]),
            )
            if cur.rowcount:
                # El dinero llega a la billetera del comercio (se abre sola si aún no existía).
                destino = asegurar_cuenta(conn, fila["clabe"], fila["beneficiario"] or "Billetera", "BILLETERA")
                saldo = mover(conn, destino["id"], "ABONO", fila["monto_cent"],
                              fila["concepto"] or "SPEI recibido", fila["referencia"], fila["folio"])
                eventos.registrar(
                    conn, "banco.liquidada",
                    f"Pasarela simulada: {fila['folio']} liquidada; ${pesos(fila['monto_cent'])} abonados a la "
                    f"billetera {clabe_mod.enmascarar(fila['clabe'])} (saldo ${saldo / 100:,.2f}); enviando webhook",
                    ref=fila["referencia"],
                    detalle={"billetera": clabe_mod.enmascarar(fila["clabe"]), "abono": pesos(fila["monto_cent"]),
                             "saldo_nuevo": pesos(saldo)},
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
                    f"Pasarela simulada: webhook de {fila['folio']} entregado ({status}) en {ms:.0f} ms",
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
                    f"Pasarela simulada: el webhook de {fila['folio']} falló ({motivo}); "
                    + ("se abandonó tras 6 intentos" if final else f"reintento {intentos + 1} en {espera} s"),
                    ref=fila["referencia"],
                )
    return hechas


def hay_pendientes(conn):
    return conn.execute(
        "SELECT EXISTS(SELECT 1 FROM spei_orden WHERE estatus = 'RECIBIDA' OR webhook_estado = 'PENDIENTE')"
    ).fetchone()[0] == 1
