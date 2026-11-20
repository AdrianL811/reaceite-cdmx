"""Contenedor inteligente ReAceite: báscula con celda de carga, compuerta con cerradura y firma HMAC.

Flujo de un depósito (evento físico → webhook del dispositivo → pago en la billetera):
1. El comercio escanea el QR pegado en el contenedor (/k/<token>) con su sesión abierta y toca
   «Abrir compuerta». Se crea el depósito y el contenedor lo recibe como orden en su siguiente señal.
2. Mientras el comercio vierte el aceite, la celda de carga reporta el peso (POST /iot/v1/telemetria).
3. Al cerrar la tapa, el dispositivo envía «deposito.cerrado» con el peso final. Cada mensaje va
   firmado con HMAC-SHA256 (secreto propio del contenedor) y lleva un evento_id único: un mensaje
   alterado o repetido no puede generar un segundo pago.
4. La plataforma calcula el peso neto (final menos inicial) y el dato recorre el mismo Data Pipeline
   de 8 etapas que la recolección en ruta: el pago sale del Fondo de Garantía de Dispersión y llega
   a la billetera del comercio.

En el piloto el contenedor físico se sustituye por su gemelo digital (la pantalla del equipo en
/k/<token>), que envía exactamente los mismos mensajes firmados que el firmware de referencia
(herramientas/contenedor_esp32.ino).
"""
import hashlib
import hmac
import json
import re
import time
import uuid
from decimal import Decimal

from flask import Blueprint, Response, abort, current_app, jsonify, redirect, render_template, request, url_for

from . import eventos, metricas, qr, servicios, transporte
from .auth import comercio_actual, requiere, requiere_comercio, usuario_actual
from .config import PARAMETROS, ZONAS
from .db import ahora_iso, get_db, local, parse_iso, siguiente_numero, transaccion
from .errores import ErrorNegocio
from .firma import firmar, verificar

dispositivo = Blueprint("iot", __name__, url_prefix="/iot")
web = Blueprint("contenedores", __name__)
api = Blueprint("contenedores_api", __name__, url_prefix="/api")


@api.before_request
def _proteccion_csrf():
    # Igual que el resto de la API: un formulario de otro sitio no puede agregar esta cabecera.
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("X-ReAceite") != "1":
        return jsonify(error="csrf", mensaje="Petición rechazada: falta la cabecera X-ReAceite."), 403
    return None


@api.errorhandler(ErrorNegocio)
def _error_negocio(e):
    return jsonify({"error": e.codigo, "mensaje": e.mensaje, **e.extra}), e.http


def _despertar():
    despachador = current_app.extensions.get("despachador")
    if despachador:
        despachador.despertar()

PESO_MINIMO_G = 50          # menos que esto no es un depósito (ruido de la báscula)
SIN_SENAL_S = 90            # sin mensajes en este tiempo, el contenedor aparece «sin señal»


# ---------------------------------------------------------------- utilidades
def secreto_dispositivo(config, codigo):
    """Cada contenedor firma con su propio secreto, derivado del secreto maestro y su código."""
    return hmac.new(config["IOT_SECRET"].encode(), codigo.encode(), hashlib.sha256).hexdigest()[:40]


def por_token(conn, token):
    token = (token or "").strip().upper()
    if not re.fullmatch(r"[0-9A-Z]{6,12}", token):
        return None
    return conn.execute("SELECT * FROM contenedor WHERE token = ?", (token,)).fetchone()


def por_codigo(conn, codigo):
    return conn.execute("SELECT * FROM contenedor WHERE codigo = ?", ((codigo or "").strip().upper(),)).fetchone()


def deposito_abierto(conn, contenedor_id):
    return conn.execute(
        "SELECT * FROM deposito WHERE contenedor_id = ? AND estado = 'ABIERTO'", (contenedor_id,)).fetchone()


def _releer(conn, c):
    return conn.execute("SELECT * FROM contenedor WHERE id = ?", (c["id"],)).fetchone()


def _litros(cl):
    return metricas.litros_txt(cl)


