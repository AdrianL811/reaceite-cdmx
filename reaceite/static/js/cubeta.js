// La cubeta de 20 L: la unidad de medida de la interfaz.
// Muestra cuánto aceite junta la zona; la franja rayada es el aceite de este comercio.

let serie = 0;
const FONDO = 142;
const LLENO = 50;
const ALTO = FONDO - LLENO;

export function crearCubeta(contenedor, { capacidad = 20, mostrarTope = true } = {}) {
  const id = `cb${++serie}`;
  contenedor.classList.add("cubeta");
  const marcas = [0.25, 0.5, 0.75]
    .map((f) => `<line x1="21" x2="29" y1="${FONDO - f * ALTO}" y2="${FONDO - f * ALTO}"/>`)
    .join("");
  contenedor.innerHTML = `
<svg viewBox="0 0 120 150" role="img" aria-labelledby="${id}-t">
  <title id="${id}-t">Cubeta de ${capacidad} litros</title>
  <defs>
    <clipPath id="${id}-c"><path d="M15.5 44 L104.5 44 L94.2 139.6 Q93.7 142 90.8 142 L29.2 142 Q26.3 142 25.8 139.6 Z"/></clipPath>
    <linearGradient id="${id}-g" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#f4b83c"/><stop offset="1" stop-color="#c98705"/>
    </linearGradient>
    <pattern id="${id}-p" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <rect width="7" height="7" fill="#f8d58a"/><rect width="2.6" height="7" fill="#fff1cf"/>
    </pattern>
  </defs>
  <path d="M13 54 C 13 2, 107 2, 107 54" fill="none" stroke="currentColor" stroke-width="3.6" stroke-linecap="round"/>
  <rect x="45" y="9.5" width="30" height="9.5" rx="4.75" fill="currentColor"/>
  <path d="M12 41 L108 41 L97.2 140 Q96.6 145 91.4 145 L28.6 145 Q23.4 145 22.8 140 Z" fill="#fff" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/>
  <g clip-path="url(#${id}-c)">
    <g class="liquido" style="transform: translateY(${ALTO + 6}px)">
      <g class="ola"><path d="M-40 ${LLENO} q10 -3.5 20 0 t20 0 t20 0 t20 0 t20 0 t20 0 t20 0 t20 0 t20 0 t20 0 V 160 H -40 Z" fill="url(#${id}-g)"/></g>
    </g>
    <rect class="propio" x="0" width="120" y="${FONDO}" height="0" fill="url(#${id}-p)"/>
  </g>
  <g stroke="currentColor" stroke-width="1.6" opacity=".5">${marcas}</g>
  ${mostrarTope ? `<line class="marca-tope" x1="16" x2="104" y1="${LLENO}" y2="${LLENO}" stroke="currentColor" stroke-width="2" stroke-dasharray="4 4"/>` : ""}
  <rect x="8" y="34" width="104" height="10" rx="5" fill="#fff" stroke="currentColor" stroke-width="3"/>
  <circle cx="13.2" cy="54" r="4.2" fill="#fff" stroke="currentColor" stroke-width="2.6"/>
  <circle cx="106.8" cy="54" r="4.2" fill="#fff" stroke="currentColor" stroke-width="2.6"/>
</svg>`;
  const titulo = contenedor.querySelector("title");
  const liquido = contenedor.querySelector(".liquido");
  const propio = contenedor.querySelector(".propio");

  function fijar(total, propios = 0) {
    const t = Math.max(0, Math.min(Number(total) || 0, capacidad));
    const superficie = FONDO - (t / capacidad) * ALTO;
    liquido.style.transform = `translateY(${t === 0 ? ALTO + 6 : superficie - LLENO}px)`;
    const p = Math.min(Number(propios) || 0, t);
    if (p > 0) {
      propio.setAttribute("y", String(superficie + 2.5));
      propio.setAttribute("height", String(Math.max(0, (p / capacidad) * ALTO - 2.5)));
    } else {
      propio.setAttribute("height", "0");
    }
    contenedor.classList.toggle("cubeta--llena", Number(total) >= capacidad);
    titulo.textContent = `${Number(total) || 0} de ${capacidad} litros`;
  }
  return { fijar };
}
