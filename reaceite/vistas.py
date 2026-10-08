"""Consultas de solo lectura que alimentan las pantallas (modelos de lectura)."""
import json

from . import clabe as clabe_mod
from .config import DEPOSITO, FRANJAS, PARAMETROS, ZONAS
from .db import local
from .eventos import ETAPAS
from .metricas import litros_txt, pesos
from .servicios import estado_zona, solicitud_abierta


def _f(texto):
    return local(texto).isoformat(timespec="seconds") if texto else None


def _zona(conn, zona):
    z = estado_zona(conn, zona)
    z["mas_antigua"] = _f(z["mas_antigua"])
    return z


def _parada_info(conn, solicitud):
    if not solicitud or not solicitud["ruta_id"]:
        return None
    ruta = conn.execute("SELECT * FROM ruta WHERE id = ?", (solicitud["ruta_id"],)).fetchone()
    orden = json.loads(ruta["orden"])
    return {
        "folio": ruta["folio"],
        "parada": orden.index(solicitud["id"]) + 1 if solicitud["id"] in orden else None,
        "de": len(orden),
        "estado": ruta["estado"],
    }


def _solicitud(conn, s):
    if s is None:
        return None
    return {
        "folio": s["folio"],
        "litros": s["litros_estimados"],
        "franja": s["franja"],
        "franja_txt": FRANJAS.get(s["franja"], s["franja"]),
        "estado": s["estado"],
        "creado": _f(s["creado"]),
        "ruta": _parada_info(conn, s),
    }


def _pago(p):
    if p is None:
        return None
    return {
        "folio": p["folio"],
        "estatus": p["estatus"],
        "monto": pesos(p["monto_cent"]),
        "clave_rastreo": p["clave_rastreo"] if p["estatus"] == "LIQUIDADO" else None,
        "folio_banco": p["folio_banco"],
        "clabe": clabe_mod.enmascarar(p["clabe"]),
        "creado": _f(p["creado"]),
        "liquidado": _f(p["liquidado"]),
        "error": p["ultimo_error"] if p["estatus"] == "RECHAZADO" else None,
    }


def comercio(conn, c):
    abierta = solicitud_abierta(conn, c["id"])
    ultimo = conn.execute(
        "SELECT p.*, r.folio AS rec_folio, r.litros_cl, r.agua_l AS rec_agua, r.peso_g, r.biocombustible_cl "
        "FROM pago p JOIN recoleccion r ON r.id = p.recoleccion_id WHERE p.comercio_id = ? "
        "ORDER BY p.id DESC LIMIT 1",
        (c["id"],),
    ).fetchone()
    ultimo_pago = None
    if ultimo:
        ultimo_pago = _pago(ultimo)
        ultimo_pago["recoleccion"] = {
            "folio": ultimo["rec_folio"],
            "litros": litros_txt(ultimo["litros_cl"]),
            "agua_l": ultimo["rec_agua"],
            "peso_kg": f"{ultimo['peso_g'] / 1000:.3f}".rstrip("0").rstrip("."),
        }
    historial = [
        {
            "folio": h["folio"],
            "fecha": _f(h["creado"]),
            "litros": litros_txt(h["litros_cl"]),
            "agua_l": h["agua_l"],
            "monto": pesos(h["monto_cent"]),
            "estatus": h["estatus"],
        }
        for h in conn.execute(
            "SELECT r.folio, r.creado, r.litros_cl, r.agua_l, p.monto_cent, p.estatus FROM recoleccion r "
            "JOIN pago p ON p.recoleccion_id = r.id WHERE r.comercio_id = ? ORDER BY r.id DESC LIMIT 6",
            (c["id"],),
        )
    ]
    return {
        "codigo": c["codigo"],
        "token": c["token"],
        "nombre": c["nombre"],
        "tipo": c["tipo"],
        "direccion": c["direccion"],
        "franja": c["franja"],
        "zona": _zona(conn, c["zona"]),
        "clabe": clabe_mod.enmascarar(c["clabe"]),
        "acumulado": {
            "litros": litros_txt(c["litros_cl"]),
            "agua_l": c["agua_l"],
            "cobrado": pesos(c["cobrado_cent"]),
        },
        "solicitud": _solicitud(conn, abierta),
        "ultimo_pago": ultimo_pago,
        "historial": historial,
    }


