"""Sprint 3: contenedor inteligente (IoT), billetera del comercio y Fondo de Garantía de Dispersión."""
import json
import uuid

from conftest import H, entrar, entrar_comercio, token

from reaceite import iot, spei_sim
from reaceite.db import conectar, transaccion
from reaceite.firma import firmar


def tick(app):
    return app.extensions["despachador"].tick()


def sql(app, consulta, params=()):
    conn = conectar(app.config["DB_PATH"])
    try:
        return conn.execute(consulta, params).fetchall()
    finally:
        conn.close()


def contenedor(app, codigo="CTN-0001"):
    return sql(app, "SELECT * FROM contenedor WHERE codigo = ?", (codigo,))[0]


def saldo(app, clabe):
    return sql(app, "SELECT saldo_cent FROM cuenta WHERE clabe = ?", (clabe,))[0][0]


def senal(cliente, codigo, tipo, peso_g, deposito=None):
    r = cliente.post(f"/api/gemelo/{codigo}/senal", json={"tipo": tipo, "peso_g": peso_g, "deposito": deposito},
                     headers=H)
    assert r.status_code == 200, r.data
    return r.get_json()


def test_deposito_en_contenedor_de_punta_a_punta(app, cliente):
    ctn = contenedor(app)
    clabe_puesto = sql(app, "SELECT clabe FROM comercio WHERE codigo = 'COM-0006'")[0][0]
    fondo_antes = saldo(app, spei_sim.FONDO_CLABE)
    assert saldo(app, clabe_puesto) == 0

    # Sin sesión, el QR del contenedor invita a entrar; con sesión de comercio, ofrece abrir la compuerta.
    assert b"Entrar con mi celular" in cliente.get(f"/k/{ctn['token']}").data
    taquero = app.test_client()
    entrar_comercio(taquero)
    assert b"Abrir compuerta" in taquero.get(f"/k/{ctn['token']}").data

    r = taquero.post(f"/api/contenedores/{ctn['token']}/depositos", json={}, headers=H)
    assert r.status_code == 201, r.data
    dep = r.get_json()
    assert dep["estado"] == "ABIERTO" and dep["folio"].startswith("DEP-")

    # El equipo opera el gemelo digital: la compuerta le llega como orden en la respuesta a su señal.
    entrar(cliente)
    envio = senal(cliente, "CTN-0001", "latido", ctn["peso_g"])
    assert envio["respuesta"]["status"] == 200
    assert envio["respuesta"]["cuerpo"]["comando"] == {
        "compuerta": "abierta", "deposito": dep["folio"], "peso_inicial_g": ctn["peso_g"],
        "vence": envio["respuesta"]["cuerpo"]["comando"]["vence"]}
    for parcial in (1200, 3100, 4600):
        senal(cliente, "CTN-0001", "peso", ctn["peso_g"] + parcial)
    vivo = taquero.get(f"/api/depositos/{dep['folio']}").get_json()
    assert vivo["peso_neto_g"] == 4600 and vivo["estado"] == "ABIERTO"

    cierre = senal(cliente, "CTN-0001", "deposito.cerrado", ctn["peso_g"] + 4600, dep["folio"])
    assert cierre["respuesta"]["status"] == 201, cierre
    assert cierre["peticion"]["cabeceras"]["X-Dispositivo-Firma"].startswith("t=")
    rec = cierre["respuesta"]["cuerpo"]["recoleccion"]

    tick(app)
    final = taquero.get(f"/api/depositos/{dep['folio']}").get_json()
    assert final["estado"] == "CERRADO"
    assert final["recoleccion"]["litros"] == "5.00"
    assert final["pago"]["estatus"] == "LIQUIDADO" and final["pago"]["monto"] == "27.00"
    etapas = [f[0] for f in sql(app, "SELECT etapa FROM evento WHERE ref = ? AND etapa IS NOT NULL ORDER BY id", (rec,))]
    assert etapas == list(range(1, 9))

    # El dinero salió del Fondo de Garantía y llegó a la billetera del comercio.
    assert saldo(app, spei_sim.FONDO_CLABE) == fondo_antes - 2700
    assert saldo(app, clabe_puesto) == 2700
    billetera = taquero.get("/api/mi-comercio/billetera").get_json()
    assert billetera["saldo"] == "27.00" and billetera["activa"] is True
    assert billetera["movimientos"][0]["tipo"] == "ABONO"
    assert billetera["fuente"]["status"] == 200

    despues = contenedor(app)
    assert despues["nivel_cl"] == ctn["nivel_cl"] + 500
    assert sql(app, "SELECT origen FROM recoleccion WHERE folio = ?", (rec,))[0][0] == "CONTENEDOR"
    vista = taquero.get(f"/api/comercio/{token(app, 'COM-0006')}").get_json()
    assert vista["historial"][0]["origen"] == "CONTENEDOR"
    assert vista["historial"][0]["contenedor"] == "Contenedor Parque México"


