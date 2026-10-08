import { $, $$, api, dinero, el, fecha, hace, hora, litros, miComercio, miles, mostrarMensaje, sondear } from "./comun.js";
import { crearCubeta } from "./cubeta.js";

const raiz = $("#pantalla-comercio");
const token = raiz.dataset.token;
const precio = Number(raiz.dataset.precio);
const comision = Number(raiz.dataset.comision);
const aguaPorLitro = Number(raiz.dataset.agua);
const tope = Number(raiz.dataset.tope);
const cubeta = crearCubeta($("#cubeta-zona"));
const mensaje = $("#mensaje");
const estado = { litros: null, franja: raiz.dataset.franja, ultimo: null, pagoVisto: null };

function elegir(grupo, valor) {
  $$(`[data-grupo="${grupo}"] button`).forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.valor === String(valor))));
  estado[grupo] = grupo === "litros" ? Number(valor) : valor;
  actualizarEstimado();
}
$$('[data-grupo] button').forEach((b) => b.addEventListener("click", () => elegir(b.closest("[data-grupo]").dataset.grupo, b.dataset.valor)));
elegir("franja", estado.franja);

function actualizarEstimado() {
  const caja = $("#estimado");
  const boton = $("#pedir");
  boton.disabled = !(estado.litros && estado.franja);
  if (!estado.litros) {
    caja.textContent = "Elige cuántos litros tienes para ver cuánto te pagamos.";
    return;
  }
  const neto = estado.litros * precio * (1 - comision);
  caja.replaceChildren(
    "Te pagamos alrededor de ", el("b", {}, dinero(neto)),
    ` y proteges ${miles(estado.litros * aguaPorLitro)} L de agua. El monto final sale del pesaje frente a ti.`,
  );
}

function textoZona(d) {
  const s = d.solicitud;
  const z = d.zona;
  if (s && s.estado === "EN_RUTA") {
    const r = s.ruta;
    return {
      total: Math.max(tope, z.litros_en_ruta), propios: s.litros, cifra: `${tope}`, de: ` de ${tope} L`,
      texto: r ? `La cubeta de ${z.nombre} se llenó y salió la ruta ${r.folio}. Eres la parada ${r.parada} de ${r.de}.` : "La ruta ya salió.",
    };
  }
  const faltan = Math.max(0, tope - z.litros_pendientes);
  return {
    total: z.litros_pendientes,
    propios: s && s.estado === "PENDIENTE" ? s.litros : 0,
    cifra: `${z.litros_pendientes}`,
    de: ` de ${tope} L`,
    texto: faltan > 0
      ? `${z.nombre} junta ${z.litros_pendientes} L entre todos. Faltan ${faltan} L para que salga la ruta; si no se llena en 48 horas, salimos de todos modos.`
      : `${z.nombre} ya juntó ${z.litros_pendientes} L: la ruta sale en este momento.`,
  };
}

function pasos(d) {
  const s = d.solicitud;
  const p = d.ultimo_pago;
  let nivel = 0;
  if (s) nivel = s.estado === "EN_RUTA" ? 2 : 1;
  else if (p && p.estatus !== "LIQUIDADO") nivel = 3;
  else if (p) nivel = 4;
  const datos = [
    ["Pedida", s ? `${s.folio}: ${s.litros} L de ${s.franja_txt}` : ""],
    ["En ruta", s && s.ruta ? `${s.ruta.folio}, parada ${s.ruta.parada} de ${s.ruta.de}` : "Sale cuando la zona junta 20 L"],
    ["Recolectada", p && nivel >= 3 ? `${litros(p.recoleccion.litros)} pesados frente a ti` : "Pesamos tu aceite frente a ti"],
    ["Pagada", p && nivel === 4 ? `${dinero(p.monto)} por transferencia` : "Transferencia al momento"],
  ];
  return datos.map(([titulo, detalle], i) => {
    const n = i + 1;
    const clase = n <= nivel ? "hecho" : n === nivel + 1 ? "actual" : "";
    return el("li", { class: clase }, el("span", {}, titulo, detalle ? el("small", {}, detalle) : null));
  });
}

function ticket(p, nuevo) {
  const liquidado = p.estatus === "LIQUIDADO";
  const filas = [
    ["Recolección", p.recoleccion.folio],
    ["Pesaje", `${p.recoleccion.peso_kg} kg = ${litros(p.recoleccion.litros)}`],
    ["Agua protegida", `${miles(p.recoleccion.agua_l)} L`],
    ["Cuenta", p.clabe],
  ];
  if (liquidado) {
    filas.push(["Clave de rastreo", p.clave_rastreo], ["Fecha", fecha(p.liquidado)]);
  }
  return el("article", { class: `ticket${liquidado ? "" : " ticket--espera"}${nuevo ? " ticket--nuevo" : ""}`, "aria-live": "polite" },
    el("div", { class: "ticket__titulo" },
      el("span", {}, liquidado ? "Pago recibido" : p.estatus === "RECHAZADO" ? "Pago rechazado" : "Pago en camino"),
      el("span", { class: "chico" }, p.folio)),
    el("p", { class: "ticket__monto" }, dinero(p.monto)),
    el("p", { class: "suave chico" }, liquidado ? "Transferencia SPEI simulada, liquidada." : "El banco está procesando la transferencia."),
    el("hr"),
    el("dl", {}, filas.map(([dt, dd]) => el("div", {}, el("dt", {}, dt), el("dd", {}, dd)))),
  );
}

