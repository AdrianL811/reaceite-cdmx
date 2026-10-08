"""Páginas HTML de la PWA, códigos QR, manifiesto y service worker."""
import json
import os

from flask import (Blueprint, Response, abort, current_app, jsonify, render_template, request, send_from_directory,
                   url_for)

from . import qr, servicios, vistas
from .auth import requiere, usuario_actual
from .config import FRANJAS, LITROS_OPCIONES, TIPOS_COMERCIO, ZONAS
from .db import get_db

bp = Blueprint("web", __name__)


def url_publica():
    base = current_app.config.get("PUBLIC_BASE_URL") or request.url_root
    return base.rstrip("/")


@bp.app_context_processor
def _contexto():
    return {"usuario": usuario_actual(), "zonas": ZONAS, "franjas": FRANJAS, "parametros": vistas.parametros()}


@bp.get("/")
def inicio():
    return render_template("inicio.html", url_app=url_publica())


@bp.get("/registro")
def registro():
    return render_template("registro.html", tipos=TIPOS_COMERCIO)


@bp.get("/c/<token>")
def comercio(token):
    c = servicios.comercio_por_token(get_db(), token)
    if c is None:
        return render_template("qr_desconocido.html"), 404
    return render_template("comercio.html", comercio=c, litros_opciones=LITROS_OPCIONES)


@bp.get("/r")
@requiere()
def recolector():
    return render_template("recolector.html")


@bp.get("/r/pesar/<token>")
@requiere()
def pesar(token):
    c = servicios.comercio_por_token(get_db(), token)
    if c is None:
        return render_template("qr_desconocido.html"), 404
    return render_template("pesar.html", comercio=c)


@bp.get("/impacto")
def impacto():
    return render_template("impacto.html")


@bp.get("/monitor")
@requiere()
def monitor():
    return render_template("monitor.html")


@bp.get("/proyecto")
def proyecto():
    fotos = {}
    for clave in ("hojas", "matriz"):
        fotos[clave] = None
        for extension in ("jpg", "jpeg", "png", "webp"):
            relativa = f"img/crazy8/{clave}.{extension}"
            if os.path.exists(os.path.join(current_app.static_folder, relativa)):
                fotos[clave] = url_for("static", filename=relativa)
                break
    return render_template("proyecto.html", url_app=url_publica(), fotos=fotos)


@bp.get("/stickers")
@requiere("admin")
def stickers():
    filas = get_db().execute("SELECT codigo, token, nombre, tipo, zona FROM comercio ORDER BY id").fetchall()
    return render_template("stickers.html", comercios=filas, url_app=url_publica())


@bp.get("/portada")
def portada():
    return render_template("portada.html", url_app=url_publica())


# ---------------------------------------------------------------- QR
def _png(datos, nombre):
    r = Response(datos, mimetype="image/png")
    r.headers["Cache-Control"] = "public, max-age=3600"
    if request.args.get("descargar"):
        r.headers["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return r


@bp.get("/qr/app.png")
def qr_app():
    return _png(qr.png(url_publica() + "/"), "reaceite-qr-portada.png")


@bp.get("/qr/c/<token>.png")
def qr_comercio(token):
    c = servicios.comercio_por_token(get_db(), token)
    if c is None:
        abort(404)
    return _png(qr.png(f"{url_publica()}/c/{c['token']}", 900), f"reaceite-{c['codigo']}.png")


@bp.get("/qr/c/<token>.svg")
def qr_comercio_svg(token):
    c = servicios.comercio_por_token(get_db(), token)
    if c is None:
        abort(404)
    return Response(qr.svg(f"{url_publica()}/c/{c['token']}"), mimetype="image/svg+xml")


# ---------------------------------------------------------------- PWA
@bp.get("/manifest.webmanifest")
def manifiesto():
    datos = {
        "name": "ReAceite CDMX",
        "short_name": "ReAceite",
        "description": "Recolección de aceite de cocina usado con pago inmediato.",
        "lang": "es-MX",
        "start_url": "/?origen=pwa",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#F2F5F2",
        "theme_color": "#12383D",
        "categories": ["utilities", "business"],
        "icons": [
            {"src": url_for("static", filename="icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": url_for("static", filename="icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": url_for("static", filename="icons/maskable-512.png"), "sizes": "512x512", "type": "image/png",
             "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Soy recolector", "url": "/r"},
            {"name": "Impacto del piloto", "url": "/impacto"},
        ],
    }
    return Response(json.dumps(datos, ensure_ascii=False), mimetype="application/manifest+json")


@bp.get("/sw.js")
def service_worker():
    r = send_from_directory(current_app.static_folder, "js/sw.js", mimetype="application/javascript")
    r.headers["Cache-Control"] = "no-cache"
    r.headers["Service-Worker-Allowed"] = "/"
    return r


@bp.get("/offline")
def offline():
    return render_template("offline.html")


@bp.get("/salud")
def salud():
    get_db().execute("SELECT 1").fetchone()
    despachador = current_app.extensions.get("despachador")
    return jsonify(ok=True, despachador=bool(despachador and despachador.vivo))
