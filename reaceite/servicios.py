"""Reglas de negocio de ReAceite CDMX.

Cada función recibe una conexión dentro de una transacción abierta por quien la llama,
así que todos los cambios de un mismo paso se guardan juntos o no se guarda ninguno.
"""
import hashlib
import json
import re
import secrets
from datetime import timedelta
from decimal import Decimal

from . import clabe as clabe_mod
from . import eventos, metricas, rutas
from .config import FRANJAS, LITROS_OPCIONES, PARAMETROS, TIPOS_COMERCIO, TZ, ZONAS
from .db import ahora_iso, ahora_utc, iso, parse_iso, siguiente_numero

ALFABETO = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CDMX_LAT = (19.0, 19.8)
CDMX_LON = (-99.5, -98.8)


class ErrorNegocio(Exception):
    def __init__(self, mensaje, codigo="invalido", http=400, extra=None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo
        self.http = http
        self.extra = extra or {}


# ---------------------------------------------------------------- utilidades
def token_aleatorio(n=8):
    return "".join(secrets.choice(ALFABETO) for _ in range(n))


def token_semilla(codigo):
    """Token fijo para los comercios de demostración: sus QR impresos siguen sirviendo tras reiniciar."""
    h = hashlib.sha256(f"reaceite-demo:{codigo}".encode()).digest()
    return "".join(ALFABETO[b % len(ALFABETO)] for b in h[:8])


def _texto(valor, minimo, maximo, campo):
    texto = re.sub(r"\s+", " ", str(valor or "")).strip()
    if len(texto) < minimo:
        raise ErrorNegocio(f"Escribe {campo}.", codigo="campo_vacio")
    if len(texto) > maximo:
        raise ErrorNegocio(f"El campo {campo} admite hasta {maximo} caracteres.")
    return texto


def _anio_local():
    return ahora_utc().astimezone(TZ).year


def comercio_por_token(conn, token):
    token = (token or "").strip().upper()
    if not re.fullmatch(r"[0-9A-Z]{6,12}", token):
        return None
    return conn.execute("SELECT * FROM comercio WHERE token = ?", (token,)).fetchone()


def solicitud_abierta(conn, comercio_id):
    return conn.execute(
        "SELECT * FROM solicitud WHERE comercio_id = ? AND estado IN ('PENDIENTE', 'EN_RUTA') "
        "ORDER BY creado, id LIMIT 1",
        (comercio_id,),
    ).fetchone()


# ---------------------------------------------------------------- comercios
def crear_comercio(conn, datos, demo=False, token=None, creado=None):
    nombre = _texto(datos.get("nombre"), 2, 60, "el nombre del negocio")
    tipo = datos.get("tipo")
    if tipo not in TIPOS_COMERCIO:
        raise ErrorNegocio("Elige el tipo de negocio.")
    telefono = re.sub(r"\D", "", str(datos.get("telefono") or ""))
    if telefono and len(telefono) != 10:
        raise ErrorNegocio("El teléfono debe tener 10 dígitos.")
    direccion = _texto(datos.get("direccion"), 4, 120, "la dirección (calle y número)")
    franja = datos.get("franja") or "10-12"
    if franja not in FRANJAS:
        raise ErrorNegocio("Elige un horario válido.")

    zona = datos.get("zona") or None
    lat, lon = datos.get("lat"), datos.get("lon")
    if lat not in (None, "") and lon not in (None, ""):
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            raise ErrorNegocio("La ubicación no es válida.") from None
        if not (CDMX_LAT[0] <= lat <= CDMX_LAT[1] and CDMX_LON[0] <= lon <= CDMX_LON[1]):
            raise ErrorNegocio("La ubicación debe estar en la Ciudad de México.")
        zona = zona or rutas.zona_mas_cercana(lat, lon)
    else:
        if zona not in ZONAS:
            raise ErrorNegocio("Comparte tu ubicación o elige tu colonia.")
        # Sin GPS: punto cercano al centro de la colonia (se puede corregir después).
        lat = ZONAS[zona]["lat"] + (secrets.randbelow(2001) - 1000) / 1_000_000
        lon = ZONAS[zona]["lon"] + (secrets.randbelow(2001) - 1000) / 1_000_000
    if zona not in ZONAS:
        raise ErrorNegocio("Elige una colonia del piloto.")

    numero = siguiente_numero(conn, "comercio")
    codigo = f"COM-{numero:04d}"
    if token is None:
        token = token_aleatorio()
        while conn.execute("SELECT 1 FROM comercio WHERE token = ?", (token,)).fetchone():
            token = token_aleatorio()
    clabe = clabe_mod.simulada(numero)
    creado = creado or ahora_iso()
    conn.execute(
        "INSERT INTO comercio(id, codigo, token, nombre, tipo, telefono, direccion, zona, franja, lat, lon, "
        "clabe, demo, creado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (numero, codigo, token, nombre, tipo, telefono or None, direccion, zona, franja, round(lat, 6),
         round(lon, 6), clabe, 1 if demo else 0, creado),
    )
    if not demo:
        eventos.registrar(
            conn, "comercio.registrado",
            f"Nuevo comercio {codigo}: {nombre}, {tipo.lower()} en {ZONAS[zona]['nombre']}",
            ref=codigo,
            detalle={"codigo": codigo, "zona": zona, "lat": round(lat, 6), "lon": round(lon, 6),
                     "clabe": clabe_mod.enmascarar(clabe)},
        )
    return conn.execute("SELECT * FROM comercio WHERE id = ?", (numero,)).fetchone()


