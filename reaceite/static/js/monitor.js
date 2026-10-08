import { $, api, el, horaSeg, mostrarMensaje, sondear } from "./comun.js";

const lista = $("#bitacora");
const eventos = [];
let ultimoId = 0;
let ultimaRecoleccion = null;
let etapasVistas = new Set();

function claseTipo(tipo) {
  const dominio = tipo.split(".")[0];
  if (/rechaz|fallid|reintento/.test(tipo)) return "tipo tipo--error";
  return `tipo tipo--${dominio}`;
}

function filaEvento(e, nuevo) {
  const resumen = el("summary", {},
    el("time", { datetime: e.ts }, horaSeg(e.ts)),
    el("span", { class: claseTipo(e.tipo) }, e.tipo),
    el("span", {}, e.resumen),
  );
  const detalles = el("details", {}, resumen);
  if (e.detalle) detalles.append(el("pre", {}, JSON.stringify(e.detalle, null, 2)));
  return el("li", { class: nuevo ? "nuevo" : "" }, detalles);
}

function pintarPipeline(p, nombres) {
  const caja = $("#pipeline");
  if (!p) {
    $("#pipeline-titulo").textContent = "Confirma una recolección para ver su recorrido completo.";
    $("#pipeline-total").textContent = "";
    caja.replaceChildren(...Object.keys(nombres).map((n) => el("li", {}, el("b", {}, nombres[n]))));
    return;
  }
  if (p.recoleccion !== ultimaRecoleccion) {
    ultimaRecoleccion = p.recoleccion;
    etapasVistas = new Set();
  }
  const porEtapa = new Map(p.etapas.map((e) => [e.etapa, e]));
  const inicio = porEtapa.get(1) ? new Date(porEtapa.get(1).ts_ms).getTime() : null;
  caja.replaceChildren(...Object.keys(nombres).map((clave) => {
    const n = Number(clave);
    const e = porEtapa.get(n);
    const clases = [e ? "hecho" : "", n === 8 ? "dinero" : "", e && !etapasVistas.has(n) ? "recien" : ""].filter(Boolean).join(" ");
    if (e) etapasVistas.add(n);
    const desfase = e && inicio !== null ? new Date(e.ts_ms).getTime() - inicio : null;
    return el("li", { class: clases },
      el("b", {}, nombres[clave]),
      e ? el("time", { datetime: e.ts }, n === 1 ? "inicio" : `+${desfase < 1000 ? `${desfase} ms` : `${(desfase / 1000).toFixed(2)} s`}`) : el("small", {}, "en espera"),
      e ? el("small", {}, e.resumen) : null,
    );
  }));
  $("#pipeline-titulo").textContent = `Recorrido del dato de ${p.recoleccion}`;
  const fin = porEtapa.get(8);
  $("#pipeline-total").textContent = fin && inicio !== null
    ? `Del pesaje al pago: ${((new Date(fin.ts_ms).getTime() - inicio) / 1000).toFixed(2)} s, sin intervención humana`
    : "En proceso…";
}

function tabla(cuerpo, filas, columnas) {
  cuerpo.replaceChildren(...filas.map((f) => el("tr", {}, columnas.map(([clave, clase]) => {
    const valor = typeof clave === "function" ? clave(f) : f[clave];
    return el("td", { class: clase || "" }, valor === null || valor === undefined ? "–" : valor);
  }))));
}

async function cargar() {
  const d = await api(`/api/monitor?desde=${ultimoId}`);
  const nuevos = d.eventos.slice().reverse();
  const primera = ultimoId === 0;
  for (const e of nuevos) {
    eventos.unshift(e);
    lista.prepend(filaEvento(e, !primera));
  }
  while (lista.children.length > 150) lista.lastElementChild.remove();
  ultimoId = Math.max(ultimoId, d.ultimo_id);
  pintarPipeline(d.pipeline, d.etapas);
  tabla($("#tabla-pagos"), d.pagos, [
    ["folio"], [(p) => el("span", { class: `estado estado--${p.estatus}` }, p.estatus)], [(p) => `$${p.monto}`, "num"], ["clave_rastreo"],
  ]);
  tabla($("#tabla-banco"), d.banco, [
    ["folio"], ["referencia"], [(o) => el("span", { class: `estado estado--${o.estatus}` }, o.estatus)],
    [(o) => el("span", { class: `estado estado--${o.webhook}` }, `${o.webhook}${o.http ? ` (${o.http})` : ""}`)],
  ]);
  const cola = d.cola || {};
  $("#cola").textContent = `Cola de salida: ${cola.PENDIENTE || 0} pendientes, ${cola.ENVIADO || 0} enviadas, ${cola.FALLIDO || 0} fallidas.`;
  const vivo = $("#en-vivo");
  vivo.classList.remove("caido");
  vivo.textContent = "En vivo";
}

const restablecer = $("#restablecer");
if (restablecer) {
  restablecer.addEventListener("click", async () => {
    if (!window.confirm("Esto borra las recolecciones de la demostración y vuelve a cargar los datos de prueba. ¿Continuar?")) return;
    try {
      await api("/api/admin/restablecer", { metodo: "POST", datos: {} });
      window.location.reload();
    } catch (error) {
      mostrarMensaje($("#mensaje"), error.message, "error");
    }
  });
}

sondear(async () => {
  try {
    await cargar();
  } catch (error) {
    const vivo = $("#en-vivo");
    vivo.classList.add("caido");
    vivo.textContent = "Sin conexión";
    throw error;
  }
}, 1200);
