# ReAceite CDMX

PWA para recolectar aceite de cocina usado en la Ciudad de México. El comercio pide la recolección desde el QR de su bote. Cuando su colonia junta 20 L, la ruta sale sola, ordenada con un algoritmo exacto. El recolector pesa el aceite frente al comercio, la app calcula las Métricas Verdes y un webhook liquida el pago en una API SPEI simulada, todo en un par de segundos y sin intervención humana.

Proyecto integrador, Sprint 2. Grupo 900 CIB, Universidad La Salle Ciudad de México.

## Accesos de la demostración

| Rol | Usuario | Contraseña |
| --- | --- | --- |
| Recolector | `recolector` | `aceite2026` (variable `RECOLECTOR_PASSWORD`) |
| Administración | `admin` | la que pongas en `ADMIN_PASSWORD`; si no pones ninguna, `900cib-admin` |

El comercio no usa contraseña: su QR lo identifica con un token aleatorio de 8 caracteres.

## Pantallas

| Ruta | Para qué sirve |
| --- | --- |
| `/` | Inicio: registrar comercio, entrar como recolector, ver impacto |
| `/registro` | Alta del comercio con GPS; al terminar muestra su QR |
| `/c/<token>` | Pantalla del comercio (la abre el QR del bote): pedir 5, 10 o 20 L, seguir la ruta y ver el comprobante |
| `/r` | Ruta del día: mapa, paradas en orden óptimo, escáner QR |
| `/r/pesar/<token>` | Pesaje con Métricas Verdes en vivo y confirmación del pago |
| `/impacto` | Tablero público para proyectar: litros, agua protegida, pagos, cubetas por colonia |
| `/monitor` | Centro de control: las 8 etapas del Data Pipeline y la bitácora con los JSON de la API y del webhook |
| `/proyecto` | Presentación sin diapositivas: problema, patentes, Gartner, Crazy 8's, Task Flow y arquitectura |
| `/portada` | QR de alta resolución de la app para la portada del reporte |
| `/stickers` | Stickers QR imprimibles de todos los comercios (solo administración) |

## Correrla en tu computadora

```bash
python -m venv .venv
source .venv/bin/activate        # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py                    # abre http://localhost:5000
```

La primera vez se crea `data/reaceite.db` con los datos de demostración.

Pruebas automáticas (53 pruebas, incluido el flujo completo por HTTP real):

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

## Publicarla gratis en Render (unos 10 minutos, sin tarjeta)

1. Crea una cuenta en github.com. Haz un repositorio nuevo **público** llamado `reaceite-cdmx`.
2. En el repositorio, elige *Add file → Upload files* y arrastra **el contenido** de esta carpeta (no la carpeta misma). Confirma con *Commit changes*.
3. Crea una cuenta en render.com con *Sign in with GitHub*.
4. En Render: *New → Web Service*, elige el repositorio. Render detecta el `Dockerfile`. Pon:
   - Name: `reaceite-cdmx` (define la URL: `https://reaceite-cdmx.onrender.com`; si está ocupada, Render agrega letras).
   - Instance type: **Free**.
   - En *Environment Variables* agrega `ADMIN_PASSWORD` con una contraseña tuya. Opcional: `SECRET_KEY`, `WEBHOOK_SECRET` y `SPEI_API_KEY` con textos largos al azar.
5. *Create Web Service*. La primera construcción tarda de 3 a 5 minutos. Cuando diga *Live*, abre la URL.

Alternativa: *New → Blueprint* con este repositorio usa `render.yaml` y genera solas las claves secretas.

### Después de publicarla

1. Abre `https://TU-URL/portada` y descarga el QR. Ese PNG va al centro de la portada del reporte, junto con la URL.
2. Entra como `admin` en `/entrar`, abre `/stickers` e imprime los QR de los botes (al menos el de **Puesto demo, COM-0006**).
3. Haz un ensayo completo y luego usa **Restablecer datos de demostración** en `/monitor` para dejar todo listo.

### Lo que hay que saber del plan gratuito de Render

- Si nadie entra durante 15 minutos, el servicio se duerme y el siguiente acceso tarda cerca de un minuto en despertar. **Abre la URL 2 minutos antes de presentar** y deja `/impacto` abierta en la laptop: su consulta cada 3 segundos la mantiene despierta.
- El disco del plan gratuito se borra al dormir o reiniciar. Al arrancar, la app vuelve a cargar el escenario de demostración, así que siempre empieza limpia. Los comercios registrados en vivo duran hasta el siguiente reinicio; los stickers de los 8 comercios de demostración siempre funcionan.

## Guion de la demo (6 minutos)

Escenario precargado: Hipódromo tiene 15 L pendientes (Tacos El Güero, 10 L, y Arrachera Don Chuy, 5 L). Usa dos celulares con datos móviles y la laptop proyectando `/monitor`.

