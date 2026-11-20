"""Cuentas de comercio: celular + PIN, bloqueo, sesiones y el QR según quién lo escanea."""
import time
from datetime import timedelta

from conftest import H, entrar, entrar_comercio, token

from reaceite.db import ahora_utc, conectar, iso


def sql(app, consulta, *args):
    conn = conectar(app.config["DB_PATH"])
    try:
        conn.execute(consulta, args)
    finally:
        conn.close()


def test_el_qr_abre_algo_distinto_segun_quien_lo_escanea(app, cliente):
    t6 = token(app, "COM-0006")
    publico = cliente.get(f"/c/{t6}")
    assert publico.status_code == 200
    assert "Es mi bote".encode() in publico.data and b"Pedir recolecci" not in publico.data

    recolector = app.test_client()
    entrar(recolector)
    r = recolector.get(f"/c/{t6}")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/r/pesar/{t6}")

    dueno = app.test_client()
    entrar_comercio(dueno)
    panel = dueno.get(f"/c/{t6}")
    assert panel.status_code == 200 and b"Mi QR" in panel.data and b"Pedir recolecci" in panel.data
    assert "no-store" in panel.headers["Cache-Control"]

    vecino = app.test_client()
    entrar_comercio(vecino, "55 1000 0002")
    r = vecino.get(f"/c/{t6}")
    assert r.status_code == 200 and "es de otro comercio".encode() in r.data
    # Ni por la API puede ver o pedir a nombre de otro comercio.
    assert vecino.get(f"/api/comercio/{t6}").status_code == 403
    r = vecino.post("/api/solicitudes", json={"token": t6, "litros": 5, "franja": "10-12"}, headers=H)
    assert r.status_code == 403 and r.get_json()["error"] == "otro_comercio"

    assert cliente.get("/c/NOEXISTE").status_code == 404


def test_bloqueo_tras_cinco_pin_incorrectos(app, cliente):
    for quedan in (4, 3, 2, 1):
        r = cliente.post("/comercio/entrar", data={"telefono": "5510000006", "pin": "111222"})
        assert r.status_code == 401
        assert f"{quedan} intento".encode() in r.data
    r = cliente.post("/comercio/entrar", data={"telefono": "5510000006", "pin": "111222"})
    assert r.status_code == 429 and "bloqueamos la cuenta 15 min".encode() in r.data
    # Bloqueada, ni el PIN correcto entra.
    assert cliente.post("/comercio/entrar", data={"telefono": "5510000006", "pin": "900900"}).status_code == 429
    sql(app, "UPDATE comercio SET bloqueado_hasta = ? WHERE codigo = 'COM-0006'", iso(ahora_utc() - timedelta(minutes=1)))
    entrar_comercio(cliente)
    # Un celular que no existe recibe el mismo mensaje genérico.
    r = app.test_client().post("/comercio/entrar", data={"telefono": "5500000000", "pin": "900900"})
    assert r.status_code == 401 and "no coinciden".encode() in r.data


def test_cambiar_pin_cierra_las_demas_sesiones(app, cliente):
    otro_telefono = app.test_client()
    entrar_comercio(cliente)
    entrar_comercio(otro_telefono)
    t6 = token(app, "COM-0006")

    r = cliente.post("/api/mi-comercio/pin", json={"actual": "000111", "nuevo": "482913", "confirmacion": "482913"},
                     headers=H)
    assert r.status_code == 403 and r.get_json()["error"] == "credenciales"
    r = cliente.post("/api/mi-comercio/pin", json={"actual": "900900", "nuevo": "111111", "confirmacion": "111111"},
                     headers=H)
    assert r.status_code == 400 and r.get_json()["error"] == "pin_debil"
    r = cliente.post("/api/mi-comercio/pin", json={"actual": "900900", "nuevo": "482913", "confirmacion": "482913"},
                     headers=H)
    assert r.status_code == 200, r.data

    assert cliente.get(f"/api/comercio/{t6}").status_code == 200       # este teléfono sigue dentro
    assert otro_telefono.get(f"/api/comercio/{t6}").status_code == 401  # el otro tiene que volver a entrar
    nuevo = app.test_client()
    assert nuevo.post("/comercio/entrar", data={"telefono": "5510000006", "pin": "900900"}).status_code == 401
    entrar_comercio(nuevo, pin="482913")


