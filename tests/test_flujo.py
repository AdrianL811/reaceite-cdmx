"""Flujo completo de la demostración, de la solicitud al pago liquidado."""
import json
from datetime import timedelta

from conftest import H, entrar, entrar_comercio, token

from reaceite.db import ahora_utc, conectar, iso, transaccion
from reaceite.firma import firmar


def tick(app):
    return app.extensions["despachador"].tick()


def etapas(app, ref):
    conn = conectar(app.config["DB_PATH"])
    try:
        return [f[0] for f in conn.execute(
            "SELECT etapa FROM evento WHERE ref = ? AND etapa IS NOT NULL ORDER BY id", (ref,))]
    finally:
        conn.close()


def test_escenario_de_la_demo(app, cliente):
    t6 = token(app, "COM-0006")
    # Sin sesión del comercio no se ve su panel ni se puede pedir.
    assert cliente.get(f"/api/comercio/{t6}").status_code == 401
    assert cliente.post("/api/solicitudes", json={"token": t6, "litros": 5, "franja": "10-12"},
                        headers=H).status_code == 401
    entrar_comercio(cliente)
    zona = cliente.get(f"/api/comercio/{t6}").get_json()["zona"]
    assert zona["nombre"] == "Hipódromo" and zona["litros_pendientes"] == 15

    r = cliente.post("/api/solicitudes", json={"token": t6, "litros": 5, "franja": "10-12"}, headers=H)
    assert r.status_code == 201, r.data
    datos = r.get_json()
    assert datos["ruta_generada"] == "RUT-0001"
    assert datos["solicitud"]["estado"] == "EN_RUTA"
    assert datos["solicitud"]["ruta"]["de"] == 3

    # Una segunda solicitud del mismo comercio no se duplica.
    r = cliente.post("/api/solicitudes", json={"token": t6, "litros": 5, "franja": "10-12"}, headers=H)
    assert r.status_code == 409 and r.get_json()["error"] == "solicitud_abierta"

    # Con la sesión del comercio no se puede pesar: eso es del recolector.
    r = cliente.post("/api/recolecciones", json={"token": t6, "peso_kg": "4.6"}, headers=H)
    assert r.status_code == 401

    comercio = app.test_client()
    entrar_comercio(comercio)
    entrar(cliente)
    rutas = cliente.get("/api/rutas").get_json()["rutas"]
    assert len(rutas) == 1 and len(rutas[0]["paradas"]) == 3
    assert rutas[0]["distancia_km"] <= rutas[0]["distancia_base_km"]

    r = cliente.post("/api/recolecciones", json={"token": t6, "peso_kg": "4.6"}, headers=H)
    assert r.status_code == 201, r.data
    rec = r.get_json()
    assert rec["metricas"]["litros"] == "5.00" and rec["metricas"]["pago_neto"] == "27.00"
    assert rec["pago"]["estatus"] == "PENDIENTE"
    folio_pago, folio_rec = rec["pago"]["folio"], rec["recoleccion"]
    assert etapas(app, folio_rec) == [1, 2, 3, 4, 5]

    assert tick(app) > 0
    pago = cliente.get(f"/api/pagos/{folio_pago}").get_json()
    assert pago["estatus"] == "LIQUIDADO", pago
    assert pago["clave_rastreo"].startswith("RAC") and pago["monto"] == "27.00"
    assert etapas(app, folio_rec) == [1, 2, 3, 4, 5, 6, 7, 8]

    vista = comercio.get(f"/api/comercio/{t6}").get_json()
    assert vista["acumulado"] == {"litros": "5.00", "agua_l": 5000, "cobrado": "27.00"}
    assert vista["solicitud"] is None
    assert vista["ultimo_pago"]["estatus"] == "LIQUIDADO"

    monitor = cliente.get("/api/monitor").get_json()
    assert monitor["pipeline"]["recoleccion"] == folio_rec
    assert [e["etapa"] for e in monitor["pipeline"]["etapas"]] == list(range(1, 9))

    impacto = cliente.get("/api/impacto").get_json()
    assert impacto["pagos"] == 16  # 15 del historial (11 en ruta y 4 en contenedores) + la demo


