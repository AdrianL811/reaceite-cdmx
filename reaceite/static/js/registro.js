import { $, $$, api, datosJSON, el, miComercio, mostrarMensaje } from "./comun.js";
import { crearMapa } from "./mapa.js";

const zonas = datosJSON("datos-zonas");
const formulario = $("#form-registro");
const mensaje = $("#mensaje");
const estado = { tipo: null, franja: "10-12", lat: null, lon: null };
let mapa = null;
let marcador = null;

function elegirChip(grupo, valor) {
  $$(`[data-grupo="${grupo}"] .chip`).forEach((chip) => chip.setAttribute("aria-pressed", String(chip.dataset.valor === valor)));
  estado[grupo] = valor;
}
$$(".chips[data-grupo] .chip").forEach((chip) => {
  chip.addEventListener("click", () => elegirChip(chip.closest("[data-grupo]").dataset.grupo, chip.dataset.valor));
});
elegirChip("franja", "10-12");

function distancia(a, b) {
  const r = Math.PI / 180;
  const x = (b[1] - a[1]) * r * Math.cos(((a[0] + b[0]) / 2) * r);
  const y = (b[0] - a[0]) * r;
  return Math.hypot(x, y);
}

function fijarUbicacion(lat, lon, centrar = true) {
  estado.lat = Number(lat.toFixed(6));
  estado.lon = Number(lon.toFixed(6));
  const cercana = Object.entries(zonas).sort((a, b) => distancia([lat, lon], [a[1].lat, a[1].lon]) - distancia([lat, lon], [b[1].lat, b[1].lon]))[0][0];
  $("#zona").value = cercana;
  $("#ubicacion-texto").textContent = `Ubicación guardada. Colonia sugerida: ${zonas[cercana].nombre}. Si el punto no es exacto, toca el mapa donde está tu puesto.`;
  $("#mapa-registro").hidden = false;
  if (!mapa) {
    mapa = crearMapa($("#mapa-registro"), { centro: [lat, lon], zoom: 17 });
    mapa.on("click", (e) => fijarUbicacion(e.latlng.lat, e.latlng.lng, false));
  }
  if (marcador) marcador.setLatLng([lat, lon]);
  else marcador = window.L.marker([lat, lon], { keyboard: false }).addTo(mapa);
  if (centrar) mapa.setView([lat, lon], 17);
  setTimeout(() => mapa.invalidateSize(), 50);
}

$("#usar-ubicacion").addEventListener("click", () => {
  if (!navigator.geolocation) {
    $("#ubicacion-texto").textContent = "Este teléfono no comparte ubicación. Elige tu colonia abajo.";
    return;
  }
  $("#ubicacion-texto").textContent = "Buscando tu ubicación…";
  navigator.geolocation.getCurrentPosition(
    (pos) => fijarUbicacion(pos.coords.latitude, pos.coords.longitude),
    () => { $("#ubicacion-texto").textContent = "No pudimos obtener tu ubicación. Elige tu colonia abajo."; },
    { enableHighAccuracy: true, timeout: 12000, maximumAge: 30000 },
  );
});

formulario.addEventListener("submit", async (e) => {
  e.preventDefault();
  mostrarMensaje(mensaje, "");
  if (!estado.tipo) {
    mostrarMensaje(mensaje, "Elige el tipo de negocio.", "error");
    return;
  }
  const boton = $("#registrar");
  boton.disabled = true;
  boton.textContent = "Registrando…";
  try {
    const c = await api("/api/comercios", {
      metodo: "POST",
      datos: {
        nombre: $("#nombre").value,
        tipo: estado.tipo,
        telefono: $("#telefono").value,
        direccion: $("#direccion").value,
        zona: $("#zona").value,
        franja: estado.franja,
        lat: estado.lat,
        lon: estado.lon,
      },
    });
    miComercio.guardar(c);
    formulario.hidden = true;
    const listo = $("#registro-listo");
    $("#listo-nombre").textContent = `Listo, ${c.nombre} ya está registrado`;
    $("#listo-codigo").textContent = `Tu código es ${c.codigo} y tu colonia, ${c.zona.nombre}.`;
    const imagen = el("img", { src: `/qr/c/${encodeURIComponent(c.token)}.png`, alt: `Código QR de ${c.nombre}`, width: 260, height: 260 });
    $("#listo-qr").replaceChildren(imagen);
    $("#listo-pedir").href = `/c/${encodeURIComponent(c.token)}`;
    $("#listo-descargar").href = `/qr/c/${encodeURIComponent(c.token)}.png?descargar=1`;
    listo.hidden = false;
    listo.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    mostrarMensaje(mensaje, error.message, "error");
    mensaje.scrollIntoView({ behavior: "smooth", block: "center" });
  } finally {
    boton.disabled = false;
    boton.textContent = "Registrar comercio";
  }
});