# ---------------------------------------------------------------- zonas y rutas
def estado_zona(conn, zona):
    fila = conn.execute(
        "SELECT COALESCE(SUM(litros_estimados), 0) AS litros, COUNT(*) AS n, MIN(creado) AS antigua "
        "FROM solicitud WHERE zona = ? AND estado = 'PENDIENTE'",
        (zona,),
    ).fetchone()
    en_ruta = conn.execute(
        "SELECT COALESCE(SUM(litros_estimados), 0) FROM solicitud WHERE zona = ? AND estado = 'EN_RUTA'", (zona,)
    ).fetchone()[0]
    return {
        "zona": zona,
        "nombre": ZONAS[zona]["nombre"],
        "litros_pendientes": fila["litros"],
        "solicitudes_pendientes": fila["n"],
        "mas_antigua": fila["antigua"],
        "litros_en_ruta": en_ruta,
        "tope": PARAMETROS["tope_ruta_litros"],
    }


def generar_ruta(conn, zona, motivo):
    filas = conn.execute(
        "SELECT s.id, s.folio, s.litros_estimados, s.creado, c.codigo, c.nombre, c.direccion, c.lat, c.lon "
        "FROM solicitud s JOIN comercio c ON c.id = s.comercio_id "
        "WHERE s.zona = ? AND s.estado = 'PENDIENTE' ORDER BY s.creado, s.id",
        (zona,),
    ).fetchall()
    if not filas:
        return None
    paradas = [dict(f) for f in filas]
    plan = rutas.planear(paradas)
    numero = siguiente_numero(conn, "ruta")
    folio = f"RUT-{numero:04d}"
    litros = sum(p["litros_estimados"] for p in paradas)
    ahora = ahora_iso()
    orden_ids = [p["id"] for p in plan["orden"]]
    conn.execute(
        "INSERT INTO ruta(id, folio, zona, motivo, orden, distancia_m, distancia_base_m, duracion_s, "
        "litros_estimados, algoritmo, calculo_ms, url_maps, estado, creado) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVA', ?)",
        (numero, folio, zona, motivo, json.dumps(orden_ids), plan["distancia_m"], plan["distancia_base_m"],
         plan["duracion_s"], litros, plan["algoritmo"], plan["calculo_ms"], plan["url_maps"], ahora),
    )
    conn.executemany(
        "UPDATE solicitud SET estado = 'EN_RUTA', ruta_id = ?, actualizado = ? WHERE id = ?",
        [(numero, ahora, sid) for sid in orden_ids],
    )
    nombre_zona = ZONAS[zona]["nombre"]
    tope = PARAMETROS["tope_ruta_litros"]
    if motivo == "umbral":
        eventos.registrar(
            conn, "zona.umbral_alcanzado",
            f"{nombre_zona} llegó a {litros} L con {len(paradas)} solicitudes (tope: {tope} L)",
            ref=folio, detalle={"zona": zona, "litros": litros, "tope": tope},
        )
    elif motivo == "espera":
        eventos.registrar(
            conn, "zona.espera_maxima",
            f"{nombre_zona} tiene solicitudes con más de {PARAMETROS['espera_maxima_horas']} h de espera: "
            f"la ruta sale con {litros} L",
            ref=folio, detalle={"zona": zona, "litros": litros},
        )
    ahorro = 0.0
    if plan["distancia_base_m"]:
        ahorro = max(0.0, 1 - plan["distancia_m"] / plan["distancia_base_m"]) * 100
    eventos.registrar(
        conn, "ruta.generada",
        f"{folio}: {len(paradas)} paradas, {plan['distancia_m'] / 1000:.1f} km, "
        f"{plan['duracion_s'] // 60} min; orden óptimo calculado en {plan['calculo_ms']:.2f} ms",
        ref=folio,
        detalle={
            "algoritmo": plan["algoritmo"],
            "orden": [f"{p['codigo']} {p['nombre']}" for p in plan["orden"]],
            "distancia_km": round(plan["distancia_m"] / 1000, 2),
            "distancia_orden_de_llegada_km": round(plan["distancia_base_m"] / 1000, 2),
            "ahorro_pct": round(ahorro, 1),
            "url_maps": plan["url_maps"],
        },
    )
    return conn.execute("SELECT * FROM ruta WHERE id = ?", (numero,)).fetchone()