def test_webhook_repetido_y_firma_falsa(app, cliente):
    t6 = token(app, "COM-0006")
    entrar_comercio(cliente)
    cliente.post("/api/solicitudes", json={"token": t6, "litros": 5, "franja": "10-12"}, headers=H)
    entrar(cliente)
    folio = cliente.post("/api/recolecciones", json={"token": t6, "peso_kg": "4.6"}, headers=H).get_json()["pago"]["folio"]
    tick(app)
    antes = cliente.get("/api/impacto").get_json()["pagado"]

    cuerpo = json.dumps({"evento": "transferencia.liquidada", "referencia": folio, "monto": "27.00",
                         "clave_rastreo": "RAC-REPETIDO", "folio": "SIMX"}).encode()
    r = cliente.post("/webhooks/spei", data=cuerpo, headers={
        "Content-Type": "application/json", "X-Spei-Firma": firmar(app.config["WEBHOOK_SECRET"], cuerpo)})
    assert r.status_code == 200 and r.get_json()["duplicado"] is True
    assert cliente.get("/api/impacto").get_json()["pagado"] == antes

    r = cliente.post("/webhooks/spei", data=cuerpo, headers={
        "Content-Type": "application/json", "X-Spei-Firma": firmar("secreto-falso", cuerpo)})
    assert r.status_code == 401


def test_idempotencia_de_la_api_spei(app, cliente):
    cuerpo = {"monto": "27.00", "clabe_destino": "999180000000000064", "referencia": "PAG-X",
              "webhook_url": "http://localhost/webhooks/spei"}
    from reaceite import clabe
    cuerpo["clabe_destino"] = clabe.simulada(6)
    cab = {"Authorization": f"Bearer {app.config['SPEI_API_KEY']}", "Idempotency-Key": "llave-1"}
    r1 = cliente.post("/sim-spei/v1/transferencias", json=cuerpo, headers=cab)
    r2 = cliente.post("/sim-spei/v1/transferencias", json=cuerpo, headers=cab)
    assert r1.status_code == 202 and r2.status_code == 200
    assert r2.headers["Idempotent-Replayed"] == "true"
    assert r1.get_json()["folio"] == r2.get_json()["folio"]
    r3 = cliente.post("/sim-spei/v1/transferencias", json={**cuerpo, "monto": "99.00"}, headers=cab)
    assert r3.status_code == 409
    r4 = cliente.post("/sim-spei/v1/transferencias", json={**cuerpo, "clabe_destino": "999180000000000000"},
                      headers={**cab, "Idempotency-Key": "llave-2"})
    assert r4.status_code == 422
    r5 = cliente.post("/sim-spei/v1/transferencias", json=cuerpo, headers={"Idempotency-Key": "llave-3"})
    assert r5.status_code == 401


def test_anomalia_y_recoleccion_directa(app, cliente):
    entrar(cliente)
    t2 = token(app, "COM-0002")  # tiene 10 L pendientes
    r = cliente.post("/api/recolecciones", json={"token": t2, "peso_kg": "20"}, headers=H)
    assert r.status_code == 409 and r.get_json()["error"] == "anomalia"
    r = cliente.post("/api/recolecciones", json={"token": t2, "peso_kg": "20", "confirmar_anomalia": True}, headers=H)
    assert r.status_code == 201 and r.get_json()["anomalia"]

    t4 = token(app, "COM-0004")  # sin solicitud abierta
    r = cliente.post("/api/recolecciones", json={"token": t4, "peso_kg": "9.2"}, headers=H)
    assert r.status_code == 409 and r.get_json()["error"] == "sin_solicitud"
    r = cliente.post("/api/recolecciones", json={"token": t4, "peso_kg": "9.2", "crear_si_falta": True}, headers=H)
    assert r.status_code == 201


def test_regla_de_48_horas(app):
    from reaceite import servicios
    conn = conectar(app.config["DB_PATH"])
    try:
        with transaccion(conn):
            conn.execute("UPDATE solicitud SET creado = ? WHERE estado = 'PENDIENTE' AND zona = 'condesa'",
                         (iso(ahora_utc() - timedelta(hours=49)),))
            generadas = [r for r in servicios.revisar_esperas(conn) if r]
        assert [r["zona"] for r in generadas] == ["condesa"]
        assert generadas[0]["motivo"] == "espera"
    finally:
        conn.close()


