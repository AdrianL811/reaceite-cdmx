"""Acceso a SQLite: esquema, conexiones y transacciones."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from flask import current_app, g

from .config import TZ

ESQUEMA = """
CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE TABLE IF NOT EXISTS usuario (
    id INTEGER PRIMARY KEY,
    usuario TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    rol TEXT NOT NULL CHECK (rol IN ('recolector', 'admin')),
    hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS comercio (
    id INTEGER PRIMARY KEY,
    codigo TEXT NOT NULL UNIQUE,
    token TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL,
    telefono TEXT,
    direccion TEXT,
    zona TEXT NOT NULL,
    franja TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    clabe TEXT NOT NULL,
    litros_cl INTEGER NOT NULL DEFAULT 0,
    agua_l INTEGER NOT NULL DEFAULT 0,
    cobrado_cent INTEGER NOT NULL DEFAULT 0,
    demo INTEGER NOT NULL DEFAULT 0,
    creado TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ruta (
    id INTEGER PRIMARY KEY,
    folio TEXT NOT NULL UNIQUE,
    zona TEXT NOT NULL,
    motivo TEXT NOT NULL,
    orden TEXT NOT NULL,
    distancia_m INTEGER NOT NULL,
    distancia_base_m INTEGER NOT NULL,
    duracion_s INTEGER NOT NULL,
    litros_estimados INTEGER NOT NULL,
    algoritmo TEXT NOT NULL,
    calculo_ms REAL NOT NULL,
    url_maps TEXT NOT NULL,
    estado TEXT NOT NULL CHECK (estado IN ('ACTIVA', 'COMPLETADA')),
    creado TEXT NOT NULL,
    completado TEXT
);

CREATE TABLE IF NOT EXISTS solicitud (
    id INTEGER PRIMARY KEY,
    folio TEXT NOT NULL UNIQUE,
    comercio_id INTEGER NOT NULL REFERENCES comercio(id),
    zona TEXT NOT NULL,
    franja TEXT NOT NULL,
    litros_estimados INTEGER NOT NULL CHECK (litros_estimados BETWEEN 1 AND 60),
    estado TEXT NOT NULL CHECK (estado IN ('PENDIENTE', 'EN_RUTA', 'RECOLECTADA', 'CANCELADA')),
    ruta_id INTEGER REFERENCES ruta(id),
    creado TEXT NOT NULL,
    actualizado TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_solicitud_zona ON solicitud(zona, estado);
CREATE INDEX IF NOT EXISTS ix_solicitud_comercio ON solicitud(comercio_id, estado);

CREATE TABLE IF NOT EXISTS recoleccion (
    id INTEGER PRIMARY KEY,
    folio TEXT NOT NULL UNIQUE,
    solicitud_id INTEGER NOT NULL UNIQUE REFERENCES solicitud(id),
    comercio_id INTEGER NOT NULL REFERENCES comercio(id),
    recolector_id INTEGER REFERENCES usuario(id),
    peso_g INTEGER NOT NULL,
    litros_cl INTEGER NOT NULL,
    agua_l INTEGER NOT NULL,
    biocombustible_cl INTEGER NOT NULL,
    bruto_cent INTEGER NOT NULL,
    comision_cent INTEGER NOT NULL,
    neto_cent INTEGER NOT NULL,
    anomalia TEXT,
    creado TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pago (
    id INTEGER PRIMARY KEY,
    folio TEXT NOT NULL UNIQUE,
    recoleccion_id INTEGER NOT NULL UNIQUE REFERENCES recoleccion(id),
    comercio_id INTEGER NOT NULL REFERENCES comercio(id),
    monto_cent INTEGER NOT NULL,
    clabe TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    estatus TEXT NOT NULL CHECK (estatus IN ('PENDIENTE', 'ENVIADO', 'LIQUIDADO', 'RECHAZADO')),
    folio_banco TEXT,
    clave_rastreo TEXT,
    intentos INTEGER NOT NULL DEFAULT 0,
    ultimo_error TEXT,
    creado TEXT NOT NULL,
    enviado TEXT,
    liquidado TEXT
);

CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL,
    ref TEXT NOT NULL,
    payload TEXT NOT NULL,
    estado TEXT NOT NULL CHECK (estado IN ('PENDIENTE', 'PROCESANDO', 'ENVIADO', 'FALLIDO')),
    intentos INTEGER NOT NULL DEFAULT 0,
    proximo TEXT NOT NULL,
    ultimo_error TEXT,
    creado TEXT NOT NULL,
    actualizado TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evento (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    tipo TEXT NOT NULL,
    etapa INTEGER,
    ref TEXT,
    resumen TEXT NOT NULL,
    detalle TEXT
);
CREATE INDEX IF NOT EXISTS ix_evento_ref ON evento(ref);

CREATE TABLE IF NOT EXISTS spei_orden (
    id INTEGER PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    huella TEXT NOT NULL,
    folio TEXT NOT NULL UNIQUE,
    clave_rastreo TEXT NOT NULL UNIQUE,
    monto_cent INTEGER NOT NULL,
    clabe TEXT NOT NULL,
    beneficiario TEXT,
    referencia TEXT NOT NULL,
    concepto TEXT,
    webhook_url TEXT NOT NULL,
    estatus TEXT NOT NULL CHECK (estatus IN ('RECIBIDA', 'LIQUIDADA', 'DEVUELTA')),
    liquidar_en TEXT NOT NULL,
    webhook_estado TEXT NOT NULL DEFAULT 'EN_ESPERA'
        CHECK (webhook_estado IN ('EN_ESPERA', 'PENDIENTE', 'PROCESANDO', 'ENTREGADO', 'FALLIDO')),
    webhook_intentos INTEGER NOT NULL DEFAULT 0,
    webhook_http INTEGER,
    webhook_proximo TEXT,
    respuesta TEXT NOT NULL,
    creado TEXT NOT NULL,
    liquidado TEXT
);
"""

TABLAS_EN_ORDEN_DE_BORRADO = (
    "evento", "outbox", "spei_orden", "pago", "recoleccion", "solicitud", "ruta", "comercio", "usuario", "meta",
)


# ---------------------------------------------------------------- tiempo
def ahora_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    """Fecha y hora en UTC, ISO 8601 con milisegundos (ordenable como texto)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def ahora_iso(desfase_s=0):
    return iso(ahora_utc() + timedelta(seconds=desfase_s))


def parse_iso(texto):
    return datetime.strptime(texto, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def local(texto):
    """Convierte un ISO UTC guardado a la hora de la Ciudad de México."""
    return parse_iso(texto).astimezone(TZ)


# ---------------------------------------------------------------- conexiones
def conectar(ruta):
    conn = sqlite3.connect(ruta, timeout=15, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def get_db():
    if "db" not in g:
        g.db = conectar(current_app.config["DB_PATH"])
    return g.db


def cerrar_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


@contextmanager
def transaccion(conn):
    """Transacción con bloqueo de escritura inmediato: serializa las escrituras concurrentes."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def crear_esquema(conn):
    conn.executescript(ESQUEMA)


def vaciar(conn):
    """Borra todos los datos; los id vuelven a empezar en 1 (no se usa AUTOINCREMENT)."""
    for tabla in TABLAS_EN_ORDEN_DE_BORRADO:
        conn.execute(f"DELETE FROM {tabla}")


def meta_get(conn, clave, defecto=None):
    fila = conn.execute("SELECT valor FROM meta WHERE clave = ?", (clave,)).fetchone()
    return json.loads(fila["valor"]) if fila else defecto


def meta_set(conn, clave, valor):
    conn.execute(
        "INSERT INTO meta(clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
        (clave, json.dumps(valor, ensure_ascii=False)),
    )


def siguiente_numero(conn, tabla):
    return conn.execute(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {tabla}").fetchone()[0]