def revisar_esperas(conn):
    """Regla de antigüedad: ninguna solicitud espera más de 48 h aunque su zona no llegue al tope."""
    limite = iso(ahora_utc() - timedelta(hours=PARAMETROS["espera_maxima_horas"]))
    zonas = [f["zona"] for f in conn.execute(
        "SELECT DISTINCT zona FROM solicitud WHERE estado = 'PENDIENTE' AND creado <= ?", (limite,))]
    return [generar_ruta(conn, z, "espera") for z in zonas]


# ---------------------------------------------------------------- solicitudes
def crear_solicitud(conn, comercio, litros, franja, creado=None):
    try:
        litros = int(litros)
    except (TypeError, ValueError):
        litros = 0
    if litros not in LITROS_OPCIONES:
        raise ErrorNegocio("Elige 5, 10 o 20 litros.")
    if franja not in FRANJAS:
        raise ErrorNegocio("Elige a qué hora podemos pasar.")
    abierta = solicitud_abierta(conn, comercio["id"])
    if abierta:
        raise ErrorNegocio(
            f"Ya tienes la solicitud {abierta['folio']} abierta.", codigo="solicitud_abierta", http=409,
            extra={"folio": abierta["folio"]},
        )
    numero = siguiente_numero(conn, "solicitud")
    folio = f"SOL-{numero:06d}"
    creado = creado or ahora_iso()
    conn.execute(
        "INSERT INTO solicitud(id, folio, comercio_id, zona, franja, litros_estimados, estado, creado, actualizado) "
        "VALUES (?, ?, ?, ?, ?, ?, 'PENDIENTE', ?, ?)",
        (numero, folio, comercio["id"], comercio["zona"], franja, litros, creado, creado),
    )
    zona = estado_zona(conn, comercio["zona"])
    eventos.registrar(
        conn, "solicitud.creada",
        f"{folio}: {comercio['nombre']} pide {litros} L ({FRANJAS[franja]}); "
        f"{zona['nombre']} suma {zona['litros_pendientes']} de {zona['tope']} L",
        ref=folio,
        detalle={"comercio": comercio["codigo"], "litros": litros, "franja": franja,
                 "zona": comercio["zona"], "litros_zona": zona["litros_pendientes"]},
    )
    ruta = None
    if zona["litros_pendientes"] >= zona["tope"]:
        ruta = generar_ruta(conn, comercio["zona"], "umbral")
    solicitud = conn.execute("SELECT * FROM solicitud WHERE id = ?", (numero,)).fetchone()
    return solicitud, ruta