def test_registro_de_comercio(app, cliente):
    base = {"nombre": "Quesadillas Lupita", "tipo": "Puesto ambulante", "direccion": "Av. Benjamín Franklin 45",
            "franja": "08-10", "lat": 19.4118, "lon": -99.1701}
    r = cliente.post("/api/comercios", json={**base, "telefono": "+52 55 1234 5678", "pin": "482913",
                                             "pin2": "482913"}, headers=H)
    assert r.status_code == 201, r.data
    c = r.get_json()
    assert c["codigo"] == "COM-0009" and c["zona"]["zona"] == "hipodromo" and len(c["token"]) == 8
    assert c["telefono"] == "55 1234 5678" and c["qr"]["pegado"] is False
    assert cliente.get(f"/qr/c/{c['token']}.png").status_code == 200
    # Quedó con la sesión abierta: ve su panel.
    assert cliente.get(f"/api/comercio/{c['token']}").status_code == 200
    assert b"Mi QR" in cliente.get(f"/c/{c['token']}").data

    otro = app.test_client()
    r = otro.post("/api/comercios", json={"nombre": "X", "tipo": "Fonda", "direccion": "Calle 1"}, headers=H)
    assert r.status_code == 400
    r = otro.post("/api/comercios", json={"nombre": "Fonda", "tipo": "Fonda", "direccion": "Calle 1 2",
                                          "telefono": "123", "zona": "condesa", "pin": "482913"}, headers=H)
    assert r.status_code == 400 and "10 dígitos" in r.get_json()["mensaje"]
    for pin, pin2, codigo in (("12345", "12345", "pin_formato"), ("123456", "123456", "pin_debil"),
                              ("777777", "777777", "pin_debil"), ("847362", "847362", "pin_debil"),
                              ("482913", "482914", "pin_distinto")):
        r = otro.post("/api/comercios", json={"nombre": "Fonda Sin GPS", "tipo": "Fonda", "direccion": "Calle 1 2",
                                              "zona": "escandon", "telefono": "5512345678" if codigo != "pin_debil"
                                              else "5591847362", "pin": pin, "pin2": pin2}, headers=H)
        assert r.status_code == 400 and r.get_json()["error"] == codigo, (pin, r.get_json())
    r = otro.post("/api/comercios", json={"nombre": "Fonda Sin GPS", "tipo": "Fonda", "direccion": "Calle 1 2",
                                          "zona": "escandon", "telefono": "55 1234 5678", "pin": "582913",
                                          "pin2": "582913"}, headers=H)
    assert r.status_code == 409 and r.get_json()["error"] == "telefono_registrado"
    r = otro.post("/api/comercios", json={"nombre": "Fonda Sin GPS", "tipo": "Fonda", "direccion": "Calle 1 2",
                                          "zona": "escandon", "telefono": "5587654321", "pin": "582913",
                                          "pin2": "582913"}, headers=H)
    assert r.status_code == 201 and r.get_json()["zona"]["zona"] == "escandon"


def test_proteccion_csrf_y_permisos(app, cliente):
    t6 = token(app, "COM-0006")
    entrar_comercio(cliente)
    assert cliente.post("/api/solicitudes", json={"token": t6, "litros": 5, "franja": "10-12"}).status_code == 403
    entrar(cliente)
    assert cliente.post("/api/admin/restablecer", json={}, headers=H).status_code == 403
    cliente.post("/salir")
    entrar(cliente, "admin", "admin-pruebas")
    assert cliente.post("/api/admin/restablecer", json={}, headers=H).status_code == 200
    assert cliente.get("/api/impacto").get_json()["pagos"] == 15


def test_qr_y_manifiesto(app, cliente):
    r = cliente.get("/qr/app.png")
    assert r.status_code == 200 and r.mimetype == "image/png"
    m = cliente.get("/manifest.webmanifest")
    assert m.mimetype == "application/manifest+json" and m.get_json()["display"] == "standalone"
    assert cliente.get("/sw.js").status_code == 200
    assert cliente.get("/salud").get_json()["ok"] is True
