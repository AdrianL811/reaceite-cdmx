"""Llamadas HTTP salientes (a la API SPEI simulada y a los webhooks).

Con TRANSPORTE=http la llamada viaja por la red local (127.0.0.1) como cualquier petición
externa. Si esa conexión no está disponible, la misma petición se despacha dentro del proceso
por la pila WSGI completa: mismas cabeceras, mismo cuerpo, misma verificación de firmas.
"""
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlsplit

_sin_proxy = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass
class Respuesta:
    status: int
    cuerpo: bytes
    ms: float
    transporte: str
    cabeceras: dict = field(default_factory=dict)

    def json(self):
        try:
            return json.loads(self.cuerpo or b"{}")
        except ValueError:
            return {}


def _ms(inicio):
    return (time.perf_counter() - inicio) * 1000


def enviar(app, metodo, url_o_ruta, cuerpo, cabeceras, timeout=8):
    base = app.config["INTERNAL_BASE_URL"].rstrip("/")
    url = url_o_ruta if url_o_ruta.startswith(("http://", "https://")) else base + url_o_ruta
    interna = url.startswith(base)
    inicio = time.perf_counter()
    if app.config.get("TRANSPORTE", "http") == "http" or not interna:
        peticion = urllib.request.Request(url, data=cuerpo, method=metodo, headers=cabeceras)
        abridor = _sin_proxy if interna else urllib.request.build_opener()
        try:
            with abridor.open(peticion, timeout=timeout) as r:
                return Respuesta(r.status, r.read(), _ms(inicio), "http", dict(r.headers))
        except urllib.error.HTTPError as e:
            return Respuesta(e.code, e.read(), _ms(inicio), "http", dict(e.headers or {}))
        except (urllib.error.URLError, OSError):
            if not interna:
                raise
    partes = urlsplit(url)
    ruta = partes.path + (f"?{partes.query}" if partes.query else "")
    with app.test_client() as cliente:
        r = cliente.open(ruta, method=metodo, data=cuerpo, headers=cabeceras)
        return Respuesta(r.status_code, r.get_data(), _ms(inicio), "en proceso", dict(r.headers))
