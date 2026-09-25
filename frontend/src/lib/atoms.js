// Atom extraction started from any screen; progress lives in app.extracting.
import { api, pollJob } from "./api.js";
import { app, t, go, toast, loadSources } from "./state.svelte.js";

export async function extractAtoms(sourceId) {
  if (app.extracting[sourceId]) return;
  app.extracting[sourceId] = { jobId: null, progress: 0, message: t("at.reading") };
  try {
    const { job_id } = await api(`/api/sources/${sourceId}/atoms/extract`, { method: "POST" });
    const job = await pollJob(job_id, j => {
      app.extracting[sourceId] = { jobId: job_id, progress: j.progress || 0, message: j.progress_msg || "" };
    }, { interval: 800 });
    const r = job.result;
    app.atomsVersion++;
    loadSources();
    const parts = [t("at.found", { n: r.extracted })];
    if (r.merged) parts.push(t("at.merged_n", { n: r.merged }));
    if (r.conflicts) parts.push(t("at.conflicts_n", { n: r.conflicts }));
    toast(parts.join(" · "), app.route.name === "atoms" ? {} : { action: t("at.open"), onAction: () => go("/atoms") });
  } catch (err) {
    const setup = err.body?.needs_setup || /API key|Settings/.test(err.message);
    toast(err.message, { kind: "danger", ...(setup ? { action: t("nav.settings"), onAction: () => go("/settings") } : {}) });
  } finally {
    delete app.extracting[sourceId];
  }
}