def estado(conn, c, con_secretos=False):
    """Lo que muestran las pantallas sobre un contenedor."""
    abierto = deposito_abierto(conn, c["id"])
    comercio = None
    if abierto:
        comercio = conn.execute("SELECT codigo, nombre FROM comercio WHERE id = ?", (abierto["comercio_id"],)).fetchone()
    nivel_l = Decimal(c["nivel_cl"]) / 100
    porcentaje = min(100, round(float(nivel_l) / c["capacidad_l"] * 100))
    en_linea = bool(c["ultima_senal"]) and (time.time() - parse_iso(c["ultima_senal"]).timestamp()) < SIN_SENAL_S
    datos = {
        "codigo": c["codigo"],
        "token": c["token"],
        "nombre": c["nombre"],
        "direccion": c["direccion"],
        "zona": c["zona"],
        "zona_nombre": ZONAS[c["zona"]]["nombre"],
        "lat": c["lat"],
        "lon": c["lon"],
        "capacidad_l": c["capacidad_l"],
        "nivel_l": _litros(c["nivel_cl"]),
        "porcentaje": porcentaje,
        "alerta": c["alerta"],
        "peso_g": c["peso_g"],
        "en_linea": en_linea,
        "ultima_senal": local(c["ultima_senal"]).isoformat(timespec="seconds") if c["ultima_senal"] else None,
        "firmware": c["firmware"],
        "qr": f"/qr/k/{c['token']}.png",
        "url": f"/k/{c['token']}",
        "deposito": None,
    }
    if abierto:
        neto = max(0, abierto["peso_actual_g"] - abierto["peso_inicial_g"])
        datos["deposito"] = {
            "folio": abierto["folio"],
            "comercio": comercio["nombre"] if comercio else None,
            "comercio_codigo": comercio["codigo"] if comercio else None,
            "peso_inicial_g": abierto["peso_inicial_g"],
            "peso_neto_g": neto,
            "vence": local(abierto["vence"]).isoformat(timespec="seconds"),
            "vence_ms": int(parse_iso(abierto["vence"]).timestamp() * 1000),
        }
    if con_secretos:
        datos["secreto_pista"] = c["secreto"][:4] + "…"
    return datos


def comando(conn, c):
    """La orden que el contenedor recibe en la respuesta a cada mensaje."""
    abierto = deposito_abierto(conn, c["id"])
    if abierto is None:
        return {"compuerta": "cerrada"}
    return {"compuerta": "abierta", "deposito": abierto["folio"], "peso_inicial_g": abierto["peso_inicial_g"],
            "vence": local(abierto["vence"]).isoformat(timespec="seconds")}


def vista_deposito(conn, d):
    c = conn.execute("SELECT * FROM contenedor WHERE id = ?", (d["contenedor_id"],)).fetchone()
    neto = d["peso_neto_g"] if d["peso_neto_g"] is not None else max(0, d["peso_actual_g"] - d["peso_inicial_g"])
    datos = {
        "folio": d["folio"],
        "estado": d["estado"],
        "motivo": d["motivo"],
        "peso_neto_g": neto,
        "vence_ms": int(parse_iso(d["vence"]).timestamp() * 1000),
        "contenedor": {"codigo": c["codigo"], "nombre": c["nombre"], "nivel_l": _litros(c["nivel_cl"]),
                       "capacidad_l": c["capacidad_l"],
                       "porcentaje": min(100, round(c["nivel_cl"] / c["capacidad_l"])),
                       "en_linea": estado(conn, c)["en_linea"]},
        "recoleccion": None,
        "pago": None,
    }
    if d["recoleccion_id"]:
        r = conn.execute("SELECT * FROM recoleccion WHERE id = ?", (d["recoleccion_id"],)).fetchone()
        p = conn.execute("SELECT * FROM pago WHERE recoleccion_id = ?", (r["id"],)).fetchone()
        datos["recoleccion"] = {"folio": r["folio"], "litros": _litros(r["litros_cl"]), "agua_l": r["agua_l"],
                                "peso_kg": f"{r['peso_g'] / 1000:.3f}", "bruto": metricas.pesos(r["bruto_cent"]),
                                "comision": metricas.pesos(r["comision_cent"])}
        datos["pago"] = {"folio": p["folio"], "estatus": p["estatus"], "monto": metricas.pesos(p["monto_cent"]),
                         "clave_rastreo": p["clave_rastreo"] if p["estatus"] == "LIQUIDADO" else None,
                         "espera": p["ultimo_error"] if p["estatus"] == "PENDIENTE" else None}
    return datos