def cancelar_solicitud(conn, comercio, folio):
    s = conn.execute(
        "SELECT * FROM solicitud WHERE folio = ? AND comercio_id = ?", (folio, comercio["id"])).fetchone()
    if not s:
        raise ErrorNegocio("No encontramos esa solicitud.", http=404)
    if s["estado"] != "PENDIENTE":
        raise ErrorNegocio("La solicitud ya va en ruta; avísale al recolector si cambió algo.", http=409)
    conn.execute(
        "UPDATE solicitud SET estado = 'CANCELADA', actualizado = ? WHERE id = ?", (ahora_iso(), s["id"]))
    eventos.registrar(conn, "solicitud.cancelada", f"{folio} cancelada por el comercio", ref=folio)


# ---------------------------------------------------------------- recolección y pago
def confirmar_recoleccion(conn, comercio, recolector, peso_kg, confirmar_anomalia=False, crear_si_falta=False,
                          webhook_url=None, creado=None):
    try:
        m = metricas.calcular(peso_kg)
    except metricas.PesoInvalido as e:
        raise ErrorNegocio(str(e), codigo="peso_invalido") from None
    creado = creado or ahora_iso()
    sol = solicitud_abierta(conn, comercio["id"])
    directa = False
    if sol is None:
        if not crear_si_falta:
            raise ErrorNegocio(
                f"{comercio['nombre']} no tiene una solicitud abierta.", codigo="sin_solicitud", http=409)
        numero = siguiente_numero(conn, "solicitud")
        estimado = max(1, min(60, int(m["litros"].to_integral_value())))
        conn.execute(
            "INSERT INTO solicitud(id, folio, comercio_id, zona, franja, litros_estimados, estado, creado, "
            "actualizado) VALUES (?, ?, ?, ?, ?, ?, 'EN_RUTA', ?, ?)",
            (numero, f"SOL-{numero:06d}", comercio["id"], comercio["zona"], comercio["franja"], estimado,
             creado, creado),
        )
        sol = conn.execute("SELECT * FROM solicitud WHERE id = ?", (numero,)).fetchone()
        directa = True

    maximo = (Decimal(sol["litros_estimados"]) * PARAMETROS["tolerancia_peso"]).quantize(Decimal("0.01"))
    excede = metricas.excede_tolerancia(m["litros"], sol["litros_estimados"])
    if excede and not confirmar_anomalia:
        raise ErrorNegocio(
            f"{m['peso_kg']} kg equivalen a {m['litros']} L, más de 1.5 veces los "
            f"{sol['litros_estimados']} L solicitados. ¿El peso es correcto?",
            codigo="anomalia", http=409, extra={"litros": str(m["litros"]), "maximo": str(maximo)},
        )

    e = metricas.a_enteros(m)
    anio = _anio_local()
    numero = siguiente_numero(conn, "recoleccion")
    folio = f"REC-{anio}-{numero:06d}"
    anomalia = (f"Peso confirmado por encima de la tolerancia ({m['litros']} L contra "
                f"{sol['litros_estimados']} L solicitados)") if excede else None
    conn.execute(
        "INSERT INTO recoleccion(id, folio, solicitud_id, comercio_id, recolector_id, peso_g, litros_cl, agua_l, "
        "biocombustible_cl, bruto_cent, comision_cent, neto_cent, anomalia, creado) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (numero, folio, sol["id"], comercio["id"], recolector["id"] if recolector else None, e["peso_g"],
         e["litros_cl"], e["agua_l"], e["biocombustible_cl"], e["bruto_cent"], e["comision_cent"],
         e["neto_cent"], anomalia, creado),
    )
    conn.execute("UPDATE solicitud SET estado = 'RECOLECTADA', actualizado = ? WHERE id = ?", (creado, sol["id"]))
    conn.execute(
        "UPDATE comercio SET litros_cl = litros_cl + ?, agua_l = agua_l + ? WHERE id = ?",
        (e["litros_cl"], e["agua_l"], comercio["id"]),
    )

    numero_pago = siguiente_numero(conn, "pago")
    pago_folio = f"PAG-{anio}-{numero_pago:06d}"
    idem = f"{folio}-v1"
    conn.execute(
        "INSERT INTO pago(id, folio, recoleccion_id, comercio_id, monto_cent, clabe, idempotency_key, estatus, "
        "creado) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDIENTE', ?)",
        (numero_pago, pago_folio, numero, comercio["id"], e["neto_cent"], comercio["clabe"], idem, creado),
    )
    orden = {
        "pago": pago_folio,
        "recoleccion": folio,
        "idempotency_key": idem,
        "monto": str(m["pago_neto"]),
        "clabe_destino": comercio["clabe"],
        "beneficiario": comercio["nombre"],
        "concepto": f"Compra de {m['litros']} L de aceite usado ({folio})",
        "webhook_url": webhook_url,
    }
    conn.execute(
        "INSERT INTO outbox(tipo, ref, payload, estado, proximo, creado, actualizado) "
        "VALUES ('pago.solicitar', ?, ?, 'PENDIENTE', ?, ?, ?)",
        (pago_folio, json.dumps(orden, ensure_ascii=False), creado, creado, creado),
    )

    ruta_completa = None
    if sol["ruta_id"]:
        faltan = conn.execute(
            "SELECT COUNT(*) FROM solicitud WHERE ruta_id = ? AND estado = 'EN_RUTA'", (sol["ruta_id"],)
        ).fetchone()[0]
        if faltan == 0:
            conn.execute(
                "UPDATE ruta SET estado = 'COMPLETADA', completado = ? WHERE id = ?", (creado, sol["ruta_id"]))
            ruta_completa = conn.execute("SELECT folio FROM ruta WHERE id = ?", (sol["ruta_id"],)).fetchone()[0]

    # Evidencia del Data Pipeline, etapas 1 a 5.
    quien = recolector["nombre"] if recolector else "recolector"
    eventos.registrar(
        conn, "pesaje.capturado", f"QR {comercio['codigo']} escaneado; báscula: {m['peso_kg']} kg ({quien})",
        ref=folio, etapa=1,
        detalle={"comercio": comercio["codigo"], "peso_kg": str(m["peso_kg"]), "solicitud": sol["folio"],
                 "recolector": quien, "recoleccion_directa": directa},
    )
    eventos.registrar(
        conn, "pesaje.normalizado", f"{m['peso_kg']} kg ÷ {PARAMETROS['densidad']} kg/L = {m['litros']} L",
        ref=folio, etapa=2,
        detalle={"formula": "litros = peso_kg / densidad", "densidad_kg_l": str(PARAMETROS["densidad"]),
                 "litros": str(m["litros"])},
    )
    validaciones = [
        f"QR {comercio['codigo']} registrado",
        f"Solicitud {sol['folio']} abierta",
        f"Peso dentro del rango 0.05 a 100 kg",
        (f"{m['litros']} L dentro de la tolerancia (máximo {maximo} L)" if not excede
         else f"{m['litros']} L excede {maximo} L: confirmado por el recolector"),
    ]
    eventos.registrar(
        conn, "pesaje.validado", "; ".join(validaciones), ref=folio, etapa=3,
        detalle={"validaciones": validaciones, "anomalia": anomalia},
    )
    eventos.registrar(
        conn, "metricas.calculadas",
        f"Agua protegida {int(m['agua_l']):,} L; biocombustible {m['biocombustible_l']} L; "
        f"bruto ${m['pago_bruto']}, comisión ${m['comision']}, neto ${m['pago_neto']}",
        ref=folio, etapa=4, detalle=metricas.a_json(m),
    )
    eventos.registrar(
        conn, "recoleccion.confirmada",
        f"{folio} guardada; orden de pago {pago_folio} por ${m['pago_neto']} en la cola de salida",
        ref=folio, etapa=5,
        detalle={"recoleccion": folio, "pago": pago_folio, "idempotency_key": idem,
                 "ruta_completada": ruta_completa},
    )
    if ruta_completa:
        eventos.registrar(conn, "ruta.completada", f"{ruta_completa}: todas las paradas recolectadas",
                          ref=ruta_completa)
    return {
        "recoleccion": conn.execute("SELECT * FROM recoleccion WHERE id = ?", (numero,)).fetchone(),
        "pago": conn.execute("SELECT * FROM pago WHERE id = ?", (numero_pago,)).fetchone(),
        "metricas": m,
        "solicitud": sol,
        "anomalia": anomalia,
    }


