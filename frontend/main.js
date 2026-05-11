const app = document.querySelector("#app");
const tokenKey = "playup-token";
const installedKey = "playup-installed";
const apiBaseUrl = resolveApiBaseUrl();
const maintenanceMode = resolveMaintenanceMode();

let token = localStorage.getItem(tokenKey);
let deferredInstallPrompt = null;
let state = {
  view: "home",
  boot: null,
  cache: {},
  authMode: "login",
  feedback: null,
  avatarFilter: "ropa",
  onboardingStep: 0,
  registrationDraft: {},
  firstMatchDraft: false,
  tutorialOpen: false,
  tutorialStep: 0,
  installAvailable: false,
  pwaInstalled: false,
  betaFeedbackOpen: false,
  betaFeedbackType: "feedback",
  backendAwake: false,
  backendWaking: false,
};

function resolveApiBaseUrl() {
  const raw =
    window.PLAYUP_CONFIG?.API_BASE_URL ||
    document.querySelector("meta[name='playup-api-base-url']")?.content ||
    localStorage.getItem("playup-api-base-url") ||
    "";
  return String(raw || "").replace(/\/+$/, "");
}

function resolveMaintenanceMode() {
  const raw =
    window.PLAYUP_CONFIG?.MAINTENANCE_MODE ??
    document.querySelector("meta[name='playup-maintenance-mode']")?.content ??
    localStorage.getItem("playup-maintenance-mode") ??
    "false";
  return ["1", "true", "yes", "on"].includes(String(raw).toLowerCase());
}

function apiUrl(path) {
  if (/^https?:\/\//i.test(path)) return path;
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return apiBaseUrl ? `${apiBaseUrl}${normalizedPath}` : normalizedPath;
}

function isNativeApp() {
  return Boolean(window.Capacitor?.isNativePlatform?.());
}

const onboardingScreens = [
  ["Registro rapido", "Email y nombre para crear tu cuenta."],
  ["Identidad competitiva", "Elige genero y avatar base para tu Player Card."],
  ["Nivel y disponibilidad", "Ciudad, nivel y horarios basicos para encontrar partido."],
  ["Asi funciona PlayUp Padel", "Juegas partidos 2v2, ganas puntos individuales y subes o bajas cada mes."],
];

const tutorialSteps = [
  {
    target: "[data-tour='home-status']",
    title: "Tu posicion y objetivo",
    body: "Aqui ves tu posicion y lo que necesitas para ascender.",
  },
  {
    target: "[data-tour='play-button']",
    title: "Jugar tu primer partido",
    body: "Pulsa aqui para jugar tu primer partido o crear uno rapido 2v2.",
  },
  {
    target: "[data-tour='ranking']",
    title: "Tu ranking",
    body: "Aqui compites contra otros jugadores de tu grupo.",
  },
  {
    target: "[data-tour='avatar-progress']",
    title: "Avatar y XP",
    body: "Gana XP para desbloquear mejoras visuales.",
  },
];

const views = [
  ["home", "Inicio"],
  ["beta", "Beta cerrada"],
  ["my-league", "Mi Liga"],
  ["matches", "Partidos"],
  ["challenges", "Retos"],
  ["leaderboard", "Ranking"],
  ["progress", "Progresion"],
  ["avatar", "Avatar"],
  ["achievements", "Logros"],
  ["notifications", "Notificaciones"],
  ["profile", "Perfil"],
  ["privacy", "Privacidad"],
  ["terms", "Términos"],
  ["support", "Soporte"],
  ["playtomic", "Playtomic"],
  ["admin", "Admin"],
];

function setupPwa() {
  state.pwaInstalled = isStandaloneMode() || localStorage.getItem(installedKey) === "1";
  if ("serviceWorker" in navigator && !isNativeApp()) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/service-worker.js").catch(() => {});
    });
  }
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredInstallPrompt = event;
    state.installAvailable = !state.pwaInstalled;
    renderPwaInstallPrompt();
  });
  window.addEventListener("appinstalled", () => {
    localStorage.setItem(installedKey, "1");
    deferredInstallPrompt = null;
    state.installAvailable = false;
    state.pwaInstalled = true;
    renderPwaInstallPrompt();
  });
}

function isStandaloneMode() {
  return window.matchMedia?.("(display-mode: standalone)")?.matches || window.navigator.standalone === true;
}

function isIosSafari() {
  const agent = window.navigator.userAgent || "";
  const isiOS = /iphone|ipad|ipod/i.test(agent);
  const isSafari = /safari/i.test(agent) && !/crios|fxios|edgios|opr/i.test(agent);
  return isiOS && isSafari && !isStandaloneMode();
}

async function api(path, options = {}) {
  if (maintenanceMode && path !== "/api/error-logs") {
    throw new Error("PlayUp Padel está en mantenimiento temporal. Volvemos en breve.");
  }
  if (path !== "/api/status") await ensureBackendReady();
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  try {
    const method = (options.method || "GET").toUpperCase();
    const response = await fetchWithWakeRetry(apiUrl(path), { ...options, method, headers }, { retry: method === "GET" });
    const contentType = response.headers.get("Content-Type") || "";
    const data = contentType.includes("application/json") ? await response.json() : { error: await response.text() };
    if (!response.ok || data.error) throw new Error(data.error || "Error de API");
    return data;
  } catch (error) {
    if (error instanceof TypeError || error.name === "AbortError") {
      throw new Error("No se puede conectar con el servidor de PlayUp Padel. Si Render Free estaba dormido, inténtalo de nuevo en unos segundos.");
    }
    throw error;
  }
}

async function ensureBackendReady() {
  if (!apiBaseUrl || state.backendAwake) return;
  showBackendWakeNotice("Conectando con PlayUp Padel...");
  try {
    await api("/api/status");
    state.backendAwake = true;
  } finally {
    hideBackendWakeNotice();
  }
}

async function fetchWithWakeRetry(url, options = {}, config = {}) {
  const maxAttempts = config.retry ? 4 : 1;
  let lastError = null;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), attempt === 1 ? 12000 : 18000);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal });
      window.clearTimeout(timeout);
      if ([502, 503, 504].includes(response.status) && attempt < maxAttempts) {
        showBackendWakeNotice("Render está despertando el servidor...");
        await sleep(2500 * attempt);
        continue;
      }
      return response;
    } catch (error) {
      window.clearTimeout(timeout);
      lastError = error;
      if (attempt >= maxAttempts) break;
      showBackendWakeNotice(error.name === "AbortError" ? "El servidor está arrancando..." : "Reintentando conexión...");
      await sleep(2500 * attempt);
    }
  }
  throw lastError || new TypeError("No se pudo conectar.");
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function showBackendWakeNotice(message) {
  state.backendWaking = true;
  let notice = document.querySelector(".server-wake-notice");
  if (!notice) {
    notice = document.createElement("div");
    notice.className = "server-wake-notice";
    document.body.appendChild(notice);
  }
  notice.innerHTML = `<strong>Conectando con el servidor</strong><span>${escapeHtml(message)} Si Render Free estaba dormido puede tardar unos segundos.</span>`;
}

function hideBackendWakeNotice() {
  state.backendWaking = false;
  document.querySelector(".server-wake-notice")?.remove();
}

function reportFrontendError(type, message, stackTrace = "") {
  fetch(apiUrl("/api/error-logs"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify({
      type,
      message: String(message || "Error frontend"),
      stack_trace: String(stackTrace || ""),
      url: location.href,
    }),
  }).catch(() => {});
}

window.addEventListener("error", (event) => {
  reportFrontendError("frontend_error", event.message, event.error?.stack || "");
});

window.addEventListener("unhandledrejection", (event) => {
  reportFrontendError("frontend_error", event.reason?.message || event.reason, event.reason?.stack || "");
});

async function boot() {
  if (maintenanceMode) {
    renderMaintenance();
    return;
  }
  if (location.pathname.startsWith("/invite/")) {
    await renderInvitationPage(location.pathname.split("/").pop());
    return;
  }
  if (!token) {
    renderAuth();
    return;
  }
  try {
    state.boot = await api("/api/bootstrap");
    prepareGuidedTutorial();
    renderShell();
    await loadView();
  } catch (error) {
    localStorage.removeItem(tokenKey);
    token = null;
    renderAuth(error.message);
  }
}

function renderMaintenance() {
  app.innerHTML = `
    <main class="legal-page public-legal">
      <section class="panel maintenance-panel">
        <img class="standalone-logo" src="/assets/playup-logo.png" alt="PlayUp Padel" />
        <span class="eyebrow">Mantenimiento</span>
        <h1>PlayUp Padel está actualizándose</h1>
        <p>Estamos preparando una mejora. Vuelve a intentarlo en unos minutos.</p>
        <button class="btn" onclick="location.reload()">Reintentar</button>
      </section>
    </main>
  `;
}

async function renderInvitationPage(inviteToken, error = "") {
  try {
    const data = await api(`/api/invitations/${inviteToken}`);
    const invitation = data.invitation;
    app.innerHTML = `
      <main class="auth invite-page">
        <section class="auth-visual">
          <div>
            <div class="eyebrow">Invitacion PlayUp Padel</div>
            <h1>${escapeHtml(invitation.inviter_name)} ha registrado un partido contigo en PlayUp Padel</h1>
            <p>Unete para confirmar el partido y entrar en la liga. Si los cuatro jugadores se registran, el partido libre se convierte en oficial.</p>
          </div>
          <img class="auth-logo" src="/assets/playup-logo.png" alt="PlayUp Padel" />
          <div class="chips">
            <span>${escapeHtml(invitation.external_player_name)}</span>
            <span>${escapeHtml(invitation.score)} · ${escapeHtml(invitation.played_on)}</span>
          </div>
        </section>
        <section class="auth-card">
          <div class="onboarding-card compact">
            <span>Entrar en PlayUp Padel</span>
            <h2>Únete para confirmar el partido</h2>
            <p>Te daremos XP de bienvenida y vincularemos tu perfil con este partido.</p>
          </div>
          ${error ? `<p class="notice danger">${error}</p>` : ""}
          <form id="inviteRegisterForm" class="form">
            <label>Nombre<input name="display_name" value="${escapeHtml(invitation.external_player_name)}" required /></label>
            <label>Email<input name="email" type="email" required /></label>
            <label>Password<input name="password" type="password" required /></label>
            <label>Genero<select name="gender" required>
              <option value="">Elige una opcion</option>
              <option value="male">Hombre</option>
              <option value="female">Mujer</option>
            </select></label>
            <label>Nivel aproximado${quickLevelSelect()}</label>
            <label>Ciudad${citySelect(invitation.city || "Madrid")}</label>
            <label>Disponibilidad inicial<input name="availability_text" placeholder="Ej: tardes, fines de semana" required /></label>
            <label class="check-row"><input name="available_for_play" type="checkbox" checked /> Disponible para jugar</label>
            <button class="btn" type="submit">Unirme a PlayUp Padel</button>
          </form>
        </section>
      </main>
    `;
    document.querySelector("#inviteRegisterForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const created = await api(`/api/invitations/${inviteToken}/register`, {
          method: "POST",
          body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))),
        });
        token = created.token;
        localStorage.setItem(tokenKey, token);
        history.replaceState({}, "", "/");
        state.feedback = {
          type: "challenge_reward",
          title: created.official_match_id ? "Partido convertido en oficial" : "Invitacion aceptada",
          message: created.official_match_id ? "Ya sois cuatro jugadores registrados. El partido entra en la liga." : "Tu perfil queda vinculado al partido libre.",
          xp_gained: 100,
          reward_item: "Bienvenida",
          achievement: "Nuevo jugador",
          ranking_label: created.official_match_id ? "Partido oficial" : "Vinculado parcialmente",
        };
        await boot();
      } catch (submitError) {
        await renderInvitationPage(inviteToken, submitError.message);
      }
    });
  } catch (loadError) {
    app.innerHTML = `<main class="auth"><section class="auth-card"><p class="notice danger">${escapeHtml(loadError.message)}</p><button class="btn" onclick="location.href='/'">Ir a PlayUp Padel</button></section></main>`;
  }
}

function renderAuth(error = "") {
  app.innerHTML = `
      <main class="auth">
      <section class="auth-visual">
        <div>
          <div class="beta-badge">Beta cerrada gratuita</div>
          <div class="eyebrow">PlayUp Padel</div>
          <h1>Competicion mensual por parejas, ascensos reales y progresion tipo videojuego.</h1>
          <p>Empieza en 3a Local, juega partidos 2v2 validos, sube rating, gana XP y persigue el ascenso.</p>
        </div>
        <img class="auth-logo" src="/assets/playup-logo.png" alt="PlayUp Padel" />
        <div class="chips">
          <span>Jugador: aitor.martin@demo.playup / demo123</span>
          <span>Admin: admin@playup.local / admin123</span>
        </div>
      </section>
      <section class="auth-card">
        <div class="tabs">
          <button class="${state.authMode === "login" ? "active" : ""}" data-auth="login">Entrar</button>
          <button class="${state.authMode === "register" ? "active" : ""}" data-auth="register">Registro</button>
        </div>
        ${error ? `<p class="notice danger">${error}</p>` : ""}
        ${state.authMode === "login" ? loginForm() : registerForm()}
        <div class="legal-links">
          <button type="button" data-legal-page="privacy">Privacidad</button>
          <button type="button" data-legal-page="terms">Términos</button>
          <button type="button" data-legal-page="support">Soporte</button>
        </div>
        ${isIosSafari() ? `<p class="ios-install-hint">Para instalar en iPhone: abre Safari, pulsa Compartir y elige “Añadir a pantalla de inicio”.</p>` : ""}
      </section>
    </main>
  `;
  document.querySelectorAll("[data-auth]").forEach((button) => {
    button.addEventListener("click", () => {
      state.authMode = button.dataset.auth;
      state.onboardingStep = 0;
      state.registrationDraft = {};
      renderAuth();
    });
  });
  document.querySelectorAll("[data-onboarding-back]").forEach((button) => {
    button.addEventListener("click", () => {
      state.onboardingStep = Math.max(0, state.onboardingStep - 1);
      renderAuth();
    });
  });
  document.querySelector("#loginForm")?.addEventListener("submit", submitLogin);
  document.querySelector("#registerStepForm")?.addEventListener("submit", submitRegisterStep);
  document.querySelector("[data-register-submit]")?.addEventListener("click", submitRegisterDraft);
  document.querySelectorAll("[data-legal-page]").forEach((button) => {
    button.addEventListener("click", () => renderLegalPage(button.dataset.legalPage));
  });
  bindPwaInstallEvents();
}

