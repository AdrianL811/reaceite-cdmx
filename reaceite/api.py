"""API JSON de la PWA y receptor del webhook bancario."""
import json
import threading

from flask import Blueprint, current_app, jsonify, request, session

from . import clabe as clabe_mod
from . import cuentas, eventos, seed, servicios, transporte, vistas
from .config import PLANTA
from .auth import comercio_actual, iniciar_sesion_comercio, requiere, requiere_comercio, usuario_actual
from .db import get_db, transaccion
from .firma import verificar
from .servicios import ErrorNegocio

bp = Blueprint("api", __name__, url_prefix="/api")
webhooks = Blueprint("webhooks", __name__, url_prefix="/webhooks")


@bp.before_request
def _proteccion_csrf():
    # Un formulario de otro sitio no puede agregar cabeceras personalizadas sin permiso CORS.
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("X-ReAceite") != "1":
        return jsonify(error="csrf", mensaje="Petición rechazada: falta la cabecera X-ReAceite."), 403


@bp.errorhandler(ErrorNegocio)
def _error_negocio(e):
    return jsonify({"error": e.codigo, "mensaje": e.mensaje, **e.extra}), e.http


def _datos():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        raise ErrorNegocio("El cuerpo de la petición debe ser JSON.")
    return datos


def _comercio_o_404(conn, token):
    c = servicios.comercio_por_token(conn, token)
    if c is None:
        raise ErrorNegocio("Este código QR no está registrado.", codigo="qr_desconocido", http=404)
    return c


def _despertar():
    despachador = current_app.extensions.get("despachador")
    if despachador:
        despachador.despertar()


# ---------------------------------------------------------------- público
@bp.get("/parametros")
def parametros():
    return jsonify(vistas.parametros())


@bp.post("/comercios")
def registrar_comercio():
    """Alta del comercio con su cuenta (celular + PIN). Al terminar, el comercio queda con la sesión abierta."""
    datos = _datos()
    conn = get_db()
    with transaccion(conn):
        c = servicios.crear_comercio(conn, datos)
    iniciar_sesion_comercio(c)
    return jsonify(vistas.comercio(conn, c)), 201


@bp.get("/impacto")
def impacto():
    return jsonify(vistas.impacto(get_db()))


# ---------------------------------------------------------------- comercio (con su sesión)
def _mi_comercio(token=None):
    """El comercio de la sesión. Si la petición nombra otro token, se rechaza: cada quien ve solo lo suyo."""
    c = comercio_actual()
    if token is not None and str(token).strip().upper() != c["token"]:
        raise ErrorNegocio("Esta pantalla es de otro comercio. Entra con tu propia cuenta.", codigo="otro_comercio",
                           http=403)
    return c


def _releer(conn, c):
    return conn.execute("SELECT * FROM comercio WHERE id = ?", (c["id"],)).fetchone()


@bp.get("/comercio/<token>")
@requiere_comercio
def ver_comercio(token):
    return jsonify(vistas.comercio(get_db(), _mi_comercio(token)))


@bp.post("/solicitudes")
@requiere_comercio
def crear_solicitud():
    datos = _datos()
    conn = get_db()
    with transaccion(conn):
        c = _releer(conn, _mi_comercio(datos.get("token")))
        solicitud, ruta = servicios.crear_solicitud(conn, c, datos.get("litros"), datos.get("franja"))
    respuesta = vistas.comercio(conn, c)
    respuesta["creada"] = solicitud["folio"]
    respuesta["ruta_generada"] = ruta["folio"] if ruta else None
    return jsonify(respuesta), 201


@bp.post("/solicitudes/<folio>/cancelar")
@requiere_comercio
def cancelar_solicitud(folio):
    datos = _datos()
    conn = get_db()
    with transaccion(conn):
        c = _releer(conn, _mi_comercio(datos.get("token")))
        servicios.cancelar_solicitud(conn, c, folio)
    return jsonify(vistas.comercio(conn, c))


@bp.post("/mi-comercio/qr/confirmar")
@requiere_comercio
def confirmar_qr():
    conn = get_db()
    with transaccion(conn):
        c = servicios.confirmar_qr_pegado(conn, _releer(conn, _mi_comercio()))
    return jsonify(vistas.comercio(conn, c))


