import itertools
import random
import time
from decimal import Decimal

import pytest

from reaceite import clabe, firma, metricas, rutas


# ---------------------------------------------------------------- Métricas Verdes
def test_ejemplo_del_reporte():
    m = metricas.calcular("4.6")
    assert m["litros"] == Decimal("5.00")
    assert m["agua_l"] == Decimal("5000")
    assert m["biocombustible_l"] == Decimal("4.50")
    assert m["pago_bruto"] == Decimal("30.00")
    assert m["comision"] == Decimal("3.00")
    assert m["pago_neto"] == Decimal("27.00")


def test_veinte_litros():
    m = metricas.calcular(18.4)
    assert (m["litros"], m["agua_l"], m["pago_bruto"], m["comision"], m["pago_neto"]) == (
        Decimal("20.00"), Decimal("20000"), Decimal("120.00"), Decimal("12.00"), Decimal("108.00"))


def test_redondeo_comercial_y_coma_decimal():
    m = metricas.calcular("1,0")
    assert m["litros"] == Decimal("1.09")          # 1.0869... redondea a 1.09
    assert m["pago_bruto"] == Decimal("6.54")
    assert m["comision"] == Decimal("0.65")         # 0.654 redondea a 0.65
    assert m["pago_neto"] == Decimal("5.89")
    assert m["pago_neto"] + m["comision"] == m["pago_bruto"]


@pytest.mark.parametrize("malo", ["", "abc", "-1", "0", "0.01", "101", "nan", "inf"])
def test_pesos_invalidos(malo):
    with pytest.raises(metricas.PesoInvalido):
        metricas.calcular(malo)


def test_enteros_sin_perdida():
    e = metricas.a_enteros(metricas.calcular("4.6"))
    assert e == {"peso_g": 4600, "litros_cl": 500, "agua_l": 5000, "biocombustible_cl": 450,
                 "bruto_cent": 3000, "comision_cent": 300, "neto_cent": 2700}


# ---------------------------------------------------------------- CLABE
def test_clabe_conocida():
    assert clabe.es_valida("032180000118359719")
    assert not clabe.es_valida("032180000118359718")
    assert not clabe.es_valida("03218000011835971")
    assert not clabe.es_valida("03218000011835971X")


def test_clabe_simulada_valida():
    for n in (1, 6, 123, 99999):
        c = clabe.simulada(n)
        assert len(c) == 18 and c.startswith("999180") and clabe.es_valida(c)


# ---------------------------------------------------------------- Rutas
def fuerza_bruta(D):
    n = len(D)
    mejor = min(itertools.permutations(range(1, n)), key=lambda p: rutas.costo_circuito(D, [0, *p]))
    return rutas.costo_circuito(D, [0, *mejor])


@pytest.mark.parametrize("semilla", range(25))
def test_held_karp_es_optimo(semilla):
    rnd = random.Random(semilla)
    n = rnd.randint(2, 8)
    puntos = [(19.40 + rnd.random() * 0.03, -99.18 + rnd.random() * 0.03) for _ in range(n)]
    D = rutas.matriz_distancias(puntos, 1.3)
    circuito, costo = rutas.held_karp(D)
    assert sorted(circuito) == list(range(n)) and circuito[0] == 0
    assert costo == pytest.approx(rutas.costo_circuito(D, circuito))
    assert costo == pytest.approx(fuerza_bruta(D))


def test_dos_opt_valido_y_no_peor_que_vecino():
    rnd = random.Random(7)
    puntos = [(19.40 + rnd.random() * 0.05, -99.19 + rnd.random() * 0.05) for _ in range(30)]
    D = rutas.matriz_distancias(puntos, 1.3)
    circuito, costo = rutas.vecino_mas_cercano_2opt(D)
    assert sorted(circuito) == list(range(30))
    assert costo <= rutas.costo_circuito(D, list(range(30)))


def test_held_karp_rapido_con_11_paradas():
    rnd = random.Random(3)
    puntos = [(19.40 + rnd.random() * 0.03, -99.18 + rnd.random() * 0.03) for _ in range(12)]
    inicio = time.perf_counter()
    rutas.held_karp(rutas.matriz_distancias(puntos, 1.3))
    assert time.perf_counter() - inicio < 5


def test_plan_y_enlace_maps():
    paradas = [{"lat": 19.4129, "lon": -99.1715}, {"lat": 19.4101, "lon": -99.1687}]
    plan = rutas.planear(paradas)
    assert plan["distancia_m"] <= plan["distancia_base_m"]
    assert plan["url_maps"].startswith("https://www.google.com/maps/dir/?api=1&origin=")
    assert "waypoints=" in plan["url_maps"]


def test_zona_mas_cercana():
    assert rutas.zona_mas_cercana(19.4118, -99.1701) == "hipodromo"
    assert rutas.zona_mas_cercana(19.4190, -99.1600) == "roma-norte"


# ---------------------------------------------------------------- Firma de webhooks
def test_firma_valida_y_alterada():
    cuerpo = b'{"monto":"27.00"}'
    cab = firma.firmar("secreto", cuerpo, ts=1_000_000)
    assert firma.verificar("secreto", cuerpo, cab, ahora=1_000_010) == (True, "")
    assert not firma.verificar("secreto", b'{"monto":"99.00"}', cab, ahora=1_000_010)[0]
    assert not firma.verificar("otro", cuerpo, cab, ahora=1_000_010)[0]
    assert not firma.verificar("secreto", cuerpo, cab, ahora=1_000_000 + 301)[0]
    assert not firma.verificar("secreto", cuerpo, "", ahora=1_000_000)[0]
