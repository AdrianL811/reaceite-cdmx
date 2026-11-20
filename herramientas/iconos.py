"""Genera los íconos de la PWA (cubeta con aceite sobre fondo petróleo)."""
import math
from pathlib import Path

from PIL import Image, ImageDraw

DESTINO = Path(__file__).resolve().parent.parent / "reaceite" / "static" / "icons"
PETROLEO = (18, 56, 61, 255)
ACEITE = (232, 161, 26, 255)
BLANCO = (255, 255, 255, 255)


def dibujar(lado, margen_seguro=0.0, redondeo=0.22):
    s = lado * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if redondeo:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * redondeo), fill=PETROLEO)
    else:
        d.rectangle([0, 0, s, s], fill=PETROLEO)
    escala = s * (1 - 2 * margen_seguro) / 32
    ox = oy = s * margen_seguro

    def p(x, y):
        return (ox + x * escala, oy + y * escala)

    # Asa de alambre con agarradera
    caja = [p(5.4, 2.6), p(26.6, 23.4)]
    d.arc(caja, start=180, end=360, fill=BLANCO, width=max(2, int(1.7 * escala)))
    d.rounded_rectangle([p(12.6, 1.6), p(19.4, 4.4)], radius=1.3 * escala, fill=BLANCO)
    # Cuerpo de la cubeta
    cuerpo = [p(4.5, 10), p(27.5, 10), p(24.9, 27.5), p(23.0, 29.3), p(9.0, 29.3), p(7.1, 27.5)]
    d.polygon(cuerpo, fill=BLANCO)
    # Aceite con superficie ondulada
    puntos = []
    for i in range(0, 41):
        x = 5.6 + i * (20.8 / 40)
        y = 17 + 0.8 * math.sin((x - 5.6) / 5.2 * math.pi)
        puntos.append(p(x, y))
    puntos += [p(24.8, 27.3), p(22.9, 28.9), p(9.1, 28.9), p(7.2, 27.3)]
    d.polygon(puntos, fill=ACEITE)
    return img.resize((lado, lado), Image.LANCZOS)


def main():
    DESTINO.mkdir(parents=True, exist_ok=True)
    dibujar(192).save(DESTINO / "icon-192.png", optimize=True)
    dibujar(512).save(DESTINO / "icon-512.png", optimize=True)
    dibujar(512, margen_seguro=0.14, redondeo=0).save(DESTINO / "maskable-512.png", optimize=True)
    fondo = Image.new("RGBA", (180, 180), PETROLEO)
    fondo.alpha_composite(dibujar(180, margen_seguro=0.08, redondeo=0))
    fondo.convert("RGB").save(DESTINO / "apple-touch-icon.png", optimize=True)
    dibujar(32, redondeo=0.2).save(DESTINO / "favicon-32.png", optimize=True)
    (DESTINO / "favicon.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        '<rect width="32" height="32" rx="7" fill="#12383d"/>'
        '<path d="M5.4 13 C 5.4 1.2, 26.6 1.2, 26.6 13" fill="none" stroke="#fff" stroke-width="1.7" stroke-linecap="round"/><rect x="12.6" y="2.2" width="6.8" height="2.6" rx="1.3" fill="#fff"/>'
        '<path d="M4.5 10 h23 l-2.6 17.5 q-.3 1.8 -2.1 1.8 h-13.6 q-1.8 0 -2.1 -1.8 z" fill="#fff"/>'
        '<path d="M5.6 17 q2.6 -1.6 5.2 0 t5.2 0 t5.2 0 t5.2 0 L24.8 27.3 q-.25 1.6 -1.9 1.6 h-13.8 q-1.65 0 -1.9 -1.6 Z" fill="#e8a11a"/>'
        "</svg>",
        encoding="utf-8",
    )
    print("Íconos generados en", DESTINO)


if __name__ == "__main__":
    main()
