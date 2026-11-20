import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reaceite import create_app  # noqa: E402

H = {"X-ReAceite": "1"}


@pytest.fixture
def app(tmp_path):
    return create_app({
        "TESTING": True,
        "DB_PATH": str(tmp_path / "prueba.db"),
        "DESPACHADOR_AUTO": False,
        "TRANSPORTE": "inproc",
        "INTERNAL_BASE_URL": "http://localhost",
        "SPEI_DEMORA_S": 0,
        "SECRET_KEY": "pruebas",
        "RECOLECTOR_PASSWORD": "aceite2026",
        "ADMIN_PASSWORD": "admin-pruebas",
        "PIN_DEMO": "900900",
    })


@pytest.fixture
def cliente(app):
    return app.test_client()


def entrar(cliente, usuario="recolector", clave="aceite2026"):
    r = cliente.post("/entrar", data={"usuario": usuario, "clave": clave})
    assert r.status_code == 302, r.data
    return r


def entrar_comercio(cliente, telefono="5510000006", pin="900900"):
    """Inicia la sesión de un comercio (por defecto, el Puesto demo COM-0006)."""
    r = cliente.post("/comercio/entrar", data={"telefono": telefono, "pin": pin})
    assert r.status_code == 302, r.data
    return r


def token(app, codigo):
    from reaceite.db import conectar
    conn = conectar(app.config["DB_PATH"])
    try:
        return conn.execute("SELECT token FROM comercio WHERE codigo = ?", (codigo,)).fetchone()[0]
    finally:
        conn.close()
