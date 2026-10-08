"""Bitácora de eventos: la evidencia de cada paso automático del sistema."""
import json

from .db import ahora_iso

# Etapas del Data Pipeline, del pesaje al activo financiero.
ETAPAS = {
    1: "Dato crudo",
    2: "Normalización",
    3: "Validación",
    4: "Enriquecimiento",
    5: "Evento",
    6: "Orden a la API SPEI",
    7: "Webhook de liquidación",
    8: "Activo financiero",
}


def registrar(conn, tipo, resumen, ref=None, etapa=None, detalle=None):
    conn.execute(
        "INSERT INTO evento(ts, tipo, etapa, ref, resumen, detalle) VALUES (?, ?, ?, ?, ?, ?)",
        (
            ahora_iso(),
            tipo,
            etapa,
            ref,
            resumen,
            json.dumps(detalle, ensure_ascii=False, default=str) if detalle is not None else None,
        ),
    )
