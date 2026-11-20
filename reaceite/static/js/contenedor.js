// Contenedor inteligente: el depósito del comercio (celular) y el gemelo digital del equipo.
import { $, api, datosJSON, dinero, el, litros, metricas, miles, mostrarMensaje, sondear } from "./comun.js";

const raiz = $("#pantalla-contenedor");
const modo = raiz.dataset.modo;
const codigo = raiz.dataset.codigo;
const token = raiz.dataset.token;
const parametros = datosJSON("datos-parametros");
const mensaje = $("#mensaje");
const GRAMOS_POR_LITRO = Math.round(Number(parametros.densidad) * 1000);

const kg = (g) => (Math.max(0, g) / 1000).toFixed(3);

// ---------------------------------------------------------------- avisos del teléfono
function pedirPermisoAvisos() {
  try {
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission().catch(() => {});
  } catch { /* navegador sin avisos */ }
}

async function avisar(titulo, cuerpo) {
  if (navigator.vibrate) navigator.vibrate([140, 70, 140]);
  try {
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    const opciones = { body: cuerpo, icon: "/static/icons/icon-192.png", badge: "/static/icons/favicon-32.png", tag: "pago" };
    const registro = "serviceWorker" in navigator ? await navigator.serviceWorker.getRegistration() : null;
    if (registro) await registro.showNotification(titulo, opciones);
    else new Notification(titulo, opciones);
  } catch { /* el aviso es un extra: la pantalla ya muestra el pago */ }
}

function cuentaAtras(venceMs) {
  const s = Math.max(0, Math.round((venceMs - Date.now()) / 1000));
  return `Quedan ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}.`;
}

function actualizarNivel(c) {
  const barra = $(".nivel-contenedor__barra");
  if (!barra || !c || c.porcentaje === undefined) return;
  barra.firstElementChild.style.height = `${c.porcentaje}%`;
  barra.setAttribute("aria-label", `Lleno al ${c.porcentaje} %`);
  const cifra = $(".nivel-contenedor .cifra");
  cifra.textContent = `${c.porcentaje} %`;
  cifra.nextElementSibling.firstElementChild.textContent = `lleno, ${c.nivel_l} de ${c.capacidad_l} L. `;
}