def rutas(conn):
    activas = []
    for r in conn.execute("SELECT * FROM ruta WHERE estado = 'ACTIVA' ORDER BY id DESC").fetchall():
        orden = json.loads(r["orden"])
        filas = {
            f["id"]: f
            for f in conn.execute(
                f"SELECT s.id, s.folio, s.estado, s.litros_estimados, s.franja, c.codigo, c.token, c.nombre, "
                f"c.direccion, c.lat, c.lon FROM solicitud s JOIN comercio c ON c.id = s.comercio_id "
                f"WHERE s.id IN ({','.join('?' * len(orden))})",
                orden,
            )
        }
        paradas = [
            {
                "n": i + 1,
                "folio": filas[sid]["folio"],
                "estado": filas[sid]["estado"],
                "litros": filas[sid]["litros_estimados"],
                "franja_txt": FRANJAS.get(filas[sid]["franja"], ""),
                "codigo": filas[sid]["codigo"],
                "token": filas[sid]["token"],
                "nombre": filas[sid]["nombre"],
                "direccion": filas[sid]["direccion"],
                "lat": filas[sid]["lat"],
                "lon": filas[sid]["lon"],
            }
            for i, sid in enumerate(orden) if sid in filas
        ]
        activas.append({
            "folio": r["folio"],
            "zona": ZONAS[r["zona"]]["nombre"],
            "motivo": r["motivo"],
            "litros": r["litros_estimados"],
            "distancia_km": round(r["distancia_m"] / 1000, 2),
            "distancia_base_km": round(r["distancia_base_m"] / 1000, 2),
            "duracion_min": round(r["duracion_s"] / 60),
            "algoritmo": r["algoritmo"],
            "calculo_ms": r["calculo_ms"],
            "url_maps": r["url_maps"],
            "creado": _f(r["creado"]),
            "paradas": paradas,
            "pendientes": sum(1 for p in paradas if p["estado"] == "EN_RUTA"),
        })
    return {
        "deposito": DEPOSITO,
        "rutas": activas,
        "zonas": [_zona(conn, z) for z in ZONAS],
    }


def previa_pesaje(conn, c):
    abierta = solicitud_abierta(conn, c["id"])
    return {
        "comercio": {
            "codigo": c["codigo"],
            "token": c["token"],
            "nombre": c["nombre"],
            "tipo": c["tipo"],
            "direccion": c["direccion"],
            "zona": ZONAS[c["zona"]]["nombre"],
        },
        "solicitud": _solicitud(conn, abierta),
        "parametros": parametros(),
    }


def parametros():
    p = PARAMETROS
    return {
        "precio_litro": str(p["precio_litro"]),
        "comision": str(p["comision"]),
        "densidad": str(p["densidad"]),
        "agua_por_litro": str(p["agua_por_litro"]),
        "biocombustible_por_litro": str(p["biocombustible_por_litro"]),
        "tope_ruta_litros": p["tope_ruta_litros"],
        "tolerancia_peso": str(p["tolerancia_peso"]),
        "espera_maxima_horas": p["espera_maxima_horas"],
        "franjas": FRANJAS,
        "zonas": {k: v["nombre"] for k, v in ZONAS.items()},
    }


def pago(conn, folio):
    p = conn.execute(
        "SELECT p.*, r.folio AS rec_folio, r.litros_cl, r.agua_l AS rec_agua, r.peso_g, c.nombre, c.codigo "
        "FROM pago p JOIN recoleccion r ON r.id = p.recoleccion_id JOIN comercio c ON c.id = p.comercio_id "
        "WHERE p.folio = ?", (folio,),
    ).fetchone()
    if p is None:
        return None
    datos = _pago(p)
    datos["comercio"] = {"codigo": p["codigo"], "nombre": p["nombre"]}
    datos["recoleccion"] = p["rec_folio"]
    datos["etapas"] = _etapas(conn, p["rec_folio"])
    return datos


def _etapas(conn, ref):
    filas = conn.execute(
        "SELECT ts, tipo, etapa, resumen FROM evento WHERE ref = ? AND etapa IS NOT NULL ORDER BY id", (ref,)
    ).fetchall()
    return [
        {"etapa": f["etapa"], "nombre": ETAPAS.get(f["etapa"]), "tipo": f["tipo"], "ts": _f(f["ts"]),
         "ts_ms": f["ts"], "resumen": f["resumen"]}
        for f in filas
    ]


