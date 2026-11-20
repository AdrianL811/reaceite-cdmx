import { $, $$, api, dinero, el, fecha, hora, litros, miles, mostrarMensaje, sondear } from "./comun.js";
import { crearCubeta } from "./cubeta.js";
import { abrirEscaner } from "./escaner.js";

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
    ["Pagada", p && nivel === 4 ? `${dinero(p.monto)} en tu billetera` : "Directo a tu billetera"],
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
    el("p", { class: "suave chico" }, liquidado ? "Abonado a tu billetera (pago simulado del piloto)."
      : p.espera || "La pasarela está procesando la transferencia."),
    el("hr"),
    el("dl", {}, filas.map(([dt, dd]) => el("div", {}, el("dt", {}, dt), el("dd", {}, dd)))),
  );
}

function render(d) {
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
    if (nuevo) cargarBilletera(true);
    estado.pagoVisto = clave;
  } else {
    comprobante.hidden = true;
    estado.pagoVisto = p ? `${p.folio}:${p.estatus}` : "";
  }

  const abierto = d.deposito_abierto;
  $("#deposito-abierto").hidden = !abierto;
  if (abierto) $("#volver-deposito").href = abierto.url;
  if (!estado.contenedoresPintados) {
    estado.contenedoresPintados = true;
    $("#lista-contenedores").replaceChildren(...d.contenedores.map((k) => el("li", {},
      el("span", { class: "mini-nivel", role: "img", "aria-label": `Lleno al ${k.porcentaje} %` },
        el("span", { style: `height:${k.porcentaje}%` })),
      el("span", {}, el("b", {}, k.nombre), el("small", {}, `${k.direccion}, ${k.zona}`)),
      el("span", { class: "chico suave" }, `${k.porcentaje} %`),
    )));
  }

  $("#total-litros").textContent = litros(d.acumulado.litros);
  $("#total-agua").textContent = `${miles(d.acumulado.agua_l)} L`;
  $("#total-cobrado").textContent = dinero(d.acumulado.cobrado);
  const lista = $("#historial");
  lista.replaceChildren(...d.historial.map((h) => el("li", {},
    el("span", {}, h.origen === "CONTENEDOR" ? `${litros(h.litros)} en contenedor` : `${litros(h.litros)} recolectados`,
      el("small", {}, `${fecha(h.fecha)}, ${miles(h.agua_l)} L de agua protegida`)),
    el("span", { class: "monto" }, dinero(h.monto)),
  )));
  $("#sin-historial").hidden = d.historial.length > 0;
  $("#actualizado").textContent = `Actualizado a las ${hora(new Date().toISOString())}`;
}

// Si la sesión terminó (PIN cambiado en otro teléfono, 90 días sin entrar), se vuelve a pedir el PIN.
function revisarSesion(error) {
  if (error && error.status === 401) {
    window.location.href = `/comercio/entrar?siguiente=${encodeURIComponent(window.location.pathname)}`;
    return true;
  }
  if (error && error.codigo === "otro_comercio") {
    // Esta pestaña quedó con un QR viejo (se reemplazó en otro teléfono): se abre el panel actual.
    window.location.href = "/mi-comercio";
    return true;
  }
  return false;
}

async function cargar() {
  try {
    render(await api(`/api/comercio/${encodeURIComponent(token)}`));
  } catch (error) {
    if (!revisarSesion(error)) throw error;
  }
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
    if (revisarSesion(error)) return;
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
    if (revisarSesion(error)) return;
    mostrarMensaje(mensaje, error.message, "error");
  }
});

// ---------------------------------------------------------------- billetera (saldo consultado a la pasarela)
async function cargarBilletera(cambio = false) {
  let b;
  try {
    b = await api("/api/mi-comercio/billetera");
  } catch (error) {
    if (revisarSesion(error)) return;
    $("#billetera-nota").textContent = "No pudimos consultar tu saldo. Intenta en un momento.";
    return;
  }
  const saldo = $("#billetera-saldo");
  saldo.textContent = dinero(b.saldo);
  if (cambio) {
    saldo.classList.remove("cambio");
    void saldo.offsetWidth;
    saldo.classList.add("cambio");
  }
  $("#billetera-celular").textContent = `Ligada al ${b.celular}`;
  $("#billetera-nota").textContent = b.activa
    ? `Cuenta ${b.clabe}. Saldo consultado a la pasarela de pagos (simulada).`
    : "Tu billetera se activa en unos segundos.";
  const lista = $("#billetera-movimientos");
  lista.hidden = !b.movimientos.length;
  lista.replaceChildren(...b.movimientos.slice(0, 3).map((m) => el("li", {},
    el("span", {}, `${fecha(m.fecha)}, ${m.concepto.replace(/\s*\([^)]*\)\s*$/, "")}`),
    el("b", { class: m.tipo === "ABONO" ? "abono" : "" }, `${m.tipo === "ABONO" ? "+" : "−"}${dinero(m.monto)}`),
  )));
}

