// popup.js — estado en vivo + control de grabación desde la extensión.
// Todo contra el agente local (127.0.0.1). Las opciones y el idioma se recuerdan.

const $ = (id) => document.getElementById(id);
const dot = $("dot"), status = $("status"), hint = $("hint");
const options = $("options"), btnStart = $("btnStart"), btnStop = $("btnStop");
const counterBox = $("counterBox"), sent = $("sent");

const OPT_KEYS = ["optLang", "optTarget", "optSmart", "optMic"];
let busy = false;        // evita parpadeo de la UI mientras arranca/para
let lastState = "";      // último estado renderizado (para retraducir en vivo)

// ── i18n del popup (ES/EN, seleccionable y persistente) ─────────────────
const I18N = {
  es: {
    sub:             "100% local · sin servidores externos",
    checking:        "Comprobando…",
    statusRecording: "Grabando sesión",
    hintRecording:   "Tus acciones se están documentando.",
    statusIdle:      "Agente conectado",
    hintIdle:        "Configura y empieza a grabar desde aquí.",
    statusOffline:   "FullQA.ai no detectado",
    hintOffline:     "Abre la app de escritorio FullQA.ai.",
    optionsTitle:    "Opciones de grabación",
    optLang:         "Idioma de la documentación",
    optTarget:       "Capturar",
    targetActive:    "Monitor activo",
    targetAll:       "Toda la pantalla",
    optSmart:        "Captura inteligente (IA local)",
    optMic:          "Grabar micrófono",
    btnStart:        "● Iniciar grabación",
    btnStarting:     "Iniciando… (cuenta atrás de 3 s)",
    btnStop:         "■ Detener grabación",
    events:          "eventos capturados",
    footer:          "Passwords jamás · todo queda en tu máquina",
  },
  en: {
    sub:             "100% local · no external servers",
    checking:        "Checking…",
    statusRecording: "Recording session",
    hintRecording:   "Your actions are being documented.",
    statusIdle:      "Agent connected",
    hintIdle:        "Set up and start recording from here.",
    statusOffline:   "FullQA.ai not detected",
    hintOffline:     "Open the FullQA.ai desktop app.",
    optionsTitle:    "Recording options",
    optLang:         "Documentation language",
    optTarget:       "Capture",
    targetActive:    "Active monitor",
    targetAll:       "Whole screen",
    optSmart:        "Smart capture (local AI)",
    optMic:          "Record microphone",
    btnStart:        "● Start recording",
    btnStarting:     "Starting… (3 s countdown)",
    btnStop:         "■ Stop recording",
    events:          "events captured",
    footer:          "Never passwords · everything stays on your machine",
  },
};
let uiLang = "es";
const t = (k) => (I18N[uiLang] && I18N[uiLang][k]) || I18N.es[k] || k;

function applyI18n() {
  document.documentElement.lang = uiLang;
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll(".lang-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.lang === uiLang);
  });
  if (!busy) btnStart.textContent = t("btnStart");
  btnStop.textContent = t("btnStop");
  if (lastState) render(lastState);
  else status.textContent = t("checking");
}

async function loadLang() {
  try {
    const { qaUiLang } = await chrome.storage.local.get("qaUiLang");
    if (qaUiLang && I18N[qaUiLang]) {
      uiLang = qaUiLang;
      return;
    }
  } catch (_) {}
  try {
    const nav = (chrome.i18n.getUILanguage() || "es").toLowerCase();
    uiLang = nav.startsWith("es") ? "es" : "en";
  } catch (_) {}
}

document.querySelectorAll(".lang-btn").forEach((b) => {
  b.addEventListener("click", async () => {
    uiLang = b.dataset.lang;
    try { await chrome.storage.local.set({ qaUiLang: uiLang }); } catch (_) {}
    applyI18n();
  });
});

// ── persistencia de opciones ────────────────────────────────────────────
async function loadOptions() {
  try {
    const saved = await chrome.storage.local.get("qaOpts");
    const o = saved.qaOpts || {};
    if (o.lang) $("optLang").value = o.lang;
    if (o.target) $("optTarget").value = o.target;
    $("optSmart").checked = !!o.smart;
    $("optMic").checked = !!o.mic;
  } catch (_) {}
}

function currentOptions() {
  return {
    lang: $("optLang").value,
    target: $("optTarget").value,
    smart: $("optSmart").checked,
    mic: $("optMic").checked,
  };
}

async function saveOptions() {
  try { await chrome.storage.local.set({ qaOpts: currentOptions() }); } catch (_) {}
}
OPT_KEYS.forEach((k) => $(k).addEventListener("change", saveOptions));

// ── render de estados ───────────────────────────────────────────────────
function render(state) {
  lastState = state;
  options.classList.add("hidden");
  btnStart.classList.add("hidden");
  btnStop.classList.add("hidden");
  counterBox.classList.add("hidden");
  if (state === "recording") {
    dot.className = "dot rec";
    status.textContent = t("statusRecording");
    hint.textContent = t("hintRecording");
    counterBox.classList.remove("hidden");
    btnStop.classList.remove("hidden");
  } else if (state === "idle") {
    dot.className = "dot ok";
    status.textContent = t("statusIdle");
    hint.textContent = t("hintIdle");
    options.classList.remove("hidden");
    btnStart.classList.remove("hidden");
  } else {
    dot.className = "dot bad";
    status.textContent = t("statusOffline");
    hint.textContent = t("hintOffline");
  }
}

// ── estado del agente ───────────────────────────────────────────────────
async function ping() {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 1500);
  try {
    const r = await fetch("http://127.0.0.1:8765/ping", { signal: ctrl.signal });
    return await r.json();
  } finally {
    clearTimeout(timer);
  }
}

async function refresh() {
  try {
    const { qaSent = 0 } = await chrome.storage.session.get("qaSent");
    sent.textContent = String(qaSent);
  } catch (_) {}
  if (busy) return;
  try {
    const data = await ping();
    render(data.recording ? "recording" : "idle");
  } catch (_) {
    render("offline");
  }
}

// ── control ─────────────────────────────────────────────────────────────
async function control(body) {
  const r = await fetch("http://127.0.0.1:8765/control", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return r.json();
}

btnStart.addEventListener("click", async () => {
  busy = true;
  btnStart.disabled = true;
  btnStart.textContent = t("btnStarting");
  try {
    await saveOptions();
    await control({ action: "start", options: currentOptions() });
    try { await chrome.storage.session.set({ qaSent: 0 }); } catch (_) {}
    try { chrome.action.setBadgeText({ text: "" }); } catch (_) {}
    // la grabación empieza tras la cuenta atrás de la app (3 s)
    setTimeout(() => { busy = false; btnStart.disabled = false;
                       btnStart.textContent = t("btnStart"); refresh(); }, 4200);
  } catch (_) {
    busy = false;
    btnStart.disabled = false;
    btnStart.textContent = t("btnStart");
    render("offline");
  }
});

btnStop.addEventListener("click", async () => {
  busy = true;
  btnStop.disabled = true;
  try {
    await control({ action: "stop" });
  } catch (_) {}
  setTimeout(() => { busy = false; btnStop.disabled = false; refresh(); }, 800);
});

(async () => {
  await loadLang();
  applyI18n();
  await loadOptions();
  refresh();
  setInterval(refresh, 2000);
})();
