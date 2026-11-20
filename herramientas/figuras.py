"""Figuras del reporte y de la página /proyecto: Curva de Gartner, Task Flow, Tech Stack Map y Data Pipeline.

Uso: python herramientas/figuras.py   (requiere matplotlib y graphviz instalados)
"""
import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager as fm  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

DESTINO = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "reaceite" / "static" / "img"
DESTINO.mkdir(parents=True, exist_ok=True)

for carpeta in ("/usr/share/fonts/truetype/crosextra/",):
    for nombre in ("Carlito-Regular.ttf", "Carlito-Bold.ttf", "Carlito-Italic.ttf", "Carlito-BoldItalic.ttf"):
        ruta = Path(carpeta) / nombre
        if ruta.exists():
            fm.fontManager.addfont(str(ruta))
FUENTE = "Carlito" if any(f.name == "Carlito" for f in fm.fontManager.ttflist) else "DejaVu Sans"
plt.rcParams["font.family"] = FUENTE
plt.rcParams["text.parse_math"] = False

PETROLEO, ACEITE, AGUA, HOJA, CHILE = "#12383D", "#E8A11A", "#1C77B3", "#2C7A4B", "#B83A2B"
GRIS, TINTA, MORADO = "#6B7280", "#1F2937", "#5B3F8C"


# ---------------------------------------------------------------- 1. Curva de Gartner
def curva(x):
    return 2.2 * np.exp(-((x - 2.3) ** 2) / (2 * 0.55 ** 2)) + 1.1 / (1 + np.exp(-(x - 5.4) / 0.7)) + 0.15