// ---------------------------------------------------------------- comercio: depositar y cobrar
function iniciarComercio() {
  let folio = raiz.dataset.deposito || null;
  let sondeo = null;
  let pagoMostrado = false;
  const pasos = ["paso-abrir", "paso-vertiendo", "paso-pago"];
  const mostrar = (paso) => pasos.forEach((id) => { $(`#${id}`).hidden = id !== paso; });

  const revisarSesion = (error) => {
    if (error && error.status === 401) {
      window.location.href = `/comercio/entrar?siguiente=${encodeURIComponent(window.location.pathname)}`;
      return true;
    }
    return false;
  };

  function seguir() {
    if (!sondeo) sondeo = sondear(cargar, 650);
  }

  function detener() {
    if (sondeo) sondeo.detener();
    sondeo = null;
  }

  async function cargar() {
    if (!folio) return;
    let d;
    try {
      d = await api(`/api/depositos/${encodeURIComponent(folio)}`);
    } catch (error) {
      if (revisarSesion(error)) return;
      throw error;
    }
    pintar(d);
    const terminado = ["CANCELADO", "VENCIDO"].includes(d.estado)
      || (d.pago && ["LIQUIDADO", "RECHAZADO"].includes(d.pago.estatus));
    if (terminado) detener();
  }

  function pintar(d) {
    if (d.estado === "ABIERTO") {
      mostrar("paso-vertiendo");
      const g = d.peso_neto_g;
      $("#peso-vivo").textContent = kg(g);
      const m = g >= 50 ? metricas(g / 1000, parametros) : null;
      $("#estimado-vivo").replaceChildren(...(m
        ? [`${litros(m.litrosCl / 100)}: te pagamos `, el("b", {}, dinero(m.netoCent / 100))]
        : ["Vierte tu aceite: la báscula lo pesa en vivo."]));
      $("#cancelar-deposito").hidden = g >= 50;
      $("#cuenta-atras").textContent = cuentaAtras(d.vence_ms);
      return;
    }
    if (d.estado === "CANCELADO" || d.estado === "VENCIDO") {
      mostrar("paso-abrir");
      $("#abrir").disabled = false;
      const texto = d.estado === "VENCIDO"
        ? "La compuerta se cerró porque pasaron 5 minutos sin aceite. Ábrela de nuevo cuando estés listo."
        : d.motivo === "la báscula no registró aceite"
          ? "La báscula no registró aceite, así que no se generó un pago."
          : "Cancelaste el depósito y la compuerta se cerró.";
      mostrarMensaje(mensaje, texto, "info");
      folio = null;
      return;
    }
    mostrar("paso-pago");
    actualizarNivel(d.contenedor);
    const r = d.recoleccion;
    const pago = d.pago;
    const liquidado = pago && pago.estatus === "LIQUIDADO";
    const filas = [
      ["hecho", "Depósito registrado", `${Number(r.peso_kg)} kg = ${litros(r.litros)} en ${d.contenedor.nombre}`],
      [pago ? "hecho" : "esperando", "Orden de pago enviada", pago ? `${pago.folio} por ${dinero(pago.monto)}` : "Calculando…"],
      [liquidado ? "hecho" : "esperando", "Pago en tu billetera",
        liquidado ? `Clave de rastreo ${pago.clave_rastreo}` : (pago && pago.espera) || "Transferencia en proceso…"],
    ];
    $("#progreso-deposito").replaceChildren(...filas.map(([clase, titulo, detalle]) =>
      el("li", { class: clase }, el("span", {}, el("b", {}, titulo), el("small", {}, detalle)))));
    if (liquidado && !pagoMostrado) {
      pagoMostrado = true;
      mostrarTicket(d);
    }
  }

  async function mostrarTicket(d) {
    let billetera = null;
    try {
      billetera = await api("/api/mi-comercio/billetera");
    } catch { /* el ticket se muestra igual */ }
    const r = d.recoleccion;
    const filas = [
      ["Saldo de tu billetera", billetera ? dinero(billetera.saldo) : "–"],
      ["Aceite", `${Number(r.peso_kg)} kg = ${litros(r.litros)}`],
      ["Agua protegida", `${miles(r.agua_l)} L`],
      ["Clave de rastreo", d.pago.clave_rastreo],
    ];
    $("#ticket-deposito").replaceChildren(el("article", { class: "ticket ticket--nuevo" },
      el("div", { class: "ticket__titulo" }, el("span", {}, "Pago recibido"), el("span", { class: "chico" }, d.pago.folio)),
      el("p", { class: "ticket__monto" }, dinero(d.pago.monto)),
      el("p", { class: "suave chico" }, billetera
        ? `Abonado a tu billetera ligada al ${billetera.celular} (pago simulado del piloto).`
        : "Abonado a tu billetera (pago simulado del piloto)."),
      el("hr"),
      el("dl", {}, filas.map(([dt, dd]) => el("div", {}, el("dt", {}, dt), el("dd", {}, dd)))),
    ));
    avisar(`ReAceite: recibiste ${dinero(d.pago.monto)}`,
      billetera ? `Saldo de tu billetera: ${dinero(billetera.saldo)}` : "Pago por tu aceite usado");
  }

  $("#abrir").addEventListener("click", async () => {
    const boton = $("#abrir");
    boton.disabled = true;
    boton.textContent = "Abriendo…";
    pedirPermisoAvisos();
    mostrarMensaje(mensaje, "");
    try {
      const d = await api(`/api/contenedores/${encodeURIComponent(token)}/depositos`, { metodo: "POST", datos: {} });
      folio = d.folio;
      pintar(d);
      seguir();
    } catch (error) {
      if (revisarSesion(error)) return;
      mostrarMensaje(mensaje, error.message, "error");
      boton.disabled = false;
    } finally {
      boton.textContent = "Abrir compuerta";
    }
  });

  $("#cancelar-deposito").addEventListener("click", async () => {
    if (!folio) return;
    try {
      pintar(await api(`/api/depositos/${encodeURIComponent(folio)}/cancelar`, { metodo: "POST", datos: {} }));
      detener();
    } catch (error) {
      if (revisarSesion(error)) return;
      mostrarMensaje(mensaje, error.message, "error");
    }
  });

  if (folio) seguir();
}

