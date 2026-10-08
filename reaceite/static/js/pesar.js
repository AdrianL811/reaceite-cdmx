import { $, api, dinero, el, horaSeg, litros, metricas, miles, mostrarMensaje } from "./comun.js";
import { abrirEscaner } from "./escaner.js";
import { irAPesaje } from "./recolector-ir.js";

const raiz = $("#pantalla-pesar");
const token = raiz.dataset.token;
const mensaje = $("#mensaje");
const entrada = $("#peso");
let parametros = null;
let solicitud = null;

const NOMBRES = {
  1: "Dato crudo", 2: "Normalización", 3: "Validación", 4: "Enriquecimiento",
  5: "Evento", 6: "Orden a la API SPEI", 7: "Webhook de liquidación", 8: "Activo financiero",
};

function pintarCalculo() {
  const m = parametros ? metricas(entrada.value, parametros) : null;
  const celdas = {
    litros: m ? litros(m.litrosCl / 100) : "",
    agua: m ? `${miles(m.aguaL)} L` : "",
    bio: m ? litros(m.bioCl / 100) : "",
    bruto: m ? dinero(m.brutoCent / 100) : "",
    comision: m ? dinero(m.comisionCent / 100) : "",
    neto: m ? dinero(m.netoCent / 100) : "",
  };
  for (const [clave, valor] of Object.entries(celdas)) $(`#c-${clave}`).textContent = valor || "–";
  $("#formula").textContent = m
    ? `${(m.gramos / 1000).toLocaleString("es-MX", { maximumFractionDigits: 3 })} kg ÷ ${parametros.densidad} kg/L`
    : `kg ÷ ${parametros ? parametros.densidad : "0.92"} kg/L`;
  $("#confirmar").disabled = !m;
  const aviso = $("#aviso-tolerancia");
  if (m && solicitud && m.litrosCl / 100 > solicitud.litros * Number(parametros.tolerancia_peso)) {
    aviso.hidden = false;
    aviso.textContent = `Ojo: ${litros(m.litrosCl / 100)} es más de 1.5 veces lo que pidió el comercio (${solicitud.litros} L). Revisa la báscula antes de confirmar.`;
  } else {
    aviso.hidden = true;
  }
}

async function cargar() {
  const d = await api(`/api/pesaje/${encodeURIComponent(token)}`);
  parametros = d.parametros;
  solicitud = d.solicitud;
  const s = d.solicitud;
  $("#detalle-solicitud").textContent = s
    ? `Pidió ${s.litros} L de ${s.franja_txt}${s.ruta ? `. Parada ${s.ruta.parada} de ${s.ruta.de} de la ruta ${s.ruta.folio}` : ""}. Folio ${s.folio}.`
    : "Este comercio no tiene una solicitud abierta. Puedes registrar una recolección directa.";
  pintarCalculo();
}

function filaEtapa(n, datos) {
  const hecho = Boolean(datos);
  return el("li", { class: hecho ? "hecho" : "esperando", "data-etapa": n },
    el("span", {}, el("b", {}, `${n}. ${NOMBRES[n]}`), datos ? el("small", {}, datos.resumen) : null),
    datos ? el("time", { datetime: datos.ts }, horaSeg(datos.ts)) : el("span"),
  );
}

function pintarProgreso(pago) {
  const porEtapa = new Map(pago.etapas.map((e) => [e.etapa, e]));
  const lista = $("#progreso");
  lista.replaceChildren(...[1, 2, 3, 4, 5, 6, 7, 8].map((n) => filaEtapa(n, porEtapa.get(n))));
  const ultima = Math.max(0, ...pago.etapas.map((e) => e.etapa));
  [...lista.children].forEach((li) => {
    const n = Number(li.dataset.etapa);
    if (n > ultima + 1 && !li.classList.contains("hecho")) li.classList.remove("esperando");
  });
}

async function seguirPago(folio) {
  const limite = Date.now() + 30000;
  while (Date.now() < limite) {
    const pago = await api(`/api/pagos/${encodeURIComponent(folio)}`);
    pintarProgreso(pago);
    if (pago.estatus === "LIQUIDADO") {
      const caja = $("#resultado");
      caja.replaceChildren(
        el("article", { class: "ticket ticket--nuevo" },
          el("div", { class: "ticket__titulo" }, el("span", {}, "Pago liquidado"), el("span", { class: "chico" }, pago.folio)),
          el("p", { class: "ticket__monto" }, dinero(pago.monto)),
          el("p", { class: "suave chico" }, `Transferido a ${pago.comercio.nombre}, ${pago.clabe}.`),
          el("hr"),
          el("dl", {},
            el("div", {}, el("dt", {}, "Clave de rastreo"), el("dd", {}, pago.clave_rastreo)),
            el("div", {}, el("dt", {}, "Folio bancario"), el("dd", {}, pago.folio_banco || "–")),
            el("div", {}, el("dt", {}, "Recolección"), el("dd", {}, pago.recoleccion))),
        ));
      caja.hidden = false;
      if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
      $("#siguientes").hidden = false;
      return;
    }
    if (pago.estatus === "RECHAZADO") {
      mostrarMensaje(mensaje, `El banco rechazó el pago: ${pago.error || "sin detalle"}.`, "error");
      $("#siguientes").hidden = false;
      return;
    }
    await new Promise((r) => setTimeout(r, 450));
  }
  mostrarMensaje(mensaje, "El pago sigue en proceso. Lo verás liquidado en el monitor en cuanto responda el banco.", "info");
  $("#siguientes").hidden = false;
}

async function confirmar(extra = {}) {
  const boton = $("#confirmar");
  boton.disabled = true;
  boton.textContent = "Confirmando…";
  mostrarMensaje(mensaje, "");
  try {
    const r = await api("/api/recolecciones", { metodo: "POST", datos: { token, peso_kg: entrada.value, ...extra } });
    $("#form-pesaje").hidden = true;
    $("#bloque-progreso").hidden = false;
    pintarProgreso(r.pago);
    $("#bloque-progreso").scrollIntoView({ behavior: "smooth", block: "start" });
    await seguirPago(r.pago.folio);
  } catch (error) {
    if (error.codigo === "anomalia" && window.confirm(`${error.message}\n\nToca Aceptar para confirmar el peso.`)) {
      return confirmar({ ...extra, confirmar_anomalia: true });
    }
    if (error.codigo === "sin_solicitud" && window.confirm(`${error.message}\n\n¿Registrar una recolección directa?`)) {
      return confirmar({ ...extra, crear_si_falta: true });
    }
    mostrarMensaje(mensaje, error.message, "error");
  } finally {
    boton.textContent = "Confirmar recolección";
    boton.disabled = false;
  }
}

entrada.addEventListener("input", pintarCalculo);
$("#form-pesaje").addEventListener("submit", (e) => {
  e.preventDefault();
  confirmar();
});
$("#escanear-otro").addEventListener("click", () => abrirEscaner((r) => irAPesaje(r).catch((e) => alert(e.message))));

cargar().catch((error) => mostrarMensaje(mensaje, error.message, "error"));
