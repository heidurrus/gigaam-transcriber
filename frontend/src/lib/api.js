// Thin client for the local Flask API. Errors carry the server's message.

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body || {};
  }
}

export async function api(path, { method = "GET", body, form, headers } = {}) {
  const init = { method, headers: { ...(headers || {}) } };
  if (form) init.body = form;
  else if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  let data = null;
  try { data = await res.json(); } catch (_) { /* not JSON */ }
  if (!res.ok) throw new ApiError((data && data.error) || `HTTP ${res.status}`, res.status, data);
  return data;
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

// Poll a job until it finishes. onUpdate(job) gets every intermediate state
// (progress, streamed partial text). Resolves with the finished job.
export async function pollJob(jobId, onUpdate, { interval = 700, signal } = {}) {
  while (true) {
    if (signal && signal.aborted) throw new DOMException("aborted", "AbortError");
    const job = await api(`/job/${jobId}`);
    if (onUpdate) onUpdate(job);
    if (job.status === "done") return job;
    if (job.status === "error") throw new ApiError(job.error || "failed", 500, job);
    await sleep(interval);
  }
}
