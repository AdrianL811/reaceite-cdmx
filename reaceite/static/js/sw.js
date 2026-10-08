// Service worker de ReAceite CDMX: hace la app instalable y la deja abrir sin señal.
// La API nunca se guarda en caché: los datos siempre vienen frescos del servidor.
const VERSION = "reaceite-v3";
const PRECARGA = [
  "/offline",
  "/static/css/app.css",
  "/static/js/comun.js",
  "/static/js/cubeta.js",
  "/static/fonts/atkinson.woff2",
  "/static/fonts/bricolage.woff2",
  "/static/icons/icon-192.png",
  "/manifest.webmanifest",
];

self.addEventListener("install", (evento) => {
  evento.waitUntil(caches.open(VERSION).then((cache) => cache.addAll(PRECARGA)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches.keys()
      .then((claves) => Promise.all(claves.filter((c) => c !== VERSION).map((c) => caches.delete(c))))
      .then(() => self.clients.claim()),
  );
});

function guardar(peticion, respuesta) {
  if (respuesta && respuesta.ok && respuesta.type === "basic") {
    const copia = respuesta.clone();
    caches.open(VERSION).then((cache) => cache.put(peticion, copia));
  }
  return respuesta;
}

self.addEventListener("fetch", (evento) => {
  const peticion = evento.request;
  const url = new URL(peticion.url);
  if (peticion.method !== "GET" || url.origin !== self.location.origin) return;
  if (/^\/(api|sim-spei|webhooks|qr|salir|entrar|salud)\b/.test(url.pathname)) return;

  // Archivos estáticos: se sirven al instante desde caché y se actualizan en segundo plano.
  if (url.pathname.startsWith("/static/")) {
    evento.respondWith(
      caches.match(peticion, { ignoreSearch: true }).then((guardada) => {
        const red = fetch(peticion).then((respuesta) => guardar(peticion, respuesta)).catch(() => guardada);
        return guardada || red;
      }),
    );
    return;
  }

  // Páginas: primero la red; sin señal, la última copia o la página sin conexión.
  if (peticion.mode === "navigate") {
    evento.respondWith(
      fetch(peticion)
        .then((respuesta) => guardar(peticion, respuesta))
        .catch(() => caches.match(peticion).then((guardada) => guardada || caches.match("/offline"))),
    );
  }
});