# ---------------------------------------------------------------- reglas del depósito
def abrir_deposito(conn, c, comercio):
    abierto = deposito_abierto(conn, c["id"])
    if abierto is not None:
        if abierto["comercio_id"] == comercio["id"]:
            return abierto
        raise ErrorNegocio("Alguien más está depositando en este contenedor. Espera un minuto y vuelve a intentar.",
                           codigo="contenedor_ocupado", http=409)
    if c["nivel_cl"] >= c["capacidad_l"] * 95:
        raise ErrorNegocio("Este contenedor está lleno. Ya avisamos para que lo vacíen; usa otro o pide la ruta.",
                           codigo="contenedor_lleno", http=409)
    numero = siguiente_numero(conn, "deposito")
    folio = f"DEP-{numero:06d}"
    ahora = ahora_iso()
    vence = ahora_iso(PARAMETROS["deposito_minutos"] * 60)
    conn.execute(
        "INSERT INTO deposito(id, folio, contenedor_id, comercio_id, estado, peso_inicial_g, peso_actual_g, abierto, "
        "vence) VALUES (?, ?, ?, ?, 'ABIERTO', ?, ?, ?, ?)",
        (numero, folio, c["id"], comercio["id"], c["peso_g"], c["peso_g"], ahora, vence),
    )
    eventos.registrar(
        conn, "contenedor.compuerta_abierta",
        f"{c['codigo']}: {comercio['nombre']} ({comercio['codigo']}) escaneó el QR del contenedor; "
        f"compuerta abierta para {folio} durante {PARAMETROS['deposito_minutos']} min",
        ref=folio,
        detalle={"contenedor": c["codigo"], "comercio": comercio["codigo"], "deposito": folio,
                 "peso_inicial_g": c["peso_g"], "vence": local(vence).isoformat(timespec="seconds")},
    )
    return conn.execute("SELECT * FROM deposito WHERE id = ?", (numero,)).fetchone()


def cancelar_deposito(conn, d):
    if d["estado"] != "ABIERTO":
        raise ErrorNegocio("Ese depósito ya terminó.", http=409)
    if d["peso_actual_g"] - d["peso_inicial_g"] >= PESO_MINIMO_G:
        raise ErrorNegocio("La báscula ya registró aceite: cierra la tapa para terminar el depósito.", http=409)
    conn.execute("UPDATE deposito SET estado = 'CANCELADO', motivo = 'cancelado por el comercio', cerrado = ? "
                 "WHERE id = ?", (ahora_iso(), d["id"]))
    eventos.registrar(conn, "contenedor.deposito_cancelado", f"{d['folio']} cancelado por el comercio; compuerta cerrada",
                      ref=d["folio"])


def _cerrar(conn, c, d, peso_final_g, motivo, telemetria=None):
    """Cierra el depósito con el peso final. Con aceite suficiente, el dato entra al Data Pipeline."""
    neto = peso_final_g - d["peso_inicial_g"]
    ahora = ahora_iso()
    conn.execute("UPDATE contenedor SET peso_g = ? WHERE id = ?", (peso_final_g, c["id"]))
    if neto < PESO_MINIMO_G:
        conn.execute("UPDATE deposito SET estado = 'CANCELADO', peso_actual_g = ?, peso_neto_g = ?, motivo = ?, "
                     "cerrado = ? WHERE id = ?",
                     (peso_final_g, max(0, neto), "la báscula no registró aceite", ahora, d["id"]))
        eventos.registrar(conn, "contenedor.deposito_vacio",
                          f"{d['folio']}: tapa cerrada sin aceite ({max(0, neto)} g); no se genera pago", ref=d["folio"])
        return None
    comercio = conn.execute("SELECT * FROM comercio WHERE id = ?", (d["comercio_id"],)).fetchone()
    peso_kg = (Decimal(neto) / 1000).quantize(Decimal("0.001"))
    r = servicios.confirmar_recoleccion(
        conn, comercio, None, peso_kg, contenedor=c,
        deposito={"folio": d["folio"], "peso_inicial_g": d["peso_inicial_g"], "peso_final_g": peso_final_g,
                  "peso_neto_g": neto, "cierre": motivo, "telemetria": telemetria},
    )
    rec = r["recoleccion"]
    conn.execute("UPDATE deposito SET estado = 'CERRADO', peso_actual_g = ?, peso_neto_g = ?, recoleccion_id = ?, "
                 "motivo = ?, cerrado = ? WHERE id = ?",
                 (peso_final_g, neto, rec["id"], motivo, ahora, d["id"]))
    conn.execute("UPDATE contenedor SET nivel_cl = nivel_cl + ? WHERE id = ?", (rec["litros_cl"], c["id"]))
    c = _releer(conn, c)
    porcentaje = c["nivel_cl"] / c["capacidad_l"]
    if porcentaje >= PARAMETROS["contenedor_alerta"] and not c["alerta"]:
        conn.execute("UPDATE contenedor SET alerta = ? WHERE id = ?", (ahora, c["id"]))
        eventos.registrar(
            conn, "contenedor.alerta_llenado",
            f"{c['codigo']} al {porcentaje:.0f} % ({_litros(c['nivel_cl'])} de {c['capacidad_l']} L): "
            f"programar vaciado en la próxima ruta de {ZONAS[c['zona']]['nombre']}", ref=c["codigo"])
    return r


