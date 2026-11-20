"""Datos de demostración: comercios ficticios, historial de recolecciones y el escenario de la demo.

Escenario: Hipódromo tiene 15 L pendientes (10 L + 5 L). Cuando el «Puesto demo» (COM-0006)
pide 5 L, la zona llega a 20 L y la ruta sale sola.

Cuentas: cada comercio de demostración entra con el celular 55 1000 00NN (NN = su número)
y el PIN de la variable PIN_DEMO (900900 si no se define).

Sprint 3: dos contenedores inteligentes con depósitos previos, el Fondo de Garantía de Dispersión
con su capital semilla (FONDO_INICIAL) y una billetera por comercio con su historial de abonos.
"""
import json
from datetime import timedelta, timezone
from decimal import Decimal

from werkzeug.security import generate_password_hash

from . import cuentas, iot, metricas, servicios, spei_sim
from .config import CONTENEDORES, PLANTA, TZ
from .db import ahora_utc, iso, meta_set, siguiente_numero, vaciar
from .metricas import a_enteros, calcular

VERSION_SEMILLA = 5


def telefono_demo(codigo):
    """COM-0006 → 5510000006."""
    return f"55100000{int(codigo[-4:]):02d}"

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

# Depósitos anteriores en contenedores: (comercio, contenedor, días atrás, horas, peso en kg)
HISTORIAL_CONTENEDOR = [
    ("COM-0004", "CTN-0001", 5, 16.8, "18.5"),
    ("COM-0005", "CTN-0001", 3, 18.2, "7.4"),
    ("COM-0003", "CTN-0001", 1, 19.0, "5.5"),
    ("COM-0007", "CTN-0002", 2, 17.5, "6.1"),
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
    pin_hash = cuentas.hash_pin(config["PIN_DEMO"])  # un solo hash: los 8 comparten el PIN de demostración
    comercios = {}
    for codigo, nombre, tipo, direccion, zona, franja, lat, lon in COMERCIOS:
        fila = servicios.crear_comercio(
            conn,
            {"nombre": nombre, "tipo": tipo, "direccion": direccion, "zona": zona, "franja": franja,
             "lat": lat, "lon": lon, "telefono": telefono_demo(codigo)},
            demo=True, token=servicios.token_semilla(codigo), creado=hace_dos_semanas,
            pin_hash=pin_hash, sal=cuentas.sal_demo(codigo, config["SECRET_KEY"]),
        )
        assert fila["codigo"] == codigo
        comercios[codigo] = fila

    contenedores = _contenedores(conn, config, hace_dos_semanas)
    medianoche = ahora.astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    historial = [(codigo, dias, horas, peso, None) for codigo, dias, horas, peso in HISTORIAL]
    historial += [(codigo, dias, horas, peso, ctn) for codigo, ctn, dias, horas, peso in HISTORIAL_CONTENEDOR]
    historial.sort(key=lambda h: (-h[1], h[2]))
    for codigo, dias, horas, peso, ctn in historial:
        cuando = (medianoche - timedelta(days=dias) + timedelta(hours=horas)).astimezone(timezone.utc)
        _recoleccion_historica(conn, comercios[codigo], cuando, peso, contenedores.get(ctn))
    _pasarela(conn, config, ahora - timedelta(days=14))

    for codigo, litros, franja, horas in PENDIENTES:
        conn.execute(
            "INSERT INTO solicitud(id, folio, comercio_id, zona, franja, litros_estimados, estado, creado, actualizado) "
            "VALUES (?, ?, ?, ?, ?, ?, 'PENDIENTE', ?, ?)",
            (n := siguiente_numero(conn, "solicitud"), f"SOL-{n:06d}", comercios[codigo]["id"],
             comercios[codigo]["zona"], franja, litros, iso(ahora - timedelta(hours=horas)),
             iso(ahora - timedelta(hours=horas))),
        )
    meta_set(conn, "semilla", {"version": VERSION_SEMILLA, "cargada": iso(ahora)})


def _contenedores(conn, config, creado):
    creados = {}
    for codigo, nombre, direccion, zona, lat, lon, capacidad in CONTENEDORES:
        if conn.execute("SELECT 1 FROM contenedor WHERE codigo = ?", (codigo,)).fetchone():
            continue
        conn.execute(
            "INSERT INTO contenedor(codigo, token, nombre, direccion, zona, lat, lon, capacidad_l, secreto, creado) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (codigo, servicios.token_semilla(codigo), nombre, direccion, zona, lat, lon, capacidad,
             iot.secreto_dispositivo(config, codigo), creado),
        )
        creados[codigo] = conn.execute("SELECT * FROM contenedor WHERE codigo = ?", (codigo,)).fetchone()
    return creados


