import { $, api, dinero, el, horaSeg, litros, mostrarMensaje, sondear } from "./comun.js";

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
  pintarFondo(d.fondo);
  pintarContenedores(d.contenedores);
  const cola = d.cola || {};
  $("#cola").textContent = `Cola de salida: ${cola.PENDIENTE || 0} pendientes, ${cola.ENVIADO || 0} enviadas, ${cola.FALLIDO || 0} fallidas.`;
  const vivo = $("#en-vivo");
  vivo.classList.remove("caido");
  vivo.textContent = "En vivo";
}

function pintarFondo(f) {
  if (!f) return;
  const saldo = $("#fondo-saldo");
  saldo.textContent = dinero(f.saldo);
  saldo.classList.toggle("bajo", f.alerta);
  $("#fondo-dispersado").textContent = dinero(f.dispersado);
  $("#fondo-espera").textContent = f.pagos_en_espera ? `${f.pagos_en_espera} (${dinero(f.monto_en_espera)})` : "Ninguno";
  $("#fondo-inventario").textContent = `${litros(f.inventario.litros)} (${f.inventario.recolecciones} entregas)`;
  $("#fondo-precio-txt").textContent = `Venta a la planta a ${dinero(f.precio_planta)}/L`;
  $("#fondo-venta").textContent = dinero(f.inventario.venta);
  $("#fondo-margen").textContent = dinero(f.inventario.margen);
  const boton = $("#vender-lote");
  if (boton) {
    boton.disabled = !f.inventario.listo;
    boton.title = f.inventario.listo ? "" : `La planta pide lotes de al menos ${f.inventario.minimo_l} L`;
  }
  $("#fondo-lotes").textContent = f.lotes.length
    ? `Último lote: ${f.lotes[0].folio}, ${litros(f.lotes[0].litros)} por ${dinero(f.lotes[0].venta)} (margen ${dinero(f.lotes[0].margen)}).`
    : `Aún no se vende ningún lote a ${f.planta}.`;
}

let contenedoresPintados = "";
function pintarContenedores(lista) {
  if (!lista) return;
  // Solo se redibuja si algo cambió: así un clic en «Abrir contenedor» nunca cae sobre un botón reemplazado.
  const firma = JSON.stringify(lista.map((c) => [c.codigo, c.en_linea, c.porcentaje, c.nivel_l, c.alerta,
    c.deposito && c.deposito.folio]));
  if (firma === contenedoresPintados) return;
  contenedoresPintados = firma;
  $("#lista-contenedores").replaceChildren(...lista.map((c) => el("li", {},
    el("span", { class: "mini-nivel", role: "img", "aria-label": `Lleno al ${c.porcentaje} %` }, el("span", { style: `height:${c.porcentaje}%` })),
    el("span", {},
      el("b", {}, `${c.codigo}, ${c.nombre}`),
      el("small", {}, el("span", { class: `punto-senal${c.en_linea ? " ok" : ""}` }),
        `${c.en_linea ? "En línea" : "Sin señal"}; ${c.porcentaje} % (${litros(c.nivel_l)})`
        + (c.deposito ? `; depósito ${c.deposito.folio} de ${c.deposito.comercio}` : "")
        + (c.alerta ? "; programar vaciado" : "")),
    ),
    el("a", { class: "boton boton--chico", href: c.url }, "Abrir gemelo digital"),
  )));
}

const vender = $("#vender-lote");
if (vender) {
  vender.addEventListener("click", async () => {
    if (!window.confirm("Se venderá a la planta todo el aceite ya pagado y aún no vendido. El cobro recarga el Fondo de Garantía. ¿Continuar?")) return;
    vender.disabled = true;
    try {
      const l = await api("/api/admin/lotes", { metodo: "POST", datos: {} });
      mostrarMensaje($("#mensaje"), `${l.folio}: ${litros(l.litros)} vendidos por ${dinero(l.venta)}; margen ${dinero(l.margen)}. `
        + `Fondo de Garantía: ${dinero(l.saldo_fondo)}.`, "ok");
    } catch (error) {
      mostrarMensaje($("#mensaje"), error.message, "error");
    } finally {
      vender.disabled = false;
    }
  });
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

const formPin = $("#form-pin-admin");
if (formPin) {
  formPin.addEventListener("submit", async (e) => {
    e.preventDefault();
    const caja = $("#pin-admin-resultado");
    const codigo = $("#pin-admin-codigo").value.trim();
    if (!window.confirm(`Se cerrarán las sesiones abiertas de ${codigo} y su PIN actual dejará de servir. ¿Generar un PIN temporal?`)) return;
    try {
      const r = await api(`/api/admin/comercios/${encodeURIComponent(codigo)}/pin`, { metodo: "POST", datos: {} });
      caja.hidden = false;
      caja.replaceChildren(el("div", { class: "mensaje mensaje--ok", role: "status" },
        `${r.nombre} (${r.codigo}), celular ${r.telefono}. PIN temporal: `, el("b", { class: "pin-mostrado" }, r.pin),
        el("br"), el("small", {}, "Dáselo en persona; no se volverá a mostrar.")));
      formPin.reset();
    } catch (error) {
      mostrarMensaje(caja, error.message, "error");
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
