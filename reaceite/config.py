"""Configuración y parámetros de negocio de ReAceite CDMX.

Todos los números que usa el algoritmo de Métricas Verdes viven aquí, en un solo lugar.
Cualquier valor puede cambiarse con una variable de entorno sin tocar el código.
"""
import hashlib
import os
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
TZ = ZoneInfo("America/Mexico_City")


def _env(nombre, defecto=None):
    valor = os.environ.get(nombre)
    return valor if valor not in (None, "") else defecto


# ---------------------------------------------------------------- parámetros de negocio
PARAMETROS = {
    # Precio que se paga al comercio por litro (MXN). Límite superior del rango del Sprint 1.
    "precio_litro": Decimal(_env("PRECIO_LITRO", "6.00")),
    # Comisión de la plataforma sobre el pago bruto.
    "comision": Decimal(_env("COMISION", "0.10")),
    # Densidad del aceite vegetal usado (kg/L) para convertir el pesaje a litros.
    "densidad": Decimal("0.92"),
    # 1 L de aceite contamina 1,000 L de agua (parámetro de la rúbrica).
    "agua_por_litro": Decimal("1000"),
    # 1 L de aceite usado rinde 0.9 L de combustible renovable (dato publicado por Repsol).
    "biocombustible_por_litro": Decimal("0.9"),
    # Litros pendientes por zona que disparan la ruta (mínimo que piden las recicladoras).
    "tope_ruta_litros": int(_env("TOPE_RUTA_LITROS", "20")),
    # Si el peso excede 1.5 veces lo solicitado se pide confirmación (posible error o fraude).
    "tolerancia_peso": Decimal("1.5"),
    # Si una solicitud espera más de 48 h, la ruta sale aunque la zona no llegue al tope.
    "espera_maxima_horas": int(_env("ESPERA_MAXIMA_HORAS", "48")),
    # Factor de rodeo urbano: la distancia por calle es ~1.3 veces la distancia en línea recta.
    "factor_rodeo": 1.3,
    # Velocidad promedio del recolector en ciudad (km/h) y tiempo de servicio por parada (min).
    "velocidad_kmh": 18,
    "servicio_min": 5,
}

LITROS_OPCIONES = (5, 10, 20)

ZONAS = {
    "condesa": {"nombre": "Condesa", "lat": 19.4128, "lon": -99.1779},
    "hipodromo": {"nombre": "Hipódromo", "lat": 19.4116, "lon": -99.1697},
    "roma-norte": {"nombre": "Roma Norte", "lat": 19.4185, "lon": -99.1603},
    "escandon": {"nombre": "Escandón", "lat": 19.4036, "lon": -99.1810},
}

FRANJAS = {
    "08-10": "8:00 a 10:00",
    "10-12": "10:00 a 12:00",
    "12-14": "12:00 a 14:00",
    "16-18": "16:00 a 18:00",
}

TIPOS_COMERCIO = ("Taquería", "Fonda", "Churrería", "Puesto ambulante", "Restaurante", "Otro")

# Centro de acopio desde donde sale y a donde regresa el recolector.
DEPOSITO = {"nombre": "Centro de acopio piloto", "lat": 19.4050, "lon": -99.1700}


class Config:
    # Si no se define SECRET_KEY, se deriva de los secretos del despliegue para que las sesiones
    # sobrevivan a los reinicios del plan gratuito.
    SECRET_KEY = _env("SECRET_KEY") or hashlib.sha256(
        f"reaceite|{_env('ADMIN_PASSWORD', '900cib-admin')}|{_env('WEBHOOK_SECRET', 'whsec_reaceite_demo')}".encode()
    ).hexdigest()
    DB_PATH = _env("DB_PATH", str(BASE_DIR / "data" / "reaceite.db"))

    # Credenciales de la API SPEI simulada y secreto para firmar sus webhooks.
    SPEI_API_KEY = _env("SPEI_API_KEY", "sk_test_reaceite_demo")
    WEBHOOK_SECRET = _env("WEBHOOK_SECRET", "whsec_reaceite_demo")
    # Segundos que tarda el banco simulado en liquidar una orden.
    SPEI_DEMORA_S = float(_env("SPEI_DEMORA_S", "1.2"))

    # URL con la que el servidor se llama a sí mismo (API SPEI y webhooks).
    PORT = int(_env("PORT", "5000"))
    INTERNAL_BASE_URL = _env("INTERNAL_BASE_URL", f"http://127.0.0.1:{_env('PORT', '5000')}")
    # "http" hace llamadas HTTP reales por la red local; "inproc" las despacha dentro del proceso.
    TRANSPORTE = _env("TRANSPORTE", "http")
    # URL pública (para el QR de la portada). Render la expone en RENDER_EXTERNAL_URL.
    PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL", _env("RENDER_EXTERNAL_URL"))
    # Webhook externo opcional (por ejemplo, webhook.site o Make) que recibe una copia de cada pago.
    NOTIFY_WEBHOOK_URL = _env("NOTIFY_WEBHOOK_URL")

    RECOLECTOR_PASSWORD = _env("RECOLECTOR_PASSWORD", "aceite2026")
    ADMIN_PASSWORD = _env("ADMIN_PASSWORD", "900cib-admin")

    DESPACHADOR_AUTO = _env("DESPACHADOR_AUTO", "1") == "1"
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = _env("RENDER") is not None or _env("COOKIE_SEGURA") == "1"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12
    JSON_SORT_KEYS = False
    MAX_CONTENT_LENGTH = 64 * 1024
