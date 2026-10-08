// Escáner de QR dentro de la app: así el recolector no depende de la cámara del sistema
// ni de que el navegador que abre el enlace tenga su sesión iniciada.
import { el } from "./comun.js";

let cargaJsQR = null;

function cargarJsQR() {
  if (window.jsQR) return Promise.resolve();
  if (!cargaJsQR) {
    cargaJsQR = new Promise((resolver, rechazar) => {
      const script = document.createElement("script");
      script.src = "/static/vendor/jsQR.js";
      script.onload = resolver;
      script.onerror = rechazar;
      document.head.append(script);
    });
  }
  return cargaJsQR;
}

async function crearDetector() {
  if (!("BarcodeDetector" in window)) return null;
  try {
    const formatos = await window.BarcodeDetector.getSupportedFormats();
    return formatos.includes("qr_code") ? new window.BarcodeDetector({ formats: ["qr_code"] }) : null;
  } catch {
    return null;
  }
}

// Extrae el token de un QR de ReAceite (https://.../c/TOKEN) o de un código escrito a mano.
export function leerCodigo(texto) {
  const limpio = String(texto || "").trim();
  const enlace = limpio.match(/\/c\/([0-9A-Za-z]{6,12})(?:[/?#]|$)/);
  if (enlace) return { token: enlace[1].toUpperCase() };
  const codigo = limpio.toUpperCase().match(/^COM-?(\d{1,4})$/);
  if (codigo) return { codigo: `COM-${codigo[1].padStart(4, "0")}` };
  if (/^[0-9A-Za-z]{6,12}$/.test(limpio)) return { token: limpio.toUpperCase() };
  return null;
}

export async function abrirEscaner(alLeer) {
  const video = el("video", { muted: true, playsinline: true, autoplay: true });
  video.muted = true;
  const aviso = el("p", { role: "status" }, "Apunta la cámara al QR del bote.");
  const campo = el("input", { type: "text", placeholder: "Código del sticker, por ejemplo COM-0006", "aria-label": "Código del sticker", autocomplete: "off" });
  let activo = true;
  let flujo = null;

  const cerrar = () => {
    activo = false;
    if (flujo) flujo.getTracks().forEach((pista) => pista.stop());
    capa.remove();
    document.removeEventListener("keydown", alTeclear);
  };
  const entregar = (texto) => {
    const resultado = leerCodigo(texto);
    if (!resultado) {
      aviso.textContent = "Ese código no es de ReAceite. Intenta de nuevo.";
      return false;
    }
    cerrar();
    alLeer(resultado, texto);
    return true;
  };
  const alTeclear = (e) => { if (e.key === "Escape") cerrar(); };

  const capa = el("div", { class: "escaner", role: "dialog", "aria-modal": "true", "aria-label": "Escanear el QR del bote" },
    el("div", { class: "escaner__cabeza" },
      el("button", { class: "boton boton--chico", type: "button", onclick: cerrar }, "Cerrar"),
    ),
    el("div", { class: "escaner__visor" }, video, el("div", { class: "escaner__marco", "aria-hidden": "true" })),
    el("div", { class: "escaner__pie" },
      aviso,
      el("form", { onsubmit: (e) => { e.preventDefault(); entregar(campo.value); } },
        campo,
        el("button", { class: "boton boton--chico", type: "submit" }, "Abrir"),
      ),
    ),
  );
  document.body.append(capa);
  document.addEventListener("keydown", alTeclear);

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    aviso.textContent = "Este navegador no permite usar la cámara aquí. Escribe el código del sticker.";
    return;
  }
  try {
    flujo = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
  } catch {
    aviso.textContent = "No pudimos abrir la cámara. Revisa el permiso o escribe el código del sticker.";
    return;
  }
  if (!activo) {
    flujo.getTracks().forEach((pista) => pista.stop());
    return;
  }
  video.srcObject = flujo;
  try { await video.play(); } catch { /* algunos navegadores reproducen solos */ }

  const detector = await crearDetector();
  if (!detector) {
    try { await cargarJsQR(); } catch { aviso.textContent = "No se pudo cargar el lector de QR. Escribe el código."; return; }
  }
  const lienzo = document.createElement("canvas");
  const contexto = lienzo.getContext("2d", { willReadFrequently: true });

  const paso = async () => {
    if (!activo) return;
    if (video.readyState >= 2 && video.videoWidth) {
      let texto = null;
      if (detector) {
        try {
          const codigos = await detector.detect(video);
          if (codigos.length) texto = codigos[0].rawValue;
        } catch { /* cuadro ilegible */ }
      } else {
        const escala = Math.min(1, 720 / Math.max(video.videoWidth, video.videoHeight));
        lienzo.width = Math.round(video.videoWidth * escala);
        lienzo.height = Math.round(video.videoHeight * escala);
        contexto.drawImage(video, 0, 0, lienzo.width, lienzo.height);
        const imagen = contexto.getImageData(0, 0, lienzo.width, lienzo.height);
        const codigo = window.jsQR(imagen.data, imagen.width, imagen.height, { inversionAttempts: "dontInvert" });
        if (codigo && codigo.data) texto = codigo.data;
      }
      if (texto && entregar(texto)) {
        if (navigator.vibrate) navigator.vibrate(60);
        return;
      }
    }
    setTimeout(paso, 120);
  };
  paso();
}
