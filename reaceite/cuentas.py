"""Cuentas de los comercios: el usuario es su celular y la contraseña, un PIN de 6 dígitos.

Un taquero no usa correo ni recuerda contraseñas inventadas, pero nunca olvida su número de celular.
El PIN se guarda solo como hash. Tras varios intentos fallidos la cuenta se bloquea unos minutos, así
que adivinar uno de un millón de PIN posibles deja de ser práctico.
"""
import hashlib
import math
import re
import secrets
from datetime import timedelta

from werkzeug.security import check_password_hash, generate_password_hash

from . import eventos
from .db import ahora_utc, iso, parse_iso, transaccion
from .errores import ErrorNegocio

# Se compara contra este hash cuando el celular no existe: la respuesta tarda lo mismo
# exista o no la cuenta, y nadie puede averiguar qué celulares están registrados por el tiempo.
_HASH_FICTICIO = generate_password_hash("000000")
CREDENCIALES = "El celular o el PIN no coinciden."


# ---------------------------------------------------------------- celular
def normalizar_telefono(valor):
    """Acepta «55 1234 5678», «55-1234-5678» o «+52 55 1234 5678» y devuelve los 10 dígitos."""
    digitos = re.sub(r"\D", "", str(valor or ""))
    if len(digitos) == 12 and digitos.startswith("52"):
        digitos = digitos[2:]
    elif len(digitos) == 13 and digitos.startswith("521"):
        digitos = digitos[3:]
    if len(digitos) != 10:
        raise ErrorNegocio("Escribe tu número de celular a 10 dígitos.", codigo="telefono")
    return digitos


def formato_telefono(telefono):
    if not telefono or len(telefono) != 10:
        return telefono or ""
    return f"{telefono[:2]} {telefono[2:6]} {telefono[6:]}"


def comercio_por_telefono(conn, telefono):
    return conn.execute("SELECT * FROM comercio WHERE telefono = ?", (telefono,)).fetchone()


# ---------------------------------------------------------------- PIN
def pin_trivial(pin):
    """Seis números iguales o una escalera (123456, 987654...) se adivinan primero."""
    return len(set(pin)) == 1 or pin in "0123456789" or pin in "9876543210"


def validar_pin_nuevo(pin, confirmacion=None, telefono=None):
    pin = str(pin or "").strip()
    if not re.fullmatch(r"\d{6}", pin):
        raise ErrorNegocio("El PIN debe tener exactamente 6 números.", codigo="pin_formato")
    if pin_trivial(pin):
        raise ErrorNegocio("Ese PIN es muy fácil de adivinar. Evita 123456 o seis números iguales.", codigo="pin_debil")
    if telefono and telefono.endswith(pin):
        raise ErrorNegocio("No uses los últimos 6 números de tu celular como PIN.", codigo="pin_debil")
    if confirmacion is not None and str(confirmacion).strip() != pin:
        raise ErrorNegocio("Los dos PIN no coinciden. Escríbelo igual en ambos campos.", codigo="pin_distinto")
    return pin


def hash_pin(pin):
    return generate_password_hash(pin)


def nueva_sal():
    """Valor aleatorio que se guarda en la sesión: si cambia, las sesiones anteriores dejan de valer."""
    return secrets.token_urlsafe(16)


def sal_demo(codigo, secreto):
    """Sal fija para los comercios de demostración: su sesión sobrevive a los reinicios del plan gratuito."""
    return hashlib.sha256(f"reaceite-demo-sesion|{codigo}|{secreto}".encode()).hexdigest()[:22]


def pin_temporal():
    while True:
        pin = f"{secrets.randbelow(1_000_000):06d}"
        if not pin_trivial(pin):
            return pin


# ---------------------------------------------------------------- verificación con bloqueo
def _error_bloqueo(hasta):
    minutos = max(1, math.ceil((parse_iso(hasta) - ahora_utc()).total_seconds() / 60))
    return ErrorNegocio(
        f"Por seguridad bloqueamos la cuenta {minutos} min por demasiados intentos. "
        "Espera o pide al equipo de ReAceite que restablezca tu PIN.",
        codigo="bloqueado", http=429, extra={"minutos": minutos},
    )