// ---------------------------------------------------------------- contenedores
$("#escanear-contenedor").addEventListener("click", () => abrirEscaner((resultado) => {
  if (resultado.contenedor) window.location.href = `/k/${encodeURIComponent(resultado.contenedor)}`;
  else if (resultado.contenedorCodigo) window.location.href = `/contenedor/${encodeURIComponent(resultado.contenedorCodigo)}`;
  else mostrarMensaje($("#mensaje-contenedor"), "Ese es el QR de un bote. Escanea el QR pegado en el contenedor.", "error");
}, { titulo: "Escanear el QR del contenedor", aviso: "Apunta la cámara al QR del contenedor.", placeholder: "Código del contenedor, por ejemplo CTN-0001" }));

// ---------------------------------------------------------------- Mi QR
const mensajeQr = $("#mensaje-qr");

$("#ya-pegue").addEventListener("click", async () => {
  const boton = $("#ya-pegue");
  boton.disabled = true;
  try {
    await api("/api/mi-comercio/qr/confirmar", { metodo: "POST", datos: {} });
    $("#falta-qr").hidden = true;
    mostrarMensaje(mensajeQr, "Perfecto: el recolector ya puede escanear tu bote.", "ok");
  } catch (error) {
    if (revisarSesion(error)) return;
    mostrarMensaje(mensaje, error.message, "error");
  } finally {
    boton.disabled = false;
  }
});

$("#form-reemplazar").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!window.confirm("Tu QR actual dejará de funcionar y tendrás que pegar el nuevo en tu bote. ¿Reemplazarlo?")) return;
  const boton = $("#form-reemplazar button");
  boton.disabled = true;
  try {
    const d = await api("/api/mi-comercio/qr/reemplazar", { metodo: "POST", datos: { pin: $("#pin-reemplazar").value } });
    window.location.href = `/c/${encodeURIComponent(d.token)}?qr=nuevo#mi-qr`;
  } catch (error) {
    if (revisarSesion(error)) return;
    mostrarMensaje(mensajeQr, error.message, "error");
    boton.disabled = false;
  }
});

if (new URLSearchParams(window.location.search).get("qr") === "nuevo") {
  mostrarMensaje(mensajeQr, "Listo: este es tu QR nuevo. Imprímelo y pégalo en tu bote; el anterior ya no funciona.", "ok");
  window.history.replaceState(null, "", window.location.pathname + "#mi-qr");
}

// ---------------------------------------------------------------- Mi cuenta
$("#form-pin").addEventListener("submit", async (e) => {
  e.preventDefault();
  const mensajeCuenta = $("#mensaje-cuenta");
  const boton = $("#form-pin button");
  boton.disabled = true;
  try {
    const r = await api("/api/mi-comercio/pin", {
      metodo: "POST",
      datos: { actual: $("#pin-actual").value, nuevo: $("#pin-nuevo").value, confirmacion: $("#pin-confirmacion").value },
    });
    $("#form-pin").reset();
    $("#form-pin").closest("details").open = false;
    const aviso = $(".aviso--pin");
    if (aviso) aviso.hidden = true;
    mostrarMensaje(mensajeCuenta, r.mensaje, "ok");
  } catch (error) {
    if (revisarSesion(error)) return;
    mostrarMensaje(mensajeCuenta, error.message, "error");
  } finally {
    boton.disabled = false;
  }
});

actualizarEstimado();
cargarBilletera();
let enCurso = false;
const cargarYMedir = async () => {
  let d;
  try {
    d = await api(`/api/comercio/${encodeURIComponent(token)}`);
  } catch (error) {
    if (revisarSesion(error)) return;
    throw error;
  }
  render(d);
  enCurso = Boolean(d.solicitud || (d.ultimo_pago && d.ultimo_pago.estatus !== "LIQUIDADO"));
};
sondear(cargarYMedir, () => (enCurso ? 2000 : 5000));
