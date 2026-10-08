import { $, api, dinero, el, hace, litros, miles, sondear } from "./comun.js";
import { crearCubeta } from "./cubeta.js";
import { crearMapa, iconoDeposito, iconoPunto } from "./mapa.js";

const cubetas = new Map();
const valores = { litros: 0, agua: 0, bio: 0, pagado: 0 };
const vistos = new Set();
let primera = true;
let mapa = null;
let capa = null;

function animar(nodo, desde, hasta, formato) {
  const reducir = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reducir || desde === hasta) {
    nodo.textContent = formato(hasta);
    return;
  }
  const inicio = performance.now();
  const duracion = 1400;
  const paso = (t) => {
    const k = Math.min(1, (t - inicio) / duracion);
    const suave = 1 - Math.pow(1 - k, 3);
    nodo.textContent = formato(desde + (hasta - desde) * suave);
    if (k < 1) requestAnimationFrame(paso);
  };
  requestAnimationFrame(paso);
}

let cubetasPintadas = -1;
function pintarCubetas(totalLitros) {
  const llenas = Math.floor(totalLitros / 20);
  const resto = totalLitros - llenas * 20;
  const clave = Math.round(totalLitros * 100);
  if (clave === cubetasPintadas) return;
  cubetasPintadas = clave;
  const caja = $("#cubetas-total");
  caja.replaceChildren();
  const visibles = Math.min(llenas, 14);
  for (let i = 0; i < visibles + (resto > 0.01 ? 1 : 0); i++) {
    const figura = el("div");
    caja.append(figura);
    crearCubeta(figura, { mostrarTope: false }).fijar(i < visibles ? 20 : resto);
  }
  caja.append(el("span", {}, `${llenas} cubetas de 20 L llenas`));
}

function render(d) {
  const nuevos = {
    litros: Number(d.litros), agua: Number(d.agua_l), bio: Number(d.biocombustible_l), pagado: Number(d.pagado),
  };
  animar($("#v-litros"), valores.litros, nuevos.litros, (v) => v.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  animar($("#v-agua"), valores.agua, nuevos.agua, (v) => miles(Math.round(v)));
  animar($("#v-bio"), valores.bio, nuevos.bio, (v) => v.toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  animar($("#v-pagado"), valores.pagado, nuevos.pagado, (v) => dinero(v));
  Object.assign(valores, nuevos);
  pintarCubetas(nuevos.litros);
  $("#v-recolecciones").textContent = `${d.recolecciones} recolecciones en ${d.comercios} comercios`;
  $("#v-pagos").textContent = `${d.pagos} transferencias liquidadas`;

  const zonas = $("#zonas");
  d.zonas.forEach((z) => {
    let caja = document.getElementById(`zona-${z.zona}`);
    if (!caja) {
      const figura = el("div");
      caja = el("div", { id: `zona-${z.zona}` }, figura, el("b"), el("span", { class: "cifra" }), el("small", { class: "suave" }));
      zonas.append(caja);
      cubetas.set(z.zona, crearCubeta(figura));
    }
    cubetas.get(z.zona).fijar(z.litros_pendientes);
    caja.querySelector("b").textContent = z.nombre;
    caja.querySelector(".cifra").textContent = `${z.litros_pendientes} de ${z.tope} L`;
    caja.querySelector("small").textContent = z.litros_en_ruta ? `${z.litros_en_ruta} L ya van en ruta` : "esperando aceite";
  });

  const feed = $("#feed");
  feed.replaceChildren(...d.ultimos.map((u) => {
    const nuevo = !primera && !vistos.has(u.folio);
    vistos.add(u.folio);
    return el("li", { class: nuevo ? "nuevo" : "" },
      el("span", { class: "gota", "aria-hidden": "true" }),
      el("span", {}, `${litros(u.litros)} de ${u.tipo.toLowerCase()} en ${u.zona}`,
        el("small", { class: "suave", style: "display:block" }, `${u.comercio}, ${hace(u.cuando)}, ${miles(u.agua_l)} L de agua protegida`)),
      el("span", { class: "monto" }, u.estatus === "LIQUIDADO" ? dinero(u.monto) : "en proceso"),
    );
  }));
  primera = false;

  if (!mapa) {
    mapa = crearMapa($("#mapa-impacto"), { centro: [d.deposito.lat, d.deposito.lon], zoom: 15 });
    capa = window.L.layerGroup().addTo(mapa);
    mapa.fitBounds(d.puntos.map((p) => [p.lat, p.lon]).concat([[d.deposito.lat, d.deposito.lon]]), { padding: [24, 24] });
  }
  capa.clearLayers();
  window.L.marker([d.deposito.lat, d.deposito.lon], { icon: iconoDeposito(), title: d.deposito.nombre }).addTo(capa);
  d.puntos.forEach((p) => window.L.marker([p.lat, p.lon], { icon: iconoPunto(p.pendiente), title: `${p.codigo}, ${p.tipo}` }).addTo(capa));

  const vivo = $("#en-vivo");
  vivo.classList.remove("caido");
  vivo.textContent = "En vivo";
}

sondear(async () => {
  try {
    render(await api("/api/impacto"));
  } catch (error) {
    const vivo = $("#en-vivo");
    vivo.classList.add("caido");
    vivo.textContent = "Sin conexión";
    throw error;
  }
}, 3000);