def _comprobar(conn, c, pin, config, mensaje, http=401):
    """Revisa el PIN y lleva la cuenta de intentos. Devuelve None si es correcto, o el error.

    Se llama dentro de una transacción que debe confirmarse aunque el PIN esté mal (para que el
    intento fallido quede guardado); por eso devuelve el error en lugar de lanzarlo.
    """
    if c["bloqueado_hasta"] and parse_iso(c["bloqueado_hasta"]) > ahora_utc():
        return _error_bloqueo(c["bloqueado_hasta"])
    if c["pin_hash"] and check_password_hash(c["pin_hash"], str(pin or "")):
        if c["intentos_pin"] or c["bloqueado_hasta"]:
            conn.execute("UPDATE comercio SET intentos_pin = 0, bloqueado_hasta = NULL WHERE id = ?", (c["id"],))
        return None
    intentos = c["intentos_pin"] + 1
    maximo = config["PIN_INTENTOS"]
    if intentos >= maximo:
        hasta = iso(ahora_utc() + timedelta(minutes=config["PIN_BLOQUEO_MIN"]))
        conn.execute("UPDATE comercio SET intentos_pin = 0, bloqueado_hasta = ? WHERE id = ?", (hasta, c["id"]))
        eventos.registrar(conn, "comercio.bloqueado",
                          f"{c['codigo']} bloqueado {config['PIN_BLOQUEO_MIN']} min tras {maximo} PIN incorrectos",
                          ref=c["codigo"])
        return _error_bloqueo(hasta)
    conn.execute("UPDATE comercio SET intentos_pin = ? WHERE id = ?", (intentos, c["id"]))
    quedan = maximo - intentos
    return ErrorNegocio(f"{mensaje} Te queda{'n' if quedan != 1 else ''} {quedan} intento{'s' if quedan != 1 else ''}.",
                        codigo="credenciales", http=http, extra={"intentos_restantes": quedan})


def iniciar_sesion(conn, telefono_crudo, pin, config):
    """Devuelve el comercio si el celular y el PIN coinciden; si no, guarda el intento y lanza el error."""
    try:
        telefono = normalizar_telefono(telefono_crudo)
    except ErrorNegocio:
        telefono = None
    with transaccion(conn):
        c = comercio_por_telefono(conn, telefono) if telefono else None
        if c is None or not c["pin_hash"]:
            check_password_hash(_HASH_FICTICIO, str(pin or ""))
            error = ErrorNegocio(CREDENCIALES, codigo="credenciales", http=401)
        else:
            error = _comprobar(conn, c, pin, config, CREDENCIALES)
            if error is None:
                c = conn.execute("SELECT * FROM comercio WHERE id = ?", (c["id"],)).fetchone()
    if error:
        raise error
    return c


def confirmar_pin(conn, comercio_id, pin, config):
    """Pide el PIN antes de una acción delicada (reemplazar el QR). Cuenta como intento."""
    with transaccion(conn):
        c = conn.execute("SELECT * FROM comercio WHERE id = ?", (comercio_id,)).fetchone()
        error = _comprobar(conn, c, pin, config, "El PIN no es correcto.", http=403)
    if error:
        raise error


def cambiar_pin(conn, comercio_id, actual, nuevo, confirmacion, config):
    """Cambia el PIN y la sal de sesión: se cierran las sesiones abiertas en otros teléfonos."""
    sal = None
    with transaccion(conn):
        c = conn.execute("SELECT * FROM comercio WHERE id = ?", (comercio_id,)).fetchone()
        error = _comprobar(conn, c, actual, config, "Tu PIN actual no es correcto.", http=403)
        if error is None:
            try:
                pin = validar_pin_nuevo(nuevo, confirmacion, c["telefono"])
                if check_password_hash(c["pin_hash"], pin):
                    raise ErrorNegocio("El PIN nuevo debe ser distinto del actual.", codigo="pin_igual")
            except ErrorNegocio as e:
                error = e
            else:
                sal = nueva_sal()
                conn.execute("UPDATE comercio SET pin_hash = ?, pin_temporal = 0, sesion_sal = ? WHERE id = ?",
                             (hash_pin(pin), sal, c["id"]))
                eventos.registrar(conn, "comercio.pin_cambiado",
                                  f"{c['codigo']} cambió su PIN; sus sesiones en otros teléfonos se cerraron",
                                  ref=c["codigo"])
    if error:
        raise error
    return sal


def restablecer_pin(conn, c):
    """La administración genera un PIN temporal (el comercio lo cambia al entrar). Debe ir en una transacción."""
    pin = pin_temporal()
    conn.execute(
        "UPDATE comercio SET pin_hash = ?, pin_temporal = 1, intentos_pin = 0, bloqueado_hasta = NULL, "
        "sesion_sal = ? WHERE id = ?",
        (hash_pin(pin), nueva_sal(), c["id"]),
    )
    eventos.registrar(conn, "comercio.pin_restablecido",
                      f"La administración generó un PIN temporal para {c['codigo']}", ref=c["codigo"])
    return pin
