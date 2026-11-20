/*
  ReAceite CDMX · Firmware de referencia del Contenedor Inteligente (Módulo Contenedor Inteligente)

  Envía a la plataforma los mismos mensajes firmados que el gemelo digital de /k/<token>:
    POST /iot/v1/telemetria
    X-Dispositivo: CTN-0001
    X-Dispositivo-Firma: t=<unix>,v1=<hex HMAC-SHA256(secreto, "<unix>." + cuerpo)>
    {"evento_id":"…","tipo":"latido|peso|deposito.cerrado","peso_g":31400,"tapa":"abierta","deposito":"DEP-000005",…}
  La respuesta trae la orden para la compuerta: {"comando":{"compuerta":"abierta","deposito":"DEP-000005",…}}.

  Hardware (lista de materiales del presupuesto, hardware IoT):
    - ESP32-DevKitC (wifi integrado)
    - Celda de carga tipo plataforma de 150–200 kg + amplificador HX711 (24 bits)
    - Sensor magnético (reed switch) en la tapa
    - Cerradura solenoide de 12 V con relé o MOSFET para la compuerta
    - Fuente 12 V con regulador a 5 V, gabinete IP65 y contenedor de 120 L
  Bibliotecas: HX711 (bogde), WiFi, HTTPClient y mbedtls (incluidas en el núcleo ESP32 de Arduino).

  Configura WIFI_*, URL_BASE, CODIGO y SECRETO. El secreto de cada contenedor es
  HMAC_SHA256(IOT_SECRET, CODIGO)[:40] (ver reaceite/iot.py, secreto_dispositivo).
*/
#include <WiFi.h>
#include <HTTPClient.h>
#include <HX711.h>
#include <time.h>
#include "mbedtls/md.h"

const char* WIFI_SSID = "mi-red";
const char* WIFI_CLAVE = "mi-clave";
const char* URL_BASE = "https://reaceite-cdmx.onrender.com";
const char* CODIGO = "CTN-0001";
const char* SECRETO = "pegar-aqui-el-secreto-de-40-caracteres";
const char* FIRMWARE = "reaceite-ctn 1.0 (esp32)";

const int PIN_HX711_DT = 16;
const int PIN_HX711_SCK = 4;
const int PIN_TAPA = 27;        // reed switch a GND: LOW = tapa cerrada
const int PIN_CERRADURA = 26;   // HIGH = compuerta liberada
const float FACTOR_ESCALA = 21.85f;   // calibrar con una pesa conocida: lectura / gramos

HX711 bascula;
String depositoAbierto = "";
unsigned long ultimoLatido = 0;
unsigned long ultimoPeso = 0;
bool tapaAbiertaAntes = false;

String hex(const uint8_t* datos, size_t n) {
  static const char* d = "0123456789abcdef";
  String s;
  for (size_t i = 0; i < n; i++) { s += d[datos[i] >> 4]; s += d[datos[i] & 15]; }
  return s;
}

String hmacSha256(const String& mensaje) {
  uint8_t salida[32];
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 1);
  mbedtls_md_hmac_starts(&ctx, (const unsigned char*)SECRETO, strlen(SECRETO));
  mbedtls_md_hmac_update(&ctx, (const unsigned char*)mensaje.c_str(), mensaje.length());
  mbedtls_md_hmac_finish(&ctx, salida);
  mbedtls_md_free(&ctx);
  return hex(salida, 32);
}

String eventoId() {
  uint8_t r[16];
  for (int i = 0; i < 16; i += 4) { uint32_t v = esp_random(); memcpy(r + i, &v, 4); }
  return hex(r, 16);
}

long pesoGramos() {
  // Mediana de 5 lecturas: descarta golpes y vibraciones del puesto.
  long v[5];
  for (int i = 0; i < 5; i++) v[i] = lround(bascula.get_units(1));
  for (int i = 0; i < 4; i++) for (int j = i + 1; j < 5; j++) if (v[j] < v[i]) { long t = v[i]; v[i] = v[j]; v[j] = t; }
  return max(0L, v[2]);
}

