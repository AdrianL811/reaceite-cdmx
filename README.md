# ReAceite CDMX

PWA para recolectar aceite de cocina usado en la Ciudad de México. El comercio pide la recolección desde el QR de su bote. Cuando su colonia junta 20 L, la ruta sale sola, ordenada con un algoritmo exacto. El recolector pesa el aceite frente al comercio, la app calcula las Métricas Verdes y un webhook liquida el pago en una API SPEI simulada, todo en un par de segundos y sin intervención humana.

Sprint 3: el comercio también puede llevar su aceite a un **contenedor inteligente** con báscula. Escanea el QR del contenedor, abre la compuerta, vierte su aceite y, al cerrar la tapa, el dispositivo manda un mensaje firmado a la plataforma. El pago sale del **Fondo de Garantía de Dispersión** y llega en segundos a la **billetera del comercio, ligada a su celular**. El fondo se recarga cuando se vende un lote de aceite a la planta de biocombustible.

Proyecto integrador, Sprints 2 y 3. Grupo 900 CIB, Universidad La Salle Ciudad de México.

## Sprint 3 en dos minutos

1. **Evento físico.** El comercio, con su sesión abierta, toca «Escanear el QR del contenedor» en su panel (o escanea el sticker del contenedor con la cámara) y luego «Abrir compuerta». La compuerta se abre 5 minutos solo para él.
2. **Dispositivo.** Mientras vierte, la celda de carga reporta el peso cada medio segundo (`POST /iot/v1/telemetria`); el celular lo muestra en vivo con el pago estimado. Al cerrar la tapa, el contenedor envía `deposito.cerrado` con el peso final, firmado con HMAC-SHA256 con su propio secreto y con un `evento_id` único (un mensaje alterado o repetido no genera otro pago).
3. **Orquestación.** El peso neto entra al mismo Data Pipeline de 8 etapas: normalización, validación, Métricas Verdes, evento, orden a la API de pagos, webhook firmado y pago liquidado. Todo se ve en `/monitor`.
4. **Impacto.** La pasarela simulada carga el monto al Fondo de Garantía de Dispersión y lo abona a la billetera del comercio. El celular muestra «Pago recibido» con el saldo nuevo, consultado a la API de la pasarela, vibra y lanza un aviso del sistema si el comercio lo permitió.
5. **Recarga del fondo.** En `/monitor`, la administración vende a la planta el aceite ya pagado (botón «Vender lote a la planta»). El cobro recarga el fondo; si algún pago esperaba fondos, sale en ese momento.

En el piloto el contenedor físico se representa con su **gemelo digital**: el equipo lo abre escaneando el QR del contenedor con su sesión (o desde la lista de contenedores de `/monitor`). Ahí mantiene presionado «Verter aceite» y luego «Cerrar la tapa». El gemelo envía exactamente los mismos mensajes firmados que el firmware de referencia para ESP32 (`herramientas/contenedor_esp32.ino`).

Para la demo con dos pantallas: en la laptop, el gemelo de `CTN-0001` (su QR se ve en pantalla); en el celular, el Puesto demo (`55 1000 0006`, PIN `900900`) escanea ese QR desde su panel.

## Accesos de la demostración

| Rol | Usuario | Contraseña |
| --- | --- | --- |
| Recolector | `recolector` | `aceite2026` (variable `RECOLECTOR_PASSWORD`) |
| Administración | `admin` | la que pongas en `ADMIN_PASSWORD`; si no pones ninguna, `900cib-admin` |
| Comercios de demostración | su celular: `55 1000 00NN` (NN = número del comercio; Puesto demo = `55 1000 0006`) | PIN `900900` (variable `PIN_DEMO`) |

### Cuentas de comercio

- El comercio entra con **su celular (usuario) y un PIN de 6 números** en `/comercio/entrar`. Su sesión dura 90 días en ese teléfono y se renueva cada vez que entra; borrar las cookies ya no le hace perder su comercio.
- No se aceptan PIN fáciles (123456, seis números iguales ni los últimos 6 dígitos del celular). El PIN se guarda solo como hash.
- Tras **5 PIN incorrectos** la cuenta se bloquea 15 minutos (`PIN_INTENTOS`, `PIN_BLOQUEO_MIN`).
- Si olvida su PIN, la administración genera uno **temporal** en `/monitor` (Cuentas de comercio). Al entrar, el comercio ve un aviso para cambiarlo. Cambiar o restablecer el PIN cierra las sesiones abiertas en otros teléfonos.
- **El QR del bote abre algo distinto según quién lo escanea:** el recolector con sesión va directo al pesaje; el dueño con sesión ve su panel; cualquier otra persona ve una página pública que no permite pedir recolecciones ni ver pagos.
- En su panel, la sección **Mi QR** muestra siempre su código, con botones para imprimir el sticker y descargarlo, la indicación de pegarlo en el bote y la opción de reemplazarlo (con su PIN) si alguien más tiene una copia.