def gartner():
    x = np.linspace(0, 10, 900)
    fig, ax = plt.subplots(figsize=(7.2, 3.9), dpi=300)
    ax.plot(x, curva(x), color=PETROLEO, lw=2.3, zorder=2)
    limites = [0, 1.75, 2.95, 4.6, 7.0, 10]
    fases = ["Disparador de\ninnovación", "Cima de\nexpectativas\ninfladas", "Valle de la\ndesilusión",
             "Pendiente de la\niluminación", "Meseta de\nproductividad"]
    for i in range(5):
        if i:
            ax.axvline(limites[i], ymin=0.19, color="#C9CED8", lw=0.8, ls=(0, (3, 3)), zorder=1)
        ax.text((limites[i] + limites[i + 1]) / 2, -0.34, fases[i], ha="center", va="top", fontsize=8.6, color=PETROLEO)

    def punto(xv, estilo):
        yv = curva(xv)
        if estilo == "gartner":
            ax.plot(xv, yv, "o", ms=7, color=PETROLEO, mec="white", mew=1.0, zorder=4)
        elif estilo == "historico":
            ax.plot(xv, yv, "o", ms=7, mfc="white", mec=GRIS, mew=1.3, zorder=4)
        elif estilo == "estimado":
            ax.plot(xv, yv, "o", ms=7, mfc="white", mec=PETROLEO, mew=1.6, zorder=4)
        else:
            ax.plot(xv, yv, "*", ms=17, color=ACEITE, mec=PETROLEO, mew=0.9, zorder=5)
        return yv

    def etiqueta(xv, yv, xt, yt, texto, color=TINTA, negrita=False):
        ax.annotate(texto, xy=(xv, yv), xytext=(xt, yt), fontsize=7.9, color=color, ha="left", va="bottom",
                    fontweight="bold" if negrita else "normal", bbox=dict(fc="white", ec="none", pad=0.4),
                    arrowprops=dict(arrowstyle="-", color=color if negrita else GRIS, lw=0.75, shrinkA=1, shrinkB=3))

    xa = 1.5
    etiqueta(xa, punto(xa, "gartner"), 0.03, 1.95, "Plataformas No-Code\n(Gartner, 2026):\nevaluadas y descartadas")
    xb = 2.6
    etiqueta(xb, punto(xb, "historico"), 2.95, 2.3, "Optimización de rutas en tiempo\nreal (Gartner, 2014 a 2018)")
    xc = 3.75
    etiqueta(xc, punto(xc, "estimado"), 1.9, -0.16, "Cobro por QR y celular\n(CoDi y DiMo)")
    xd = 4.85
    etiqueta(xd, punto(xd, "estimado"), 3.95, 1.62, "IoT de monitoreo\nde recipientes")
    xe = 5.6
    etiqueta(xe, punto(xe, "mvp"), 4.75, -0.14, "Núcleo del MVP: ruteo dinámico\npor umbral de 20 L (Held-Karp)", color=PETROLEO, negrita=True)
    xf = 6.45
    etiqueta(xf, punto(xf, "estimado"), 5.5, 1.98, "APIs de pago\ny webhooks")
    xg = 7.6
    etiqueta(xg, punto(xg, "estimado"), 6.95, 1.55, "PWA (apps web\ninstalables)")
    xh = 8.9
    etiqueta(xh, punto(xh, "estimado"), 8.05, 1.98, "Transferencias SPEI\n(7,300 millones en 2025)")
    ax.annotate("", xy=(5.42, curva(5.6) + 0.08), xytext=(2.78, curva(2.6) - 0.12),
                arrowprops=dict(arrowstyle="->", color=ACEITE, lw=1.1, ls=(0, (4, 3)), connectionstyle="arc3,rad=0.25"))
    ax.set_xlim(0, 10)
    ax.set_ylim(-1.05, 2.95)
    ax.set_xticks([])
    ax.set_yticks([])
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    ax.spines["left"].set_color(PETROLEO)
    ax.spines["bottom"].set_color(PETROLEO)
    ax.spines["bottom"].set_position(("data", -0.25))
    ax.spines["left"].set_bounds(-0.25, 2.95)
    ax.set_ylabel("Expectativas", fontsize=9, color=PETROLEO)
    ax.text(10, -0.2, "Tiempo y madurez", ha="right", va="bottom", fontsize=8.6, color=PETROLEO)
    leyenda = [
        Line2D([], [], marker="o", ls="", ms=6, color=PETROLEO, mec="white", label="Posición reportada por Gartner"),
        Line2D([], [], marker="o", ls="", ms=6, mfc="white", mec=GRIS, mew=1.3, label="Posición histórica de Gartner"),
        Line2D([], [], marker="o", ls="", ms=6, mfc="white", mec=PETROLEO, mew=1.6, label="Estimación del equipo con datos de adopción"),
        Line2D([], [], marker="*", ls="", ms=12, color=ACEITE, mec=PETROLEO, label="Núcleo del MVP (estimación)"),
    ]
    ax.legend(handles=leyenda, loc="upper right", fontsize=7.4, frameon=False, bbox_to_anchor=(1.01, 1.06))
    plt.tight_layout(pad=0.4)
    plt.savefig(DESTINO / "gartner.png", dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------- 2. Task Flow
TASKFLOW = r'''
digraph TF {
  graph [rankdir=TB, fontname="FUENTE", nodesep=0.30, ranksep=0.22, pad=0.10, newrank=true];
  node  [fontname="FUENTE", fontsize=13, shape=box, style="rounded,filled", fillcolor="#EEF3F2", color="#12383D", penwidth=1.2, margin="0.12,0.05"];
  edge  [fontname="FUENTE", fontsize=11.5, color="#12383D", arrowsize=0.7];
  inicio [label="Inicio", shape=ellipse, style=filled, fillcolor="#12383D", fontcolor=white, width=0.9];
  subgraph cluster_com { label="COMERCIANTE (celular y PIN)"; fontname="FUENTE"; fontsize=13; fontcolor="#2C7A4B"; color="#2C7A4B"; style="rounded,dashed";
    p1 [label="P1  Escanea el QR de su bote\n(/c/TOKEN)"];
    p2 [label="P2  ¿Sesión del\ndueño abierta?", shape=diamond, style=filled, fillcolor="#FFF5DF", margin="0.02,0.02"];
    p3 [label="P3  Entra con su PIN o se registra:\ndatos, GPS, celular y PIN;\npega su QR en el bote"];
    p4 [label="P4  Elige 5, 10 o 20 L y horario\ny toca «Pedir recolección»"];
    p5 [label="P5  Confirmación: folio, cubeta\nde la zona y pago estimado"];
    p9 [label="P9  Comprobante: LIQUIDADO,\nclave de rastreo y monto"];
  }
  subgraph cluster_pla { label="PLATAFORMA (automática)"; fontname="FUENTE"; fontsize=13; fontcolor="#5B3F8C"; color="#5B3F8C"; style="rounded,dashed";
    d1 [label="¿La zona suma 20 L\no alguien espera 48 h?", shape=diamond, style=filled, fillcolor="#FFF5DF", margin="0.02,0.02"];
    a1 [label="Motor de rutas Held-Karp:\norden óptimo de paradas"];
    a2 [label="Ruta creada con enlace\nde navegación"];
    a3 [label="Métricas Verdes, pago y orden\nen la cola (una transacción)"];
    a4 [label="API SPEI simulada: 202 y\nwebhook firmado de liquidación"];
  }
  subgraph cluster_rec { label="RECOLECTOR (con sesión)"; fontname="FUENTE"; fontsize=13; fontcolor="#B5650A"; color="#B5650A"; style="rounded,dashed";
    p6 [label="P6  Ruta del día: mapa,\nparadas y botón de navegación"];
    p7 [label="P7  Escanea el QR con el\nescáner de la app"];
    p8 [label="P8  Captura el peso, revisa la vista\nprevia y confirma la recolección"];
  }
  fin [label="Fin: aceite trazado y pagado", shape=ellipse, style=filled, fillcolor="#2C7A4B", fontcolor=white];
  { rank=same; p2; p3; }
  { rank=same; p5; d1; }
  { rank=same; a2; p6; }
  { rank=same; a3; p8; }
  { rank=same; p9; a4; }
  inicio -> p1 -> p2;
  p2 -> p3 [label=" No", constraint=false];
  p2 -> p4 [label=" Sí"];
  p3 -> p4;
  p4 -> p5;
  p5 -> d1 [constraint=false];
  d1:e -> d1:n [label=" No: espera", fontsize=10.5];
  d1 -> a1 [label=" Sí"];
  a1 -> a2;
  a2 -> p6 [constraint=false];
  p6 -> p7 -> p8;
  p8 -> a3 [constraint=false];
  a3 -> a4;
  a4 -> p9 [constraint=false];
  p9 -> fin;
}
'''


def taskflow():
    dot = DESTINO / "taskflow.dot"
    dot.write_text(TASKFLOW.replace("FUENTE", FUENTE), encoding="utf-8")
    subprocess.run(["dot", "-Tpng", "-Gdpi=220", str(dot), "-o", str(DESTINO / "taskflow.png")], check=True)
    dot.unlink()


# ---------------------------------------------------------------- 3. Tech Stack Map
def stack():
    fig, ax = plt.subplots(figsize=(7.2, 5.9), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 80)
    ax.axis("off")
    bandas = [  # y0, alto, título vertical, fondo, borde
        (66.5, 12.5, "NEGOCIO", "#E7F3EA", HOJA),
        (47.5, 15.5, "APLICACIÓN\n(PWA)", "#E3EEF6", PETROLEO),
        (20.5, 22.0, "DATOS E\nINTEGRACIÓN", "#EFE9F6", MORADO),
        (1.0, 15.5, "TECNOLOGÍA", "#FFF2DD", "#B5650A"),
    ]
    for y0, alto, titulo, fondo, borde in bandas:
        ax.add_patch(FancyBboxPatch((0.8, y0), 98.4, alto, boxstyle="round,pad=0.2,rounding_size=1.6", fc=fondo, ec=borde, lw=1.1))
        ax.text(3.9, y0 + alto / 2, titulo, ha="center", va="center", rotation=90, fontsize=7.0, color=borde,
                fontweight="bold", linespacing=1.05)

    def caja(x, y, w, h, titulo, sub, color, punteada=False):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.15,rounding_size=1.2", fc="white", ec=color,
                                    lw=1.1, ls=(0, (3, 2)) if punteada else "-"))
        ax.text(x + w / 2, y + h - 1.3, titulo, ha="center", va="top", fontsize=7.5, color=color, fontweight="bold")
        ax.text(x + w / 2, y + h - 4.3, sub, ha="center", va="top", fontsize=6.6, color=TINTA, linespacing=1.15)
        return (x, y, w, h)

    def columnas(n, izquierda=8.0, derecha=1.8, hueco=2.6):
        ancho = (100 - izquierda - derecha - (n - 1) * hueco) / n
        return [izquierda + i * (ancho + hueco) for i in range(n)], ancho

    xs4, w4 = columnas(4)
    xs5, w5 = columnas(5)
    n = [caja(xs4[0], 68.0, w4, 7.8, "Recicladora o planta", "compra el aceite trazado", HOJA),
         caja(xs4[1], 68.0, w4, 7.8, "Comerciante", "proveedor de aceite usado", HOJA),
         caja(xs4[2], 68.0, w4, 7.8, "Recolector", "logística y pesaje", HOJA),
         caja(xs4[3], 68.0, w4, 7.8, "Squad", "administración y parámetros", HOJA)]
    a = [caja(xs4[0], 50.0, w4, 10.0, "Impacto y monitor", "/impacto y /monitor:\nMétricas Verdes en vivo", PETROLEO),
         caja(xs4[1], 50.0, w4, 10.0, "Comercio", "/registro y /c/TOKEN:\nsolicitud y comprobante", PETROLEO),
         caja(xs4[2], 50.0, w4, 10.0, "Pesaje", "/r/pesar: escáner QR,\nbáscula y vista previa", PETROLEO),
         caja(xs4[3], 50.0, w4, 10.0, "Ruta del día", "/r: mapa Leaflet y\nparadas en orden", PETROLEO)]
    d = [caja(xs5[0], 26.5, w5, 12.2, "Motor de rutas", "Held-Karp exacto\nhasta 11 paradas;\n2-opt después", MORADO),
         caja(xs5[1], 26.5, w5, 12.2, "SQLite (WAL)", "9 tablas: comercio,\nsolicitud, ruta,\npago, eventos...", MORADO),
         caja(xs5[2], 26.5, w5, 12.2, "API REST Flask", "Métricas Verdes\n(Decimal), regla de\n20 L, sesiones, CSRF", MORADO),
         caja(xs5[3], 26.5, w5, 12.2, "Despachador", "cola outbox con\nreintentos e\nidempotencia", MORADO),
         caja(xs5[4], 26.5, w5, 12.2, "API SPEI simulada", "202 Accepted y\nwebhook firmado\nHMAC-SHA256", CHILE)]
    t = [caja(xs5[0], 2.6, w5, 10.6, "Google Maps", "enlace de navegación\n(sin API key)", "#B5650A"),
         caja(xs5[1], 2.6, w5, 10.6, "Render", "contenedor Linux,\ngunicorn y HTTPS", "#B5650A"),
         caja(xs5[2], 2.6, w5, 10.6, "Báscula IoT", "siguiente iteración:\npeso automático", "#B5650A", punteada=True),
         caja(xs5[3], 2.6, w5, 10.6, "Navegador móvil", "service worker,\ncámara y GPS", "#B5650A"),
         caja(xs5[4], 2.6, w5, 10.6, "OpenStreetMap", "teselas de los\nmapas de la PWA", "#B5650A")]

    gris = "#4B5563"

    def flecha(p, q, doble=False, punteada=False, color=gris, curva=None):
        ax.add_patch(FancyArrowPatch(p, q, arrowstyle="<|-|>" if doble else "-|>", mutation_scale=7.5, color=color,
                                     lw=1.0, ls=(0, (3, 2)) if punteada else "-", shrinkA=0, shrinkB=0,
                                     connectionstyle=f"arc3,rad={curva}" if curva else "arc3"))

    def centro_x(b, f=0.5):
        return b[0] + b[2] * f

    def nota(x, y, texto, color="#374151", italica=True, ha="center"):
        ax.text(x, y, texto, fontsize=6.5, color=color, ha=ha, va="center", style="italic" if italica else "normal",
                bbox=dict(fc="white", ec="none", pad=0.4))

    # Actores a la PWA
    flecha((centro_x(n[0]), n[0][1]), (centro_x(a[0]), a[0][1] + a[0][3]), punteada=True)
    flecha((centro_x(n[1]), n[1][1]), (centro_x(a[1]), a[1][1] + a[1][3]))
    flecha((centro_x(n[2], 0.4), n[2][1]), (centro_x(a[2], 0.6), a[2][1] + a[2][3]))
    flecha((centro_x(n[2], 0.8), n[2][1]), (centro_x(a[3], 0.3), a[3][1] + a[3][3]))
    flecha((centro_x(n[3]), n[3][1]), (centro_x(a[0], 0.85), a[0][1] + a[0][3]), punteada=True)
    nota(53, 64.7, "los actores entran escaneando un QR o desde el navegador")

    # PWA al backend: un solo canal de peticiones JSON
    bus_y = 45.6
    for caja_app in a:
        ax.plot([centro_x(caja_app)] * 2, [caja_app[1], bus_y], color=gris, lw=1.0)
    ax.plot([centro_x(a[0]), centro_x(a[3])], [bus_y, bus_y], color=gris, lw=1.0)
    api_x = centro_x(d[2])
    flecha((api_x, bus_y), (api_x, d[2][1] + d[2][3]), doble=True)
    nota(api_x + 1.6, 44.0, "peticiones JSON por HTTPS (fetch)", ha="left")

    # Dentro del backend
    flecha((d[2][0], d[2][1] + d[2][3] / 2), (d[1][0] + d[1][2], d[1][1] + d[1][3] / 2), doble=True)
    flecha((d[2][0] + d[2][2], d[2][1] + d[2][3] / 2), (d[3][0], d[3][1] + d[3][3] / 2))
    flecha((d[3][0] + d[3][2], d[3][1] + d[3][3] / 2), (d[4][0], d[4][1] + d[4][3] / 2), doble=True)
    flecha((d[2][0] + 2.5, d[2][1] + d[2][3]), (d[0][0] + d[0][2] - 2.5, d[0][1] + d[0][3]), curva=0.2)
    nota(centro_x(d[1]), 39.9, "calcula la ruta al llegar a 20 L")
    # Webhook de regreso: por debajo de las cajas
    y_regreso = 23.6
    ax.plot([centro_x(d[4]), centro_x(d[4])], [d[4][1], y_regreso], color=CHILE, lw=1.1)
    ax.plot([centro_x(d[4]), centro_x(d[2], 0.75)], [y_regreso, y_regreso], color=CHILE, lw=1.1)
    flecha((centro_x(d[2], 0.75), y_regreso), (centro_x(d[2], 0.75), d[2][1]), color=CHILE)
    nota(centro_x(d[3]), y_regreso, "webhook firmado de regreso", color=CHILE, italica=False)

    # Servicios
    flecha((centro_x(d[0]), d[0][1]), (centro_x(t[0]), t[0][1] + t[0][3]))
    flecha((centro_x(t[1]), t[1][1] + t[1][3]), (centro_x(d[1]), d[1][1]), punteada=True)
    flecha((centro_x(t[2], 0.35), t[2][1] + t[2][3]), (centro_x(d[2], 0.35), d[2][1]), punteada=True)
    nota(centro_x(t[0]), 18.5, "url de navegación", italica=False)
    nota(centro_x(t[1]), 18.5, "aloja el backend", italica=False)
    nota(centro_x(t[2], 0.35), 18.5, "peso (kg)", italica=False)
    plt.savefig(DESTINO / "stack.png", dpi=300, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)


