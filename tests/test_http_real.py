"""Mismo flujo, pero como en producción: servidor HTTP real, hilo despachador y llamadas por la red local."""
import http.cookiejar
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from werkzeug.serving import make_server

from reaceite import create_app


def puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_flujo_por_http_con_hilo_en_segundo_plano(tmp_path):
    puerto = puerto_libre()
    app = create_app({
        "DB_PATH": str(tmp_path / "http.db"),
        "TRANSPORTE": "http",
        "INTERNAL_BASE_URL": f"http://127.0.0.1:{puerto}",
        "DESPACHADOR_AUTO": True,
        "SPEI_DEMORA_S": 0.8,
        "SECRET_KEY": "http",
    })
    servidor = make_server("127.0.0.1", puerto, app, threaded=True)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    base = f"http://127.0.0.1:{puerto}"
    jar = http.cookiejar.CookieJar()
    abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))

    def pedir(metodo, ruta, datos=None, form=None):
        cabeceras = {"X-ReAceite": "1"}
        cuerpo = None
        if datos is not None:
            cuerpo = json.dumps(datos).encode()
            cabeceras["Content-Type"] = "application/json"
        if form is not None:
            cuerpo = urllib.parse.urlencode(form).encode()
            cabeceras["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(base + ruta, data=cuerpo, method=metodo, headers=cabeceras)
        with abridor.open(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null") if r.headers.get_content_type() == "application/json" else None

    try:
        from reaceite.db import conectar
        conn = conectar(app.config["DB_PATH"])
        t6 = conn.execute("SELECT token FROM comercio WHERE codigo = 'COM-0006'").fetchone()[0]
        conn.close()

        try:
            pedir("POST", "/comercio/entrar", form={"telefono": "55 1000 0006", "pin": "900900"})
        except urllib.error.HTTPError as e:  # el redirect tras entrar lleva a una página HTML
            raise AssertionError(e.read()) from e
        status, datos = pedir("POST", "/api/solicitudes", {"token": t6, "litros": 5, "franja": "10-12"})
        assert status == 201 and datos["ruta_generada"]
        pedir("POST", "/entrar", form={"usuario": "recolector", "clave": "aceite2026"})
        status, rec = pedir("POST", "/api/recolecciones", {"token": t6, "peso_kg": "4.6"})
        assert status == 201
        folio = rec["pago"]["folio"]
        inicio = time.monotonic()
        estatus = None
        while time.monotonic() - inicio < 10:
            _, pago = pedir("GET", f"/api/pagos/{folio}")
            estatus = pago["estatus"]
            if estatus == "LIQUIDADO":
                break
            time.sleep(0.2)
        transcurrido = time.monotonic() - inicio
        assert estatus == "LIQUIDADO", pago
        assert transcurrido < 4, transcurrido
        assert [e["etapa"] for e in pago["etapas"]] == list(range(1, 9))
        _, monitor = pedir("GET", "/api/monitor")
        envio = next(e for e in monitor["eventos"] if e["tipo"] == "spei.orden_enviada")
        assert envio["detalle"]["transporte"] == "http"
        assert envio["detalle"]["respuesta"]["status"] == 202
    finally:
        servidor.shutdown()