@bp.post("/mi-comercio/qr/reemplazar")
@requiere_comercio
def reemplazar_qr():
    datos = _datos()
    conn = get_db()
    c = _mi_comercio()
    cuentas.confirmar_pin(conn, c["id"], datos.get("pin"), current_app.config)
    with transaccion(conn):
        c = servicios.reemplazar_qr(conn, _releer(conn, c))
    return jsonify(vistas.comercio(conn, c))


@bp.post("/mi-comercio/pin")
@requiere_comercio
def cambiar_pin():
    datos = _datos()
    conn = get_db()
    c = _mi_comercio()
    sal = cuentas.cambiar_pin(conn, c["id"], datos.get("actual"), datos.get("nuevo"), datos.get("confirmacion"),
                              current_app.config)
    session["csal"] = sal  # este teléfono sigue dentro; los demás tendrán que volver a entrar
    return jsonify(ok=True, mensaje="Listo: tu PIN cambió. Tus sesiones en otros teléfonos se cerraron.")


@bp.get("/mi-comercio/billetera")
@requiere_comercio
def billetera():
    """Saldo y movimientos de la billetera del comercio, consultados a la API de la pasarela de pagos."""
    c = comercio_actual()
    app = current_app._get_current_object()
    cabeceras = {"Authorization": f"Bearer {app.config['SPEI_API_KEY']}", "Accept": "application/json"}
    try:
        r = transporte.enviar(app, "GET", f"/sim-spei/v1/cuentas/{c['clabe']}/movimientos?limite=5", None, cabeceras,
                              timeout=5)
    except Exception:
        raise ErrorNegocio("No pudimos consultar tu billetera. Intenta en un momento.", codigo="pasarela", http=502) \
            from None
    if r.status == 404:
        return jsonify(activa=False, saldo="0.00", movimientos=[], celular=cuentas.formato_telefono(c["telefono"]),
                       clabe=clabe_mod.enmascarar(c["clabe"]))
    if r.status != 200:
        raise ErrorNegocio("La pasarela de pagos no respondió bien. Intenta en un momento.", codigo="pasarela", http=502)
    datos = r.json()
    return jsonify(
        activa=True,
        saldo=datos["saldo"],
        movimientos=datos["movimientos"],
        celular=cuentas.formato_telefono(c["telefono"]),
        clabe=clabe_mod.enmascarar(c["clabe"]),
        fuente={"url": "/sim-spei/v1/cuentas/••••/movimientos", "status": r.status, "latencia_ms": round(r.ms, 1),
                "transporte": r.transporte},
    )


# ---------------------------------------------------------------- recolector
@bp.get("/rutas")
@requiere()
def rutas():
    return jsonify(vistas.rutas(get_db()))


@bp.get("/buscar")
@requiere()
def buscar_por_codigo():
    codigo = (request.args.get("codigo") or "").strip().upper()
    fila = get_db().execute("SELECT token FROM comercio WHERE codigo = ?", (codigo,)).fetchone()
    if fila is None:
        raise ErrorNegocio(f"No hay ningún comercio con el código {codigo}.", http=404)
    return jsonify(token=fila["token"])


@bp.get("/pesaje/<token>")
@requiere()
def previa_pesaje(token):
    conn = get_db()
    return jsonify(vistas.previa_pesaje(conn, _comercio_o_404(conn, token)))


@bp.post("/recolecciones")
@requiere()
def confirmar_recoleccion():
    datos = _datos()
    conn = get_db()
    with transaccion(conn):
        c = _comercio_o_404(conn, datos.get("token"))
        r = servicios.confirmar_recoleccion(
            conn, c, usuario_actual(), datos.get("peso_kg"),
            confirmar_anomalia=bool(datos.get("confirmar_anomalia")),
            crear_si_falta=bool(datos.get("crear_si_falta")),
        )
    _despertar()
    return jsonify({
        "recoleccion": r["recoleccion"]["folio"],
        "pago": vistas.pago(conn, r["pago"]["folio"]),
        "metricas": {k: str(v) for k, v in r["metricas"].items()},
        "anomalia": r["anomalia"],
    }), 201