## Pantallas

| Ruta | Para qué sirve |
| --- | --- |
| `/` | Inicio: registrar comercio, entrar como recolector, ver impacto |
| `/registro` | Alta del comercio con GPS, celular y PIN; al terminar pide pegar su QR en el bote |
| `/comercio/entrar` | Inicio de sesión del comercio con celular y PIN |
| `/c/<token>` | El QR del bote. Dueño con sesión: su panel (pedir 5, 10 o 20 L, seguir la ruta, comprobante, Mi QR, Mi cuenta). Recolector: pesaje. Cualquier otra persona: página pública |
| `/mi-comercio` | Lleva al panel del comercio con sesión abierta |
| `/mi-comercio/sticker` | Hoja imprimible con dos copias del sticker QR del comercio |
| `/k/<token>` | El QR del contenedor. Comercio con sesión: abrir la compuerta, peso en vivo y pago. Equipo: gemelo digital (verter, cerrar la tapa, vaciar). Cualquier otra persona: página pública |
| `/contenedor/<código>` | Acceso por código escrito (`CTN-0001`) si la cámara no funciona |
| `/r` | Ruta del día: mapa, paradas en orden óptimo, escáner QR |
| `/r/pesar/<token>` | Pesaje con Métricas Verdes en vivo y confirmación del pago |
| `/impacto` | Tablero público para proyectar: litros, agua protegida, pagos, cubetas por colonia |
| `/monitor` | Centro de control: las 8 etapas del Data Pipeline, la bitácora con los JSON de la API y de los webhooks, el Fondo de Garantía de Dispersión (venta de lotes) y los contenedores |
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

Pruebas automáticas (68 pruebas, incluido el flujo completo por HTTP real, las cuentas de comercio, el contenedor inteligente, la billetera y el fondo):

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
3. En el celular que hará de comerciante, entra a `/comercio/entrar` con `55 1000 0006` y el PIN `900900`. La sesión se queda abierta (90 días) y sobrevive a los reinicios del plan gratuito y a **Restablecer datos de demostración**.
4. Haz un ensayo completo y luego usa **Restablecer datos de demostración** en `/monitor` para dejar todo listo.

### Lo que hay que saber del plan gratuito de Render

- Si nadie entra durante 15 minutos, el servicio se duerme y el siguiente acceso tarda cerca de un minuto en despertar. **Abre la URL 2 minutos antes de presentar** y deja `/impacto` abierta en la laptop: su consulta cada 3 segundos la mantiene despierta.
- El disco del plan gratuito se borra al dormir o reiniciar. Al arrancar, la app vuelve a cargar el escenario de demostración, así que siempre empieza limpia. Los comercios registrados en vivo duran hasta el siguiente reinicio; los stickers de los 8 comercios de demostración siempre funcionan.

## Guion de la demo (6 minutos)

Escenario precargado: Hipódromo tiene 15 L pendientes (Tacos El Güero, 10 L, y Arrachera Don Chuy, 5 L). Usa dos celulares con datos móviles y la laptop proyectando `/monitor`. Antes de empezar, el celular A ya tiene abierta la sesión del Puesto demo (`55 1000 0006`, PIN `900900`) y el celular B, la del recolector.

| Minuto | Acción | Qué se ve |
| --- | --- | --- |
| 0:00 | Celular A escanea el sticker de **Puesto demo (COM-0006)** con la cámara | Como tiene la sesión del dueño, se abre su panel: la cubeta de Hipódromo en 15 de 20 L |
| 0:45 | Elige 5 L y 10:00 a 12:00, toca *Pedir recolección* | La cubeta llega a 20 L y la ruta RUT-0001 sale sola; en el monitor aparecen `zona.umbral_alcanzado` y `ruta.generada` |
| 1:45 | Celular B (sesión `recolector`) abre *Ruta del día* | Mapa con 3 paradas en orden óptimo (Held-Karp) y botón de Google Maps |
| 2:30 | Celular B toca *Escanear el QR del bote*, apunta al sticker, escribe 4.6 kg | Vista previa: 5.00 L, 5,000 L de agua, $27.00 al comercio |
| 3:15 | Toca *Confirmar recolección* | Las 8 etapas se encienden en el monitor; en unos 2 s el pago queda LIQUIDADO con clave de rastreo |
| 4:00 | Celular A, sin tocar nada | Le aparece *Pago recibido $27.00* con su comprobante |
| 4:30 | Laptop: abre un evento de la bitácora | Se ven el JSON de la orden (202 Accepted) y el del webhook con firma HMAC válida |
| 5:15 | Laptop: `/impacto` | Los contadores suben 5 L y 5,000 L de agua |

Plan B: si la cámara del celular A no lee el sticker, abre `/mi-comercio` (lleva a su panel). Si falla la cámara del recolector, el escáner acepta escribir `COM-0006`. Si no hay señal en el salón, usa el hotspot de otro celular.

