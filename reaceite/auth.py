"""Sesiones firmadas en cookie: el equipo (recolector y administración) y los comercios.

Una cookie guarda una sola identidad a la vez:
- equipo: `uid` y `exp` (caduca a las 12 horas);
- comercio: `cid` y `csal` (dura 90 días y se renueva con cada visita). `csal` debe coincidir con
  la sal guardada en la base: si el comercio cambia su PIN, si la administración lo restablece o si
  la base se reinicia, las sesiones anteriores dejan de valer.
"""
import time
from functools import wraps

from flask import (Blueprint, current_app, g, jsonify, redirect, render_template, request, session,
                   url_for)
from werkzeug.security import check_password_hash

from . import cuentas
from .db import get_db
from .errores import ErrorNegocio

bp = Blueprint("auth", __name__)


# ---------------------------------------------------------------- equipo
def usuario_actual():
    if "usuario" not in g:
        g.usuario = None
        uid = session.get("uid")
        if uid:
            exp = session.get("exp")
            if exp is None:  # sesiones abiertas antes de que existiera la caducidad
                session["exp"] = exp = int(time.time()) + current_app.config["SESION_EQUIPO_HORAS"] * 3600
            if exp < time.time():
                session.clear()
            else:
                fila = get_db().execute("SELECT id, usuario, nombre, rol FROM usuario WHERE id = ?", (uid,)).fetchone()
                g.usuario = dict(fila) if fila else None
    return g.usuario


def requiere(rol=None):
    """rol=None: cualquier persona del equipo con sesión; rol='admin': solo administración."""
    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            u = usuario_actual()
            permitido = u is not None and (rol is None or u["rol"] == rol)
            if permitido:
                return vista(*args, **kwargs)
            if request.path.startswith("/api/"):
                if u is None:
                    return jsonify(error="sesion", mensaje="Inicia sesión como recolector."), 401
                return jsonify(error="permiso", mensaje="Tu usuario no tiene permiso para esto."), 403
            return redirect(url_for("auth.login", siguiente=request.full_path.rstrip("?")))
        return envoltura
    return decorador


# ---------------------------------------------------------------- comercios
def comercio_actual():
    """El comercio de la sesión, o None si no hay sesión de comercio o ya no es válida."""
    if "comercio_sesion" not in g:
        g.comercio_sesion = None
        cid, sal = session.get("cid"), session.get("csal")
        if cid:
            fila = get_db().execute("SELECT * FROM comercio WHERE id = ?", (cid,)).fetchone()
            if fila and fila["sesion_sal"] and fila["sesion_sal"] == sal:
                g.comercio_sesion = fila
            else:
                session.pop("cid", None)
                session.pop("csal", None)
    return g.comercio_sesion


def iniciar_sesion_comercio(c):
    session.clear()
    session["cid"] = c["id"]
    session["csal"] = c["sesion_sal"]
    session.permanent = True
    g.comercio_sesion = c
    g.usuario = None


def requiere_comercio(vista):
    @wraps(vista)
    def envoltura(*args, **kwargs):
        if comercio_actual() is not None:
            return vista(*args, **kwargs)
        if request.path.startswith("/api/"):
            return jsonify(error="sesion_comercio",
                           mensaje="Tu sesión terminó. Entra con tu celular y tu PIN."), 401
        return redirect(url_for("auth.login_comercio", siguiente=request.full_path.rstrip("?")))
    return envoltura


# ---------------------------------------------------------------- inicio y cierre de sesión
def _destino_seguro(destino, defecto):
    if destino and destino.startswith("/") and not destino.startswith("//") and "\\" not in destino:
        return destino
    return defecto


@bp.route("/entrar", methods=["GET", "POST"])
def login():
    siguiente = request.values.get("siguiente", "")
    error = None
    if request.method == "POST":
        usuario = (request.form.get("usuario") or "").strip().lower()
        clave = request.form.get("clave") or ""
        fila = get_db().execute("SELECT * FROM usuario WHERE usuario = ?", (usuario,)).fetchone()
        if fila and check_password_hash(fila["hash"], clave):
            session.clear()
            session["uid"] = fila["id"]
            session["exp"] = int(time.time()) + current_app.config["SESION_EQUIPO_HORAS"] * 3600
            session.permanent = True
            return redirect(_destino_seguro(siguiente, url_for("web.recolector")))
        error = "El usuario o la contraseña no coinciden."
    return render_template("entrar.html", siguiente=siguiente, error=error), (401 if error else 200)


@bp.route("/comercio/entrar", methods=["GET", "POST"])
def login_comercio():
    siguiente = request.values.get("siguiente", "")
    error, telefono, status = None, "", 200
    if request.method == "POST":
        telefono = (request.form.get("telefono") or "").strip()[:20]
        try:
            c = cuentas.iniciar_sesion(get_db(), telefono, request.form.get("pin"), current_app.config)
        except ErrorNegocio as e:
            error, status = e.mensaje, e.http
        else:
            iniciar_sesion_comercio(c)
            return redirect(_destino_seguro(siguiente, url_for("web.comercio", token=c["token"])))
    elif comercio_actual() is not None:
        c = comercio_actual()
        return redirect(_destino_seguro(siguiente, url_for("web.comercio", token=c["token"])))
    return render_template("entrar_comercio.html", siguiente=siguiente, error=error, telefono=telefono), status


@bp.post("/salir")
def logout():
    session.clear()
    return redirect(url_for("web.inicio"))
