"""Códigos QR de alta resolución (corrección de errores H: siguen leyéndose con 30 % dañado)."""
import io

import qrcode
from qrcode.image.svg import SvgPathImage

BORDE = 4


def _qr(texto, caja=10):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=caja, border=BORDE)
    qr.add_data(texto)
    qr.make(fit=True)
    return qr


def png(texto, lado_px=1200):
    """PNG nítido: cada módulo mide un número entero de píxeles (sin reescalar)."""
    modulos = _qr(texto, 1).modules_count + 2 * BORDE
    caja = max(1, lado_px // modulos)
    imagen = _qr(texto, caja).make_image(fill_color="black", back_color="white").get_image().convert("1")
    salida = io.BytesIO()
    imagen.save(salida, format="PNG", optimize=True, dpi=(600, 600))
    return salida.getvalue()


def svg(texto):
    imagen = _qr(texto).make_image(image_factory=SvgPathImage)
    salida = io.BytesIO()
    imagen.save(salida)
    return salida.getvalue()