## Arquitectura

- **Frontend (PWA)**: HTML, CSS y JavaScript sin frameworks; manifiesto web y service worker (instalable, con página sin conexión). Escáner QR con `BarcodeDetector` o `jsQR`; mapas con Leaflet y OpenStreetMap.
- **Backend**: Python 3 con Flask; SQLite en modo WAL; gunicorn con un proceso y 8 hilos.
- **Métricas Verdes** (`reaceite/metricas.py`): aritmética decimal exacta, redondeo comercial.
  `litros = kg / 0.92`; `agua = litros × 1,000`; `biocombustible = litros × 0.9`; `bruto = litros × $6.00`; `comisión = 10 %`; `neto = bruto − comisión`.
- **Motor de rutas** (`reaceite/rutas.py`): programación dinámica de Held-Karp (óptimo exacto hasta 11 paradas); vecino más cercano con 2-opt para rutas más grandes. Distancia haversine con factor de rodeo urbano de 1.3.
- **Disparadores automáticos**: la ruta sale cuando la colonia junta 20 L, o cuando una solicitud lleva 48 horas esperando.
- **Pagos** (`reaceite/despachador.py`, `reaceite/spei_sim.py`): patrón outbox. La recolección, el pago y la orden se guardan en la misma transacción. Un hilo envía la orden a la API SPEI simulada (`Idempotency-Key`, reintentos con espera exponencial). El banco responde 202 y, al liquidar, manda un webhook firmado con HMAC-SHA256 y marca de tiempo. El receptor verifica la firma y es idempotente.
- **Contenedor inteligente** (`reaceite/iot.py`): `POST /iot/v1/telemetria` con cabeceras `X-Dispositivo` y `X-Dispositivo-Firma: t=<unix>,v1=<hmac>`. Cada contenedor firma con su propio secreto, `HMAC(IOT_SECRET, código)`; la firma vence a los 5 minutos y cada `evento_id` se acepta una sola vez. Un depósito a la vez por contenedor; si la compuerta vence con aceite en la báscula, se cierra con la última lectura. Alerta de vaciado al 80 % de llenado.
- **Pasarela de pagos simulada** (`reaceite/spei_sim.py`): cuentas con saldo y movimientos. `POST /v1/transferencias` carga el monto al Fondo de Garantía al aceptar la orden (409 `fondos_insuficientes` si no alcanza: el pago espera, no se pierde) y lo abona a la billetera al liquidar. `POST /v1/cuentas` abre la billetera ligada al celular (por la cola, al registrarse el comercio); `GET /v1/cuentas/<clabe>` y `/movimientos` devuelven saldo y movimientos. Todo con API key; ningún peso real se mueve.
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
| `PIN_DEMO` | `900900` | PIN de los 8 comercios de demostración |
| `PIN_INTENTOS`, `PIN_BLOQUEO_MIN` | 5, 15 | Intentos fallidos antes del bloqueo y minutos de bloqueo |
| `PRECIO_LITRO`, `COMISION`, `TOPE_RUTA_LITROS`, `ESPERA_MAXIMA_HORAS` | 6.00, 0.10, 20, 48 | Parámetros de negocio |
| `FONDO_INICIAL` | `45000.00` | Capital semilla del Fondo de Garantía de Dispersión (el mismo monto del Presupuesto Maestro) |
| `FONDO_ALERTA` | `10000.00` | Saldo del fondo que enciende la alerta en `/monitor` |
| `PRECIO_PLANTA`, `LOTE_MINIMO_LITROS` | 10.00, 20 | Precio por litro que paga la planta y litros mínimos por lote |
| `IOT_SECRET` | `iot_reaceite_demo` | Secreto maestro del que se deriva el secreto de cada contenedor |
| `DEPOSITO_MINUTOS`, `CONTENEDOR_ALERTA` | 5, 80 | Minutos que la compuerta queda abierta y porcentaje que dispara la alerta de vaciado |

## Fotos del Crazy 8's

Guarda las fotos como `reaceite/static/img/crazy8/hojas.jpg` y `reaceite/static/img/crazy8/matriz.jpg` y súbelas al repositorio: aparecen solas en `/proyecto`.

## Herramientas

- `python herramientas/figuras.py` regenera la Curva de Gartner, el Task Flow, el Tech Stack Map y el Data Pipeline (requiere matplotlib y Graphviz).
- `python herramientas/iconos.py` regenera los íconos de la PWA.
- `herramientas/contenedor_esp32.ino`: firmware de referencia del contenedor (ESP32, celda de carga con HX711, sensor de tapa y cerradura).

## Licencias de terceros

Leaflet (BSD-2-Clause), jsQR (Apache-2.0), Bricolage Grotesque y Atkinson Hyperlegible Next (SIL Open Font License). Teselas de mapa © colaboradores de OpenStreetMap.