def test_la_administracion_restablece_el_pin(app, cliente):
    entrar(cliente)
    assert cliente.post("/api/admin/comercios/COM-0006/pin", json={}, headers=H).status_code == 403
    admin = app.test_client()
    entrar(admin, "admin", "admin-pruebas")
    assert admin.post("/api/admin/comercios/COM-0999/pin", json={}, headers=H).status_code == 404
    sesion_vieja = app.test_client()
    entrar_comercio(sesion_vieja)

    r = admin.post("/api/admin/comercios/com6/pin", json={}, headers=H)
    assert r.status_code == 200, r.data
    datos = r.get_json()
    assert datos["codigo"] == "COM-0006" and datos["telefono"] == "55 1000 0006"
    assert len(datos["pin"]) == 6 and datos["pin"].isdigit()

    t6 = token(app, "COM-0006")
    assert sesion_vieja.get(f"/api/comercio/{t6}").status_code == 401
    assert app.test_client().post("/comercio/entrar", data={"telefono": "5510000006", "pin": "900900"}).status_code == 401
    dueno = app.test_client()
    entrar_comercio(dueno, pin=datos["pin"])
    assert dueno.get(f"/api/comercio/{t6}").get_json()["pin_temporal"] is True
    assert "PIN temporal".encode() in dueno.get(f"/c/{t6}").data
    r = dueno.post("/api/mi-comercio/pin", json={"actual": datos["pin"], "nuevo": "482913", "confirmacion": "482913"},
                   headers=H)
    assert r.status_code == 200
    assert dueno.get(f"/api/comercio/{t6}").get_json()["pin_temporal"] is False


def test_reemplazar_el_qr(app, cliente):
    entrar_comercio(cliente)
    viejo = token(app, "COM-0006")
    r = cliente.post("/api/mi-comercio/qr/reemplazar", json={"pin": "123123"}, headers=H)
    assert r.status_code == 403
    r = cliente.post("/api/mi-comercio/qr/reemplazar", json={"pin": "900900"}, headers=H)
    assert r.status_code == 200, r.data
    nuevo = r.get_json()
    assert nuevo["token"] != viejo and nuevo["qr"]["pegado"] is False
    assert app.test_client().get(f"/c/{viejo}").status_code == 404     # el sticker anterior ya no sirve
    assert cliente.get(f"/c/{nuevo['token']}").status_code == 200
    r = cliente.post("/api/mi-comercio/qr/confirmar", json={}, headers=H)
    assert r.status_code == 200 and r.get_json()["qr"]["pegado"] is True


def test_sesiones_y_reinicios_de_la_base(app, cliente):
    # Un comercio nuevo (id 9) con su sesión abierta.
    r = cliente.post("/api/comercios", json={
        "nombre": "Tortas Doña Rosa", "tipo": "Fonda", "direccion": "Calle Tlaxcala 12", "zona": "condesa",
        "telefono": "5522223333", "pin": "482913", "pin2": "482913"}, headers=H)
    assert r.status_code == 201
    demo = app.test_client()
    entrar_comercio(demo)

    admin = app.test_client()
    entrar(admin, "admin", "admin-pruebas")
    assert admin.post("/api/admin/restablecer", json={}, headers=H).status_code == 200

    # Otro comercio se registra y recibe el mismo id 9: la sesión vieja no debe abrir su cuenta.
    otro = app.test_client()
    r = otro.post("/api/comercios", json={
        "nombre": "Jugos La Güera", "tipo": "Puesto ambulante", "direccion": "Calle Sonora 3", "zona": "condesa",
        "telefono": "5544445555", "pin": "582913", "pin2": "582913"}, headers=H)
    assert r.status_code == 201 and r.get_json()["codigo"] == "COM-0009"
    assert cliente.get(f"/api/comercio/{r.get_json()['token']}").status_code == 401

    # Los comercios de demostración conservan su sesión tras restablecer los datos.
    assert demo.get(f"/api/comercio/{token(app, 'COM-0006')}").status_code == 200


def test_mi_comercio_sticker_y_sesion_del_equipo(app, cliente):
    r = cliente.get("/mi-comercio")
    assert r.status_code == 302 and "/comercio/entrar" in r.headers["Location"]
    entrar_comercio(cliente)
    r = cliente.get("/mi-comercio")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/c/{token(app, 'COM-0006')}")
    sticker = cliente.get("/mi-comercio/sticker")
    assert sticker.status_code == 200 and b"Puesto demo" in sticker.data
    assert cliente.get("/registro").status_code == 302    # con sesión abierta no se registra otra vez

    # La sesión del recolector caduca a las 12 horas.
    recolector = app.test_client()
    entrar(recolector)
    assert recolector.get("/r").status_code == 200
    with recolector.session_transaction() as s:
        s["exp"] = int(time.time()) - 1
    r = recolector.get("/r")
    assert r.status_code == 302 and "/entrar" in r.headers["Location"]