bool tapaAbierta() { return digitalRead(PIN_TAPA) == HIGH; }

// Envía un mensaje firmado y aplica el comando de la respuesta. Devuelve el código HTTP.
int enviar(const char* tipo, long peso, const String& deposito) {
  time_t ahora = time(nullptr);
  String cuerpo = String("{\"evento_id\":\"") + eventoId() + "\",\"tipo\":\"" + tipo + "\",\"peso_g\":" + peso +
                  ",\"tapa\":\"" + (tapaAbierta() ? "abierta" : "cerrada") + "\",\"firmware\":\"" + FIRMWARE +
                  "\",\"ts\":" + (long)ahora;
  if (deposito.length()) cuerpo += ",\"deposito\":\"" + deposito + "\"";
  cuerpo += "}";
  String firma = String("t=") + (long)ahora + ",v1=" + hmacSha256(String((long)ahora) + "." + cuerpo);

  HTTPClient http;
  http.begin(String(URL_BASE) + "/iot/v1/telemetria");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("User-Agent", "ReAceite-Contenedor/1.0");
  http.addHeader("X-Dispositivo", CODIGO);
  http.addHeader("X-Dispositivo-Firma", firma);
  int status = http.POST(cuerpo);
  String respuesta = status > 0 ? http.getString() : "";
  http.end();

  // Comando: abrir la compuerta para un depósito o mantenerla cerrada.
  int i = respuesta.indexOf("\"compuerta\":\"abierta\"");
  if (i >= 0) {
    int d = respuesta.indexOf("\"deposito\":\"", i);
    if (d >= 0) depositoAbierto = respuesta.substring(d + 12, respuesta.indexOf('"', d + 12));
    digitalWrite(PIN_CERRADURA, HIGH);
  } else if (respuesta.indexOf("\"compuerta\":\"cerrada\"") >= 0) {
    depositoAbierto = "";
    digitalWrite(PIN_CERRADURA, LOW);
  }
  return status;
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_TAPA, INPUT_PULLUP);
  pinMode(PIN_CERRADURA, OUTPUT);
  digitalWrite(PIN_CERRADURA, LOW);
  bascula.begin(PIN_HX711_DT, PIN_HX711_SCK);
  bascula.set_scale(FACTOR_ESCALA);
  bascula.tare();  // al instalarse vacío; después la tara se guarda en NVS
  WiFi.begin(WIFI_SSID, WIFI_CLAVE);
  while (WiFi.status() != WL_CONNECTED) delay(300);
  configTime(-6 * 3600, 0, "pool.ntp.org", "time.google.com");  // la firma lleva hora: el servidor tolera 5 min
  while (time(nullptr) < 1700000000) delay(200);
  enviar("latido", pesoGramos(), "");
}

void loop() {
  unsigned long ms = millis();
  bool abierta = tapaAbierta();

  // Mientras hay un depósito, el peso viaja cada 0.5 s: el celular del comercio lo ve en vivo.
  if (depositoAbierto.length() && ms - ultimoPeso > 500) {
    ultimoPeso = ms;
    enviar("peso", pesoGramos(), "");
  }

  // La tapa se cerró después de abrirse durante un depósito: espera a que el peso se estabilice y cierra.
  if (tapaAbiertaAntes && !abierta && depositoAbierto.length()) {
    delay(2000);
    String folio = depositoAbierto;
    int status = enviar("deposito.cerrado", pesoGramos(), folio);
    Serial.printf("deposito.cerrado %s -> HTTP %d\n", folio.c_str(), status);
    if (status == 200 || status == 201) {
      depositoAbierto = "";
      digitalWrite(PIN_CERRADURA, LOW);
    }
  }
  tapaAbiertaAntes = abierta;

  // Latido: cada 2 s esperando orden de apertura (respuesta casi inmediata al escaneo), cada 20 s si no.
  unsigned long intervalo = depositoAbierto.length() ? 20000 : 2000;
  if (ms - ultimoLatido > intervalo) {
    ultimoLatido = ms;
    enviar("latido", pesoGramos(), "");
  }
  delay(50);
}
