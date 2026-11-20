import { api } from "./comun.js";

// Lleva al recolector a la pantalla de pesaje a partir de un QR leído o un código escrito.
export async function irAPesaje(resultado) {
  // El QR de un contenedor lleva a su gemelo digital (vaciado y estado).
  if (resultado.contenedor) {
    window.location.href = `/k/${encodeURIComponent(resultado.contenedor)}`;
    return;
  }
  if (resultado.contenedorCodigo) {
    window.location.href = `/contenedor/${encodeURIComponent(resultado.contenedorCodigo)}`;
    return;
  }
  let token = resultado.token;
  if (!token && resultado.codigo) {
    const r = await api(`/api/buscar?codigo=${encodeURIComponent(resultado.codigo)}`);
    token = r.token;
  }
  window.location.href = `/r/pesar/${encodeURIComponent(token)}`;
}
