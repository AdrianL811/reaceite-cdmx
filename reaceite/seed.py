"""Datos de demostración: comercios ficticios, historial de recolecciones y el escenario de la demo.

Escenario: Hipódromo tiene 15 L pendientes (10 L + 5 L). Cuando el «Puesto demo» (COM-0006)
pide 5 L, la zona llega a 20 L y la ruta sale sola.
"""
import json
from datetime import timedelta, timezone

from werkzeug.security import generate_password_hash

from . import metricas, servicios
from .config import TZ
from .db import ahora_utc, iso, meta_set, siguiente_numero, vaciar
from .metricas import a_enteros, calcular

VERSION_SEMILLA = 3

COMERCIOS = [
    # código, nombre, tipo, dirección, zona, franja, lat, lon
    ("COM-0001", "Fonda Doña Mary", "Fonda", "Calle Atlixco 112", "condesa", "12-14", 19.41264, -99.17818),
    ("COM-0002", "Tacos El Güero", "Taquería", "Calle Ámsterdam 210", "hipodromo", "10-12", 19.41291, -99.17148),
    ("COM-0003", "Arrachera Don Chuy", "Puesto ambulante", "Av. México 45", "hipodromo", "10-12", 19.41009, -99.16872),
    ("COM-0004", "Churros La Esquina", "Churrería", "Calle Campeche 300", "hipodromo", "16-18", 19.40921, -99.16655),
    ("COM-0005", "Garnachas Celaya", "Puesto ambulante", "Calle Celaya 17", "hipodromo", "08-10", 19.41382, -99.16917),
    ("COM-0006", "Puesto demo", "Puesto ambulante", "Av. Michoacán 30", "hipodromo", "10-12", 19.41147, -99.17046),
    ("COM-0007", "Taquería Los Primos", "Taquería", "Calle Colima 150", "roma-norte", "12-14", 19.41941, -99.16013),
    ("COM-0008", "Fonda La Escandón", "Fonda", "Calle José Martí 80", "escandon", "12-14", 19.40393, -99.18122),
]

# Historial: (código, días atrás, horas, peso en kg)
HISTORIAL = [
    ("COM-0002", 11, 10.5, "18.4"),
    ("COM-0004", 10, 17.0, "27.6"),
    ("COM-0001", 9, 13.2, "17.5"),
    ("COM-0003", 8, 11.1, "9.1"),
    ("COM-0007", 7, 12.4, "16.6"),
    ("COM-0005", 6, 9.0, "8.3"),
    ("COM-0002", 5, 10.8, "14.7"),
    ("COM-0008", 5, 13.5, "6.9"),
    ("COM-0004", 4, 16.6, "22.1"),
    ("COM-0001", 3, 12.9, "9.2"),
    ("COM-0007", 2, 13.1, "12.0"),
]

# Solicitudes pendientes al iniciar la demo: (código, litros, franja, horas atrás)
PENDIENTES = [
    ("COM-0002", 10, "10-12", 3.5),
    ("COM-0003", 5, "10-12", 2.0),
    ("COM-0007", 10, "12-14", 4.0),
    ("COM-0001", 5, "12-14", 1.5),
]


def sembrar(conn, config):
    """Borra todo y carga el escenario de demostración. Debe llamarse dentro de una transacción."""
    vaciar(conn)
    ahora = ahora_utc()
    conn.executemany(
        "INSERT INTO usuario(id, usuario, nombre, rol, hash) VALUES (?, ?, ?, ?, ?)",
        [
            (1, "admin", "Administración del squad", "admin", generate_password_hash(config["ADMIN_PASSWORD"])),
            (2, "recolector", "Recolector demo", "recolector", generate_password_hash(config["RECOLECTOR_PASSWORD"])),
        ],
    )
    hace_dos_semanas = iso(ahora - timedelta(days=14))
    comercios = {}
    for codigo, nombre, tipo, direccion, zona, franja, lat, lon in COMERCIOS:
        fila = servicios.crear_comercio(
            conn,
            {"nombre": nombre, "tipo": tipo, "direccion": direccion, "zona": zona, "franja": franja,
             "lat": lat, "lon": lon},
            demo=True, token=servicios.token_semilla(codigo), creado=hace_dos_semanas,
        )
        assert fila["codigo"] == codigo
        comercios[codigo] = fila

    medianoche = ahora.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    for codigo, dias, horas, peso in HISTORIAL:
        cuando = (medianoche - timedelta(days=dias) + timedelta(hours=horas)).astimezone(timezone.utc)
        _recoleccion_historica(conn, comercios[codigo], cuando, peso)

    for codigo, litros, franja, horas in PENDIENTES:
        conn.execute(
            "INSERT INTO solicitud(id, folio, comercio_id, zona, franja, litros_estimados, estado, creado, actualizado) "
            "VALUES (?, ?, ?, ?, ?, ?, 'PENDIENTE', ?, ?)",
            (n := siguiente_numero(conn, "solicitud"), f"SOL-{n:06d}", comercios[codigo]["id"],
             comercios[codigo]["zona"], franja, litros, iso(ahora - timedelta(hours=horas)),
             iso(ahora - timedelta(hours=horas))),
        )
    meta_set(conn, "semilla", {"version": VERSION_SEMILLA, "cargada": iso(ahora)})


