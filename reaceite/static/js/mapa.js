// Mapas con Leaflet y teselas de OpenStreetMap.
const L = window.L;
const TESELAS = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATRIBUCION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>';

export function crearMapa(contenedor, { centro = [19.4116, -99.1697], zoom = 15, interactivo = true } = {}) {
  const mapa = L.map(contenedor, {
    zoomControl: interactivo,
    dragging: interactivo,
    scrollWheelZoom: false,
    attributionControl: true,
  }).setView(centro, zoom);
  L.tileLayer(TESELAS, { maxZoom: 19, attribution: ATRIBUCION }).addTo(mapa);
  return mapa;
}

export function iconoParada(numero, hecha) {
  return L.divIcon({
    className: "",
    html: `<div class="marcador-parada${hecha ? " hecha" : ""}">${Number(numero)}</div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });
}

export function iconoDeposito() {
  return L.divIcon({ className: "", html: '<div class="marcador-deposito"></div>', iconSize: [26, 26], iconAnchor: [13, 13] });
}

export function iconoPunto(pendiente) {
  const tam = pendiente ? 18 : 14;
  return L.divIcon({
    className: "",
    html: `<div class="marcador-punto${pendiente ? " pendiente" : ""}"></div>`,
    iconSize: [tam, tam],
    iconAnchor: [tam / 2, tam / 2],
  });
}