def aplicar_liquidacion(conn, datos, firma_ok_detalle=None):
    """Aplica el webhook firmado del banco: el pago pasa a LIQUIDADO (idempotente)."""
    referencia = str(datos.get("referencia") or "")
    pago = conn.execute(
        "SELECT p.*, r.folio AS rec_folio, r.creado AS rec_creado, c.codigo, c.nombre "
        "FROM pago p JOIN recoleccion r ON r.id = p.recoleccion_id JOIN comercio c ON c.id = p.comercio_id "
        "WHERE p.folio = ?",
        (referencia,),
    ).fetchone()
    if pago is None:
        raise ErrorNegocio("Referencia de pago desconocida.", codigo="pago_desconocido", http=404)
    if pago["estatus"] == "LIQUIDADO":
        eventos.registrar(
            conn, "spei.webhook_duplicado",
            f"Webhook repetido para {referencia}: se ignora (el pago ya estaba liquidado)", ref=pago["rec_folio"])
        return {"duplicado": True, "pago": pago}
    try:
        monto_cent = int((Decimal(str(datos.get("monto"))) * 100).to_integral_value())
    except Exception:
        raise ErrorNegocio("Monto inválido en el webhook.", http=400) from None
    if monto_cent != pago["monto_cent"]:
        raise ErrorNegocio("El monto liquidado no coincide con la orden.", codigo="monto_distinto", http=409)
    ahora = ahora_iso()
    clave = str(datos.get("clave_rastreo") or "")[:30]
    conn.execute(
        "UPDATE pago SET estatus = 'LIQUIDADO', clave_rastreo = ?, folio_banco = COALESCE(folio_banco, ?), "
        "liquidado = ? WHERE id = ?",
        (clave, datos.get("folio"), ahora, pago["id"]),
    )
    conn.execute("UPDATE comercio SET cobrado_cent = cobrado_cent + ? WHERE id = ?", (monto_cent, pago["comercio_id"]))
    segundos = (parse_iso(ahora) - parse_iso(pago["rec_creado"])).total_seconds()
    eventos.registrar(
        conn, "spei.webhook_recibido",
        f"Webhook «{datos.get('evento')}» con firma HMAC válida; clave de rastreo {clave}",
        ref=pago["rec_folio"], etapa=7,
        detalle={"cuerpo": datos, "firma": firma_ok_detalle or "válida"},
    )
    eventos.registrar(
        conn, "pago.liquidado",
        f"{pago['folio']} LIQUIDADO: ${metricas.pesos(monto_cent)} a {pago['nombre']} "
        f"({clabe_mod.enmascarar(pago['clabe'])}); del pesaje al pago en {segundos:.1f} s",
        ref=pago["rec_folio"], etapa=8,
        detalle={"pago": pago["folio"], "clave_rastreo": clave, "monto": metricas.pesos(monto_cent),
                 "segundos_desde_pesaje": round(segundos, 2)},
    )
    return {"duplicado": False, "pago": conn.execute("SELECT * FROM pago WHERE id = ?", (pago["id"],)).fetchone()}