def _recoleccion_historica(conn, comercio, cuando, peso):
    m = calcular(peso)
    e = a_enteros(m)
    t = iso(cuando)
    anio = cuando.year
    n_sol = siguiente_numero(conn, "solicitud")
    estimado = min(20, max(5, int(round(float(m["litros"]) / 5) * 5)))
    conn.execute(
        "INSERT INTO solicitud(id, folio, comercio_id, zona, franja, litros_estimados, estado, creado, actualizado) "
        "VALUES (?, ?, ?, ?, ?, ?, 'RECOLECTADA', ?, ?)",
        (n_sol, f"SOL-{n_sol:06d}", comercio["id"], comercio["zona"], comercio["franja"], estimado,
         iso(cuando - timedelta(hours=20)), t),
    )
    n_rec = siguiente_numero(conn, "recoleccion")
    folio = f"REC-{anio}-{n_rec:06d}"
    conn.execute(
        "INSERT INTO recoleccion(id, folio, solicitud_id, comercio_id, recolector_id, peso_g, litros_cl, agua_l, "
        "biocombustible_cl, bruto_cent, comision_cent, neto_cent, creado) VALUES (?, ?, ?, ?, 2, ?, ?, ?, ?, ?, ?, ?, ?)",
        (n_rec, folio, n_sol, comercio["id"], e["peso_g"], e["litros_cl"], e["agua_l"], e["biocombustible_cl"],
         e["bruto_cent"], e["comision_cent"], e["neto_cent"], t),
    )
    n_pag = siguiente_numero(conn, "pago")
    folio_pago = f"PAG-{anio}-{n_pag:06d}"
    liquidado = cuando + timedelta(seconds=2)
    n_orden = siguiente_numero(conn, "spei_orden")
    folio_banco = f"SIM{cuando:%y%m%d}{n_orden:06d}"
    clave = f"RAC{cuando:%Y%m%d%H%M%S}{(n_orden * 7919) % 10000:04d}"
    conn.execute(
        "INSERT INTO pago(id, folio, recoleccion_id, comercio_id, monto_cent, clabe, idempotency_key, estatus, "
        "folio_banco, clave_rastreo, intentos, creado, enviado, liquidado) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'LIQUIDADO', ?, ?, 1, ?, ?, ?)",
        (n_pag, folio_pago, n_rec, comercio["id"], e["neto_cent"], comercio["clabe"], f"{folio}-v1", folio_banco,
         clave, t, t, iso(liquidado)),
    )
    conn.execute(
        "INSERT INTO spei_orden(id, idempotency_key, huella, folio, clave_rastreo, monto_cent, clabe, beneficiario, "
        "referencia, concepto, webhook_url, estatus, liquidar_en, webhook_estado, webhook_intentos, webhook_http, "
        "respuesta, creado, liquidado) VALUES (?, ?, 'historial', ?, ?, ?, ?, ?, ?, ?, '/webhooks/spei', "
        "'LIQUIDADA', ?, 'ENTREGADO', 1, 200, ?, ?, ?)",
        (n_orden, f"{folio}-v1", folio_banco, clave, e["neto_cent"], comercio["clabe"], comercio["nombre"],
         folio_pago, f"Compra de {m['litros']} L de aceite usado ({folio})", iso(liquidado),
         json.dumps({"folio": folio_banco, "clave_rastreo": clave, "estatus": "RECIBIDA",
                     "monto": metricas.pesos(e["neto_cent"])}), t, iso(liquidado)),
    )
    conn.execute(
        "UPDATE comercio SET litros_cl = litros_cl + ?, agua_l = agua_l + ?, cobrado_cent = cobrado_cent + ? "
        "WHERE id = ?",
        (e["litros_cl"], e["agua_l"], e["neto_cent"], comercio["id"]),
    )