# ---------------------------------------------------------------- 4. Data Pipeline
def pipeline():
    fig, ax = plt.subplots(figsize=(7.2, 2.75), dpi=300)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 38)
    ax.axis("off")
    ancho, alto = 22.2, 15.2
    xs = [1.0, 26.0, 51.0, 76.0]
    fila_sup, fila_inf = 21.6, 1.6
    etapas = [
        ("1. DATO CRUDO", "QR COM-0006 escaneado\nbáscula: 4.6 kg", "#FFF2DD", "#B5650A"),
        ("2. NORMALIZACIÓN", "4.6 kg ÷ 0.92 kg/L\n= 5.00 L (decimal exacto)", "#E9F0F1", PETROLEO),
        ("3. VALIDACIÓN", "QR registrado, solicitud\nabierta, 5.00 L ≤ 7.50 L", "#E9F0F1", PETROLEO),
        ("4. ENRIQUECIMIENTO", "agua 5,000 L; bio 4.50 L\nbruto $30, comisión $3\nneto $27", "#E9F0F1", PETROLEO),
        ("5. EVENTO", "recolección, pago y orden\nen la cola: una transacción", "#E9F0F1", PETROLEO),
        ("6. ORDEN A LA API SPEI", "POST /sim-spei/v1/\ntransferencias: 202\ncon Idempotency-Key", "#EFE9F6", MORADO),
        ("7. WEBHOOK", "POST /webhooks/spei\nfirma HMAC-SHA256\nverificada", "#FBE6E2", CHILE),
        ("8. ACTIVO FINANCIERO", "pago LIQUIDADO, clave\nde rastreo, comprobante\ny tablero", "#E2F2E7", HOJA),
    ]
    posiciones = [(xs[0], fila_sup), (xs[1], fila_sup), (xs[2], fila_sup), (xs[3], fila_sup),
                  (xs[3], fila_inf), (xs[2], fila_inf), (xs[1], fila_inf), (xs[0], fila_inf)]
    for (titulo, cuerpo, fondo, borde), (px, py) in zip(etapas, posiciones):
        ax.add_patch(FancyBboxPatch((px, py), ancho, alto, boxstyle="round,pad=0.2,rounding_size=2.0", fc=fondo, ec=borde, lw=1.2))
        ax.text(px + ancho / 2, py + alto - 2.2, titulo, ha="center", va="top", fontsize=8.1, fontweight="bold", color=borde)
        ax.text(px + ancho / 2, py + alto - 5.8, cuerpo, ha="center", va="top", fontsize=7.6, color=TINTA, linespacing=1.15)

    def flecha(p, q):
        ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=9, color=PETROLEO, lw=1.3))

    for i in range(3):
        flecha((xs[i] + ancho + 0.4, fila_sup + alto / 2), (xs[i + 1] - 0.4, fila_sup + alto / 2))
    flecha((xs[3] + ancho / 2, fila_sup - 0.4), (xs[3] + ancho / 2, fila_inf + alto + 0.4))
    for i in (3, 2, 1):
        flecha((xs[i] - 0.4, fila_inf + alto / 2), (xs[i - 1] + ancho + 0.4, fila_inf + alto / 2))
    plt.savefig(DESTINO / "pipeline.png", dpi=300, bbox_inches="tight", pad_inches=0.03)
    plt.close(fig)


if __name__ == "__main__":
    gartner()
    if shutil.which("dot"):
        taskflow()
    else:
        print("Graphviz no está instalado: se omite el Task Flow")
    stack()
    pipeline()
    print("Figuras guardadas en", DESTINO)
