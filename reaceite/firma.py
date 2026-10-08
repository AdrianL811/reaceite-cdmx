"""Firma HMAC-SHA256 de webhooks con marca de tiempo (evita alteraciones y repeticiones).

Cabecera: X-Spei-Firma: t=<unix>,v1=<hex>, donde hex = HMAC_SHA256(secreto, "<t>." + cuerpo).
"""
import hashlib
import hmac
import time

TOLERANCIA_S = 300


def firmar(secreto, cuerpo, ts=None):
    ts = int(time.time()) if ts is None else int(ts)
    mac = hmac.new(secreto.encode(), f"{ts}.".encode() + cuerpo, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verificar(secreto, cuerpo, cabecera, ahora=None, tolerancia=TOLERANCIA_S):
    """Devuelve (True, "") si la firma es válida; si no, (False, motivo)."""
    if not cabecera:
        return False, "Falta la cabecera X-Spei-Firma"
    partes = dict(p.split("=", 1) for p in cabecera.split(",") if "=" in p)
    try:
        ts = int(partes.get("t", ""))
    except ValueError:
        return False, "Marca de tiempo inválida"
    recibida = partes.get("v1", "")
    ahora = int(time.time()) if ahora is None else int(ahora)
    if abs(ahora - ts) > tolerancia:
        return False, "Firma vencida (más de 5 minutos)"
    esperada = hmac.new(secreto.encode(), f"{ts}.".encode() + cuerpo, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(esperada, recibida):
        return False, "La firma no coincide con el cuerpo"
    return True, ""