function renderLegalPage(page) {
  app.innerHTML = `
    <main class="legal-page public-legal">
      <section class="panel">
        ${legalContent(page)}
        <button class="btn secondary" data-back-auth>Volver</button>
      </section>
    </main>
  `;
  document.querySelector("[data-back-auth]").addEventListener("click", () => renderAuth());
}

function loginForm() {
  return `
    <form id="loginForm" class="form">
      <label>Email<input name="email" type="email" value="aitor.martin@demo.playup" required /></label>
      <label>Password<input name="password" type="password" value="demo123" required /></label>
      <button class="btn" type="submit">Entrar</button>
    </form>
  `;
}

function registerForm() {
  const [title, description] = onboardingScreens[Math.min(state.onboardingStep, onboardingScreens.length - 1)];
  if (state.onboardingStep === 0) {
    return `
      <form id="registerStepForm" class="form">
        <div class="onboarding-card compact">
          <span>Paso 1/4</span>
          <h2>${title}</h2>
          <p>${description}</p>
          <div class="onboarding-dots">${onboardingScreens.map((_, index) => `<i class="${index === state.onboardingStep ? "active" : ""}"></i>`).join("")}</div>
        </div>
        <div class="social-auth-row">
          <button class="btn secondary" type="button" disabled>Google</button>
          <button class="btn secondary" type="button" disabled>Apple</button>
        </div>
        <label>Nombre<input name="display_name" value="${escapeHtml(state.registrationDraft.display_name || "")}" required /></label>
        <label>Email<input name="email" type="email" value="${escapeHtml(state.registrationDraft.email || "")}" required /></label>
        <label>Password<input name="password" type="password" value="${escapeHtml(state.registrationDraft.password || "")}" required /></label>
        <button class="btn" type="submit">Continuar</button>
      </form>
    `;
  }
  if (state.onboardingStep === 1) {
    return `
      <form id="registerStepForm" class="form">
        <div class="onboarding-card compact">
          <span>Paso 2/4</span>
          <h2>${title}</h2>
          <p>${description}</p>
          <div class="onboarding-dots">${onboardingScreens.map((_, index) => `<i class="${index === state.onboardingStep ? "active" : ""}"></i>`).join("")}</div>
        </div>
        <div class="gender-choice">
          <label class="${state.registrationDraft.gender === "male" ? "selected" : ""}">
            <input type="radio" name="gender" value="male" required ${state.registrationDraft.gender === "male" ? "checked" : ""} />
            <img src="/assets/avatars/male_base.png" alt="" />
            <strong>Hombre</strong>
            <span>Avatar masculino base</span>
          </label>
          <label class="${state.registrationDraft.gender === "female" ? "selected" : ""}">
            <input type="radio" name="gender" value="female" required ${state.registrationDraft.gender === "female" ? "checked" : ""} />
            <img src="/assets/avatars/female_base.png" alt="" />
            <strong>Mujer</strong>
            <span>Avatar femenino base</span>
          </label>
        </div>
        <p class="notice info">Tu avatar empezará ya personalizado con peinado, equipación, zapatillas y pala.</p>
        <div class="actions">
          <button class="btn secondary" type="button" data-onboarding-back>Anterior</button>
          <button class="btn" type="submit">Continuar</button>
        </div>
      </form>
    `;
  }
  if (state.onboardingStep === 2) {
    return `
      <form id="registerStepForm" class="form">
        <div class="onboarding-card compact">
          <span>Paso 3/4</span>
          <h2>${title}</h2>
          <p>${description}</p>
          <div class="onboarding-dots">${onboardingScreens.map((_, index) => `<i class="${index === state.onboardingStep ? "active" : ""}"></i>`).join("")}</div>
        </div>
        <label>Nivel aproximado${quickLevelSelect(state.registrationDraft.level_guess)}</label>
        <label>Ciudad${citySelect(state.registrationDraft.city)}</label>
        <label>Disponibilidad inicial<input name="availability_text" value="${escapeHtml(state.registrationDraft.availability_text || "")}" placeholder="Ej: tardes, lunes y miércoles, fines de semana" required /></label>
        <label class="check-row"><input name="available_for_play" type="checkbox" ${state.registrationDraft.available_for_play ? "checked" : ""} /> Disponible para jugar</label>
        <div class="actions">
          <button class="btn secondary" type="button" data-onboarding-back>Anterior</button>
          <button class="btn" type="submit">Ver resumen</button>
        </div>
      </form>
    `;
  }
  return `
    <div class="onboarding-card onboarding-summary">
      <span>Paso 4/4</span>
      <h2>${title}</h2>
      <p>${description}</p>
      <div class="onboarding-dots">${onboardingScreens.map((_, index) => `<i class="${index === state.onboardingStep ? "active" : ""}"></i>`).join("")}</div>
      <div class="playup-summary-list">
        <div><strong>Juegas partidos 2v2</strong><span>Siempre por parejas.</span></div>
        <div><strong>Ganas puntos individuales</strong><span>Tu progreso es tuyo aunque juegues con pareja.</span></div>
        <div><strong>Subes o bajas cada mes</strong><span>Top 3 suben y bottom 3 bajan.</span></div>
      </div>
      <p class="notice info">No necesitas que todos estén en la app. Puedes registrar partidos y luego invitarles.</p>
      <div class="actions">
        <button class="btn secondary" type="button" data-onboarding-back>Anterior</button>
        <button class="btn" type="button" data-register-submit>Entendido</button>
      </div>
    </div>
  `;
}

function saveRegisterDraft(form) {
  const values = Object.fromEntries(new FormData(form));
  if (form.elements.available_for_play) {
    values.available_for_play = form.elements.available_for_play.checked ? "on" : "";
  }
  if (values.gender) values.avatar_type = values.gender;
  state.registrationDraft = { ...state.registrationDraft, ...values };
}

async function submitRegisterStep(event) {
  event.preventDefault();
  saveRegisterDraft(event.currentTarget);
  state.onboardingStep = Math.min(onboardingScreens.length - 1, state.onboardingStep + 1);
  renderAuth();
}

async function submitRegisterDraft() {
  await submitRegister(null, state.registrationDraft);
}

async function submitLogin(event) {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(event.currentTarget));
  const data = await api("/api/auth/login", { method: "POST", body: JSON.stringify(body) });
  token = data.token;
  localStorage.setItem(tokenKey, token);
  await boot();
}

async function submitRegister(event, draft = null) {
  event?.preventDefault();
  const body = { ...(draft || Object.fromEntries(new FormData(event.currentTarget))) };
  if (body.gender) body.avatar_type = body.gender;
  const data = await api("/api/auth/register", { method: "POST", body: JSON.stringify(body) });
  token = data.token;
  localStorage.setItem(tokenKey, token);
  state.registrationDraft = {};
  state.onboardingStep = 0;
  await boot();
}

function renderShell() {
  const user = state.boot.user;
  app.innerHTML = `
    <div class="layout">
      <aside class="sidebar">
        <div class="brand">
          <img class="brand-logo" src="/assets/playup-logo.png" alt="PlayUp Padel" />
          <div><strong>PlayUp Padel</strong><span>MVP competitivo</span></div>
        </div>
        <nav>${views.filter(([id]) => id !== "admin" || user.role === "admin").map(([id, label]) => `
          <button class="${state.view === id ? "active" : ""}" data-view="${id}">${label}</button>
        `).join("")}</nav>
        <button class="btn secondary" id="logout">Salir</button>
      </aside>
      <main class="content">
        <header class="top">
          <div>
            <div class="eyebrow">${state.boot.season.name}</div>
            <h1>${titleFor(state.view)}</h1>
          </div>
          <button class="notification-chip ${state.boot.unread_notifications ? "has-unread" : ""}" data-go-view="notifications">
            <span>${state.boot.unread_notifications || 0}</span>
            Notificaciones
          </button>
          <button class="feedback-chip" data-open-feedback="bug">Reportar error</button>
          ${pwaInstallButton()}
          <div class="player-chip" data-tour="avatar">
            ${playerAvatar(user)}
            <div><strong>${user.display_name}</strong><small>${user.division_name || "Sin division"} · ${user.rating} rating</small></div>
          </div>
        </header>
        <section id="view"></section>
      </main>
    </div>
  `;
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.view = button.dataset.view;
      renderShell();
      await loadView();
    });
  });
  document.querySelector("#logout").addEventListener("click", () => {
    localStorage.removeItem(tokenKey);
    token = null;
    state.cache = {};
    renderAuth();
  });
  bindPwaInstallEvents();
  renderPwaInstallPrompt();
  renderBetaFeedbackModal();
}

function pwaInstallButton() {
  if (state.pwaInstalled) return `<span class="pwa-chip installed" data-standalone-status>App instalada</span>`;
  if (isNativeApp()) return "";
  if (state.installAvailable || isIosSafari()) return `<button class="pwa-chip" data-install-pwa>Instalar PlayUp Padel</button>`;
  return "";
}

function renderPwaInstallPrompt() {
  document.querySelector(".pwa-install-panel")?.remove();
  if (state.pwaInstalled || (!state.installAvailable && !isIosSafari())) return;
  const panel = document.createElement("div");
  panel.className = "pwa-install-panel";
  panel.innerHTML = isIosSafari() ? `
    <strong>Instala PlayUp Padel en tu iPhone</strong>
    <span>En Safari: Compartir → Añadir a pantalla de inicio.</span>
    <button class="btn small secondary" data-dismiss-pwa>Ahora no</button>
  ` : `
    <strong>Instalar PlayUp Padel</strong>
    <span>Abre PlayUp Padel como una app real y accede mas rapido a tus partidos.</span>
    <div class="actions"><button class="btn small" data-install-pwa>Instalar PlayUp Padel</button><button class="btn small secondary" data-dismiss-pwa>Ahora no</button></div>
  `;
  document.body.appendChild(panel);
  bindPwaInstallEvents();
}

function bindPwaInstallEvents() {
  document.querySelectorAll("[data-install-pwa]").forEach((button) => button.addEventListener("click", async () => {
    if (isIosSafari()) {
      renderPwaInstallPrompt();
      return;
    }
    if (!deferredInstallPrompt) return;
    deferredInstallPrompt.prompt();
    const choice = await deferredInstallPrompt.userChoice;
    if (choice.outcome === "accepted") {
      localStorage.setItem(installedKey, "1");
      state.pwaInstalled = true;
      state.installAvailable = false;
    }
    deferredInstallPrompt = null;
    renderShellIfReady();
  }));
  document.querySelectorAll("[data-dismiss-pwa]").forEach((button) => button.addEventListener("click", () => {
    document.querySelector(".pwa-install-panel")?.remove();
  }));
}

function renderShellIfReady() {
  document.querySelector(".pwa-install-panel")?.remove();
  if (state.boot) {
    renderShell();
    loadView();
  } else {
    renderAuth();
  }
}

async function loadView() {
  const target = document.querySelector("#view");
  target.innerHTML = `<div class="panel">Cargando...</div>`;
  try {
    if (state.view === "home") target.innerHTML = renderHome(await api("/api/home"));
    if (state.view === "beta") target.innerHTML = renderBetaClosed();
    if (state.view === "my-league") target.innerHTML = renderMyLeague(await api("/api/my-league"));
    if (state.view === "matches") target.innerHTML = renderMatches(await api("/api/matches"));
    if (state.view === "challenges") target.innerHTML = renderChallenges(await api("/api/challenges"));
    if (state.view === "leaderboard") target.innerHTML = renderLeaderboard(await api("/api/leaderboard?order=rating"));
    if (state.view === "progress") target.innerHTML = renderProgress(await api("/api/progress"));
    if (state.view === "avatar") target.innerHTML = renderAvatar(await api("/api/avatar"));
    if (state.view === "achievements") target.innerHTML = renderAchievements(await api("/api/achievements"));
    if (state.view === "notifications") target.innerHTML = renderNotifications(await api("/api/notifications"));
    if (state.view === "profile") target.innerHTML = renderProfile(await api("/api/profile"));
    if (state.view === "privacy") target.innerHTML = legalContent("privacy");
    if (state.view === "terms") target.innerHTML = legalContent("terms");
    if (state.view === "support") target.innerHTML = legalContent("support");
    if (state.view === "playtomic") target.innerHTML = renderPlaytomic(await api("/api/playtomic"));
    if (state.view === "admin") target.innerHTML = renderAdmin(await api("/api/admin/overview"));
    bindViewEvents();
    renderFeedbackOverlay();
    renderGuidedTutorial();
  } catch (error) {
    target.innerHTML = `<div class="notice danger">${error.message}</div>`;
  }
}

