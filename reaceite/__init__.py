"""ReAceite CDMX: PWA para recolectar aceite de cocina usado con pago inmediato."""
import logging
import os

from flask import Flask, request
from werkzeug.middleware.proxy_fix import ProxyFix

from . import api, auth, db, seed, spei_sim, web
from .config import Config
from .despachador import Despachador

CSP = (
    "default-src 'self'; "
    "img-src 'self' data: blob: https://tile.openstreetmap.org; "
    "style-src 'self' 'unsafe-inline'; "
    "script-src 'self'; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "media-src 'self' blob:; "
    "worker-src 'self'; "
    "manifest-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config:
        app.config.update(config)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    os.makedirs(os.path.dirname(os.path.abspath(app.config["DB_PATH"])), exist_ok=True)
    conn = db.conectar(app.config["DB_PATH"])
    try:
        db.crear_esquema(conn)
        with db.transaccion(conn):
            if conn.execute("SELECT COUNT(*) FROM usuario").fetchone()[0] == 0:
                seed.sembrar(conn, app.config)
                app.logger.info("Base de datos vacía: se cargaron los datos de demostración")
    finally:
        conn.close()

    app.teardown_appcontext(db.cerrar_db)
    app.register_blueprint(web.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(api.webhooks)
    app.register_blueprint(spei_sim.bp)

    @app.after_request
    def _cabeceras(respuesta):
        respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
        respuesta.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        respuesta.headers.setdefault("Permissions-Policy", "camera=(self), geolocation=(self), microphone=()")
        if respuesta.mimetype == "text/html":
            respuesta.headers.setdefault("Content-Security-Policy", CSP)
        if request.path.startswith("/api/"):
            respuesta.headers["Cache-Control"] = "no-store"
        return respuesta

    despachador = Despachador(app)
    app.extensions["despachador"] = despachador
    if app.config.get("DESPACHADOR_AUTO"):
        despachador.iniciar()
    return app