def _telemetria(app, cliente, codigo, datos, secreto=None):
    c = contenedor(app, codigo)
    cuerpo = json.dumps(datos).encode()
    return cliente.post("/iot/v1/telemetria", data=cuerpo, headers={
        "Content-Type": "application/json", "X-Dispositivo": codigo,
        "X-Dispositivo-Firma": firmar(secreto or c["secreto"], cuerpo)})


def test_telemetria_firmada_e_idempotente(app, cliente):
    datos = {"evento_id": uuid.uuid4().hex, "tipo": "latido", "peso_g": 100}
    assert _telemetria(app, cliente, "CTN-0002", datos, secreto="secreto-falso").status_code == 401
    # La firma de un contenedor no sirve para otro.
    otro = contenedor(app, "CTN-0001")["secreto"]
    assert _telemetria(app, cliente, "CTN-0002", datos, secreto=otro).status_code == 401
    sin_firma = cliente.post("/iot/v1/telemetria", json=datos, headers={"X-Dispositivo": "CTN-0002"})
    assert sin_firma.status_code == 401
    r = _telemetria(app, cliente, "CTN-0002", datos)
    assert r.status_code == 200 and r.get_json()["comando"] == {"compuerta": "cerrada"}
    repetido = _telemetria(app, cliente, "CTN-0002", datos)
    assert repetido.status_code == 200 and repetido.get_json()["duplicado"] is True
    assert sql(app, "SELECT COUNT(*) FROM lectura WHERE evento_id = ?", (datos["evento_id"],))[0][0] == 1
    malo = _telemetria(app, cliente, "CTN-0002", {"evento_id": uuid.uuid4().hex, "tipo": "peso", "peso_g": -5})
    assert malo.status_code == 422
    sin_deposito = _telemetria(app, cliente, "CTN-0002", {"evento_id": uuid.uuid4().hex, "tipo": "deposito.cerrado",
                                                          "peso_g": 9000, "deposito": "DEP-999999"})
    assert sin_deposito.status_code == 409
    assert cliente.post("/iot/v1/telemetria", json=datos, headers={"X-Dispositivo": "CTN-9999"}).status_code == 404


def test_cierre_repetido_no_paga_dos_veces(app, cliente):
    ctn = contenedor(app)
    taquero = app.test_client()
    entrar_comercio(taquero)
    folio = taquero.post(f"/api/contenedores/{ctn['token']}/depositos", json={}, headers=H).get_json()["folio"]
    datos = {"evento_id": uuid.uuid4().hex, "tipo": "deposito.cerrado", "peso_g": ctn["peso_g"] + 2300,
             "deposito": folio}
    assert _telemetria(app, cliente, "CTN-0001", datos).status_code == 201
    # El mismo mensaje reenviado (o uno nuevo con el mismo folio) no crea otra recolección.
    assert _telemetria(app, cliente, "CTN-0001", datos).get_json()["duplicado"] is True
    otra = {**datos, "evento_id": uuid.uuid4().hex}
    assert _telemetria(app, cliente, "CTN-0001", otra).get_json()["duplicado"] is True
    assert sql(app, "SELECT COUNT(*) FROM recoleccion WHERE origen = 'CONTENEDOR' AND contenedor_id = ?",
               (ctn["id"],))[0][0] == 4  # 3 del historial + este


