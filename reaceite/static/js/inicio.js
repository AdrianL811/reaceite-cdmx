import { $, miComercio } from "./comun.js";
import { crearCubeta } from "./cubeta.js";

crearCubeta($("#cubeta-portada"), { mostrarTope: false }).fijar(13);

const mio = miComercio.leer();
if (mio && mio.token) {
  const enlace = $("#mi-comercio");
  enlace.href = `/c/${encodeURIComponent(mio.token)}`;
  enlace.textContent = `Abrir mi comercio: ${mio.nombre}`;
  enlace.hidden = false;
}
