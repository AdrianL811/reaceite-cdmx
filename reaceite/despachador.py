"""Despachador en segundo plano: cola de salida (outbox), banco simulado y regla de 48 h.

Patrón outbox: la orden de pago se guarda en la misma transacción que la recolección; este hilo
la envía después a la API SPEI con reintentos. Si el servidor se reinicia, nada se pierde:
lo pendiente se retoma al arrancar.
"""
import json
import logging
import threading
import time

from . import eventos, servicios, spei_sim, transporte
from .db import ahora_iso, conectar, transaccion

log = logging.getLogger("reaceite.despachador")
MAX_INTENTOS = 6


class Despachador:
    def __init__(self, app):
        self.app = app
        self._senal = threading.Event()
        self._candado = threading.Lock()
        self._hilo = None
        self._ultima_revision = 0.0
        self._ocupado = False

    @property
    def vivo(self):
        return bool(self._hilo and self._hilo.is_alive())

    def iniciar(self):
        if self.vivo:
            return
        self._hilo = threading.Thread(target=self._bucle, name="despachador", daemon=True)
        self._hilo.start()

    def despertar(self):
        self._senal.set()
        if not self.vivo and self.app.config.get("DESPACHADOR_AUTO"):
            self.iniciar()

    def _bucle(self):
        self._recuperar()
        while True:
            self._senal.wait(timeout=0.25 if self._ocupado else 2.0)
            self._senal.clear()
            try:
                self.tick()
            except Exception:  # el hilo nunca debe morir
                log.exception("Fallo en el despachador")

    def _recuperar(self):
        """Tras un reinicio, lo que quedó a medias vuelve a la cola."""
        conn = conectar(self.app.config["DB_PATH"])
        try:
            conn.execute("UPDATE outbox SET estado = 'PENDIENTE' WHERE estado = 'PROCESANDO'")
            conn.execute("UPDATE spei_orden SET webhook_estado = 'PENDIENTE' WHERE webhook_estado = 'PROCESANDO'")
        finally:
            conn.close()

    def tick(self):
        if not self._candado.acquire(blocking=False):
            return 0
        try:
            conn = conectar(self.app.config["DB_PATH"])
            try:
                total = 0
                for _ in range(6):
                    hecho = procesar_outbox(self.app, conn) + spei_sim.procesar(self.app, conn)
                    total += hecho
                    if not hecho:
                        break
                if time.monotonic() - self._ultima_revision > 60:
                    self._ultima_revision = time.monotonic()
                    with transaccion(conn):
                        servicios.revisar_esperas(conn)
                self._ocupado = spei_sim.hay_pendientes(conn) or conn.execute(
                    "SELECT EXISTS(SELECT 1 FROM outbox WHERE estado = 'PENDIENTE')").fetchone()[0] == 1
                return total
            finally:
                conn.close()
        finally:
            self._candado.release()


def procesar_outbox(app, conn):
    hechas = 0
    filas = conn.execute(
        "SELECT * FROM outbox WHERE estado = 'PENDIENTE' AND proximo <= ? ORDER BY id LIMIT 20", (ahora_iso(),)
    ).fetchall()
    for fila in filas:
        cur = conn.execute(
            "UPDATE outbox SET estado = 'PROCESANDO', actualizado = ? WHERE id = ? AND estado = 'PENDIENTE'",
            (ahora_iso(), fila["id"]),
        )
        if cur.rowcount != 1:
            continue
        hechas += 1
        if fila["tipo"] == "pago.solicitar":
            _solicitar_pago(app, conn, fila)
        else:
            conn.execute("UPDATE outbox SET estado = 'FALLIDO', ultimo_error = 'tipo desconocido' WHERE id = ?",
                         (fila["id"],))
    return hechas