@bp.get("/pagos/<folio>")
@requiere()
def ver_pago(folio):
    _despertar()
    datos = vistas.pago(get_db(), folio)
    if datos is None:
        raise ErrorNegocio("No existe ese pago.", http=404)
    return jsonify(datos)


@bp.get("/monitor")
@requiere()
def monitor():
    _despertar()
    try:
        desde = int(request.args.get("desde", "0"))
    except ValueError:
        desde = 0
    return jsonify(vistas.monitor(get_db(), desde))


@bp.post("/admin/restablecer")
@requiere("admin")
def restablecer():
    conn = get_db()
    with transaccion(conn):
        seed.sembrar(conn, current_app.config)
        eventos.registrar(conn, "demo.restablecida", "Datos de demostración restablecidos")
    return jsonify({"ok": True})


@bp.post("/admin/lotes")
@requiere("admin")
def vender_lote():
    """Vende a la planta el aceite ya pagado y aún no vendido; el cobro recarga el Fondo de Garantía."""
    conn = get_db()
    with transaccion(conn):
        lote = servicios.vender_lote(conn, PLANTA["nombre"])
    _despertar()
    return jsonify(lote), 201


@bp.post("/admin/comercios/<codigo>/pin")
@requiere("admin")
def restablecer_pin(codigo):
    """PIN temporal para un comercio que olvidó el suyo. Se muestra una sola vez a la administración."""
    codigo = (codigo or "").strip().upper()
    if codigo.isdigit():
        codigo = f"COM-{codigo}"
    if codigo.startswith("COM") and not codigo.startswith("COM-"):
        codigo = "COM-" + codigo[3:]
    if codigo.startswith("COM-") and codigo[4:].isdigit():
        codigo = f"COM-{int(codigo[4:]):04d}"
    conn = get_db()
    with transaccion(conn):
        c = conn.execute("SELECT * FROM comercio WHERE codigo = ?", (codigo,)).fetchone()
        if c is None:
            raise ErrorNegocio(f"No hay ningún comercio con el código {codigo}.", http=404)
        if not c["telefono"]:
            raise ErrorNegocio(f"{codigo} no tiene celular registrado: no puede tener cuenta.", http=409)
        pin = cuentas.restablecer_pin(conn, c)
    return jsonify(codigo=c["codigo"], nombre=c["nombre"], telefono=cuentas.formato_telefono(c["telefono"]), pin=pin)


# ---------------------------------------------------------------- webhook del banco
@webhooks.post("/spei")
def webhook_spei():
    cuerpo = request.get_data(cache=False)
    ok, motivo = verificar(current_app.config["WEBHOOK_SECRET"], cuerpo, request.headers.get("X-Spei-Firma", ""))
    conn = get_db()
    if not ok:
        from . import eventos
        with transaccion(conn):
            eventos.registrar(conn, "spei.webhook_rechazado", f"Webhook rechazado: {motivo}",
                              detalle={"cabeceras": {k: v for k, v in request.headers.items() if k.startswith("X-")}})
        return jsonify(error="firma", mensaje=motivo), 401
    try:
        datos = json.loads(cuerpo)
    except ValueError:
        return jsonify(error="json_invalido"), 400
    try:
        with transaccion(conn):
            resultado = servicios.aplicar_liquidacion(
                conn, datos, firma_ok_detalle=f"válida (entrega {request.headers.get('X-Spei-Entrega', '')[:12]})")
    except ErrorNegocio as e:
        return jsonify(error=e.codigo, mensaje=e.mensaje), e.http
    url = current_app.config.get("NOTIFY_WEBHOOK_URL")
    if url and not resultado["duplicado"]:
        _notificar_externo(current_app._get_current_object(), url, datos)
    return jsonify(ok=True, duplicado=resultado["duplicado"])


def _notificar_externo(app, url, datos):
    """Copia opcional del pago liquidado a un webhook externo (Make, webhook.site...)."""
    def enviar():
        try:
            cuerpo = json.dumps({"evento": "pago.liquidado", **datos}, ensure_ascii=False).encode()
            transporte.enviar(app, "POST", url, cuerpo, {"Content-Type": "application/json"}, timeout=5)
        except Exception:
            pass
    threading.Thread(target=enviar, daemon=True).start()