def _pasarela(conn, config, desde):
    """Cuentas de la pasarela simulada y sus movimientos, coherentes con el historial de pagos."""
    t = iso(desde)
    fondo = spei_sim.asegurar_cuenta(conn, spei_sim.FONDO_CLABE, "ReAceite CDMX · Fondo de Garantía de Dispersión",
                                     "FONDO", creado=t)
    planta = spei_sim.asegurar_cuenta(conn, spei_sim.PLANTA_CLABE, f"{PLANTA['nombre']} (simulada)", "PLANTA",
                                      creado=t)
    if conn.execute("SELECT COUNT(*) FROM movimiento").fetchone()[0]:
        return
    inicial = int(Decimal(str(config.get("FONDO_INICIAL", "45000.00"))) * 100)
    spei_sim.mover(conn, fondo["id"], "ABONO", inicial, "Capital semilla del Fondo de Garantía de Dispersión",
                   "CAPITAL-SEMILLA", creado=t)
    spei_sim.mover(conn, planta["id"], "ABONO", 100_000_000, "Saldo de la planta en el banco simulado", creado=t)
    for c in conn.execute("SELECT * FROM comercio ORDER BY id").fetchall():
        spei_sim.asegurar_cuenta(conn, c["clabe"], c["nombre"], "BILLETERA", c["telefono"], creado=c["creado"])
    for p in conn.execute(
            "SELECT p.*, o.folio AS orden, o.concepto, c.nombre FROM pago p JOIN spei_orden o ON o.referencia = p.folio "
            "JOIN comercio c ON c.id = p.comercio_id WHERE p.estatus = 'LIQUIDADO' ORDER BY p.liquidado").fetchall():
        destino = spei_sim.cuenta_por_clabe(conn, p["clabe"])
        spei_sim.mover(conn, fondo["id"], "CARGO", p["monto_cent"], f"SPEI enviado a {p['nombre']}", p["folio"],
                       p["orden"], creado=p["creado"])
        spei_sim.mover(conn, destino["id"], "ABONO", p["monto_cent"], p["concepto"], p["folio"], p["orden"],
                       creado=p["liquidado"])
    conn.execute("UPDATE spei_orden SET clabe_origen = ?", (spei_sim.FONDO_CLABE,))


def completar_sprint3(conn, config):
    """Bases creadas antes del Sprint 3: agrega contenedores, cuentas de la pasarela y billeteras que falten."""
    _contenedores(conn, config, iso(ahora_utc()))
    if spei_sim.cuenta_por_clabe(conn, spei_sim.FONDO_CLABE) is None:
        _pasarela(conn, config, ahora_utc())
    for c in conn.execute("SELECT * FROM comercio WHERE clabe NOT IN (SELECT clabe FROM cuenta)").fetchall():
        cuenta = spei_sim.asegurar_cuenta(conn, c["clabe"], c["nombre"], "BILLETERA", c["telefono"])
        if c["cobrado_cent"]:
            spei_sim.mover(conn, cuenta["id"], "ABONO", c["cobrado_cent"], "Saldo de pagos anteriores", c["codigo"])


def completar_cuentas_demo(conn, config):
    """Bases creadas antes de las cuentas: da celular y PIN a los comercios de demostración que no tengan."""
    pin_hash = None
    for fila in conn.execute("SELECT id, codigo FROM comercio WHERE demo = 1 AND pin_hash IS NULL").fetchall():
        telefono = telefono_demo(fila["codigo"])
        if cuentas.comercio_por_telefono(conn, telefono):
            continue
        pin_hash = pin_hash or cuentas.hash_pin(config["PIN_DEMO"])
        conn.execute(
            "UPDATE comercio SET telefono = ?, pin_hash = ?, sesion_sal = ?, qr_confirmado = COALESCE(qr_confirmado, "
            "creado) WHERE id = ?",
            (telefono, pin_hash, cuentas.sal_demo(fila["codigo"], config["SECRET_KEY"]), fila["id"]),
        )


def _recoleccion_historica(conn, comercio, cuando, peso, contenedor=None):
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
    if contenedor is not None:
        actual = conn.execute("SELECT nivel_cl, peso_g FROM contenedor WHERE id = ?", (contenedor["id"],)).fetchone()
        n_dep = siguiente_numero(conn, "deposito")
        conn.execute("UPDATE recoleccion SET origen = 'CONTENEDOR', contenedor_id = ? WHERE id = ?",
                     (contenedor["id"], n_rec))
        conn.execute(
            "INSERT INTO deposito(id, folio, contenedor_id, comercio_id, estado, peso_inicial_g, peso_actual_g, "
            "peso_neto_g, recoleccion_id, motivo, abierto, vence, cerrado) "
            "VALUES (?, ?, ?, ?, 'CERRADO', ?, ?, ?, ?, 'tapa cerrada', ?, ?, ?)",
            (n_dep, f"DEP-{n_dep:06d}", contenedor["id"], comercio["id"], actual["peso_g"],
             actual["peso_g"] + e["peso_g"], e["peso_g"], n_rec, iso(cuando - timedelta(minutes=2)),
             iso(cuando + timedelta(minutes=3)), t),
        )
        conn.execute("UPDATE contenedor SET nivel_cl = nivel_cl + ?, peso_g = peso_g + ? WHERE id = ?",
                     (e["litros_cl"], e["peso_g"], contenedor["id"]))