function renderBetaClosed() {
  return `
    <section class="beta-screen">
      <div class="beta-hero panel">
        <span class="beta-badge">Beta cerrada gratuita</span>
        <h2>PlayUp Padel está en beta privada</h2>
        <p>Estamos probando con primeros jugadores reales. Puedes usar la app gratis, registrar partidos, invitar jugadores y ayudarnos a detectar errores antes del lanzamiento público.</p>
        <div class="beta-actions">
          <button class="btn" data-go-view="home">Ir a jugar</button>
          <button class="btn secondary" data-open-feedback="feedback">Enviar feedback</button>
          <button class="btn secondary" data-open-feedback="bug">Reportar error</button>
        </div>
      </div>
      <div class="grid two">
        <section class="panel">
          <h3>Qué probar</h3>
          <div class="starter-checklist">
            <div>Registro y login</div>
            <div>Buscar partido</div>
            <div>Registrar partido libre</div>
            <div>Ranking y Mi Liga</div>
            <div>Avatar y XP</div>
            <div>Compartir progreso</div>
          </div>
        </section>
        <section class="panel">
          <h3>Instalar en iPhone</h3>
          <p>Abre PlayUp Padel en Safari, pulsa Compartir y elige “Añadir a pantalla de inicio”.</p>
          <p class="notice info">En Android puedes instalar la PWA o usar el APK debug cuando esté generado desde Capacitor.</p>
        </section>
      </div>
    </section>
  `;
}

function legalContent(page) {
  const updated = "Actualizado: mayo de 2026";
  if (page === "terms") {
    return `
      <div class="legal-content">
        <span class="eyebrow">Legal</span>
        <h2>Términos de uso</h2>
        <p>${updated}</p>
        <h3>Uso de PlayUp Padel</h3>
        <p>PlayUp Padel organiza ligas amateur, retos, ranking, XP y estadísticas de pádel. El usuario debe introducir información veraz y respetar a otros jugadores.</p>
        <h3>Resultados y competición</h3>
        <p>Los resultados introducidos manualmente pueden requerir confirmación del rival o revisión del administrador. PlayUp Padel puede corregir resultados, resolver disputas y suspender cuentas ante abuso.</p>
        <h3>Responsabilidad deportiva</h3>
        <p>Los partidos se juegan fuera de la app. Cada jugador es responsable de su disponibilidad, reserva de pista, condición física y cumplimiento de normas del club.</p>
        <h3>Cuenta</h3>
        <p>El usuario debe mantener sus credenciales seguras. Podemos limitar el acceso si detectamos fraude, conflictos reiterados o uso contrario a la comunidad.</p>
      </div>
    `;
  }
  if (page === "support") {
    return `
      <div class="legal-content">
        <span class="eyebrow">Ayuda</span>
        <h2>Soporte</h2>
        <p>Para soporte, privacidad, cuentas o incidencias de resultados, contacta con:</p>
        <div class="support-card">
          <strong>support@playuppadel.com</strong>
          <span>Respondemos incidencias de beta y revisión de resultados lo antes posible.</span>
        </div>
        <h3>Antes de escribir</h3>
        <p>Incluye tu email de cuenta, ciudad, partido afectado y una descripción breve del problema.</p>
      </div>
    `;
  }
  return `
    <div class="legal-content">
      <span class="eyebrow">Legal</span>
      <h2>Política de privacidad</h2>
      <p>${updated}</p>
      <h3>Datos que usamos</h3>
      <p>Recogemos email, nombre, ciudad, club habitual, nivel aproximado, disponibilidad, resultados, ranking, XP, avatar, retos y actividad necesaria para operar la competición.</p>
      <h3>Finalidad</h3>
      <p>Usamos estos datos para crear grupos, calcular clasificaciones, recomendar rivales, validar resultados, mostrar progreso y mantener la seguridad de la comunidad.</p>
      <h3>Playtomic</h3>
      <p>La integración con Playtomic está preparada pero no se usa scraping. En el MVP solo guardamos el identificador o estado de vinculación si el usuario lo introduce.</p>
      <h3>Contacto y derechos</h3>
      <p>Puedes solicitar acceso, corrección o eliminación escribiendo a support@playuppadel.com.</p>
    </div>
  `;
}