def impacto(conn):
    t = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(litros_cl), 0) AS litros, COALESCE(SUM(agua_l), 0) AS agua, "
        "COALESCE(SUM(biocombustible_cl), 0) AS bio FROM recoleccion"
    ).fetchone()
    pagado = conn.execute(
        "SELECT COALESCE(SUM(monto_cent), 0) AS monto, COUNT(*) AS n FROM pago WHERE estatus = 'LIQUIDADO'"
    ).fetchone()
    ultimos = [
        {
            "folio": u["folio"],
            "cuando": _f(u["creado"]),
            "comercio": u["codigo"],
            "tipo": u["tipo"],
            "zona": ZONAS[u["zona"]]["nombre"],
            "litros": litros_txt(u["litros_cl"]),
            "agua_l": u["agua_l"],
            "monto": pesos(u["monto_cent"]),
            "estatus": u["estatus"],
        }
        for u in conn.execute(
            "SELECT r.folio, r.creado, r.litros_cl, r.agua_l, c.codigo, c.tipo, c.zona, p.monto_cent, p.estatus "
            "FROM recoleccion r JOIN comercio c ON c.id = r.comercio_id JOIN pago p ON p.recoleccion_id = r.id "
            "ORDER BY r.id DESC LIMIT 6"
        )
    ]
    puntos = [
        {"codigo": c["codigo"], "tipo": c["tipo"], "zona": c["zona"], "lat": c["lat"], "lon": c["lon"],
         "pendiente": c["pendiente"]}
        for c in conn.execute(
            "SELECT c.codigo, c.tipo, c.zona, c.lat, c.lon, EXISTS(SELECT 1 FROM solicitud s WHERE s.comercio_id = c.id "
            "AND s.estado IN ('PENDIENTE', 'EN_RUTA')) AS pendiente FROM comercio c"
        )
    ]
    return {
        "recolecciones": t["n"],
        "litros": litros_txt(t["litros"]),
        "agua_l": t["agua"],
        "biocombustible_l": litros_txt(t["bio"]),
        "pagado": pesos(pagado["monto"]),
        "pagos": pagado["n"],
        "comercios": conn.execute("SELECT COUNT(*) FROM comercio").fetchone()[0],
        "zonas": [_zona(conn, z) for z in ZONAS],
        "ultimos": ultimos,
        "puntos": puntos,
        "deposito": DEPOSITO,
        "version": conn.execute("SELECT COALESCE(MAX(id), 0) FROM evento").fetchone()[0],
    }


def monitor(conn, desde=0):
    if desde:
        filas = conn.execute("SELECT * FROM evento WHERE id > ? ORDER BY id DESC LIMIT 200", (desde,)).fetchall()
    else:
        filas = conn.execute("SELECT * FROM evento ORDER BY id DESC LIMIT 80").fetchall()
    eventos = [
        {"id": f["id"], "ts": _f(f["ts"]), "ts_ms": f["ts"], "tipo": f["tipo"], "etapa": f["etapa"],
         "ref": f["ref"], "resumen": f["resumen"], "detalle": json.loads(f["detalle"]) if f["detalle"] else None}
        for f in filas
    ]
    ultima = conn.execute(
        "SELECT ref FROM evento WHERE etapa IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    pipeline = None
    if ultima:
        pipeline = {"recoleccion": ultima["ref"], "etapas": _etapas(conn, ultima["ref"])}
    pagos = [
        {"folio": p["folio"], "estatus": p["estatus"], "monto": pesos(p["monto_cent"]), "intentos": p["intentos"],
         "clave_rastreo": p["clave_rastreo"], "creado": _f(p["creado"]), "liquidado": _f(p["liquidado"])}
        for p in conn.execute("SELECT * FROM pago ORDER BY id DESC LIMIT 6")
    ]
    banco = [
        {"folio": o["folio"], "referencia": o["referencia"], "estatus": o["estatus"], "monto": pesos(o["monto_cent"]),
         "webhook": o["webhook_estado"], "http": o["webhook_http"], "intentos": o["webhook_intentos"],
         "creado": _f(o["creado"])}
        for o in conn.execute("SELECT * FROM spei_orden ORDER BY id DESC LIMIT 6")
    ]
    cola = {
        f["estado"]: f["n"]
        for f in conn.execute("SELECT estado, COUNT(*) AS n FROM outbox GROUP BY estado")
    }
    return {
        "eventos": eventos,
        "ultimo_id": conn.execute("SELECT COALESCE(MAX(id), 0) FROM evento").fetchone()[0],
        "pipeline": pipeline,
        "pagos": pagos,
        "banco": banco,
        "cola": cola,
        "etapas": ETAPAS,
    }