def recibir_telemetria(conn, c, datos, cabeceras=None):
    """Aplica un mensaje firmado del contenedor. Devuelve (respuesta, status HTTP)."""
    evento_id = str(datos.get("evento_id") or "")[:64]
    tipo = str(datos.get("tipo") or "")
    if not re.fullmatch(r"[0-9A-Za-z_.:-]{8,64}", evento_id):
        raise ErrorNegocio("Falta un evento_id válido (8 a 64 caracteres).", codigo="evento_id", http=422)
    if tipo not in ("latido", "peso", "deposito.cerrado"):
        raise ErrorNegocio("Tipo de mensaje desconocido.", codigo="tipo", http=422)
    try:
        peso_g = int(datos.get("peso_g"))
    except (TypeError, ValueError):
        raise ErrorNegocio("Falta peso_g (gramos, entero).", codigo="peso_g", http=422) from None
    if not 0 <= peso_g <= c["capacidad_l"] * 1000:
        raise ErrorNegocio("Lectura fuera del rango de la celda de carga.", codigo="peso_fuera_de_rango", http=422)

    repetido = conn.execute("SELECT 1 FROM lectura WHERE evento_id = ?", (evento_id,)).fetchone()
    if repetido:
        return {"ok": True, "duplicado": True, "comando": comando(conn, c)}, 200

    ahora = ahora_iso()
    conn.execute("INSERT INTO lectura(contenedor_id, evento_id, tipo, peso_g, cuerpo, recibido) VALUES (?, ?, ?, ?, ?, ?)",
                 (c["id"], evento_id, tipo, peso_g, json.dumps(datos, ensure_ascii=False)[:2000], ahora))
    firmware = str(datos.get("firmware") or "")[:40] or c["firmware"]
    conn.execute("UPDATE contenedor SET ultima_senal = ?, firmware = ? WHERE id = ?", (ahora, firmware, c["id"]))
    abierto = deposito_abierto(conn, c["id"])

    if tipo in ("latido", "peso"):
        conn.execute("UPDATE contenedor SET peso_g = ? WHERE id = ?", (peso_g, c["id"]))
        if abierto is not None:
            conn.execute("UPDATE deposito SET peso_actual_g = ? WHERE id = ?", (peso_g, abierto["id"]))
        return {"ok": True, "comando": comando(conn, c)}, 200

    folio = str(datos.get("deposito") or "")
    if abierto is None or abierto["folio"] != folio:
        previo = conn.execute("SELECT * FROM deposito WHERE folio = ? AND contenedor_id = ?", (folio, c["id"])).fetchone()
        if previo is not None and previo["estado"] != "ABIERTO":
            return {"ok": True, "duplicado": True, "deposito": vista_deposito(conn, previo), "comando": comando(conn, c)}, 200
        raise ErrorNegocio("No hay un depósito abierto con ese folio en este contenedor.", codigo="sin_deposito",
                           http=409)
    eventos.registrar(
        conn, "iot.deposito_cerrado",
        f"{c['codigo']} → POST /iot/v1/telemetria «deposito.cerrado» con firma HMAC válida: "
        f"{peso_g - abierto['peso_inicial_g']} g netos en {folio}",
        ref=folio, detalle={"cabeceras": cabeceras or {}, "cuerpo": datos},
    )
    r = _cerrar(conn, c, abierto, peso_g, "tapa cerrada", telemetria={"evento_id": evento_id})
    d = conn.execute("SELECT * FROM deposito WHERE id = ?", (abierto["id"],)).fetchone()
    return {"ok": True, "deposito": vista_deposito(conn, d), "comando": comando(conn, c),
            "recoleccion": r["recoleccion"]["folio"] if r else None}, 201 if r else 200


