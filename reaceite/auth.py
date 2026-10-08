"""Inicio de sesión del recolector y de la administración (sesión firmada en cookie)."""
from functools import wraps

from flask import Blueprint, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from .db import get_db

bp = Blueprint("auth", __name__)


def usuario_actual():
    if "usuario" not in g:
        uid = session.get("uid")
        g.usuario = None
        if uid:
            fila = get_db().execute("SELECT id, usuario, nombre, rol FROM usuario WHERE id = ?", (uid,)).fetchone()
            g.usuario = dict(fila) if fila else None
    return g.usuario


def requiere(rol=None):
    """rol=None: cualquier usuario con sesión; rol='admin': solo administración."""
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


def _destino_seguro(destino):
    if destino and destino.startswith("/") and not destino.startswith("//") and "\\" not in destino:
        return destino
    return url_for("web.recolector")


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
            session.permanent = True
            return redirect(_destino_seguro(siguiente))
        error = "El usuario o la contraseña no coinciden."
    return render_template("entrar.html", siguiente=siguiente, error=error), (401 if error else 200)


@bp.post("/salir")
def logout():
    session.clear()
    return redirect(url_for("web.inicio"))