function render(d) {
  miComercio.guardar(d);
  const z = textoZona(d);
  cubeta.fijar(z.total, z.propios);
  $("#zona-cifra").replaceChildren(z.cifra, el("small", {}, z.de));
  $("#zona-texto").textContent = z.texto;

  const s = d.solicitud;
  const p = d.ultimo_pago;
  $("#bloque-pedir").hidden = Boolean(s);
  $("#bloque-estado").hidden = !(s || (p && p.estatus !== "LIQUIDADO"));
  $("#pasos").replaceChildren(...pasos(d));
  const cancelar = $("#cancelar");
  cancelar.hidden = !(s && s.estado === "PENDIENTE");
  cancelar.dataset.folio = s ? s.folio : "";

  const reciente = p && (p.estatus !== "LIQUIDADO" || Date.now() - new Date(p.liquidado).getTime() < 12 * 3600 * 1000);
  const comprobante = $("#comprobante");
  if (reciente) {
    const clave = `${p.folio}:${p.estatus}`;
    const nuevo = estado.pagoVisto !== null && estado.pagoVisto !== clave && p.estatus === "LIQUIDADO";
    comprobante.replaceChildren(el("h2", {}, "Tu último pago"), ticket(p, nuevo));
    comprobante.hidden = false;
    if (nuevo && navigator.vibrate) navigator.vibrate([120, 60, 120]);
    estado.pagoVisto = clave;
  } else {
    comprobante.hidden = true;
    estado.pagoVisto = p ? `${p.folio}:${p.estatus}` : "";
  }

  $("#total-litros").textContent = litros(d.acumulado.litros);
  $("#total-agua").textContent = `${miles(d.acumulado.agua_l)} L`;
  $("#total-cobrado").textContent = dinero(d.acumulado.cobrado);
  const lista = $("#historial");
  lista.replaceChildren(...d.historial.map((h) => el("li", {},
    el("span", {}, `${litros(h.litros)} recolectados`, el("small", {}, `${fecha(h.fecha)}, ${miles(h.agua_l)} L de agua protegida`)),
    el("span", { class: "monto" }, dinero(h.monto)),
  )));
  $("#sin-historial").hidden = d.historial.length > 0;
  $("#actualizado").textContent = `Actualizado a las ${hora(new Date().toISOString())}`;
}

async function cargar() {
  render(await api(`/api/comercio/${encodeURIComponent(token)}`));
}

$("#pedir").addEventListener("click", async () => {
  const boton = $("#pedir");
  boton.disabled = true;
  boton.textContent = "Enviando…";
  mostrarMensaje(mensaje, "");
  try {
    const d = await api("/api/solicitudes", { metodo: "POST", datos: { token, litros: estado.litros, franja: estado.franja } });
    render(d);
    mostrarMensaje(mensaje, d.ruta_generada
      ? `Listo, folio ${d.creada}. Con tu aceite la zona llegó a ${tope} L y la ruta ${d.ruta_generada} ya salió.`
      : `Listo, folio ${d.creada}. Te avisamos aquí cuando salga la ruta.`, "ok");
    estado.litros = null;
    $$('[data-grupo="litros"] button').forEach((b) => b.setAttribute("aria-pressed", "false"));
  } catch (error) {
    mostrarMensaje(mensaje, error.message, "error");
    if (error.codigo === "solicitud_abierta") cargar();
  } finally {
    boton.textContent = "Pedir recolección";
    actualizarEstimado();
  }
});

$("#cancelar").addEventListener("click", async () => {
  const folio = $("#cancelar").dataset.folio;
  if (!folio || !window.confirm(`¿Cancelar la solicitud ${folio}?`)) return;
  try {
    render(await api(`/api/solicitudes/${encodeURIComponent(folio)}/cancelar`, { metodo: "POST", datos: { token } }));
    mostrarMensaje(mensaje, `Cancelaste la solicitud ${folio}.`, "info");
  } catch (error) {
    mostrarMensaje(mensaje, error.message, "error");
  }
});

actualizarEstimado();
let enCurso = false;
const cargarYMedir = async () => {
  const d = await api(`/api/comercio/${encodeURIComponent(token)}`);
  render(d);
  enCurso = Boolean(d.solicitud || (d.ultimo_pago && d.ultimo_pago.estatus !== "LIQUIDADO"));
};
sondear(cargarYMedir, () => (enCurso ? 2000 : 5000));