// ---------------------------------------------------------------- equipo: gemelo digital del contenedor
function iniciarGemelo() {
  const VELOCIDAD_G_S = 460;           // un chorro de aceite de una cubeta: ~0.5 kg por segundo
  const estado = { datos: datosJSON("datos-contenedor"), peso: 0, vertiendo: false, tocado: 0, enviando: false };
  estado.peso = estado.datos.peso_g;
  const boton = $("#verter");
  const bote = $("#bote");

  function pintar() {
    const d = estado.datos;
    const dep = d.deposito;
    const neto = dep ? Math.max(0, estado.peso - dep.peso_inicial_g) : 0;
    $("#lcd-peso").textContent = `${kg(estado.peso)} kg`;
    $("#dato-compuerta").textContent = dep ? "Abierta" : "Cerrada";
    $("#dato-deposito").textContent = dep ? `${dep.folio}, ${dep.comercio}` : "Ninguno";
    $("#dato-neto").textContent = dep ? `${kg(neto)} kg` : "–";
    $("#dato-nivel").textContent = `${d.porcentaje} %, ${d.nivel_l} de ${d.capacidad_l} L`;
    const base = Number(d.nivel_l) / d.capacidad_l;
    const extra = neto / GRAMOS_POR_LITRO / d.capacidad_l;
    const total = Math.min(1, base + extra);
    $("#bote-nivel").style.transform = `translateY(${(168 * (1 - total)).toFixed(1)}px)`;
    $("#bote-deposito").setAttribute("height", (168 * Math.min(extra, total)).toFixed(1));
    bote.classList.toggle("bote--abierta", Boolean(dep));
    bote.classList.toggle("bote--vertiendo", estado.vertiendo);
    boton.disabled = !dep;
    $("#cerrar-tapa").disabled = !dep || estado.vertiendo;
    $("#ayuda-gemelo").textContent = dep
      ? `Compuerta abierta para ${dep.comercio}. Mantén presionado «Verter aceite» y luego cierra la tapa.`
      : "Esperando a que un comercio escanee el QR y abra la compuerta.";
    const senal = $("#senal");
    senal.classList.toggle("caido", !d.en_linea);
    senal.textContent = d.en_linea ? "En línea" : "Sin señal";
  }

  function mostrarEnvio(envio) {
    const cuerpo = envio.peticion.cuerpo;
    $("#ultima-senal").textContent = `«${cuerpo.tipo}» → ${envio.respuesta.status} en ${Math.round(envio.latencia_ms)} ms`
      + ` (${envio.transporte === "http" ? "HTTP" : "en proceso"})`;
    const log = $("#log-senal");
    log.hidden = false;
    log.textContent = [
      `${envio.peticion.metodo} ${envio.peticion.url}`,
      ...Object.entries(envio.peticion.cabeceras).map(([k, v]) => `${k}: ${v}`),
      "",
      JSON.stringify(cuerpo, null, 2),
      "",
      `← ${envio.respuesta.status}`,
      JSON.stringify(envio.respuesta.cuerpo, null, 2),
    ].join("\n");
  }

  async function senal(tipo, extra = {}) {
    const envio = await api(`/api/gemelo/${encodeURIComponent(codigo)}/senal`,
      { metodo: "POST", datos: { tipo, peso_g: Math.round(estado.peso), ...extra } });
    mostrarEnvio(envio);
    return envio;
  }

  async function enviarPeso() {
    if (estado.enviando) return;
    estado.enviando = true;
    try {
      await senal("peso");
    } catch (error) {
      mostrarMensaje(mensaje, error.message, "error");
    } finally {
      estado.enviando = false;
    }
  }

  let reloj = null;
  let ultimoEnvio = 0;
  function empezar(e) {
    if (e) e.preventDefault();
    if (!estado.datos.deposito || estado.vertiendo) return;
    estado.vertiendo = true;
    boton.classList.add("activo");
    let previo = performance.now();
    reloj = setInterval(() => {
      const ahora = performance.now();
      estado.peso += VELOCIDAD_G_S * ((ahora - previo) / 1000) * (0.85 + Math.random() * 0.3);
      previo = ahora;
      estado.tocado = Date.now();
      pintar();
      if (ahora - ultimoEnvio > 450) {
        ultimoEnvio = ahora;
        enviarPeso();
      }
    }, 80);
    pintar();
  }
  async function terminar() {
    if (!estado.vertiendo) return;
    clearInterval(reloj);
    estado.vertiendo = false;
    estado.tocado = Date.now();
    boton.classList.remove("activo");
    pintar();
    while (estado.enviando) await new Promise((r) => setTimeout(r, 40));
    await enviarPeso();
  }
  boton.addEventListener("pointerdown", empezar);
  ["pointerup", "pointerleave", "pointercancel"].forEach((t) => boton.addEventListener(t, terminar));
  boton.addEventListener("contextmenu", (e) => e.preventDefault());
  boton.addEventListener("keydown", (e) => { if ((e.key === " " || e.key === "Enter") && !e.repeat) empezar(e); });
  boton.addEventListener("keyup", (e) => { if (e.key === " " || e.key === "Enter") terminar(); });

  $("#cerrar-tapa").addEventListener("click", async () => {
    const dep = estado.datos.deposito;
    if (!dep) return;
    const cerrar = $("#cerrar-tapa");
    cerrar.disabled = true;
    try {
      while (estado.enviando) await new Promise((r) => setTimeout(r, 40));
      const envio = await senal("deposito.cerrado", { deposito: dep.folio });
      const r = envio.respuesta;
      if (r.status === 201) {
        mostrarMensaje(mensaje, `Tapa cerrada: ${kg(r.cuerpo.deposito.peso_neto_g)} kg netos en ${dep.folio}. `
          + `La plataforma ya registró ${r.cuerpo.recoleccion} y está pagando.`, "ok");
      } else if (r.status === 200) {
        mostrarMensaje(mensaje, "Tapa cerrada sin aceite: no se genera pago.", "info");
      } else {
        mostrarMensaje(mensaje, (r.cuerpo && r.cuerpo.mensaje) || `La plataforma respondió ${r.status}.`, "error");
      }
      estado.tocado = 0;
      await refrescar();
    } catch (error) {
      mostrarMensaje(mensaje, error.message, "error");
    }
  });

  $("#vaciar").addEventListener("click", async () => {
    if (!window.confirm(`¿Registrar que vaciaste ${codigo} en el camión? El nivel y la báscula vuelven a cero.`)) return;
    try {
      estado.datos = { ...estado.datos, ...(await api(`/api/contenedores/${encodeURIComponent(codigo)}/vaciar`, { metodo: "POST", datos: {} })) };
      estado.peso = 0;
      estado.tocado = 0;
      pintar();
      mostrarMensaje(mensaje, `${codigo} vaciado.`, "ok");
    } catch (error) {
      mostrarMensaje(mensaje, error.message, "error");
    }
  });

  async function refrescar() {
    const antes = estado.datos.deposito && estado.datos.deposito.folio;
    const d = await api(`/api/gemelo/${encodeURIComponent(codigo)}`);
    estado.datos = d;
    const nuevo = d.deposito && d.deposito.folio !== antes;
    if (nuevo || (!estado.vertiendo && !estado.enviando && Date.now() - estado.tocado > 2500)) estado.peso = d.peso_g;
    if (nuevo) {
      mostrarMensaje(mensaje, `${d.deposito.comercio} escaneó el QR: compuerta abierta para ${d.deposito.folio}.`, "info");
      senal("latido").catch(() => {});   // el contenedor confirma que recibió la orden
    }
    pintar();
  }

  pintar();
  requestAnimationFrame(() => requestAnimationFrame(() => bote.classList.add("bote--listo")));
  senal("latido").then(refrescar).catch(() => {});
  setInterval(() => { if (!estado.vertiendo && !estado.enviando) senal("latido").catch(() => {}); }, 20000);
  sondear(refrescar, 800);
}

if (modo === "comercio") iniciarComercio();
else if (modo === "equipo") iniciarGemelo();
