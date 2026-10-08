"""Algoritmo de Métricas Verdes.

Convierte el peso medido en la báscula (kg) en litros, agua protegida, biocombustible
estimado y montos. Se usa aritmética decimal exacta: nada de errores de punto flotante
en dinero. Cada valor se redondea al centavo o al centilitro con redondeo comercial.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .config import PARAMETROS

CENTESIMA = Decimal("0.01")
UNIDAD = Decimal("1")
GRAMO = Decimal("0.001")

PESO_MINIMO_KG = Decimal("0.05")
PESO_MAXIMO_KG = Decimal("100")


class PesoInvalido(ValueError):
    pass


def leer_peso(valor):
    """Acepta 4.6, "4.6" o "4,6". Devuelve Decimal en kg con precisión de gramos."""
    if isinstance(valor, float):
        valor = repr(valor)
    texto = str(valor).strip().replace(",", ".")
    try:
        peso = Decimal(texto).quantize(GRAMO, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise PesoInvalido("Escribe el peso en kilos, por ejemplo 4.6") from None
    if not peso.is_finite() or peso < PESO_MINIMO_KG:
        raise PesoInvalido("El peso debe ser de al menos 0.05 kg")
    if peso > PESO_MAXIMO_KG:
        raise PesoInvalido("El peso no puede superar 100 kg en una sola recolección")
    return peso


def calcular(peso_kg, parametros=PARAMETROS):
    """Métricas Verdes de una recolección.

    litros          = peso_kg / densidad
    agua_protegida  = litros x 1,000
    biocombustible  = litros x 0.9
    pago_bruto      = litros x precio_litro
    comision        = pago_bruto x 10 %
    pago_neto       = pago_bruto - comision
    """
    peso = leer_peso(peso_kg)
    litros = (peso / parametros["densidad"]).quantize(CENTESIMA, rounding=ROUND_HALF_UP)
    agua = (litros * parametros["agua_por_litro"]).quantize(UNIDAD, rounding=ROUND_HALF_UP)
    bio = (litros * parametros["biocombustible_por_litro"]).quantize(CENTESIMA, rounding=ROUND_HALF_UP)
    bruto = (litros * parametros["precio_litro"]).quantize(CENTESIMA, rounding=ROUND_HALF_UP)
    comision = (bruto * parametros["comision"]).quantize(CENTESIMA, rounding=ROUND_HALF_UP)
    neto = bruto - comision
    return {
        "peso_kg": peso,
        "litros": litros,
        "agua_l": agua,
        "biocombustible_l": bio,
        "pago_bruto": bruto,
        "comision": comision,
        "pago_neto": neto,
    }


def a_enteros(m):
    """Unidades mínimas para guardar sin decimales: gramos, centilitros y centavos."""
    return {
        "peso_g": int(m["peso_kg"] * 1000),
        "litros_cl": int(m["litros"] * 100),
        "agua_l": int(m["agua_l"]),
        "biocombustible_cl": int(m["biocombustible_l"] * 100),
        "bruto_cent": int(m["pago_bruto"] * 100),
        "comision_cent": int(m["comision"] * 100),
        "neto_cent": int(m["pago_neto"] * 100),
    }


def excede_tolerancia(litros, litros_estimados, parametros=PARAMETROS):
    return litros > Decimal(litros_estimados) * parametros["tolerancia_peso"]


def a_json(m):
    return {k: str(v) for k, v in m.items()}


def pesos(cent):
    return f"{Decimal(cent) / 100:.2f}"


def litros_txt(cl):
    return f"{Decimal(cl) / 100:.2f}"
