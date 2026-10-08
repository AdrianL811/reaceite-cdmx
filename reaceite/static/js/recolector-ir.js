import { api } from "./comun.js";

// Lleva al recolector a la pantalla de pesaje a partir de un QR leído o un código escrito.
export async function irAPesaje(resultado) {
  let token = resultado.token;
  if (!token && resultado.codigo) {
    const r = await api(`/api/buscar?codigo=${encodeURIComponent(resultado.codigo)}`);
    token = r.token;
  }
  window.location.href = `/r/pesar/${encodeURIComponent(token)}`;
}