def test_un_deposito_a_la_vez_cancelacion_y_vencimiento(app, cliente):
    ctn = contenedor(app)
    puesto = app.test_client()
    entrar_comercio(puesto)
    dep = puesto.post(f"/api/contenedores/{ctn['token']}/depositos", json={}, headers=H).get_json()
    # Volver a tocar «Abrir» devuelve el mismo depósito.
    assert puesto.post(f"/api/contenedores/{ctn['token']}/depositos", json={}, headers=H).get_json()["folio"] == dep["folio"]
    vecino = app.test_client()
    entrar_comercio(vecino, telefono="5510000002")
    r = vecino.post(f"/api/contenedores/{ctn['token']}/depositos", json={}, headers=H)
    assert r.status_code == 409 and r.get_json()["error"] == "contenedor_ocupado"
    # Un comercio no ve depósitos ajenos.
    assert vecino.get(f"/api/depositos/{dep['folio']}").status_code == 404
    assert puesto.post(f"/api/depositos/{dep['folio']}/cancelar", json={}, headers=H).get_json()["estado"] == "CANCELADO"

    # Compuerta vencida con aceite en la báscula: se cierra con la última lectura y se paga.
    dep2 = vecino.post(f"/api/contenedores/{ctn['token']}/depositos", json={}, headers=H).get_json()
    entrar(cliente)
    senal(cliente, "CTN-0001", "peso", ctn["peso_g"] + 1840)
    conn = conectar(app.config["DB_PATH"])
    try:
        with transaccion(conn):
            conn.execute("UPDATE deposito SET vence = '2000-01-01T00:00:00.000Z' WHERE folio = ?", (dep2["folio"],))
            assert iot.revisar_depositos(conn) == 1
    finally:
        conn.close()
    tick(app)
    final = vecino.get(f"/api/depositos/{dep2['folio']}").get_json()
    assert final["estado"] == "CERRADO" and final["recoleccion"]["litros"] == "2.00"
    assert final["pago"]["estatus"] == "LIQUIDADO"

    # Sin aceite, la compuerta vencida solo se cierra.
    dep3 = puesto.post(f"/api/contenedores/{ctn['token']}/depositos", json={}, headers=H).get_json()
    conn = conectar(app.config["DB_PATH"])
    try:
        with transaccion(conn):
            conn.execute("UPDATE deposito SET vence = '2000-01-01T00:00:00.000Z' WHERE folio = ?", (dep3["folio"],))
            assert iot.revisar_depositos(conn) == 0
    finally:
        conn.close()
    assert puesto.get(f"/api/depositos/{dep3['folio']}").get_json()["estado"] == "VENCIDO"


def test_fondo_insuficiente_espera_y_venta_de_lote_lo_recarga(app, cliente):
    # El fondo se queda casi vacío: el pago no se rechaza, espera.
    conn = conectar(app.config["DB_PATH"])
    try:
        with transaccion(conn):
            conn.execute("UPDATE cuenta SET saldo_cent = 1000 WHERE clabe = ?", (spei_sim.FONDO_CLABE,))
    finally:
        conn.close()
    t2 = token(app, "COM-0002")
    entrar(cliente)
    folio = cliente.post("/api/recolecciones", json={"token": t2, "peso_kg": "9.2"}, headers=H).get_json()["pago"]["folio"]
    tick(app)
    pago = cliente.get(f"/api/pagos/{folio}").get_json()
    assert pago["estatus"] == "PENDIENTE" and pago["espera"].startswith("En espera")
    monitor = cliente.get("/api/monitor").get_json()
    assert monitor["fondo"]["pagos_en_espera"] == 1 and monitor["fondo"]["alerta"] is True
    assert any(e["tipo"] == "fondo.insuficiente" for e in monitor["eventos"])

    # Solo la administración vende lotes.
    assert cliente.post("/api/admin/lotes", json={}, headers=H).status_code == 403
    cliente.post("/salir")
    entrar(cliente, "admin", "admin-pruebas")
    inventario = monitor["fondo"]["inventario"]
    r = cliente.post("/api/admin/lotes", json={}, headers=H)
    assert r.status_code == 201, r.data
    lote = r.get_json()
    assert lote["folio"] == "LOT-0001" and lote["reactivados"] == 1
    assert lote["litros"] == inventario["litros"] and lote["venta"] == inventario["venta"]
    assert float(lote["margen"]) > 0
    tick(app)
    assert cliente.get(f"/api/pagos/{folio}").get_json()["estatus"] == "LIQUIDADO"
    # Ya no queda aceite pagado sin vender: un segundo lote se rechaza hasta juntar el mínimo... salvo el recién pagado.
    r = cliente.post("/api/admin/lotes", json={}, headers=H)
    assert r.status_code == 409 and r.get_json()["error"] == "lote_insuficiente"


