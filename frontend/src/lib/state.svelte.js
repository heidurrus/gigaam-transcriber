// App-wide state (Svelte 5 runes). Components read and mutate `app` directly.
import { api } from "./api.js";
import { translate } from "./i18n.js";

function readPref(key, fallback) {
  try { const v = localStorage.getItem("wb." + key); return v === null ? fallback : JSON.parse(v); }
  catch (_) { return fallback; }
}
export function writePref(key, value) {
  try { localStorage.setItem("wb." + key, JSON.stringify(value)); } catch (_) { /* private mode */ }
}

export function parseRoute(hash = location.hash) {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "source" && parts[1]) return { name: "transcript", id: parts[1], summarize: parts[2] === "summarize",
                                                  seg: parts[2] === "seg" ? Number(parts[3]) : null };
  if (parts[0] === "atoms") return { name: "atoms", source: parts[1] === "source" ? parts[2] : null };
  if (parts[0] === "settings") return { name: "settings" };
  if (parts[0] === "transcript") return { name: "transcript", id: null };
  return { name: "sources" };
}

export const app = $state({
  route: parseRoute(),
  lang: readPref("lang", "ru"),
  projects: [],
  archivedProjects: [],
  currentProjectId: null,
  sources: [],
  lastSourceId: readPref("lastSource", null),
  device: { cuda: false, mps: false, gpu_name: null, desktop: false },
  health: null,
  models: [],
  options: readPref("asrOptions", { model: "v3_e2e_rnnt", device: "cpu", diarize: false, word_timestamps: false }),
  toast: null,
  // source id → { jobId, progress, message } for work started in this session
  jobs: {},
  // source id → { jobId, progress, message } for atom extraction
  extracting: {},
  atomsVersion: 0,          // bumped when atoms change elsewhere, so open screens reload
});

export const t = (key, vars) => translate(app.lang, key, vars);

export function go(path) {
  if (location.hash !== "#" + path) location.hash = path;
  else app.route = parseRoute();
}
window.addEventListener("hashchange", () => { app.route = parseRoute(); });

export function setLang(lang) {
  app.lang = lang;
  writePref("lang", lang);
  document.documentElement.lang = lang;
}

export function saveOptions() { writePref("asrOptions", app.options); }

export function currentProject() {
  return app.projects.find(p => p.id === app.currentProjectId) || null;
}

export async function loadProjects() {
  const body = await api("/api/projects?archived=1");
  app.projects = body.projects.filter(p => !p.archived);
  app.archivedProjects = body.projects.filter(p => p.archived);
  app.currentProjectId = body.current_project_id;
}

export async function loadSources() {
  if (!app.currentProjectId) return;
  const body = await api(`/api/projects/${app.currentProjectId}/sources`);
  app.sources = body.sources;
}

export async function switchProject(id) {
  await api(`/api/projects/${id}/current`, { method: "POST" });
  app.currentProjectId = id;
  app.sources = [];
  await loadSources();
  go("/sources");
}

let toastTimer = null;
export function toast(message, { action, onAction, kind = "info", ms = 6000 } = {}) {
  clearTimeout(toastTimer);
  app.toast = { message, action, onAction, kind };
  toastTimer = setTimeout(() => { app.toast = null; }, ms);
}

export function rememberSource(id) {
  app.lastSourceId = id;
  writePref("lastSource", id);
}