function renderHome(data) {
  const entry = data.ranking_entry || {};
  const progress = data.matches_progress || { played: 0, max: 10 };
  const promotionGap = data.promotion_gap || {};
  const playNow = data.play_now || {};
  const partner = playNow.suggested_partner;
  const rivals = playNow.recommended_rivals || data.recommended_rivals || [];
  const activePlayers = playNow.active_players_48h || [];
  const avatarProgress = data.avatar_progress || { xp: { total: data.profile.xp_total, progress: 0, needed: 500 }, next_unlocks: [] };
  const xp = avatarProgress.xp || { total: data.profile.xp_total, progress: 0, needed: 500 };
  if ((progress.played || 0) === 0) {
    return `
      ${renderSeasonFeedback(data.season_feedback)}
      ${renderFirstMatchMode(data.profile, partner, rivals)}
    `;
  }
  return `
    ${renderSeasonFeedback(data.season_feedback)}
    <section class="competition-home">
      <div class="competition-primary">
        <article class="competition-card zone-${data.status.code}" data-tour="home-status">
          <div class="competition-player">
            ${playerAvatar(data.profile, "hero-avatar", `<small>Nv. ${data.level}</small>`)}
            <div>
              <span class="eyebrow">Tu liga este mes</span>
              <h2>${data.profile.display_name}</h2>
              <p>${data.profile.division_name} · ${data.group.name}</p>
            </div>
            <span class="status-pill ${data.status.code}">${data.status.label}</span>
          </div>
          <div class="competition-metrics">
            <div class="metric-main"><span>Posición</span><strong>${entry.rank_position ? `#${entry.rank_position}` : "-"}</strong></div>
            <div><span>Puntos</span><strong>${entry.points || 0}</strong></div>
            <div><span>Ascenso</span><strong>${promotionGap.points === 0 ? "Top 3" : `${promotionGap.points || "-"} pts`}</strong></div>
            <div><span>Partidos</span><strong>${progress.played}/${progress.max}</strong></div>
          </div>
          <div class="objective home-objective">
            <span>Objetivo inmediato</span>
            <strong>${escapeHtml(data.next_objective || data.competitive_message)}</strong>
          </div>
          <div class="home-progress">
            <div class="toolbar"><strong>Cupo mensual competitivo</strong><span>${progress.played}/${progress.max}</span></div>
            <progress max="${progress.max}" value="${progress.played}"></progress>
          </div>
          <div class="share-actions">
            <button class="btn home-cta big" data-jump-play-now data-tour="play-button">Jugar partido</button>
            <button class="btn secondary big" data-share-card="status">Compartir</button>
          </div>
        </article>
        ${data.is_new_player ? renderNewPlayerGuide(data) : ""}
      </div>

      <aside class="competition-sidebar">
        <article class="avatar-xp-card" data-tour="avatar-progress">
          <div class="toolbar">
            <div>
              <span class="eyebrow">Avatar y XP</span>
              <h3>Nivel ${avatarProgress.level || data.level}</h3>
            </div>
            <strong>${xp.total || 0} XP</strong>
          </div>
          <progress max="${xp.needed || 500}" value="${xp.progress || 0}"></progress>
          <div class="unlock-list">
            ${(avatarProgress.next_unlocks || []).map((item) => `
              <div>
                <img src="${item.image_path}" alt="${item.name}" />
                <span>${item.name}</span>
                <small>Nv. ${item.required_level}</small>
              </div>
            `).join("") || `<small>No hay desbloqueos pendientes.</small>`}
          </div>
        </article>
        <article class="activity-card">
          <div class="toolbar"><h3>Actividad reciente</h3><button class="btn small" data-go-view="matches">Partidos</button></div>
          <div class="activity-feed">
            ${(data.recent_activity || []).map((item) => `
              <div class="activity-item">
                <strong>${item.team_a_label} vs ${item.team_b_label}</strong>
                <small>${item.status_label}${item.score ? ` · ${item.score}` : ""}</small>
              </div>
            `).join("") || activePlayers.slice(0, 4).map((player) => `
              <div class="activity-item player-active">
                ${playerAvatar(player)}
                <div><strong>${player.display_name}</strong><small>${player.available_for_play ? "Disponible para jugar" : "Activo ultimas 48h"}</small></div>
              </div>
            `).join("") || `<p class="muted">Aun no hay actividad reciente en tu grupo.</p>`}
          </div>
        </article>
      </aside>
    </section>

    <section class="home-play-now panel">
      <div class="toolbar">
        <div>
          <span class="eyebrow">Jugar ahora</span>
          <h2>Encuentra partido en segundos</h2>
        </div>
        <button class="btn" data-create-play-now ${partner && rivals.length >= 2 ? "" : "disabled"}>Crear partido 2v2</button>
      </div>
      <div class="activation-quick-grid">
        <article class="activation-card partner">
          <span>Compañero sugerido</span>
          ${partner ? playerActionCard(partner) : `<p class="muted">Marca disponibilidad para mejorar la sugerencia.</p>`}
        </article>
        <article class="activation-card rivals">
          <span>Rivales recomendados</span>
          <div class="recommended-rivals">
            ${rivals.slice(0, 3).map((rival) => `
              <div class="recommended-rival">
                ${playerMini(rival)}
                ${availabilityPill(rival)}
                <button class="btn small" data-home-challenge="${rival.user_id}">Retar</button>
              </div>
            `).join("") || `<p class="muted">No hay rivales compatibles ahora mismo.</p>`}
          </div>
        </article>
      </div>
    </section>

    <section class="home-grid">
      <article class="panel mini-ranking-card" data-tour="ranking">
        <div class="toolbar">
          <h2>Tu zona del ranking</h2>
          <button class="btn small" data-go-view="my-league">Ver liga</button>
        </div>
        <div class="mini-ranking-list">
          ${(data.mini_ranking || []).map((row) => `
            <div class="mini-ranking-row ${row.user_id === data.profile.user_id ? "me" : ""} zone-${row.movement_zone}">
              <span>${movementIcon(row.movement_zone)} #${row.rank_position}</span>
              ${playerMini(row)}
              <strong>${row.points} pts</strong>
              <small>${row.played}/10</small>
            </div>
          `).join("") || `<p class="muted">Juega tu primer partido para entrar en ranking.</p>`}
        </div>
      </article>
      <article class="panel home-rivals">
        <div class="toolbar">
          <h2>Jugadores activos</h2>
          <button class="btn small" data-go-view="challenges">Retos</button>
        </div>
        <div class="active-player-grid">
          ${activePlayers.slice(0, 6).map((player) => `
            <div class="active-player-card">
              ${playerMini(player)}
              ${availabilityPill(player)}
            </div>
          `).join("") || `<p class="muted">No hay jugadores activos en las últimas 48h.</p>`}
        </div>
      </article>
    </section>

    ${(data.pending_results || []).length ? `<section class="panel pending-strip">
      <div class="toolbar"><h2>Resultados pendientes</h2><button class="btn small" data-go-view="matches">Resolver</button></div>
      <div class="pending-grid">
        ${data.pending_results.map((match) => `
          <div class="home-alert ${match.pending_for_me ? "needs-action" : ""}">
            <strong>${match.pending_for_me ? "Por confirmar" : "Esperando rival"}</strong>
            <small>${match.team_a_label} vs ${match.team_b_label} · ${match.score}</small>
          </div>
        `).join("")}
      </div>
    </section>` : ""}
  `;
}

function renderFirstMatchMode(profile, partner, rivals = []) {
  const canCreate = partner && rivals.length >= 2;
  const teamSummary = canCreate ? `Tú + ${partner.display_name} vs ${rivals[0].display_name} + ${rivals[1].display_name}` : "";
  if (!canCreate) {
    return `
      <section class="first-match-mode">
        <div class="first-match-card first-match-empty" data-tour="home-status">
          <span class="eyebrow">Primer partido</span>
          <h1>Empieza tu camino hacia el ascenso 🔥</h1>
          <p>No necesitas que todos estén en PlayUp Padel para empezar.</p>
          <div class="first-match-actions">
            <button class="btn first-match-button" data-create-match-request data-tour="play-button">Jugar partido</button>
            <button class="btn first-match-secondary" data-go-view="matches">Registrar partido libre</button>
            <button class="btn first-match-secondary" data-availability="1">Marcarme como disponible</button>
          </div>
        </div>
      </section>
    `;
  }
  if (state.firstMatchDraft) {
    return `
      <section class="first-match-mode">
        <div class="first-match-card first-match-confirm" data-tour="home-status">
          <span class="eyebrow">Partido listo</span>
          <h1>${teamSummary}</h1>
          <p>No necesitas que todos estén en PlayUp Padel para empezar.</p>
          <div class="first-match-lineup">
            <div>${playerMini(profile)}${playerMini(partner)}</div>
            <strong>vs</strong>
            <div>${playerMini(rivals[0])}${playerMini(rivals[1])}</div>
          </div>
          <button class="btn first-match-button" data-create-play-now data-tour="play-button">Crear partido 2v2</button>
          <button class="btn first-match-secondary" data-go-view="matches">Registrar partido libre</button>
        </div>
      </section>
    `;
  }
  return `
    <section class="first-match-mode">
      <div class="first-match-card" data-tour="home-status">
        <span class="eyebrow">Primer partido</span>
        <h1>Empieza tu camino hacia el ascenso 🔥</h1>
        <p>No necesitas que todos estén en PlayUp Padel para empezar.</p>
        <button class="btn first-match-button" data-first-match-plan data-tour="play-button">Jugar partido</button>
        <div class="first-match-options">
          <button class="btn first-match-secondary" data-first-match-plan>Crear partido</button>
          <button class="btn first-match-secondary" data-go-view="matches">Registrar partido libre</button>
        </div>
      </div>
    </section>
  `;
}

function prepareGuidedTutorial() {
  state.tutorialOpen = false;
  state.tutorialStep = 0;
}

function tutorialStorageKey() {
  const userId = state.boot?.user?.user_id;
  return userId ? `playup-tutorial-done-${userId}` : "";
}

function completeGuidedTutorial() {
  const key = tutorialStorageKey();
  if (key) localStorage.setItem(key, "1");
  state.tutorialOpen = false;
  document.querySelector(".guided-tutorial")?.remove();
  document.querySelectorAll(".tour-highlight").forEach((node) => node.classList.remove("tour-highlight"));
}

function renderGuidedTutorial() {
  document.querySelector(".guided-tutorial")?.remove();
  document.querySelectorAll(".tour-highlight").forEach((node) => node.classList.remove("tour-highlight"));
  if (!state.tutorialOpen || state.view !== "home" || !state.boot) return;

  const step = tutorialSteps[Math.min(state.tutorialStep, tutorialSteps.length - 1)];
  const target = document.querySelector(step.target);
  if (target) {
    target.classList.add("tour-highlight");
  }

  const wrapper = document.createElement("div");
  wrapper.className = "guided-tutorial";
  wrapper.innerHTML = `
    <section class="tutorial-coach">
      <span>Paso ${state.tutorialStep + 1}/${tutorialSteps.length}</span>
      <h2>${step.title}</h2>
      <p>${step.body}</p>
      <div class="tutorial-actions">
        <button class="btn secondary small" data-tour-skip>Saltar</button>
        <button class="btn small" data-tour-next>${state.tutorialStep === tutorialSteps.length - 1 ? "Terminar" : "Siguiente"}</button>
      </div>
    </section>
  `;
  document.body.appendChild(wrapper);
  wrapper.querySelector("[data-tour-skip]").addEventListener("click", completeGuidedTutorial);
  wrapper.querySelector("[data-tour-next]").addEventListener("click", () => {
    if (state.tutorialStep >= tutorialSteps.length - 1) {
      completeGuidedTutorial();
      return;
    }
    state.tutorialStep += 1;
    renderGuidedTutorial();
  });
}

function renderNewPlayerGuide(data) {
  const mission = data.starter_mission || {};
  const checklist = data.starter_checklist || [];
  return `
    <section class="new-player-guide">
      <span>Primeros pasos</span>
      <h2>Empieza con un partido competitivo</h2>
      <p>Marca disponibilidad, busca pareja/rivales y registra tu primer resultado 2v2. Tu progreso individual empieza desde el primer partido confirmado.</p>
      <div class="starter-actions">
        <button class="btn big" data-jump-play-now>Buscar partido</button>
        <button class="btn secondary big" data-go-view="matches">Añadir resultado</button>
      </div>
      <article class="starter-mission ${mission.status}">
        <div>
          <strong>${mission.title}</strong>
          <small>${mission.description} · +${mission.reward_xp} XP</small>
        </div>
        <progress max="${mission.target || 3}" value="${mission.progress || 0}"></progress>
        ${mission.status === "completed" ? `<button class="btn small" data-starter-claim>Reclamar</button>` : `<span>${mission.status === "claimed" ? "Reclamado" : "Pendiente"}</span>`}
      </article>
      <div class="starter-checklist">
        ${checklist.map((item) => `<div class="${item.done ? "done" : ""}"><strong>${item.done ? "✓" : "·"}</strong><span>${item.label}</span></div>`).join("")}
      </div>
    </section>
  `;
}

function renderSeasonFeedback(feedback) {
  if (!feedback) return "";
  return `
    <section class="promotion-screen">
      <div>
        <span>Ascenso desbloqueado</span>
        <h2>${escapeHtml(feedback.title)}</h2>
        <p>${escapeHtml(feedback.message)}</p>
      </div>
      <div class="promotion-badge">↑</div>
    </section>
  `;
}

function renderPlayNow(playNow = {}) {
  const availability = playNow.availability || {};
  const partner = playNow.suggested_partner;
  const rivals = playNow.recommended_rivals || [];
  const activePlayers = playNow.active_players_48h || [];
  const requests = playNow.open_match_requests || [];
  return `
    <section class="panel play-now">
      <div class="toolbar">
        <div>
          <h2>Jugar ahora</h2>
          <small>${availability.available ? "Disponible para jugar" : "No marcado como disponible"}</small>
        </div>
        <button class="btn ${availability.available ? "secondary dark" : ""}" data-availability="${availability.available ? "0" : "1"}">
          ${availability.available ? "Dejar de buscar" : "Estoy disponible"}
        </button>
      </div>
      <div class="play-now-grid">
        <article class="activation-card">
          <span>Companero sugerido</span>
          ${partner ? playerActionCard(partner) : `<p class="muted">No hay companero sugerido todavia.</p>`}
        </article>
        <article class="activation-card rivals">
          <span>3 rivales recomendados</span>
          <div class="activation-list">${rivals.map(playerActionCard).join("") || `<p class="muted">Faltan rivales activos.</p>`}</div>
        </article>
        <article class="activation-card create">
          <span>Partido 2v2</span>
          <strong>${partner && rivals.length >= 2 ? "Equipo listo" : "A la espera"}</strong>
          <small>${partner && rivals.length >= 2 ? `${state.boot.user.display_name} / ${partner.display_name} vs ${rivals.slice(0, 2).map((p) => p.display_name).join(" / ")}` : "Necesitas companero y dos rivales."}</small>
          <button class="btn" data-create-play-now ${partner && rivals.length >= 2 ? "" : "disabled"}>Crear partido 2v2</button>
        </article>
      </div>
      <div class="grid two activation-section">
        <div>
          <h3>Busco partido</h3>
          <div class="list compact">${requests.map(matchRequestCard).join("") || `<p class="muted">Aun no hay busquedas abiertas.</p>`}</div>
        </div>
        <div>
          <h3>Activos ultimas 48h</h3>
          <div class="active-strip">${activePlayers.map((player) => `<div class="active-player ${player.available_for_play ? "available" : ""}">${playerMini(player)}<small>${availabilityPill(player)}</small></div>`).join("") || `<p class="muted">Sin actividad reciente en tu grupo.</p>`}</div>
        </div>
      </div>
    </section>
  `;
}

function matchRequestCard(request) {
  return `
    <article class="match-request">
      <div>
        ${playerMini(request.owner)}
        <small>${escapeHtml(request.message || "Busco partido competitivo.")}</small>
      </div>
      ${request.joined ? `<small>Se ha unido ${escapeHtml(request.joined.display_name)}</small>` : ""}
      ${request.can_join ? `<button class="btn small" data-join-request="${request.id}">Unirme</button>` : `<span class="status-pill middle">${request.status}</span>`}
    </article>
  `;
}

function renderMyLeague(data) {
  return `
    <div class="grid two">
      <section class="panel">
        <div class="toolbar"><h2>${data.group.name}</h2><button class="btn small" data-share-card="status">Compartir</button></div>
        ${rankingTable(data.ranking)}
      </section>
      <section class="panel">
        <h2>Jugadores del grupo</h2>
        <div class="list">${data.members.map(playerRow).join("")}</div>
      </section>
    </div>
  `;
}

function renderMatches(data) {
  return `
    <div class="grid two">
      <section class="panel">
        <h2>Anadir resultado 2v2</h2>
        <form id="matchForm" class="form">
          <div class="team-form">
            <div>
              <h3>Equipo A</h3>
              <div class="player-mini">${playerAvatar(state.boot.user)}<div><strong>${state.boot.user.display_name}</strong><small>Tu</small></div></div>
              <label>Companero<select name="team_a_player_2_id">${playerOptions(data.players, 0)}</select></label>
            </div>
            <div>
              <h3>Equipo B</h3>
              <label>Rival 1<select name="team_b_player_1_id">${playerOptions(data.players, 1)}</select></label>
              <label>Rival 2<select name="team_b_player_2_id">${playerOptions(data.players, 2)}</select></label>
            </div>
          </div>
          <label>Resultado<input name="score" placeholder="6-4 4-6 10-8" required /></label>
          <button class="btn" type="submit">Enviar al rival</button>
        </form>
      </section>
      <section class="panel free-match-panel">
        <div class="toolbar">
          <div>
            <h2>Registrar partido libre</h2>
            <small>Usalo cuando hayas jugado con personas que aun no estan en PlayUp Padel.</small>
          </div>
        </div>
        <form id="freeMatchForm" class="form">
          <div class="team-form">
            <div>
              <h3>Tu equipo</h3>
              <div class="player-mini">${playerAvatar(state.boot.user)}<div><strong>${state.boot.user.display_name}</strong><small>Tu</small></div></div>
              <label>Pareja externa<input name="partner_external_name" placeholder="Nombre de tu pareja" required /></label>
            </div>
            <div>
              <h3>Rivales externos</h3>
              <label>Rival externo 1<input name="rival_1_external_name" placeholder="Nombre rival" required /></label>
              <label>Rival externo 2<input name="rival_2_external_name" placeholder="Nombre rival" required /></label>
            </div>
          </div>
          <label>Club/lugar opcional<input name="club_name" placeholder="Club o pista" /></label>
          <label>Fecha<input name="played_on" type="date" /></label>
          <label>Marcador<input name="score" placeholder="6-4 4-6 10-8" required /></label>
          <p class="notice info">Suma XP y estadisticas personales. No afecta al ranking oficial ni a ascensos/descensos.</p>
          <button class="btn" type="submit">Registrar partido libre</button>
        </form>
      </section>
      <section class="panel">
        <h2>Partidos del mes</h2>
        <div class="list">${data.matches.map(matchCard).join("") || `<p class="muted">Sin partidos todavia.</p>`}</div>
      </section>
      <section class="panel">
        <h2>Partidos libres</h2>
        <div class="list">${(data.free_matches || []).map(freeMatchCard).join("") || `<p class="muted">Aun no has registrado partidos libres.</p>`}</div>
      </section>
    </div>
  `;
}

function freeMatchCard(match) {
  const winnerClassA = match.winner_team === "A" ? "winner" : "";
  const winnerClassB = match.winner_team === "B" ? "winner" : "";
  return `
    <article class="match match-versus free-match-card">
      <div class="match-meta">
        <strong class="match-status confirmed">Libre</strong>
        <small>${match.played_on}${match.club_name ? ` · ${escapeHtml(match.club_name)}` : ""} · No afecta ranking</small>
      </div>
      <div class="versus-grid">
        <div class="team-card ${winnerClassA}">
          <span>Tu equipo</span>
          ${playerMini(state.boot.user)}
          ${externalPlayerMini(match.partner_external_name, match.partner_linked_user_id)}
        </div>
        <div class="score-card">
          <strong>${match.score}</strong>
          <small>${match.winner_team === "A" ? "Victoria" : "Derrota"} libre</small>
        </div>
        <div class="team-card ${winnerClassB}">
          <span>Rivales</span>
          ${externalPlayerMini(match.rival_1_external_name, match.rival_1_linked_user_id)}
          ${externalPlayerMini(match.rival_2_external_name, match.rival_2_linked_user_id)}
        </div>
      </div>
      <p class="notice info">Invita a estos jugadores para convertirlo en partido oficial.</p>
      <button class="btn small" data-invite-free-match="${match.id}">Invitar jugadores</button>
      ${freeMatchInvites(match)}
    </article>
  `;
}

function freeMatchInvites(match) {
  const invitations = match.invitations || [];
  if (!invitations.length) return "";
  return `
    <div class="invite-links">
      ${invitations.map((invite) => `
        <div>
          <small>${invite.accepted_at ? "Registrado" : "Pendiente"}</small>
          <input readonly value="${location.origin}/invite/${invite.token}" />
        </div>
      `).join("")}
    </div>
  `;
}

function externalPlayerMini(name, linkedUserId) {
  return `<div class="player-mini external-player"><span class="avatar">EXT</span><div><strong>${escapeHtml(name)}</strong><small>${linkedUserId ? "Vinculado a PlayUp Padel" : "Jugador externo"}</small></div></div>`;
}

function matchCard(match) {
  const winnerClassA = match.winner_team === "A" ? "winner" : "";
  const winnerClassB = match.winner_team === "B" ? "winner" : "";
  return `
    <article class="match match-versus">
      <div class="match-meta"><strong class="match-status ${match.status}">${match.status_label || match.status}</strong><small>${match.source}${match.is_discarded ? " · descartado por limite 10" : ""}</small></div>
      <div class="versus-grid">
        <div class="team-card ${winnerClassA}">
          <span>Equipo A</span>
          ${match.team_a.map(matchPlayerMini).join("")}
        </div>
        <div class="score-card">
          <strong>${match.score || "-"}</strong>
          <small>${match.winner_team ? `Gana Equipo ${match.winner_team}` : "Sin marcador"}</small>
        </div>
        <div class="team-card ${winnerClassB}">
          <span>Equipo B</span>
          ${match.team_b.map(matchPlayerMini).join("")}
        </div>
      </div>
      ${match.pending_for_me ? `<div class="actions"><button class="btn small" data-confirm="${match.id}">Confirmar</button><button class="btn small danger" data-conflict="${match.id}">Discrepancia</button></div>` : ""}
      ${match.conflict_note ? `<p class="notice danger">${match.conflict_note}</p>` : ""}
    </article>
  `;
}

function renderChallenges(data) {
  return `
    <section class="panel monthly-challenges">
      <div class="toolbar">
        <div>
          <h2>Retos del mes</h2>
          <small>Objetivos de temporada para volver cada semana.</small>
        </div>
      </div>
      <div class="monthly-grid">${(data.monthly || []).map(monthlyChallengeCard).join("")}</div>
    </section>
    <div class="grid two">
      <section class="panel">
        <h2>Reto abierto</h2>
        <form id="challengeForm" class="form">
          <div class="team-form">
            <div>
              <h3>Tu pareja</h3>
              <label>Companero<select name="challenger_partner_id">${playerOptions(data.suggested_rivals, 0)}</select></label>
            </div>
            <div>
              <h3>Pareja rival</h3>
              <label>Rival 1<select name="challenged_id">${playerOptions(data.suggested_rivals, 1)}</select></label>
              <label>Rival 2<select name="challenged_partner_id">${playerOptions(data.suggested_rivals, 2)}</select></label>
            </div>
          </div>
          <label>Mensaje<input name="description" value="Partido competitivo esta semana?" /></label>
          <button class="btn" type="submit">Enviar reto</button>
        </form>
        <div class="suggestions">
          <h3>Retos automaticos</h3>
          ${data.suggested_rivals.map((p) => `
            <article class="challenge-card">
              <div class="player-mini">${playerAvatar(p)}<div><strong>${p.display_name}</strong><small>${p.level_guess} · ${p.rating} rating · ${p.active_matches} partidos este mes</small></div></div>
              <button class="btn small" data-auto-challenge="${p.user_id}">Retar</button>
            </article>
          `).join("") || `<p class="muted">No hay rivales sugeridos ahora mismo.</p>`}
        </div>
      </section>
      <section class="panel">
        <h2>Retos semanales</h2>
        <div class="list">${data.weekly.map((item) => `
          <article class="weekly ${item.completed ? "done" : ""}">
            <div><strong>${item.title}</strong><small>${item.progress}/${item.target} · +${item.reward_xp} XP</small></div>
            <progress max="${item.target}" value="${item.progress}"></progress>
          </article>
        `).join("")}</div>
      </section>
    </div>
    <div class="grid two challenge-section">
      <section class="panel">
        <h2>Mis retos</h2>
        <div class="list">${data.challenges.map(challengeCard).join("") || `<p class="muted">Todavia no hay retos abiertos.</p>`}</div>
      </section>
      <section class="panel">
        <h2>Notificaciones</h2>
        <div class="list">${data.notifications.map((n) => `
          <div class="row"><span>${n.title}</span><small>${n.body}</small></div>
        `).join("") || `<p class="muted">Sin notificaciones.</p>`}</div>
      </section>
    </div>
  `;
}

function monthlyChallengeCard(item) {
  const percent = Math.min(100, Math.round((item.progress / item.target) * 100));
  return `
    <article class="monthly-card ${item.status}">
      <div class="monthly-head">
        <span>${item.status === "claimed" ? "Reclamado" : item.completed ? "Completado" : "Pendiente"}</span>
        <small>${item.time_remaining}</small>
      </div>
      <strong>${item.title}</strong>
      <p>${item.description}</p>
      <div class="challenge-progress">
        <div><span>${item.progress}/${item.target}</span><small>${percent}%</small></div>
        <progress max="${item.target}" value="${item.progress}"></progress>
      </div>
      <div class="reward-row">
        ${item.reward_item_image ? `<img src="${item.reward_item_image}" alt="${item.reward_item_name}" />` : ""}
        <span>${item.reward_label}</span>
      </div>
      ${item.status === "completed" ? `<button class="btn small" data-monthly-claim="${item.id}">Reclamar</button>` : ""}
    </article>
  `;
}

function challengeCard(challenge) {
  const rival = challenge.type === "weekly"
    ? "Sistema"
    : challenge.challenger_name === state.boot.user.display_name ? teamNames(challenge.team_b) : teamNames(challenge.team_a);
  return `
    <article class="match challenge">
      <div>
        <strong>${challenge.title}</strong>
        <small>${challenge.type} · ${challenge.status} · rival: ${rival} · +${challenge.reward_xp} XP</small>
      </div>
      ${challenge.type !== "weekly" ? `<div class="versus-grid compact"><div class="team-card">${(challenge.team_a || []).map(playerMini).join("")}</div><div class="score-card"><strong>VS</strong></div><div class="team-card">${(challenge.team_b || []).map(playerMini).join("")}</div></div>` : ""}
      ${challenge.description ? `<p>${escapeHtml(challenge.description)}</p>` : ""}
      ${challenge.can_accept ? `<div class="actions"><button class="btn small" data-challenge-accept="${challenge.id}">Aceptar</button><button class="btn small danger" data-challenge-reject="${challenge.id}">Rechazar</button></div>` : ""}
      ${challenge.can_submit_result ? `
        <form class="challenge-result" data-challenge-result="${challenge.id}">
          <input name="score" placeholder="6-4 4-6 10-8" required />
          <button class="btn small" type="submit">Subir resultado</button>
        </form>
      ` : ""}
      ${challenge.match_id ? `<small>Partido asociado #${challenge.match_id}</small>` : ""}
    </article>
  `;
}

function renderLeaderboard(data) {
  return `
    <section class="panel">
      <div class="toolbar">
        <h2>Ranking</h2>
        <select id="leaderboardOrder">
          <option value="rating">Rating interno</option>
          <option value="xp">XP</option>
          <option value="division">Division</option>
        </select>
      </div>
      <table><thead><tr><th>#</th><th>Jugador</th><th>Division</th><th>Rating</th><th>XP</th><th>Localidad</th></tr></thead>
      <tbody>${data.leaderboard.map((p) => `<tr><td>${p.rank_position}</td><td>${playerMini(p)}</td><td>${p.division_name}</td><td>${p.rating}</td><td>${p.xp_total}</td><td>${p.city}</td></tr>`).join("")}</tbody></table>
    </section>
  `;
}

function renderProgress(data) {
  const identity = data.identity || {};
  const statsData = identity.stats || {};
  const advanced = identity.advanced || {};
  const cardProfile = { ...data.profile, ...(identity.profile || {}) };
  const currentRank = identity.current_ranking?.rank_position ? `#${identity.current_ranking.rank_position}` : "-";
  return `
    <section class="player-identity-hero">
      <div class="sport-card">
        ${playerAvatar(cardProfile, "sport-card-avatar")}
        <div class="sport-card-rating">${data.level}</div>
        <span class="eyebrow">Player Card</span>
        <h2>${cardProfile.display_name}</h2>
        <p>${cardProfile.division_name} · Ranking ${currentRank}</p>
        <div class="style-tags">${(identity.styles || ["En crecimiento"]).map((style) => `<span>${style}</span>`).join("")}</div>
        <div class="sport-card-stats">
          ${stat("Rating", cardProfile.rating)}
          ${stat("Win rate", `${statsData.win_rate || 0}%`)}
          ${stat("Racha", advanced.current_streak?.label || "-")}
          ${stat("Ascensos", advanced.promotions || 0)}
        </div>
      </div>
      <div class="identity-summary">
        <div class="toolbar">
          <div>
            <span class="eyebrow">Identidad competitiva</span>
            <h2>${cardProfile.display_name}</h2>
          </div>
        </div>
        <div class="stats identity-stats">
          ${stat("Partidos", statsData.played || 0)}
          ${stat("Victorias", statsData.wins || 0)}
          ${stat("Derrotas", statsData.losses || 0)}
          ${stat("Sets + / -", `${statsData.sets_won || 0}/${statsData.sets_lost || 0}`)}
          ${stat("Game avg", signed(statsData.game_average || 0))}
          ${stat("Mejor racha", advanced.best_streak?.label || "-")}
          ${stat("Pos. media", advanced.average_position || "-")}
          ${stat("Giant Killer", advanced.giant_killer_wins || 0)}
        </div>
        <div class="featured-badges">
          ${(identity.highlighted_achievements || []).map((badge) => `<span>${badge.name}</span>`).join("") || `<span>Logros destacados pendientes</span>`}
        </div>
      </div>
    </section>
    <div class="grid two identity-grid">
      <section class="panel">
        <h2>Últimas 10 partidas</h2>
        <div class="list">${(identity.last_matches || []).map((match) => `
          <div class="row result-item ${match.result}">
            <span>${match.label}</span>
            <strong>${match.score}</strong>
            <small>vs ${match.opponents}</small>
          </div>
        `).join("") || `<p class="muted">Sin partidos confirmados todavía.</p>`}</div>
      </section>
      <section class="panel">
        <h2>Evolución de ranking</h2>
        <div class="timeline-list">${(identity.ranking_evolution || []).map((row) => `
          <div><strong>#${row.rank_position}</strong><span>${row.points} pts · ${row.played}/10 partidos</span></div>
        `).join("") || `<p class="muted">Aún no hay ranking persistido.</p>`}</div>
      </section>
      <section class="panel">
        <h2>Evolución de rating</h2>
        <div class="timeline-list">${(identity.rating_evolution || []).map((r) => `
          <div><strong>${r.delta > 0 ? "+" : ""}${r.delta}</strong><span>${r.rating_before} -> ${r.rating_after}</span></div>
        `).join("") || `<p class="muted">Sin cambios de rating todavía.</p>`}</div>
      </section>
      <section class="panel">
        <h2>Histórico de divisiones</h2>
        <div class="timeline-list">${(identity.division_timeline || []).map((h) => `
          <div><strong>${h.movement}</strong><span>${h.from_division || "-"} -> ${h.to_division || "-"}</span></div>
        `).join("") || `<p class="muted">Sin cierres mensuales todavía.</p>`}</div>
      </section>
    </div>
  `;
}