def revisar_depositos(conn):
    """Depósitos con la compuerta vencida: si la báscula registró aceite, se cierran con la última lectura."""
    pagados = 0
    for d in conn.execute("SELECT * FROM deposito WHERE estado = 'ABIERTO' AND vence <= ?", (ahora_iso(),)).fetchall():
        c = conn.execute("SELECT * FROM contenedor WHERE id = ?", (d["contenedor_id"],)).fetchone()
        if d["peso_actual_g"] - d["peso_inicial_g"] >= PESO_MINIMO_G:
            if _cerrar(conn, c, d, d["peso_actual_g"], "cerrado por tiempo con la última lectura"):
                pagados += 1
        else:
            conn.execute("UPDATE deposito SET estado = 'VENCIDO', motivo = 'nadie depositó a tiempo', cerrado = ? "
                         "WHERE id = ?", (ahora_iso(), d["id"]))
            eventos.registrar(conn, "contenedor.deposito_vencido",
                              f"{d['folio']}: pasaron {PARAMETROS['deposito_minutos']} min sin aceite; compuerta cerrada",
                              ref=d["folio"])
    return pagados


def vaciar(conn, c, usuario):
    if deposito_abierto(conn, c["id"]) is not None:
        raise ErrorNegocio("Hay un depósito en curso; espera a que el comercio cierre la tapa.", http=409)
    litros = _litros(c["nivel_cl"])
    conn.execute("UPDATE contenedor SET nivel_cl = 0, peso_g = 0, alerta = NULL WHERE id = ?", (c["id"],))
    eventos.registrar(conn, "contenedor.vaciado",
                      f"{c['codigo']} vaciado por {usuario['nombre']}: {litros} L al camión rumbo al centro de acopio",
                      ref=c["codigo"], detalle={"litros": litros})


# ---------------------------------------------------------------- endpoint del dispositivo
@dispositivo.post("/v1/telemetria")
def telemetria():
    """Mensajes del contenedor. Cabeceras: X-Dispositivo (código) y X-Dispositivo-Firma: t=<unix>,v1=<hmac>."""
    codigo = request.headers.get("X-Dispositivo", "")
    cuerpo = request.get_data(cache=False)
    conn = get_db()
    c = por_codigo(conn, codigo)
    if c is None:
        return jsonify(error="dispositivo_desconocido", mensaje="Contenedor no registrado"), 404
    firma = request.headers.get("X-Dispositivo-Firma", "")
    ok, motivo = verificar(c["secreto"], cuerpo, firma) if firma else (False, "Falta la cabecera X-Dispositivo-Firma")
    if not ok:
        with transaccion(conn):
            eventos.registrar(conn, "iot.firma_rechazada", f"{c['codigo']}: mensaje rechazado ({motivo})",
                              ref=c["codigo"])
        return jsonify(error="firma", mensaje=motivo), 401
    try:
        datos = json.loads(cuerpo)
        if not isinstance(datos, dict):
            raise ValueError
    except ValueError:
        return jsonify(error="json_invalido", mensaje="El cuerpo debe ser un objeto JSON"), 400
    cabeceras = {"X-Dispositivo": codigo, "X-Dispositivo-Firma": firma[:24] + "…"}
    try:
        with transaccion(conn):
            respuesta, status = recibir_telemetria(conn, c, datos, cabeceras)
    except ErrorNegocio as e:
        return jsonify(error=e.codigo, mensaje=e.mensaje), e.http
    if respuesta.get("recoleccion"):
        _despertar()
    return jsonify(respuesta), status


