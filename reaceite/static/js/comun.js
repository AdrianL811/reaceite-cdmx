// Utilidades compartidas por todas las pantallas.

export class ErrorApi extends Error {
  constructor(mensaje, status, codigo, datos) {
    super(mensaje);
    this.status = status;
    this.codigo = codigo;
    this.datos = datos || {};
  }
}

export async function api(ruta, { metodo = "GET", datos } = {}) {
  const opciones = { method: metodo, headers: { Accept: "application/json" }, credentials: "same-origin" };
  if (metodo !== "GET") opciones.headers["X-ReAceite"] = "1";
  if (datos !== undefined) {
    opciones.headers["Content-Type"] = "application/json";
    opciones.body = JSON.stringify(datos);
  }
  let respuesta;
  try {
    respuesta = await fetch(ruta, opciones);
  } catch {
    throw new ErrorApi("No hay conexión. Revisa tus datos móviles o el wifi.", 0, "red");
  }
  let cuerpo = null;
  try {
    cuerpo = await respuesta.json();
  } catch {
    cuerpo = null;
  }
  if (!respuesta.ok) {
    throw new ErrorApi((cuerpo && cuerpo.mensaje) || `El servidor respondió ${respuesta.status}.`,
      respuesta.status, cuerpo && cuerpo.error, cuerpo);
  }
  return cuerpo;
}

const formatoNumero = new Intl.NumberFormat("es-MX");
const formatoDinero = new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN" });
const formatoLitros = new Intl.NumberFormat("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const formatoHora = new Intl.DateTimeFormat("es-MX", { hour: "2-digit", minute: "2-digit", timeZone: "America/Mexico_City" });
const formatoHoraSeg = new Intl.DateTimeFormat("es-MX", { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23", timeZone: "America/Mexico_City" });
const formatoFecha = new Intl.DateTimeFormat("es-MX", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "America/Mexico_City" });

export const miles = (n) => formatoNumero.format(Number(n));
export const dinero = (n) => formatoDinero.format(Number(n));
export const litros = (n) => `${formatoLitros.format(Number(n))} L`;
export const hora = (iso) => formatoHora.format(new Date(iso));
export const horaSeg = (iso) => formatoHoraSeg.format(new Date(iso));
export const fecha = (iso) => formatoFecha.format(new Date(iso));

export function hace(iso) {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 50) return "hace un momento";
  const m = Math.round(s / 60);
  if (m < 60) return `hace ${m} min`;
  const h = Math.round(m / 60);
  if (h < 24) return `hace ${h} h`;
  return `hace ${Math.round(h / 24)} d`;
}

// Construye nodos del DOM sin innerHTML: los datos de usuarios nunca se interpretan como HTML.
export function el(etiqueta, atributos = {}, ...hijos) {
  const nodo = document.createElement(etiqueta);
  for (const [clave, valor] of Object.entries(atributos || {})) {
    if (valor === null || valor === undefined || valor === false) continue;
    if (clave === "class") nodo.className = valor;
    else if (clave === "dataset") Object.assign(nodo.dataset, valor);
    else if (clave.startsWith("on") && typeof valor === "function") nodo.addEventListener(clave.slice(2), valor);
    else nodo.setAttribute(clave, valor === true ? "" : String(valor));
  }
  for (const hijo of hijos.flat(Infinity)) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    nodo.append(hijo instanceof Node ? hijo : document.createTextNode(String(hijo)));
  }
  return nodo;
}

export const $ = (selector, raiz = document) => raiz.querySelector(selector);
export const $$ = (selector, raiz = document) => [...raiz.querySelectorAll(selector)];

export function mostrarMensaje(contenedor, texto, tipo = "info") {
  contenedor.replaceChildren();
  if (!texto) {
    contenedor.hidden = true;
    return;
  }
  contenedor.hidden = false;
  contenedor.append(el("div", { class: `mensaje mensaje--${tipo}`, role: tipo === "error" ? "alert" : "status" }, texto));
}

// Consulta periódica que se frena cuando la pestaña está oculta y espera más si el servidor falla.
export function sondear(funcion, intervalo) {
  let temporizador = null;
  let activo = true;
  let enCurso = false;
  let fallos = 0;
  const ciclo = async () => {
    if (!activo || enCurso) return;
    enCurso = true;
    clearTimeout(temporizador);
    try {
      await funcion();
      fallos = 0;
    } catch (error) {
      fallos += 1;
      console.warn(error);
    } finally {
      enCurso = false;
    }
    if (!activo) return;
    const base = typeof intervalo === "function" ? intervalo() : intervalo;
    const espera = document.hidden ? base * 4 : Math.min(base * (1 + fallos), 15000);
    temporizador = setTimeout(ciclo, espera);
  };
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) ciclo();
  });
  ciclo();
  return {
    detener() { activo = false; clearTimeout(temporizador); },
    ahora() { ciclo(); },
  };
}

export const miComercio = {
  leer() {
    try { return JSON.parse(localStorage.getItem("reaceite.comercio")); } catch { return null; }
  },
  guardar(c) {
    try {
      localStorage.setItem("reaceite.comercio", JSON.stringify({ token: c.token, nombre: c.nombre, codigo: c.codigo }));
    } catch { /* almacenamiento no disponible */ }
  },
};

export function datosJSON(id) {
  const nodo = document.getElementById(id);
  return nodo ? JSON.parse(nodo.textContent) : null;
}

// Redondeo comercial con enteros: igual que Decimal ROUND_HALF_UP del servidor.
export const redondear = (numerador, denominador) => Math.floor((2 * numerador + denominador) / (2 * denominador));

// Métricas Verdes en el navegador, con la misma aritmética exacta que el servidor.
export function metricas(pesoKg, p) {
  const gramos = Math.round(Number(String(pesoKg).replace(",", ".")) * 1000);
  if (!Number.isFinite(gramos) || gramos < 50 || gramos > 100000) return null;
  const densidadG = Math.round(Number(p.densidad) * 1000);             // 920 g por litro
  const precioCent = Math.round(Number(p.precio_litro) * 100);         // 600
  const comisionPb = Math.round(Number(p.comision) * 10000);           // 1000 = 10 %
  const litrosCl = redondear(gramos * 100, densidadG);
  const aguaL = redondear(litrosCl * Math.round(Number(p.agua_por_litro)), 100);
  const bioCl = redondear(litrosCl * Math.round(Number(p.biocombustible_por_litro) * 100), 100);
  const brutoCent = redondear(litrosCl * precioCent, 100);
  const comisionCent = redondear(brutoCent * comisionPb, 10000);
  return {
    gramos, litrosCl, aguaL, bioCl, brutoCent, comisionCent, netoCent: brutoCent - comisionCent,
  };
}

// Service worker (PWA instalable) y aviso de conexión.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
  });
}
const avisoRed = document.getElementById("aviso-red");
const actualizarRed = () => { if (avisoRed) avisoRed.hidden = navigator.onLine; };
window.addEventListener("online", actualizarRed);
window.addEventListener("offline", actualizarRed);
actualizarRed();
