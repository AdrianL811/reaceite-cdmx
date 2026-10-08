"""Motor de rutas: problema del agente viajero con depósito (TSP, caso de un vehículo del VRP).

Para hasta 11 paradas se resuelve de forma exacta con programación dinámica de Held-Karp
(O(2^n · n^2)); para más paradas se usa vecino más cercano mejorado con 2-opt.
Las distancias son haversine multiplicadas por un factor de rodeo urbano.
"""
import math
import time
from urllib.parse import quote

from .config import DEPOSITO, PARAMETROS, ZONAS

RADIO_TIERRA_M = 6_371_008.8
LIMITE_EXACTO = 11


def haversine_m(a, b):
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * RADIO_TIERRA_M * math.asin(math.sqrt(h))


def matriz_distancias(puntos, factor):
    n = len(puntos)
    return [[0.0 if i == j else haversine_m(puntos[i], puntos[j]) * factor for j in range(n)] for i in range(n)]


def costo_circuito(D, circuito):
    return sum(D[circuito[i]][circuito[(i + 1) % len(circuito)]] for i in range(len(circuito)))


def held_karp(D):
    """Circuito óptimo que sale del nodo 0, visita todos los demás y regresa al 0."""
    n = len(D)
    if n == 1:
        return [0], 0.0
    if n == 2:
        return [0, 1], D[0][1] + D[1][0]
    m = n - 1
    completo = (1 << m) - 1
    inf = float("inf")
    costo = [[inf] * m for _ in range(1 << m)]
    previo = [[-1] * m for _ in range(1 << m)]
    for j in range(m):
        costo[1 << j][j] = D[0][j + 1]
    for mascara in range(1, 1 << m):
        fila = costo[mascara]
        for j in range(m):
            c = fila[j]
            if c == inf or not (mascara >> j) & 1:
                continue
            dj = D[j + 1]
            for k in range(m):
                if (mascara >> k) & 1:
                    continue
                nueva = mascara | (1 << k)
                candidato = c + dj[k + 1]
                if candidato < costo[nueva][k]:
                    costo[nueva][k] = candidato
                    previo[nueva][k] = j
    mejor, ultimo = inf, -1
    for j in range(m):
        c = costo[completo][j] + D[j + 1][0]
        if c < mejor:
            mejor, ultimo = c, j
    orden, mascara, j = [], completo, ultimo
    while j != -1:
        orden.append(j + 1)
        anterior = previo[mascara][j]
        mascara ^= 1 << j
        j = anterior
    orden.reverse()
    return [0] + orden, mejor


def vecino_mas_cercano_2opt(D):
    n = len(D)
    pendientes = set(range(1, n))
    circuito, actual = [0], 0
    while pendientes:
        siguiente = min(pendientes, key=lambda j: D[actual][j])
        circuito.append(siguiente)
        pendientes.remove(siguiente)
        actual = siguiente
    mejora = True
    while mejora:
        mejora = False
        for i in range(1, n - 1):
            for k in range(i + 1, n):
                a, b = circuito[i - 1], circuito[i]
                c, d = circuito[k], circuito[(k + 1) % n]
                if D[a][c] + D[b][d] - D[a][b] - D[c][d] < -1e-9:
                    circuito[i:k + 1] = reversed(circuito[i:k + 1])
                    mejora = True
    return circuito, costo_circuito(D, circuito)


def url_google_maps(origen, paradas):
    """Enlace de navegación (no requiere API key): sale del depósito, visita y regresa."""
    def punto(p):
        return f"{p['lat']:.6f},{p['lon']:.6f}"
    url = (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={quote(punto(origen))}&destination={quote(punto(origen))}"
        "&travelmode=driving"
    )
    if paradas:
        url += "&waypoints=" + quote("|".join(punto(p) for p in paradas), safe="")
    return url


def planear(paradas, deposito=DEPOSITO, parametros=PARAMETROS):
    """paradas: lista de dicts con lat, lon (y cualquier otro dato). Devuelve el plan de la ruta."""
    puntos = [(deposito["lat"], deposito["lon"])] + [(p["lat"], p["lon"]) for p in paradas]
    D = matriz_distancias(puntos, parametros["factor_rodeo"])
    inicio = time.perf_counter()
    if len(paradas) <= LIMITE_EXACTO:
        circuito, distancia = held_karp(D)
        algoritmo = f"Held-Karp, programación dinámica exacta ({len(paradas)} paradas)"
    else:
        circuito, distancia = vecino_mas_cercano_2opt(D)
        algoritmo = f"Vecino más cercano con mejora 2-opt ({len(paradas)} paradas)"
    calculo_ms = (time.perf_counter() - inicio) * 1000
    distancia_base = costo_circuito(D, list(range(len(puntos))))
    orden = [paradas[i - 1] for i in circuito[1:]]
    duracion_s = distancia / 1000 / parametros["velocidad_kmh"] * 3600 + parametros["servicio_min"] * 60 * len(paradas)
    return {
        "orden": orden,
        "distancia_m": round(distancia),
        "distancia_base_m": round(distancia_base),
        "duracion_s": round(duracion_s),
        "algoritmo": algoritmo,
        "calculo_ms": round(calculo_ms, 3),
        "url_maps": url_google_maps(deposito, orden),
    }


def zona_mas_cercana(lat, lon):
    return min(ZONAS, key=lambda z: haversine_m((lat, lon), (ZONAS[z]["lat"], ZONAS[z]["lon"])))