def enviar_senal(app, c, tipo, peso_g, deposito=None, tapa_abierta=False):
    """Lo que hace el firmware: arma el mensaje, lo firma con el secreto del contenedor y lo envía por HTTP."""
    datos = {
        "evento_id": uuid.uuid4().hex,
        "tipo": tipo,
        "peso_g": int(peso_g),
        "tapa": "abierta" if tapa_abierta and tipo != "deposito.cerrado" else "cerrada",
        "firmware": "reaceite-ctn 1.0 (gemelo digital)",
        "ts": int(time.time()),
    }
    if deposito:
        datos["deposito"] = deposito
    cuerpo = json.dumps(datos, ensure_ascii=False).encode()
    firma = firmar(c["secreto"], cuerpo)
    cabeceras = {"Content-Type": "application/json", "User-Agent": "ReAceite-Contenedor/1.0",
                 "X-Dispositivo": c["codigo"], "X-Dispositivo-Firma": firma}
    r = transporte.enviar(app, "POST", "/iot/v1/telemetria", cuerpo, cabeceras, timeout=6)
    return {
        "peticion": {"metodo": "POST", "url": "/iot/v1/telemetria",
                     "cabeceras": {"X-Dispositivo": c["codigo"], "X-Dispositivo-Firma": firma[:30] + "…"},
                     "cuerpo": datos},
        "respuesta": {"status": r.status, "cuerpo": r.json()},
        "latencia_ms": round(r.ms, 1),
        "transporte": r.transporte,
    }


# ---------------------------------------------------------------- páginas y QR
@web.get("/k/<token>")
def pagina_contenedor(token):
    """El QR del contenedor. El equipo ve el gemelo digital; el comercio con sesión, su depósito."""
    conn = get_db()
    c = por_token(conn, token)
    if c is None:
        return render_template("qr_desconocido.html"), 404
    propio = comercio_actual()
    if usuario_actual() is not None:
        modo = "equipo"
    elif propio is not None:
        modo = "comercio"
    else:
        modo = "publico"
    datos = estado(conn, c)
    mi_deposito = None
    if propio is not None and datos["deposito"] and datos["deposito"]["comercio_codigo"] == propio["codigo"]:
        mi_deposito = datos["deposito"]["folio"]
    if modo != "equipo" and datos["deposito"]:
        # Al comercio solo se le dice si la compuerta está ocupada, no quién deposita.
        datos["deposito"] = {"folio": datos["deposito"]["folio"] if mi_deposito else None,
                             "ocupado": not mi_deposito}
    otros = [f[0] for f in conn.execute("SELECT codigo FROM contenedor WHERE id != ? ORDER BY id", (c["id"],))]
    return render_template("contenedor.html", modo=modo, contenedor=datos, mi_deposito=mi_deposito, otros=otros,
                           parametros_json={"densidad": str(PARAMETROS["densidad"]),
                                            "precio_litro": str(PARAMETROS["precio_litro"]),
                                            "comision": str(PARAMETROS["comision"]),
                                            "agua_por_litro": str(PARAMETROS["agua_por_litro"]),
                                            "biocombustible_por_litro": str(PARAMETROS["biocombustible_por_litro"])})


@web.get("/gemelo")
@requiere()
def gemelo_digital():
    """Acceso directo del equipo al gemelo digital (por defecto, el primer contenedor)."""
    conn = get_db()
    codigo = (request.args.get("c") or "").strip().upper()
    c = por_codigo(conn, codigo) if codigo else None
    c = c or conn.execute("SELECT * FROM contenedor ORDER BY id LIMIT 1").fetchone()
    if c is None:
        abort(404)
    return redirect(url_for("contenedores.pagina_contenedor", token=c["token"]))


@web.get("/contenedor/<codigo>")
def contenedor_por_codigo(codigo):
    """Para escribir el código del sticker a mano (CTN-0001) cuando la cámara no está disponible."""
    codigo = (codigo or "").strip().upper()
    if re.fullmatch(r"CTN-?\d{1,4}", codigo):
        codigo = f"CTN-{int(codigo.replace('CTN', '').strip('-')):04d}"
    c = por_codigo(get_db(), codigo)
    if c is None:
        return render_template("qr_desconocido.html"), 404
    return redirect(url_for("contenedores.pagina_contenedor", token=c["token"]))