def test_api_de_la_pasarela(app, cliente):
    cab = {"Authorization": f"Bearer {app.config['SPEI_API_KEY']}"}
    assert cliente.get(f"/sim-spei/v1/cuentas/{spei_sim.FONDO_CLABE}").status_code == 401
    r = cliente.get(f"/sim-spei/v1/cuentas/{spei_sim.FONDO_CLABE}", headers=cab)
    assert r.status_code == 200 and r.get_json()["tipo"] == "FONDO"
    assert cliente.get("/sim-spei/v1/cuentas/999180000000009999/movimientos", headers=cab).status_code == 404
    from reaceite import clabe
    nueva = clabe.simulada(4321)
    alta = {"clabe": nueva, "titular": "Tamales Rosy", "celular": "5512345678"}
    assert cliente.post("/sim-spei/v1/cuentas", json=alta, headers=cab).status_code == 201
    assert cliente.post("/sim-spei/v1/cuentas", json=alta, headers=cab).status_code == 200
    assert cliente.post("/sim-spei/v1/cuentas", json={**alta, "clabe": "999180000000000000"},
                        headers=cab).status_code == 422


def test_registro_abre_billetera_por_la_cola(app, cliente):
    r = cliente.post("/api/comercios", json={
        "nombre": "Tlacoyos Mary", "tipo": "Puesto ambulante", "direccion": "Calle Sonora 12", "zona": "condesa",
        "telefono": "5598765432", "pin": "482913", "pin2": "482913"}, headers=H)
    assert r.status_code == 201
    assert cliente.get("/api/mi-comercio/billetera").get_json()["activa"] is False
    tick(app)
    b = cliente.get("/api/mi-comercio/billetera").get_json()
    assert b["activa"] is True and b["saldo"] == "0.00" and b["celular"] == "55 9876 5432"


def test_qr_del_contenedor_y_vaciado(app, cliente):
    ctn = contenedor(app)
    assert cliente.get("/k/NOEXISTE").status_code == 404
    assert cliente.get(f"/qr/k/{ctn['token']}.png").mimetype == "image/png"
    assert cliente.get("/gemelo").status_code == 302  # sin sesión del equipo: lo manda a entrar
    entrar(cliente)
    r = cliente.get("/gemelo")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/k/{ctn['token']}")
    assert cliente.get("/gemelo?c=CTN-0002").headers["Location"].endswith(f"/k/{contenedor(app, 'CTN-0002')['token']}")
    assert b"Gemelo digital" in cliente.get("/r").data
    pagina = cliente.get(f"/k/{ctn['token']}").data
    assert b"Gemelo digital" in pagina and b"Vaciar contenedor" in pagina
    estado = cliente.get("/api/gemelo/CTN-0001").get_json()
    assert estado["porcentaje"] > 0 and estado["comando"] == {"compuerta": "cerrada"}
    r = cliente.post("/api/contenedores/CTN-0001/vaciar", json={}, headers=H)
    assert r.status_code == 200 and r.get_json()["nivel_l"] == "0.00"
    assert contenedor(app)["peso_g"] == 0
    monitor = cliente.get("/api/monitor").get_json()
    assert [c["codigo"] for c in monitor["contenedores"]] == ["CTN-0001", "CTN-0002"]
    assert monitor["eventos"][0]["tipo"] == "contenedor.vaciado"