function renderAvatar(data) {
  const p = data.profile;
  const entry = data.ranking_entry || {};
  const items = data.items || [];
  const filters = {
    ropa: ["face", "hair", "hair_color", "beard", "top", "bottom", "shoes"],
    pala: ["racket"],
    accesorios: ["headband", "wristband", "overgrip"],
    marcos: ["frame"],
    fondos: ["background"],
    efectos: ["effect"],
  };
  const activeFilter = state.avatarFilter || "ropa";
  const visibleItems = items.filter((item) => filters[activeFilter].includes(item.category));
  const unlockedCount = items.filter((item) => item.unlocked).length;
  const xp = data.xp || { progress: 0, needed: 500, total: p.xp_total };
  const nextUnlocks = data.next_unlocks || [];
  return `
    <div class="avatar-workshop">
      <section class="player-card avatar-preview-card">
        <div class="player-card-top">
          ${avatarPreview(p, data)}
          <div>
            <span class="eyebrow">Player Card</span>
            <h2>${p.display_name}</h2>
            <p>${p.division_name} · ${p.group_name}</p>
          </div>
        </div>
        <div class="player-card-stats">
          ${stat("Ranking", entry.rank_position ? `#${entry.rank_position}` : "-")}
          ${stat("XP", p.xp_total)}
          ${stat("Rating", p.rating)}
          ${stat("Items", `${unlockedCount}/${items.length}`)}
        </div>
        <div class="home-progress avatar-xp">
          <div class="toolbar"><strong>Nivel ${data.level}</strong><span>${xp.total} XP total · ${xp.progress}/${xp.needed} al siguiente nivel</span></div>
          <progress max="${xp.needed}" value="${xp.progress}"></progress>
        </div>
        <div class="next-unlocks">
          <strong>Próximos desbloqueos</strong>
          ${nextUnlocks.map((item) => `
            <div class="next-unlock">
              <img src="${item.image_path}" alt="${item.name}" />
              <span>${item.name}</span>
              <small>Nivel ${item.required_level}</small>
            </div>
          `).join("") || `<small>No hay desbloqueos por nivel pendientes.</small>`}
        </div>
        <div class="base-picker">
          ${(data.bases || []).map((base) => `
            <button class="base-option ${data.avatar?.base_avatar_id === base.id ? "active" : ""}" data-avatar-base="${base.id}">
              <img src="${base.image_path}" alt="${base.name}" />
              <span>${base.name}</span>
            </button>
          `).join("")}
        </div>
        <div class="badges-row">${(data.achievements || []).map((item) => `<span>${item.name}</span>`).join("") || `<span>Primer logro pendiente</span>`}</div>
      </section>
      <section class="panel avatar-inventory">
        <div class="toolbar">
          <div>
            <h2>Avatar</h2>
            <small>Personaliza tu carta con items desbloqueados por XP.</small>
          </div>
        </div>
        <div class="avatar-filters">
          ${Object.keys(filters).map((filter) => `<button class="${activeFilter === filter ? "active" : ""}" data-avatar-filter="${filter}">${filter}</button>`).join("")}
        </div>
        <div class="avatar-item-grid">
          ${visibleItems.map(avatarItemCard).join("") || `<p class="muted">No hay items en esta categoria.</p>`}
        </div>
      </section>
    </div>
  `;
}

function avatarPreview(profile, data = {}) {
  const avatar = data.avatar || {};
  const items = data.items || [];
  const equipped = items.filter((item) => item.equipped);
  const frame = equipped.find((item) => item.category === "frame");
  const background = equipped.find((item) => item.category === "background");
  const effect = equipped.find((item) => item.category === "effect");
  return `
    <div class="avatar-card-visual rarity-${frame?.rarity || "comun"} ${effect ? "has-effect" : ""}">
      <div class="avatar-card-bg">${background?.name || "Fondo base"}</div>
      <img class="avatar-portrait" src="${avatar.base_image_path || profile.avatar_base_image || "/assets/avatars/neutral_base.png"}" alt="${profile.display_name}" />
      <small>Nv. ${data.level || profile.xp_level || 1}</small>
      <div class="avatar-equipped-list">
        ${equipped.slice(0, 5).map((item) => `<span>${item.name}</span>`).join("") || `<span>Avatar base</span>`}
      </div>
    </div>
  `;
}

function avatarItemCard(item) {
  const locked = !item.unlocked;
  const progressMax = item.unlock_target_xp || item.required_xp || 1;
  const progressValue = item.unlock_progress_xp || 0;
  const lockText = item.unlock_achievement_name ? item.unlock_label : `Nivel ${item.required_level} · ${item.xp_missing} XP restantes`;
  return `
    <article class="avatar-item-card rarity-${item.rarity} ${item.equipped ? "equipped" : ""} ${locked ? "locked" : ""}">
      <img src="${item.image_path || "/assets/avatar/item-accessory.svg"}" alt="${item.name}" />
      <div>
        <strong>${item.name}</strong>
        <small>${rarityLabel(item.rarity)} · Nivel ${item.required_level}</small>
      </div>
      <span class="item-state">${item.equipped ? "Equipado" : locked ? `<i class="lock-mark"></i> Bloqueado` : "Desbloqueado"}</span>
      ${locked ? `
        <div class="item-lock-progress">
          <small>${lockText}</small>
          <progress max="${progressMax}" value="${progressValue}"></progress>
        </div>
      ` : `<button class="btn small" data-avatar-equip="${item.id}" ${item.equipped ? "disabled" : ""}>Equipar</button>`}
    </article>
  `;
}

function renderAchievements(data) {
  return `
    <section class="panel">
      <h2>Logros</h2>
      <div class="achievements">${data.achievements.map((a) => `
        <article class="${a.earned_at ? "earned" : ""}">
          <strong>${a.name}</strong>
          <p>${a.description}</p>
          <small>${a.earned_at ? "Conseguido" : "Pendiente"}</small>
        </article>
      `).join("")}</div>
    </section>
  `;
}

function renderNotifications(data) {
  return `
    <section class="panel notifications-panel">
      <div class="toolbar">
        <div>
          <h2>Notificaciones</h2>
          <small>${data.unread_count || 0} sin leer</small>
        </div>
        <button class="btn small" data-notifications-read-all>Marcar todo como leído</button>
      </div>
      <div class="notification-list">
        ${(data.notifications || []).map((notification) => `
          <article class="notification-card ${notification.status} priority-${notification.priority}">
            <div>
              <span>${notificationTypeLabel(notification.type)}</span>
              <strong>${notification.title}</strong>
              <p>${notification.body}</p>
              <small>${notification.created_at}</small>
            </div>
            ${notification.unread ? `<button class="btn small" data-notification-read="${notification.id}">Leída</button>` : `<small>Leída</small>`}
          </article>
        `).join("") || `<p class="muted">Sin notificaciones todavía.</p>`}
      </div>
    </section>
  `;
}

function renderProfile(data) {
  const p = data.profile;
  return `
    <section class="panel narrow">
      <div class="toolbar"><h2>Perfil</h2><button class="btn small" data-share-card="status">Compartir</button></div>
      <form id="profileForm" class="form">
        <label>Nombre<input name="display_name" value="${escapeHtml(p.display_name)}" /></label>
        <label>Email<input name="email" type="email" value="${escapeHtml(p.email)}" /></label>
        <label>Ciudad${citySelect(p.city)}</label>
        <label>Club habitual<input name="club" value="${escapeHtml(p.club || "")}" /></label>
        <label>Nivel aproximado${levelSelect(p.level_guess)}</label>
        <label>Latitud<input name="lat" type="number" step="0.0001" value="${p.lat}" /></label>
        <label>Longitud<input name="lng" type="number" step="0.0001" value="${p.lng}" /></label>
        <label>Playtomic ID<input name="playtomic_id" value="${escapeHtml(p.playtomic_id || "")}" /></label>
        <input type="hidden" name="playtomic_status" value="${p.playtomic_status || "not_connected"}" />
        <button class="btn" type="submit">Guardar</button>
      </form>
    </section>
  `;
}

function renderPlaytomic(data) {
  const c = data.connection || {};
  return `
    <section class="panel narrow">
      <h2>Playtomic Connect</h2>
      <p class="notice">Arquitectura preparada para API/importacion futura. No scraping.</p>
      <form id="playtomicForm" class="form">
        <label>Playtomic ID<input name="playtomic_id" value="${escapeHtml(c.playtomic_id || "")}" /></label>
        <label>Estado<select name="status">
          ${["not_connected", "pending", "connected"].map((s) => `<option value="${s}" ${c.status === s ? "selected" : ""}>${s}</option>`).join("")}
        </select></label>
        <button class="btn" type="submit">Guardar estado</button>
      </form>
    </section>
  `;
}

function renderAdmin(data) {
  const metrics = data.metrics || {};
  const activity = data.activity || {};
  const competitive = data.competitive || {};
  const health = data.health || {};
  const alerts = data.alerts || [];
  const maxActivity = Math.max(1, ...(activity.series || []).map((day) => (day.users || 0) + (day.matches || 0)));
  return `
    <section class="admin-dashboard">
      <div class="admin-hero panel">
        <div>
          <span class="eyebrow">Founder Dashboard</span>
          <h2>Estado real de PlayUp Padel</h2>
          <p>Usuarios, actividad, ligas, errores y crecimiento operativo en una sola pantalla.</p>
        </div>
        <div class="health-strip">
          <span>DB ${escapeHtml(health.database || "-")}</span>
          <span>${escapeHtml(health.environment || "local")}</span>
          <span>${escapeHtml(health.version || "-")}</span>
          <span>Tests ${health.tests_passed ?? "N/D"}</span>
        </div>
      </div>

      <div class="admin-metrics">
        ${adminMetric("Usuarios", metrics.registered_users)}
        ${adminMetric("Activos hoy", metrics.active_today)}
        ${adminMetric("Activos 7d", metrics.active_7d)}
        ${adminMetric("Partidos", metrics.matches_registered)}
        ${adminMetric("Oficiales", metrics.official_matches)}
        ${adminMetric("Libres", metrics.free_matches)}
        ${adminMetric("Pendientes", metrics.pending_results)}
        ${adminMetric("Invitaciones", metrics.invitations_sent)}
        ${adminMetric("Convertidas", metrics.invitations_converted)}
        ${adminMetric("Ligas", metrics.active_leagues)}
        ${adminMetric("Grupos", metrics.active_groups)}
        ${adminMetric("Feedback beta", metrics.beta_feedback)}
      </div>

      <div class="grid two admin-grid">
        <section class="panel">
          <div class="toolbar">
            <div><h2>Actividad 7 días</h2><small>Registros y partidos creados</small></div>
          </div>
          <div class="activity-chart">
            ${(activity.series || []).map((day) => `
              <div class="activity-bar">
                <span style="height:${Math.max(8, Math.round((((day.users || 0) + (day.matches || 0)) / maxActivity) * 120))}px"></span>
                <small>${day.date.slice(5)}</small>
                <strong>${(day.users || 0) + (day.matches || 0)}</strong>
              </div>
            `).join("")}
          </div>
        </section>
        <section class="panel">
          <div class="toolbar"><h2>Alertas importantes</h2><span>${alerts.length}</span></div>
          <div class="alert-list">
            ${alerts.map((alert) => `<article class="admin-alert ${alert.type}"><strong>${escapeHtml(alert.title)}</strong><small>${escapeHtml(alert.message)}</small></article>`).join("")}
          </div>
        </section>
      </div>

      <section class="panel">
        <div class="toolbar"><h2>Acciones rápidas</h2><input class="admin-search" placeholder="Buscar usuario" /></div>
        <div class="admin-actions">
          <button class="btn" data-admin-action="recalculate-rankings">Recalcular rankings</button>
          <button class="btn" data-admin-action="regenerate-groups">Regenerar grupos</button>
          <button class="btn" data-admin-action="validate-pending-result">Validar resultado pendiente</button>
          <button class="btn" data-admin-action="resolve-dispute">Resolver disputa</button>
          <button class="btn danger" data-admin-action="close-season">Cierre mensual</button>
          <button class="btn secondary" disabled>Ver perfil / suspender usuario</button>
        </div>
      </section>

      <div class="grid two admin-grid">
        <section class="panel">
          <h2>Actividad en tiempo real</h2>
          <div class="admin-events">
            ${adminEventBlock("Últimos registros", activity.latest_registrations, (item) => `${item.display_name} · ${item.city}`)}
            ${adminEventBlock("Últimos partidos", activity.latest_matches, (item) => `#${item.id} ${item.player_a} vs ${item.player_b} · ${item.status}`)}
            ${adminEventBlock("Resultados confirmados", activity.latest_confirmed_results, (item) => `#${item.id} ${item.score} · ${item.player_a} vs ${item.player_b}`)}
            ${adminEventBlock("Retos completados", activity.latest_completed_challenges, (item) => `${item.title} · ${item.challenger} vs ${item.challenged}`)}
            ${adminEventBlock("Ascensos/descensos", activity.latest_movements, (item) => `${item.display_name} · ${item.movement} · ${item.from_division || "-"} -> ${item.to_division || "-"}`)}
            ${adminEventBlock("Usuarios invitados", activity.latest_invitations, (item) => `${item.external_player} · invitado por ${item.invited_by_name}${item.registered_user_id ? " · convertido" : ""}`)}
          </div>
        </section>
        <section class="panel">
          <h2>Errores recientes</h2>
          <div class="admin-error-table">
            ${(data.errors || []).map((error) => `
              <article class="error-row ${error.resolved ? "resolved" : ""}">
                <div><strong>${escapeHtml(error.type)}</strong><small>${escapeHtml(error.display_name || "Sin usuario")} · ${escapeHtml(error.created_at)}</small></div>
                <p>${escapeHtml(error.message)}</p>
                <small>${escapeHtml(error.url || "")}</small>
              </article>
            `).join("") || `<p class="muted">Sin errores registrados.</p>`}
          </div>
        </section>
        <section class="panel">
          <h2>Feedback beta</h2>
          <div class="admin-error-table">
            ${(data.beta_feedback || []).map((item) => `
              <article class="error-row">
                <div><strong>${escapeHtml(item.type)}${item.rating ? ` · ${item.rating}/5` : ""}</strong><small>${escapeHtml(item.display_name || "Sin usuario")} · ${escapeHtml(item.created_at)}</small></div>
                <p>${escapeHtml(item.message)}</p>
                <small>${escapeHtml(item.url || "")}</small>
              </article>
            `).join("") || `<p class="muted">Sin feedback todavía.</p>`}
          </div>
        </section>
      </div>

      <div class="grid two admin-grid">
        <section class="panel">
          <h2>Estado competitivo</h2>
          <div class="stats compact">
            ${stat("Pocos jugadores", (competitive.low_player_groups || []).length)}
            ${stat("En formación", (competitive.forming_groups || []).length)}
            ${stat("Completos", (competitive.complete_groups || []).length)}
            ${stat("Sin grupo", (competitive.users_without_group || []).length)}
            ${stat("Sin partidos", (competitive.users_without_matches || []).length)}
            ${stat("Sin avatar", (competitive.users_without_avatar_complete || []).length)}
            ${stat("Ascenso", (competitive.promotion_zone_users || []).length)}
            ${stat("Descenso", (competitive.relegation_zone_users || []).length)}
          </div>
          <div class="admin-subgrid">
            ${adminSmallList("Grupos con pocos jugadores", competitive.low_player_groups, (group) => `${group.name} · ${group.players} jugadores`)}
            ${adminSmallList("Usuarios sin partidos", competitive.users_without_matches, (user) => `${user.display_name} · ${user.city}`)}
            ${adminSmallList("Usuarios sin avatar completo", competitive.users_without_avatar_complete, (user) => `${user.display_name} · ${user.city}`)}
          </div>
        </section>
        <section class="panel">
          <h2>Conflictos y revisiones</h2>
          <div class="list">${data.conflicts.map((c) => `<div class="row"><span>${escapeHtml(c.player_a)} vs ${escapeHtml(c.player_b)}</span><small>${escapeHtml(c.score)} · ${escapeHtml(c.reason)}</small></div>`).join("") || `<p class="muted">Sin conflictos abiertos.</p>`}</div>
        </section>
      </div>
    </section>
  `;
}

function adminMetric(label, value) {
  return `<article class="admin-metric"><span>${label}</span><strong>${value ?? 0}</strong></article>`;
}

function adminEventBlock(title, items = [], renderItem) {
  return `
    <article class="admin-event-block">
      <h3>${title}</h3>
      ${(items || []).slice(0, 5).map((item) => `<div><span>${escapeHtml(renderItem(item))}</span><small>${escapeHtml(item.created_at || item.confirmed_at || item.completed_at || item.accepted_at || "")}</small></div>`).join("") || `<p class="muted">Sin datos.</p>`}
    </article>
  `;
}

function adminSmallList(title, items = [], renderItem) {
  return `
    <article class="admin-small-list">
      <h3>${title}</h3>
      ${(items || []).slice(0, 6).map((item) => `<div>${escapeHtml(renderItem(item))}</div>`).join("") || `<p class="muted">Sin datos.</p>`}
    </article>
  `;
}

function bindViewEvents() {
  document.querySelectorAll("[data-open-feedback]").forEach((button) => button.addEventListener("click", () => {
    state.betaFeedbackOpen = true;
    state.betaFeedbackType = button.dataset.openFeedback || "feedback";
    renderBetaFeedbackModal();
  }));
  document.querySelector("#matchForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await api("/api/matches", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) });
    await loadView();
  });
  document.querySelector("#freeMatchForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = await api("/api/free-matches", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) });
    state.feedback = data.feedback || null;
    state.boot = await api("/api/bootstrap");
    renderShell();
    await loadView();
  });
  document.querySelectorAll("[data-invite-free-match]").forEach((button) => button.addEventListener("click", async () => {
    await api(`/api/free-matches/${button.dataset.inviteFreeMatch}/invitations`, { method: "POST" });
    await loadView();
  }));
  document.querySelectorAll("[data-confirm]").forEach((button) => button.addEventListener("click", async () => {
    const data = await api(`/api/matches/${button.dataset.confirm}/confirm`, { method: "POST" });
    state.feedback = data.feedback || null;
    await loadView();
  }));
  document.querySelectorAll("[data-conflict]").forEach((button) => button.addEventListener("click", async () => {
    await api(`/api/matches/${button.dataset.conflict}/conflict`, { method: "POST", body: JSON.stringify({ reason: "Discrepancia reportada por el rival." }) });
    await loadView();
  }));
  document.querySelectorAll("[data-go-view]").forEach((button) => button.addEventListener("click", async () => {
    state.view = button.dataset.goView;
    renderShell();
    await loadView();
  }));
  document.querySelectorAll("[data-jump-play-now]").forEach((button) => button.addEventListener("click", () => {
    document.querySelector(".home-play-now, .play-now")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
  document.querySelectorAll("[data-starter-claim]").forEach((button) => button.addEventListener("click", async () => {
    const data = await api("/api/starter-mission/claim", { method: "POST" });
    state.feedback = data.feedback || null;
    state.boot = await api("/api/bootstrap");
    renderShell();
    await loadView();
  }));
  document.querySelectorAll("[data-home-challenge]").forEach((button) => button.addEventListener("click", async () => {
    await api("/api/challenges", { method: "POST", body: JSON.stringify({ type: "automatic", challenged_id: button.dataset.homeChallenge }) });
    state.view = "challenges";
    renderShell();
    await loadView();
  }));
  document.querySelectorAll("[data-notification-read]").forEach((button) => button.addEventListener("click", async () => {
    const data = await api(`/api/notifications/${button.dataset.notificationRead}/read`, { method: "POST" });
    state.boot = await api("/api/bootstrap");
    renderShell();
    document.querySelector("#view").innerHTML = renderNotifications(data);
    bindViewEvents();
  }));
  document.querySelectorAll("[data-notifications-read-all]").forEach((button) => button.addEventListener("click", async () => {
    const data = await api("/api/notifications/read-all", { method: "POST" });
    state.boot = await api("/api/bootstrap");
    renderShell();
    document.querySelector("#view").innerHTML = renderNotifications(data);
    bindViewEvents();
  }));
  document.querySelectorAll("[data-share-card]").forEach((button) => button.addEventListener("click", async () => {
    await openShareCard(button.dataset.shareCard || "status");
  }));
  document.querySelectorAll("[data-availability]").forEach((button) => button.addEventListener("click", async () => {
    await api("/api/availability", { method: "POST", body: JSON.stringify({ available: button.dataset.availability === "1" }) });
    await loadView();
  }));
  document.querySelectorAll("[data-first-match-plan]").forEach((button) => button.addEventListener("click", async () => {
    state.firstMatchDraft = true;
    await loadView();
  }));
  document.querySelectorAll("[data-create-match-request]").forEach((button) => button.addEventListener("click", async () => {
    await api("/api/availability", { method: "POST", body: JSON.stringify({ available: true, message: "Busco mi primer partido competitivo." }) });
    state.firstMatchDraft = false;
    await loadView();
  }));
  document.querySelectorAll("[data-create-play-now]").forEach((button) => button.addEventListener("click", async () => {
    if (button.disabled) return;
    const data = await api("/api/play-now/create-match", { method: "POST", body: JSON.stringify({}) });
    state.feedback = data.feedback || null;
    state.firstMatchDraft = false;
    renderShell();
    await loadView();
  }));
  document.querySelectorAll("[data-join-request]").forEach((button) => button.addEventListener("click", async () => {
    await api(`/api/match-requests/${button.dataset.joinRequest}/join`, { method: "POST" });
    await loadView();
  }));
  document.querySelector("#challengeForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await api("/api/challenges", { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) });
    await loadView();
  });
  document.querySelectorAll("[data-auto-challenge]").forEach((button) => button.addEventListener("click", async () => {
    await api("/api/challenges", { method: "POST", body: JSON.stringify({ type: "automatic", challenged_id: button.dataset.autoChallenge }) });
    await loadView();
  }));
  document.querySelectorAll("[data-challenge-accept]").forEach((button) => button.addEventListener("click", async () => {
    await api(`/api/challenges/${button.dataset.challengeAccept}/accept`, { method: "POST" });
    await loadView();
  }));
  document.querySelectorAll("[data-challenge-reject]").forEach((button) => button.addEventListener("click", async () => {
    await api(`/api/challenges/${button.dataset.challengeReject}/reject`, { method: "POST" });
    await loadView();
  }));
  document.querySelectorAll("[data-challenge-result]").forEach((form) => form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await api(`/api/challenges/${form.dataset.challengeResult}/submit-result`, { method: "POST", body: JSON.stringify(Object.fromEntries(new FormData(form))) });
    await loadView();
  }));
  document.querySelectorAll("[data-monthly-claim]").forEach((button) => button.addEventListener("click", async () => {
    const data = await api(`/api/monthly-challenges/${button.dataset.monthlyClaim}/claim`, { method: "POST" });
    state.feedback = data.feedback || null;
    state.boot = await api("/api/bootstrap");
    await loadView();
  }));
  document.querySelector("#leaderboardOrder")?.addEventListener("change", async (event) => {
    document.querySelector("#view").innerHTML = renderLeaderboard(await api(`/api/leaderboard?order=${event.target.value}`));
    bindViewEvents();
  });
  document.querySelector("#profileForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await api("/api/profile", { method: "PUT", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) });
    state.boot = await api("/api/bootstrap");
    renderShell();
    await loadView();
  });
  document.querySelector("#playtomicForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    await api("/api/playtomic", { method: "PUT", body: JSON.stringify(Object.fromEntries(new FormData(event.currentTarget))) });
    await loadView();
  });
  document.querySelectorAll("[data-avatar-filter]").forEach((button) => button.addEventListener("click", async () => {
    state.avatarFilter = button.dataset.avatarFilter;
    await loadView();
  }));
  document.querySelectorAll("[data-avatar-equip]").forEach((button) => button.addEventListener("click", async () => {
    if (button.disabled) return;
    try {
      await api("/api/avatar", { method: "PUT", body: JSON.stringify({ item_id: button.dataset.avatarEquip }) });
      state.boot = await api("/api/bootstrap");
      renderShell();
      await loadView();
    } catch (error) {
      state.feedback = {
        type: "neutral",
        title: "Item bloqueado",
        message: error.message,
        ranking_label: "Sigue ganando XP",
      };
      renderFeedbackOverlay();
    }
  }));
  document.querySelectorAll("[data-avatar-base]").forEach((button) => button.addEventListener("click", async () => {
    await api("/api/avatar", { method: "PUT", body: JSON.stringify({ base_avatar_id: button.dataset.avatarBase }) });
    state.boot = await api("/api/bootstrap");
    renderShell();
    await loadView();
  }));
  document.querySelectorAll("[data-admin-action]").forEach((button) => button.addEventListener("click", async () => {
    await api(`/api/admin/${button.dataset.adminAction}`, { method: "POST" });
    state.boot = await api("/api/bootstrap");
    renderShell();
    await loadView();
  }));
}

function renderBetaFeedbackModal() {
  document.querySelector(".beta-feedback-overlay")?.remove();
  if (!state.betaFeedbackOpen) return;
  const isBug = state.betaFeedbackType === "bug";
  const overlay = document.createElement("div");
  overlay.className = "beta-feedback-overlay";
  overlay.innerHTML = `
    <section class="beta-feedback-card">
      <button class="close-btn" data-close-beta-feedback type="button">×</button>
      <span class="eyebrow">Beta cerrada</span>
      <h2>${isBug ? "Reportar error" : "Feedback rápido"}</h2>
      <p>${isBug ? "Cuéntanos qué ha fallado y en qué pantalla estabas." : "Dinos qué mejorarías o qué te ha resultado confuso."}</p>
      <form id="betaFeedbackForm" class="form">
        <input type="hidden" name="type" value="${isBug ? "bug" : "feedback"}" />
        <label>Valoración<select name="rating">
          <option value="">Sin valoración</option>
          <option value="5">5 · Muy bien</option>
          <option value="4">4 · Bien</option>
          <option value="3">3 · Mejorable</option>
          <option value="2">2 · Confuso</option>
          <option value="1">1 · Bloqueante</option>
        </select></label>
        <label>Mensaje<textarea name="message" rows="4" placeholder="${isBug ? "Ej: Al confirmar resultado aparece un error..." : "Ej: Me costó entender cómo crear mi primer partido..."}" required></textarea></label>
        <div class="actions">
          <button class="btn" type="submit">${isBug ? "Enviar error" : "Enviar feedback"}</button>
          <button class="btn secondary" type="button" data-close-beta-feedback>Cancelar</button>
        </div>
      </form>
    </section>
  `;
  document.body.appendChild(overlay);
  overlay.querySelectorAll("[data-close-beta-feedback]").forEach((button) => button.addEventListener("click", closeBetaFeedback));
  overlay.querySelector("#betaFeedbackForm").addEventListener("submit", submitBetaFeedback);
}

function closeBetaFeedback() {
  state.betaFeedbackOpen = false;
  document.querySelector(".beta-feedback-overlay")?.remove();
}

async function submitBetaFeedback(event) {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(event.currentTarget));
  body.url = location.href;
  try {
    const response = await api("/api/feedback", { method: "POST", body: JSON.stringify(body) });
    closeBetaFeedback();
    state.feedback = {
      type: "challenge_reward",
      title: "Feedback recibido",
      message: response.message || "Gracias por ayudarnos a mejorar la beta.",
      reward_item: "Beta cerrada",
      achievement: "Feedback",
      xp_gained: 0,
      ranking_label: "Equipo avisado",
    };
    renderFeedbackOverlay();
  } catch (error) {
    event.currentTarget.insertAdjacentHTML("beforeend", `<p class="notice danger">${escapeHtml(error.message)}</p>`);
  }
}

function renderFeedbackOverlay() {
  document.querySelector(".feedback-overlay")?.remove();
  if (!state.feedback) return;
  const feedback = state.feedback;
  const isChallengeReward = feedback.type === "challenge_reward";
  const isMatchCreated = feedback.type === "match_created";
  const overlay = document.createElement("div");
  overlay.className = `feedback-overlay ${feedback.type}`;
  overlay.innerHTML = `
    <section class="feedback-card">
      ${feedback.type === "victory" || isChallengeReward ? `<div class="feedback-burst"><i></i><i></i><i></i><i></i><i></i></div>` : ""}
      <span class="feedback-kicker">${isMatchCreated ? "Primer paso listo" : isChallengeReward ? "Recompensa" : feedback.type === "victory" ? "Victoria" : "Partido confirmado"}</span>
      <h2>${escapeHtml(feedback.title)}</h2>
      <p>${escapeHtml(feedback.message)}</p>
      ${isMatchCreated ? `
        <div class="created-match-summary">
          <strong>${escapeHtml(feedback.summary)}</strong>
          <div class="first-match-lineup">
            <div>${(feedback.team_a || []).map(playerMini).join("")}</div>
            <strong>vs</strong>
            <div>${(feedback.team_b || []).map(playerMini).join("")}</div>
          </div>
        </div>
      ` : `<div class="feedback-stats">
        <div><strong>${escapeHtml(feedback.score || feedback.reward_item || "-")}</strong><span>${isChallengeReward ? "Item" : "Marcador"}</span></div>
        <div><strong>${escapeHtml(feedback.achievement || `+${feedback.points_gained || 0}`)}</strong><span>${isChallengeReward ? "Insignia" : "Puntos"}</span></div>
        <div><strong>+${feedback.xp_gained || 0} XP</strong><span>XP ganada</span></div>
        <div><strong>${escapeHtml(feedback.ranking_label || (isChallengeReward ? "Temporada actualizada" : "Ranking actualizado"))}</strong><span>${isChallengeReward ? "Estado" : "Clasificacion"}</span></div>
      </div>`}
      <button class="btn" data-close-feedback>Continuar</button>
    </section>
  `;
  document.body.appendChild(overlay);
  overlay.querySelector("[data-close-feedback]").addEventListener("click", () => {
    state.feedback = null;
    renderFeedbackOverlay();
  });
}

async function openShareCard(type = "status") {
  const data = await api(`/api/share-card?type=${encodeURIComponent(type)}&format=story`);
  renderShareOverlay(data.card);
}

function renderShareOverlay(card) {
  document.querySelector(".share-overlay")?.remove();
  const overlay = document.createElement("div");
  overlay.className = "share-overlay";
  overlay.innerHTML = `
    <section class="share-panel">
      <div class="toolbar">
        <div>
          <span class="eyebrow">Compartir progreso</span>
          <h2>${escapeHtml(card.headline)}</h2>
        </div>
        <button class="btn secondary small" data-close-share>Cerrar</button>
      </div>
      <div class="share-options">
        <label>Tipo<select data-share-type>
          ${[
            ["status", "Estado competitivo"],
            ["promotion_gap", "Me faltan puntos"],
            ["promoted", "Ascenso"],
            ["avatar_unlock", "Item desbloqueado"],
            ["monthly_challenge", "Reto mensual"],
          ].map(([value, label]) => `<option value="${value}" ${card.type === value ? "selected" : ""}>${label}</option>`).join("")}
        </select></label>
        <label>Formato<select data-share-format>
          <option value="story" ${card.format === "story" ? "selected" : ""}>Story 1080x1920</option>
          <option value="square" ${card.format === "square" ? "selected" : ""}>Cuadrado 1080x1080</option>
        </select></label>
      </div>
      <canvas class="share-canvas" width="${card.dimensions.width}" height="${card.dimensions.height}"></canvas>
      <div class="share-link">
        <span>${escapeHtml(card.cta)}</span>
        <input readonly value="${escapeHtml(card.share_url)}" />
      </div>
      <div class="actions">
        <button class="btn" data-share-download>Exportar imagen</button>
      </div>
    </section>
  `;
  document.body.appendChild(overlay);
  const canvas = overlay.querySelector("canvas");
  drawShareCard(canvas, card);
  overlay.querySelector("[data-close-share]").addEventListener("click", () => overlay.remove());
  overlay.querySelector("[data-share-download]").addEventListener("click", () => downloadCanvas(canvas, `playup-${card.format}.png`));
  overlay.querySelector("[data-share-type]").addEventListener("change", async (event) => {
    const format = overlay.querySelector("[data-share-format]").value;
    const data = await api(`/api/share-card?type=${encodeURIComponent(event.target.value)}&format=${encodeURIComponent(format)}`);
    overlay.remove();
    renderShareOverlay(data.card);
  });
  overlay.querySelector("[data-share-format]").addEventListener("change", async (event) => {
    const selectedType = overlay.querySelector("[data-share-type]").value;
    const data = await api(`/api/share-card?type=${encodeURIComponent(selectedType)}&format=${encodeURIComponent(event.target.value)}`);
    overlay.remove();
    renderShareOverlay(data.card);
  });
}

async function drawShareCard(canvas, card) {
  const ctx = canvas.getContext("2d");
  const { width, height } = card.dimensions;
  canvas.width = width;
  canvas.height = height;
  const square = width === height;
  const pad = square ? 78 : 92;
  ctx.fillStyle = "#07111a";
  ctx.fillRect(0, 0, width, height);
  const gradient = ctx.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, "rgba(99,210,183,.34)");
  gradient.addColorStop(.55, "rgba(201,247,100,.18)");
  gradient.addColorStop(1, "rgba(255,255,255,.05)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);

  await drawImageCover(ctx, card.logo_path, pad, pad, 140, 140, 24);
  ctx.fillStyle = "#ffffff";
  ctx.font = "900 54px Inter, sans-serif";
  ctx.fillText("PlayUp Padel", pad + 168, pad + 86);
  ctx.fillStyle = "#c7f464";
  ctx.font = "800 28px Inter, sans-serif";
  ctx.fillText("Liga amateur competitiva", pad + 170, pad + 124);

  await drawImageCover(ctx, card.player.avatar, pad, square ? 255 : 360, square ? 250 : 340, square ? 250 : 340, 34);
  ctx.fillStyle = "#ffffff";
  ctx.font = `1000 ${square ? 58 : 72}px Inter, sans-serif`;
  wrapText(ctx, card.headline, pad, square ? 570 : 790, width - pad * 2, square ? 66 : 82);
  ctx.fillStyle = "rgba(255,255,255,.72)";
  ctx.font = `700 ${square ? 28 : 34}px Inter, sans-serif`;
  wrapText(ctx, card.subheadline, pad, square ? 708 : 985, width - pad * 2, square ? 36 : 44);

  const y = square ? 800 : 1180;
  drawMetric(ctx, "Posición", card.competition.position_label, pad, y, 210, 130);
  drawMetric(ctx, "División", card.player.division, pad + 230, y, 300, 130);
  drawMetric(ctx, "Puntos", String(card.competition.points), pad + 550, y, 180, 130);
  drawMetric(ctx, "Partidos", `${card.competition.played}/10`, pad + 750, y, 210, 130);

  ctx.fillStyle = card.competition.status === "promotion" ? "#c7f464" : card.competition.status === "relegation" ? "#ff6b4a" : "#63d2b7";
  roundRect(ctx, pad, y + 164, width - pad * 2, 86, 22, true);
  ctx.fillStyle = "#07111a";
  ctx.font = "1000 36px Inter, sans-serif";
  ctx.fillText(card.competition.status_label, pad + 30, y + 219);

  drawQr(ctx, card.qr_matrix, width - pad - 182, height - pad - 182, 182, card.share_url);
  ctx.fillStyle = "#ffffff";
  ctx.font = "900 34px Inter, sans-serif";
  ctx.fillText(card.cta, pad, height - pad - 108);
  ctx.fillStyle = "rgba(255,255,255,.66)";
  ctx.font = "700 24px Inter, sans-serif";
  ctx.fillText(card.share_url, pad, height - pad - 64);
}

function drawMetric(ctx, label, value, x, y, w, h) {
  ctx.fillStyle = "rgba(255,255,255,.12)";
  roundRect(ctx, x, y, w, h, 18, true);
  ctx.fillStyle = "rgba(255,255,255,.68)";
  ctx.font = "800 21px Inter, sans-serif";
  ctx.fillText(label, x + 18, y + 38);
  ctx.fillStyle = "#fff";
  ctx.font = value.length > 10 ? "900 26px Inter, sans-serif" : "1000 44px Inter, sans-serif";
  ctx.fillText(value, x + 18, y + 92);
}

function drawQr(ctx, matrix, x, y, size, fallbackText = "") {
  ctx.fillStyle = "#fff";
  roundRect(ctx, x, y, size, size, 16, true);
  if (!matrix || !matrix.length) {
    ctx.fillStyle = "#07111a";
    ctx.font = "900 24px Inter, sans-serif";
    ctx.fillText("PlayUp Padel", x + 28, y + 72);
    ctx.font = "700 13px Inter, sans-serif";
    wrapText(ctx, fallbackText, x + 20, y + 108, size - 40, 18);
    return;
  }
  const cells = matrix.length;
  const cell = (size - 26) / cells;
  ctx.fillStyle = "#07111a";
  matrix.forEach((row, rowIndex) => row.forEach((active, colIndex) => {
    if (active) ctx.fillRect(x + 13 + colIndex * cell, y + 13 + rowIndex * cell, Math.ceil(cell), Math.ceil(cell));
  }));
}

async function drawImageCover(ctx, src, x, y, w, h, radius = 0) {
  try {
    const image = await loadImage(src);
    ctx.save();
    roundRect(ctx, x, y, w, h, radius, false);
    ctx.clip();
    ctx.drawImage(image, x, y, w, h);
    ctx.restore();
  } catch {
    ctx.fillStyle = "#c7f464";
    roundRect(ctx, x, y, w, h, radius, true);
  }
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = src;
  });
}

function roundRect(ctx, x, y, w, h, r, fill) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  if (fill) ctx.fill();
}

function wrapText(ctx, text, x, y, maxWidth, lineHeight) {
  const words = String(text).split(" ");
  let line = "";
  for (const word of words) {
    const testLine = `${line}${word} `;
    if (ctx.measureText(testLine).width > maxWidth && line) {
      ctx.fillText(line.trim(), x, y);
      line = `${word} `;
      y += lineHeight;
    } else {
      line = testLine;
    }
  }
  ctx.fillText(line.trim(), x, y);
}

function downloadCanvas(canvas, filename) {
  const link = document.createElement("a");
  link.download = filename;
  link.href = canvas.toDataURL("image/png");
  link.click();
}

function rankingTable(rows) {
  return `<table class="standings-table"><thead><tr><th>#</th><th>Jugador</th><th>Pts</th><th>PJ</th><th>V</th><th>D</th><th>Set avg</th><th>Game avg</th><th>Situacion</th><th>Zona</th></tr></thead><tbody>
    ${rows.map((r) => `<tr class="zone-${r.movement_zone}"><td>${movementIcon(r.movement_zone)} ${r.rank_position}</td><td>${playerMini(r)}</td><td>${r.points}</td><td>${r.played}</td><td>${r.wins}</td><td>${r.losses}</td><td>${signed(r.set_average)}</td><td>${signed(r.game_average)}</td><td>${standingSituation(r)}</td><td>${zone(r.movement_zone)}</td></tr>`).join("")}
  </tbody></table>`;
}

function playerRow(player) {
  return `<div class="row player-row">${playerMini(player)}<small>${player.city || player.division_name || "-"} · ${player.rating}</small></div>`;
}

function playerMini(player = {}) {
  return `<div class="player-mini">${playerAvatar(player)}<div><strong>${escapeHtml(player.display_name || "Jugador")}</strong><small>${escapeHtml(player.division_name || player.level_guess || "")}${player.rating ? ` · ${player.rating}` : ""}</small></div></div>`;
}

function playerAvatar(player = {}, extraClass = "", badge = "") {
  const seedClass = player.user_id ? `avatar-seed-${Number(player.user_id) % 8}` : "";
  const genderClass = player.gender ? `avatar-${player.gender}` : "";
  if (player.avatar_base_image) {
    return `<span class="avatar avatar-image ${seedClass} ${genderClass} ${extraClass} ${player.equipped_frame_name ? "framed" : ""}"><img src="${player.avatar_base_image}" alt="${escapeHtml(player.display_name || "Jugador")}" /><i></i>${badge}</span>`;
  }
  return `<span class="avatar ${seedClass} ${genderClass} ${extraClass}">${initials(player.display_name || "PU")}<i></i>${badge}</span>`;
}

function playerActionCard(player = {}) {
  return `<div class="player-action-card">${playerMini(player)}<span>${player.rating ? `${player.rating} rating` : "Rating pendiente"}</span>${availabilityPill(player)}</div>`;
}

function matchPlayerMini(player = {}) {
  return `
    <div class="match-player">
      ${playerMini(player)}
      <div class="reward-line"><span>${pointsLabel(player.match_points || 0)}</span><span>+${player.match_xp || 0} XP</span></div>
    </div>
  `;
}

function availabilityPill(player = {}) {
  return `<span class="availability-pill ${player.available_for_play ? "available" : ""}">${player.available_for_play ? "Disponible" : "Activo"}</span>`;
}

function rarityLabel(rarity = "comun") {
  return {
    comun: "Comun",
    poco_comun: "Poco comun",
    raro: "Raro",
    epico: "Epico",
    legendario: "Legendario",
  }[rarity] || rarity;
}

function notificationTypeLabel(type = "") {
  return {
    competition: "Competición",
    activity: "Actividad",
    challenge: "Retos",
    match: "Partidos",
    inactivity: "Inactividad",
    reward: "Recompensas",
    avatar_unlock: "Recompensas",
  }[type] || type;
}

function teamNames(players = []) {
  return players.length ? players.map((player) => player.display_name).join(" / ") : "Buscando pareja";
}

function playerOptions(players = [], selectedIndex = 0) {
  return players.map((p, index) => `<option value="${p.user_id}" ${index === selectedIndex ? "selected" : ""}>${p.display_name} · ${p.level_guess || p.division_name || ""} · ${p.rating}</option>`).join("");
}

function pointsLabel(points) {
  return points === 1 ? "1 punto individual" : `${points} pts individuales`;
}

function citySelect(selected = "Madrid") {
  const cities = ["Madrid", "Alcobendas", "Getafe", "Barcelona", "Sabadell", "Valencia", "Sevilla", "Malaga"];
  return `<select name="city">${cities.map((city) => `<option ${city === selected ? "selected" : ""}>${city}</option>`).join("")}</select>`;
}

function levelSelect(selected = "Intermedio") {
  return `<select name="level_guess">${["Iniciacion", "Intermedio", "Avanzado", "Competicion"].map((level) => `<option ${level === selected ? "selected" : ""}>${level}</option>`).join("")}</select>`;
}

function quickLevelSelect(selected = "Intermedio") {
  return `<select name="level_guess">${["Principiante", "Intermedio", "Avanzado"].map((level) => `<option ${level === selected ? "selected" : ""}>${level}</option>`).join("")}</select>`;
}

function stat(label, value) {
  return `<div class="stat"><strong>${value}</strong><span>${label}</span></div>`;
}

function titleFor(id) {
  return (views.find(([view]) => view === id) || ["", "PlayUp Padel"])[1];
}

function initials(name = "PU") {
  return name.split(/\s+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

function signed(value) {
  return value > 0 ? `+${value}` : value;
}

function zone(value) {
  if (value === "promotion") return `<span class="up">↑ Ascenso</span>`;
  if (value === "relegation") return `<span class="down">↓ Descenso</span>`;
  return "Mantiene";
}

function standingSituation(row) {
  if (row.movement_zone === "promotion") return `<span class="standing-note up">↑ Ascenso</span>`;
  if (row.movement_zone === "relegation") return `<span class="standing-note down">↓ Descenso</span>`;
  return `<span class="standing-note">${escapeHtml(row.standing_note || distanceToNext(row.points_to_next_position))}</span>`;
}

function movementIcon(value) {
  if (value === "promotion") return `<span class="up">↑</span>`;
  if (value === "relegation") return `<span class="down">↓</span>`;
  return `<span class="muted">·</span>`;
}

function distanceToNext(value) {
  return value === 0 ? "Lider" : `+${value}`;
}

function escapeHtml(value) {
  return String(value || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

setupPwa();
boot();