@web.get("/qr/k/<token>.png")
def qr_contenedor(token):
    from .web import url_publica
    c = por_token(get_db(), token)
    if c is None:
        abort(404)
    r = Response(qr.png(f"{url_publica()}/k/{c['token']}", 900), mimetype="image/png")
    r.headers["Cache-Control"] = "public, max-age=3600"
    if request.args.get("descargar"):
        r.headers["Content-Disposition"] = f'attachment; filename="reaceite-{c["codigo"]}.png"'
    return r


# ---------------------------------------------------------------- API del comercio
def _contenedor_o_404(conn, token):
    c = por_token(conn, token)
    if c is None:
        raise ErrorNegocio("Este QR no es de un contenedor ReAceite.", codigo="qr_desconocido", http=404)
    return c


def _mi_deposito(conn, folio):
    d = conn.execute("SELECT * FROM deposito WHERE folio = ?", ((folio or "").strip().upper(),)).fetchone()
    if d is None or d["comercio_id"] != comercio_actual()["id"]:
        raise ErrorNegocio("No encontramos ese depósito.", http=404)
    return d


@api.post("/contenedores/<token>/depositos")
@requiere_comercio
def abrir(token):
    conn = get_db()
    with transaccion(conn):
        c = _contenedor_o_404(conn, token)
        d = abrir_deposito(conn, c, comercio_actual())
    return jsonify(vista_deposito(conn, d)), 201


@api.get("/depositos/<folio>")
@requiere_comercio
def ver_deposito(folio):
    conn = get_db()
    _despertar()
    return jsonify(vista_deposito(conn, _mi_deposito(conn, folio)))


@api.post("/depositos/<folio>/cancelar")
@requiere_comercio
def cancelar(folio):
    conn = get_db()
    with transaccion(conn):
        d = _mi_deposito(conn, folio)
        cancelar_deposito(conn, d)
        d = conn.execute("SELECT * FROM deposito WHERE id = ?", (d["id"],)).fetchone()
    return jsonify(vista_deposito(conn, d))


# ---------------------------------------------------------------- API del equipo (gemelo digital)
def _por_codigo_o_404(conn, codigo):
    c = por_codigo(conn, codigo)
    if c is None:
        raise ErrorNegocio("No existe ese contenedor.", http=404)
    return c


@api.get("/gemelo/<codigo>")
@requiere()
def gemelo(codigo):
    conn = get_db()
    c = _por_codigo_o_404(conn, codigo)
    return jsonify({**estado(conn, c), "comando": comando(conn, c)})


@api.post("/gemelo/<codigo>/senal")
@requiere()
def gemelo_senal(codigo):
    """El gemelo digital manda una lectura: el servidor la firma con el secreto del contenedor y la envía
    por HTTP al endpoint de telemetría, igual que lo haría el firmware."""
    datos = request.get_json(silent=True) or {}
    conn = get_db()
    c = _por_codigo_o_404(conn, codigo)
    tipo = datos.get("tipo")
    if tipo not in ("latido", "peso", "deposito.cerrado"):
        raise ErrorNegocio("Tipo de señal desconocido.")
    try:
        peso_g = max(0, int(datos.get("peso_g", c["peso_g"])))
    except (TypeError, ValueError):
        raise ErrorNegocio("peso_g debe ser un entero.") from None
    deposito = datos.get("deposito") or None
    try:
        envio = enviar_senal(current_app._get_current_object(), c, tipo, peso_g, deposito,
                             tapa_abierta=deposito_abierto(conn, c["id"]) is not None)
    except Exception as e:  # la red local falló
        raise ErrorNegocio(f"El contenedor no pudo enviar su señal ({type(e).__name__}).", http=502) from None
    return jsonify(envio)


@api.post("/contenedores/<codigo>/vaciar")
@requiere()
def vaciar_contenedor(codigo):
    conn = get_db()
    with transaccion(conn):
        c = _por_codigo_o_404(conn, codigo)
        vaciar(conn, c, usuario_actual())
        c = _releer(conn, c)
    return jsonify(estado(conn, c))


def lista(conn):
    return [estado(conn, c) for c in conn.execute("SELECT * FROM contenedor ORDER BY id").fetchall()]