def _solicitar_pago(app, conn, fila):
    cfg = app.config
    orden = json.loads(fila["payload"])
    webhook_url = orden.get("webhook_url") or cfg["INTERNAL_BASE_URL"].rstrip("/") + "/webhooks/spei"
    cuerpo = {
        "monto": orden["monto"],
        "moneda": "MXN",
        "clabe_destino": orden["clabe_destino"],
        "beneficiario": orden["beneficiario"],
        "referencia": orden["pago"],
        "concepto": orden["concepto"],
        "webhook_url": webhook_url,
    }
    datos = json.dumps(cuerpo, ensure_ascii=False).encode()
    cabeceras = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['SPEI_API_KEY']}",
        "Idempotency-Key": orden["idempotency_key"],
    }
    respuesta, error = None, None
    try:
        respuesta = transporte.enviar(app, "POST", "/sim-spei/v1/transferencias", datos, cabeceras)
    except Exception as e:
        error = type(e).__name__
    intentos = fila["intentos"] + 1
    ahora = ahora_iso()
    with transaccion(conn):
        if respuesta is not None and respuesta.status in (200, 201, 202):
            r = respuesta.json()
            conn.execute(
                "UPDATE pago SET estatus = CASE WHEN estatus = 'PENDIENTE' THEN 'ENVIADO' ELSE estatus END, "
                "folio_banco = COALESCE(folio_banco, ?), clave_rastreo = COALESCE(clave_rastreo, ?), "
                "enviado = COALESCE(enviado, ?), intentos = intentos + 1 WHERE folio = ?",
                (r.get("folio"), r.get("clave_rastreo"), ahora, orden["pago"]),
            )
            conn.execute("UPDATE outbox SET estado = 'ENVIADO', intentos = ?, actualizado = ? WHERE id = ?",
                         (intentos, ahora, fila["id"]))
            texto = {200: "200 OK (repetición idempotente)", 201: "201 Created", 202: "202 Accepted"}[respuesta.status]
            eventos.registrar(
                conn, "spei.orden_enviada",
                f"POST /sim-spei/v1/transferencias: {texto} en {respuesta.ms:.0f} ms; folio bancario {r.get('folio')}",
                ref=orden["recoleccion"], etapa=6,
                detalle={
                    "peticion": {
                        "metodo": "POST",
                        "url": "/sim-spei/v1/transferencias",
                        "cabeceras": {"Authorization": "Bearer sk_test_••••", "Idempotency-Key": orden["idempotency_key"]},
                        "cuerpo": cuerpo,
                    },
                    "respuesta": {"status": respuesta.status, "cuerpo": r},
                    "latencia_ms": round(respuesta.ms, 1),
                    "transporte": respuesta.transporte,
                },
            )
            return
        definitivo = respuesta is not None and 400 <= respuesta.status < 500 and respuesta.status not in (408, 425, 429)
        motivo = f"HTTP {respuesta.status}: {respuesta.json().get('mensaje', '')}" if respuesta is not None else error
        if definitivo or intentos >= MAX_INTENTOS:
            conn.execute("UPDATE outbox SET estado = 'FALLIDO', intentos = ?, ultimo_error = ?, actualizado = ? "
                         "WHERE id = ?", (intentos, motivo, ahora, fila["id"]))
            conn.execute("UPDATE pago SET estatus = 'RECHAZADO', ultimo_error = ?, intentos = ? WHERE folio = ?",
                         (motivo, intentos, orden["pago"]))
            eventos.registrar(conn, "spei.orden_rechazada", f"{orden['pago']} rechazado: {motivo}",
                              ref=orden["recoleccion"], etapa=6, detalle={"motivo": motivo})
        else:
            espera = min(60, 2 ** intentos)
            conn.execute("UPDATE outbox SET estado = 'PENDIENTE', intentos = ?, ultimo_error = ?, proximo = ?, "
                         "actualizado = ? WHERE id = ?", (intentos, motivo, ahora_iso(espera), ahora, fila["id"]))
            conn.execute("UPDATE pago SET intentos = ?, ultimo_error = ? WHERE folio = ?",
                         (intentos, motivo, orden["pago"]))
            eventos.registrar(conn, "spei.reintento",
                              f"El envío de {orden['pago']} falló ({motivo}); reintento en {espera} s",
                              ref=orden["recoleccion"], detalle={"intento": intentos, "motivo": motivo})