| Minuto | Acción | Qué se ve |
| --- | --- | --- |
| 0:00 | Celular A escanea el sticker de **Puesto demo (COM-0006)** con la cámara | Se abre su pantalla: la cubeta de Hipódromo en 15 de 20 L |
| 0:45 | Elige 5 L y 10:00 a 12:00, toca *Pedir recolección* | La cubeta llega a 20 L y la ruta RUT-0001 sale sola; en el monitor aparecen `zona.umbral_alcanzado` y `ruta.generada` |
| 1:45 | Celular B (sesión `recolector`) abre *Ruta del día* | Mapa con 3 paradas en orden óptimo (Held-Karp) y botón de Google Maps |
| 2:30 | Celular B toca *Escanear el QR del bote*, apunta al sticker, escribe 4.6 kg | Vista previa: 5.00 L, 5,000 L de agua, $27.00 al comercio |
| 3:15 | Toca *Confirmar recolección* | Las 8 etapas se encienden en el monitor; en unos 2 s el pago queda LIQUIDADO con clave de rastreo |
| 4:00 | Celular A, sin tocar nada | Le aparece *Pago recibido $27.00* con su comprobante |
| 4:30 | Laptop: abre un evento de la bitácora | Se ven el JSON de la orden (202 Accepted) y el del webhook con firma HMAC válida |
| 5:15 | Laptop: `/impacto` | Los contadores suben 5 L y 5,000 L de agua |

Plan B: si falla la cámara, el escáner acepta escribir `COM-0006`. Si no hay señal en el salón, usa el hotspot de otro celular.

## Arquitectura

- **Frontend (PWA)**: HTML, CSS y JavaScript sin frameworks; manifiesto web y service worker (instalable, con página sin conexión). Escáner QR con `BarcodeDetector` o `jsQR`; mapas con Leaflet y OpenStreetMap.
- **Backend**: Python 3 con Flask; SQLite en modo WAL; gunicorn con un proceso y 8 hilos.
- **Métricas Verdes** (`reaceite/metricas.py`): aritmética decimal exacta, redondeo comercial.
  `litros = kg / 0.92`; `agua = litros × 1,000`; `biocombustible = litros × 0.9`; `bruto = litros × $6.00`; `comisión = 10 %`; `neto = bruto − comisión`.
- **Motor de rutas** (`reaceite/rutas.py`): programación dinámica de Held-Karp (óptimo exacto hasta 11 paradas); vecino más cercano con 2-opt para rutas más grandes. Distancia haversine con factor de rodeo urbano de 1.3.
- **Disparadores automáticos**: la ruta sale cuando la colonia junta 20 L, o cuando una solicitud lleva 48 horas esperando.
- **Pagos** (`reaceite/despachador.py`, `reaceite/spei_sim.py`): patrón outbox. La recolección, el pago y la orden se guardan en la misma transacción. Un hilo envía la orden a la API SPEI simulada (`Idempotency-Key`, reintentos con espera exponencial). El banco responde 202 y, al liquidar, manda un webhook firmado con HMAC-SHA256 y marca de tiempo. El receptor verifica la firma y es idempotente.
- **Seguridad**: contraseñas con hash, cookies de sesión `HttpOnly` y `SameSite`, cabecera anti-CSRF en la API, Content-Security-Policy estricta, tokens QR no adivinables, CLABE validada con su dígito de control y siempre simulada.

### Variables de entorno

| Variable | Valor por defecto | Uso |
| --- | --- | --- |
| `ADMIN_PASSWORD` | `900cib-admin` | Contraseña de `admin` |
| `RECOLECTOR_PASSWORD` | `aceite2026` | Contraseña de `recolector` |
| `SECRET_KEY` | derivada de `ADMIN_PASSWORD` y `WEBHOOK_SECRET` | Firma de las sesiones (en producción conviene un texto largo al azar) |
| `WEBHOOK_SECRET` | `whsec_reaceite_demo` | Secreto HMAC de los webhooks |
| `SPEI_API_KEY` | `sk_test_reaceite_demo` | API key de la API SPEI simulada |
| `SPEI_DEMORA_S` | `1.2` | Segundos que tarda el banco simulado en liquidar |
| `NOTIFY_WEBHOOK_URL` | vacío | Copia opcional de cada pago liquidado a un webhook externo (Make, webhook.site) |
| `PRECIO_LITRO`, `COMISION`, `TOPE_RUTA_LITROS`, `ESPERA_MAXIMA_HORAS` | 6.00, 0.10, 20, 48 | Parámetros de negocio |

## Fotos del Crazy 8's

Guarda las fotos como `reaceite/static/img/crazy8/hojas.jpg` y `reaceite/static/img/crazy8/matriz.jpg` y súbelas al repositorio: aparecen solas en `/proyecto`.

## Herramientas

- `python herramientas/figuras.py` regenera la Curva de Gartner, el Task Flow, el Tech Stack Map y el Data Pipeline (requiere matplotlib y Graphviz).
- `python herramientas/iconos.py` regenera los íconos de la PWA.

## Licencias de terceros

Leaflet (BSD-2-Clause), jsQR (Apache-2.0), Bricolage Grotesque y Atkinson Hyperlegible Next (SIL Open Font License). Teselas de mapa © colaboradores de OpenStreetMap.
