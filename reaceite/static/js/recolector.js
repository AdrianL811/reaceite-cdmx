import { $, api, el, hace, miles, sondear } from "./comun.js";
import { crearCubeta } from "./cubeta.js";
import { abrirEscaner } from "./escaner.js";
import { crearMapa, iconoDeposito, iconoParada } from "./mapa.js";
import { irAPesaje } from "./recolector-ir.js";

const mapas = new Map();
const cubetas = new Map();

$("#escanear").addEventListener("click", () => abrirEscaner((resultado) => irAPesaje(resultado).catch((e) => alert(e.message))));

function dibujarMapa(ruta, contenedor, deposito) {
  let registro = mapas.get(ruta.folio);
  if (!registro) {
    const mapa = crearMapa(contenedor, { centro: [deposito.lat, deposito.lon], zoom: 15 });
    registro = { mapa, capa: window.L.layerGroup().addTo(mapa), ajustado: false };
    mapas.set(ruta.folio, registro);
  }
  registro.capa.clearLayers();
  const puntos = [[deposito.lat, deposito.lon], ...ruta.paradas.map((p) => [p.lat, p.lon]), [deposito.lat, deposito.lon]];
  window.L.polyline(puntos, { color: "#12383d", weight: 4, opacity: 0.8, dashArray: "8 8" }).addTo(registro.capa);
  window.L.marker([deposito.lat, deposito.lon], { icon: iconoDeposito(), title: deposito.nombre }).addTo(registro.capa);
  ruta.paradas.forEach((p) => {
    window.L.marker([p.lat, p.lon], { icon: iconoParada(p.n, p.estado === "RECOLECTADA"), title: `${p.n}. ${p.nombre}` }).addTo(registro.capa);
  });
  if (!registro.ajustado) {
    registro.mapa.fitBounds(puntos, { padding: [28, 28] });
    registro.ajustado = true;
  }
  setTimeout(() => registro.mapa.invalidateSize(), 60);
}

function tarjetaRuta(ruta, deposito) {
  let tarjeta = document.getElementById(`ruta-${ruta.folio}`);
  const nueva = !tarjeta;
  if (nueva) {
    tarjeta = el("article", { class: "ruta superficie", id: `ruta-${ruta.folio}` },
      el("div", { class: "ruta__cabeza" }, el("h2", {}), el("span", { class: "etiqueta" })),
      el("div", { class: "ruta__datos" }),
      el("div", { class: "mapa" }),
      el("ol", { class: "paradas" }),
      el("p", { class: "suave chico algoritmo" }),
      el("a", { class: "boton boton--petroleo", target: "_blank", rel: "noopener" }, "Abrir la ruta en Google Maps"),
    );
  }
  tarjeta.querySelector("h2").textContent = `${ruta.folio} en ${ruta.zona}`;
  tarjeta.querySelector(".etiqueta").textContent = ruta.pendientes ? `${ruta.pendientes} por recoger` : "Completa";
  const ahorro = ruta.distancia_base_km > 0 ? Math.max(0, Math.round((1 - ruta.distancia_km / ruta.distancia_base_km) * 100)) : 0;
  tarjeta.querySelector(".ruta__datos").replaceChildren(
    el("div", {}, el("span", { class: "cifra" }, String(ruta.paradas.length)), el("small", {}, "paradas")),
    el("div", {}, el("span", { class: "cifra" }, `${ruta.distancia_km.toFixed(1)} km`), el("small", {}, "ida y vuelta")),
    el("div", {}, el("span", { class: "cifra" }, `${ruta.duracion_min} min`), el("small", {}, "con 5 min por parada")),
    el("div", {}, el("span", { class: "cifra" }, `${ruta.litros} L`), el("small", {}, "solicitados")),
  );
  tarjeta.querySelector(".paradas").replaceChildren(...ruta.paradas.map((p) => el("li", { class: p.estado === "RECOLECTADA" ? "hecha" : "" },
    el("span", { class: "n" }, String(p.n)),
    el("span", {}, el("span", { class: "nombre" }, p.nombre), el("small", {}, `${p.direccion}, ${p.litros} L, ${p.franja_txt}`)),
    p.estado === "RECOLECTADA"
      ? el("span", { class: "suave chico" }, "Recogida")
      : el("a", { class: "boton boton--aceite boton--chico", href: `/r/pesar/${encodeURIComponent(p.token)}` }, "Pesar"),
  )));
  const motivo = ruta.motivo === "espera" ? "Salió por la regla de 48 horas." : `Salió cuando ${ruta.zona} juntó 20 L.`;
  tarjeta.querySelector(".algoritmo").textContent =
    `${motivo} Orden calculado con ${ruta.algoritmo} en ${Number(ruta.calculo_ms).toFixed(2)} ms; ${ahorro} % menos recorrido que visitar en orden de llegada (${ruta.distancia_base_km.toFixed(2)} km).`;
  tarjeta.querySelector("a.boton--petroleo").href = ruta.url_maps;
  return { tarjeta, nueva };
}

function render(d) {
  const contenedor = $("#rutas");
  const vigentes = new Set(d.rutas.map((r) => r.folio));
  [...contenedor.querySelectorAll(".ruta")].forEach((t) => {
    const folio = t.id.replace("ruta-", "");
    if (!vigentes.has(folio)) {
      t.remove();
      const registro = mapas.get(folio);
      if (registro) registro.mapa.remove();
      mapas.delete(folio);
    }
  });
  d.rutas.forEach((ruta) => {
    const { tarjeta, nueva } = tarjetaRuta(ruta, d.deposito);
    if (nueva) contenedor.append(tarjeta);
    dibujarMapa(ruta, tarjeta.querySelector(".mapa"), d.deposito);
  });
  $("#sin-rutas").hidden = d.rutas.length > 0;

  const zonas = $("#zonas");
  d.zonas.forEach((z) => {
    let caja = document.getElementById(`zona-${z.zona}`);
    if (!caja) {
      const figura = el("div");
      caja = el("div", { id: `zona-${z.zona}` }, figura, el("span", {}, el("b"), el("small")));
      zonas.append(caja);
      cubetas.set(z.zona, crearCubeta(figura, { mostrarTope: false }));
    }
    cubetas.get(z.zona).fijar(z.litros_pendientes);
    caja.querySelector("b").textContent = z.nombre;
    caja.querySelector("small").textContent = z.solicitudes_pendientes
      ? `${z.litros_pendientes} de ${z.tope} L, la más antigua ${hace(z.mas_antigua)}`
      : `${z.litros_pendientes} de ${z.tope} L`;
  });
}

sondear(async () => render(await api("/api/rutas")), 5000);
