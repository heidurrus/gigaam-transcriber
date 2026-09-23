<script>
  import Block from "../components/Block.svelte";
  import Icon from "../components/Icon.svelte";
  import { api, pollJob } from "../lib/api.js";
  import { DesktopRecorder, BrowserRecorder, listMicrophones } from "../lib/recorder.js";
  import { fmtDate, fmtDuration, isTranscriptFile } from "../lib/format.js";
  import { app, t, go, loadSources, saveOptions, toast, rememberSource } from "../lib/state.svelte.js";

  // ── upload ────────────────────────────────────────────────────────────────
  let file = $state(null);
  let dragging = $state(false);
  let uploading = $state(false);
  let uploadError = $state("");
  const fileIsTranscript = $derived(file ? isTranscriptFile(file.name) : false);

  function pickFile(f) { if (f) { file = f; uploadError = ""; } }

  function optionsPayload() {
    const o = app.options;
    return { model: o.model, device: o.device, diarize: String(o.diarize),
             word_timestamps: String(!o.diarize && o.word_timestamps) };
  }

  async function submitUpload(f = file, kind = null) {
    uploading = true;
    uploadError = "";
    try {
      const form = new FormData();
      form.append("audio", f);
      form.append("project_id", app.currentProjectId);
      Object.entries(optionsPayload()).forEach(([k, v]) => form.append(k, v));
      if (kind) form.append("kind", kind);
      const res = await api("/transcribe", { method: "POST", form });
      file = null;
      await loadSources();
      if (isTranscriptFile(f.name)) {
        rememberSource(res.source_id);
        go(`/source/${res.source_id}/summarize`);   // imported: go straight to the summary
      } else {
        track(res.source_id, res.job_id);
      }
    } catch (err) {
      uploadError = err.message;
    } finally {
      uploading = false;
    }
  }

  // Follow a transcription job; the list row shows its progress.
  async function track(sourceId, jobId) {
    app.jobs[sourceId] = { jobId, progress: 0, message: "" };
    try {
      await pollJob(jobId, job => {
        app.jobs[sourceId] = { jobId, progress: job.progress || 0, message: job.progress_msg || "" };
      });
      delete app.jobs[sourceId];
      await loadSources();
      const s = app.sources.find(x => x.id === sourceId);
      toast(`${s ? s.title : ""} · ${t("status.ready")}`, { action: t("nav.transcript"), onAction: () => open(sourceId) });
    } catch (err) {
      delete app.jobs[sourceId];
      await loadSources();
      toast(err.message, { kind: "danger" });
    }
  }

  async function transcribeSaved(sourceId) {
    try {
      const res = await api(`/api/sources/${sourceId}/transcribe`, { method: "POST", body: optionsPayload() });
      await loadSources();
      track(sourceId, res.job_id);
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  // ── recording ─────────────────────────────────────────────────────────────
  let mics = $state([]);
  let mic = $state("");
  let recorder = null;
  let recording = $state(false);
  let recStarted = $state(0);
  let elapsed = $state(0);
  let recProblems = $state([]);
  let recError = $state("");
  let timer = null;

  $effect(() => { listMicrophones(app.device.desktop).then(m => (mics = m)); });

  const channelName = c => t(c === "mic" ? "channel.mic" : "channel.sys");

  async function startRecording() {
    recError = "";
    recProblems = [];
    try {
      if (app.device.desktop) {
        recorder = new DesktopRecorder();
        await recorder.start(mic === "" ? null : Number(mic), st => {
          recProblems = Object.entries(st.channels || {}).filter(([, c]) => c.error)
            .map(([n, c]) => `${channelName(n)}: ${c.error}`);
        });
      } else {
        recorder = new BrowserRecorder();
        await recorder.start(mic, which => recProblems = [...recProblems, `${channelName(which)}: —`]);
      }
      recording = true;
      recStarted = Date.now();
      elapsed = 0;
      timer = setInterval(() => (elapsed = Math.floor((Date.now() - recStarted) / 1000)), 500);
    } catch (err) {
      recError = err.message;
    }
  }

  async function stopRecording() {
    clearInterval(timer);
    recording = false;
    try {
      if (recorder instanceof DesktopRecorder) {
        const { sourceId, errors } = await recorder.stop(`${t("rec.title")} ${fmtDate(Date.now() / 1000, app.lang)}`);
        const missing = Object.entries(errors).map(([n, e]) => `${channelName(n)}: ${e}`);
        recProblems = missing;
        if (sourceId) { await loadSources(); transcribeSaved(sourceId); }
      } else {
        const blob = await recorder.stop();
        const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
        await submitUpload(new File([blob], `recording_${ts}.webm`, { type: "audio/webm" }), "recording");
      }
    } catch (err) {
      recError = err.message;
      recProblems = Object.entries(err.errors || {}).map(([n, e]) => `${channelName(n)}: ${e}`);
    }
  }

  const clock = s => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

  // ── list ──────────────────────────────────────────────────────────────────
  let editingId = $state(null);
  let editTitle = $state("");

  function open(id) { rememberSource(id); go(`/source/${id}`); }

  function startRename(s) { editingId = s.id; editTitle = s.title; }
  async function saveRename(s) {
    const title = editTitle.trim();
    editingId = null;
    if (!title || title === s.title) return;
    try { await api(`/api/sources/${s.id}`, { method: "PATCH", body: { title } }); await loadSources(); }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function remove(s) {
    await api(`/api/sources/${s.id}`, { method: "DELETE" });
    await loadSources();
    toast(t("sources.deleted", { title: s.title }), {
      action: t("sources.undo"),
      onAction: async () => { await api(`/api/sources/${s.id}/restore`, { method: "POST" }); await loadSources(); },
    });
  }

  const busy = $derived(app.sources.filter(s => s.status === "processing").length);
  const optionsMeta = $derived([app.options.model, app.options.device === "cpu" ? "CPU" : "GPU",
    app.options.diarize ? t("opt.diarize").toLowerCase() : null].filter(Boolean).join(" · "));
  const statusTag = { ready: "ok", processing: "accent", failed: "danger", recorded: "warn" };

  function sourceMeta(s) {
    return [fmtDate(s.created_at, app.lang), t("kind." + s.kind), fmtDuration(s.duration, app.lang),
      s.speakers && !["email", "document"].includes(s.kind) ? t("meta.speakers", { n: s.speakers }) : null]
      .filter(Boolean).join(" · ");
  }
</script>

<div class="screen-inner">
  <header class="screen-head">
    <div>
      <h1 class="screen-title">{t("sources.title")}</h1>
      <p class="screen-sub">{t("sources.count", { n: app.sources.length }) + (busy ? " · " + t("sources.busy", { busy }) : "")}</p>
    </div>
    {#if app.health?.gpu && (app.health.gpu.cuda || app.health.gpu.mps)}<span class="tag ok">GPU</span>{/if}
  </header>

  <div class="stack">
    <div class="grid-2">
      <section class="panel">
        <h2 class="panel-title">{t("sources.record.title")}</h2>
        <p class="panel-desc">{app.device.desktop ? t("sources.record.desc") : t("sources.record.desc_browser")}</p>
        <div class="stack-sm">
          <div class="field">
            <label class="label" for="mic">{t("rec.mic")}</label>
            <select class="select" id="mic" bind:value={mic} disabled={recording}>
              <option value="">{t("rec.mic_default")}</option>
              {#each mics as m (m.id)}<option value={m.id}>{m.name}</option>{/each}
            </select>
          </div>
          <div class="actions">
            {#if !recording}
              <button class="btn btn-primary" onclick={startRecording}><Icon name="mic" /> {t("rec.start")}</button>
            {:else}
              <button class="btn btn-danger" onclick={stopRecording}>{t("rec.stop")}</button>
              <span class="rec-live"><span class="dot"></span>{t("rec.recording")} <span class="mono">{clock(elapsed)}</span></span>
            {/if}
          </div>
          {#if recProblems.length}
            <p class="note warn">{recording ? t("rec.problems") : t("rec.saved_partial")}: {recProblems.join(" · ")}</p>
          {/if}
          {#if recError}<p class="note danger">{recError}</p>{/if}
        </div>
      </section>

      <section class="panel">
        <h2 class="panel-title">{t("sources.upload.title")}</h2>
        <p class="panel-desc">{t("sources.upload.desc")}</p>
        <label class="drop" class:dragging
               ondragover={e => { e.preventDefault(); dragging = true; }}
               ondragleave={() => (dragging = false)}
               ondrop={e => { e.preventDefault(); dragging = false; pickFile(e.dataTransfer.files[0]); }}>
          <!-- no accept filter: the macOS desktop picker ignores extensions; the server validates -->
          <input type="file" onchange={e => pickFile(e.currentTarget.files[0])} />
          <span class="drop-title"><Icon name="upload" /> {t("sources.upload.drop")} <span class="link">{t("sources.upload.browse")}</span></span>
          <span class="hint">{t("sources.upload.formats")}</span>
          {#if file}<span class="file">{file.name}{#if fileIsTranscript} · {t("sources.upload.is_transcript")}{/if}</span>{/if}
        </label>
        <div class="actions" style="margin-top: var(--s-3)">
          <button class="btn btn-primary btn-block" disabled={!file || uploading} onclick={() => submitUpload()}>
            {#if uploading}<span class="spinner"></span>{/if}
            {fileIsTranscript ? t("sources.upload.summarize") : t("sources.upload.transcribe")}
          </button>
        </div>
        {#if uploadError}<p class="note danger" style="margin-top: var(--s-3)">{uploadError}</p>{/if}
      </section>
    </div>

    <Block id="sources-options" title={t("sources.options")} meta={optionsMeta} open={false}>
      <div class="row">
        <div class="field grow">
          <label class="label" for="model">{t("opt.model")}</label>
          <select class="select" id="model" bind:value={app.options.model} onchange={saveOptions}>
            {#each app.models as m (m)}<option value={m}>{m}</option>{/each}
          </select>
        </div>
        <div class="field">
          <span class="label">{t("opt.device")}</span>
          <div class="seg" role="group" aria-label={t("opt.device")}>
            <button aria-pressed={app.options.device === "cpu"} onclick={() => { app.options.device = "cpu"; saveOptions(); }}>CPU</button>
            <button aria-pressed={app.options.device !== "cpu"} disabled={!app.device.cuda && !app.device.mps}
                    onclick={() => { app.options.device = app.device.cuda ? "cuda" : "mps"; saveOptions(); }}>GPU</button>
          </div>
        </div>
      </div>
      <div class="row" style="margin-top: var(--s-3)">
        <label class="check"><input type="checkbox" class="switch" bind:checked={app.options.diarize} onchange={saveOptions} />
          {t("opt.diarize")} <span class="hint">{t("opt.diarize_hint")}</span></label>
        {#if !app.options.diarize}
          <label class="check"><input type="checkbox" class="switch" bind:checked={app.options.word_timestamps} onchange={saveOptions} />
            {t("opt.words")}</label>
        {/if}
      </div>
    </Block>

    <Block id="sources-list" title={t("sources.list")} meta={String(app.sources.length)}>
      {#if !app.sources.length}
        <div class="empty">
          <p class="panel-title">{t("sources.empty.title")}</p>
          <p>{t("sources.empty.desc")}</p>
        </div>
      {:else}
        <ul class="list">
          {#each app.sources as s (s.id)}
            <li class="item">
              <div class="item-main">
                {#if editingId === s.id}
                  <!-- svelte-ignore a11y_autofocus -->
                  <input class="input" bind:value={editTitle} autofocus
                         onkeydown={e => { if (e.key === "Enter") saveRename(s); if (e.key === "Escape") editingId = null; }}
                         onblur={() => saveRename(s)} />
                {:else}
                  <button class="title-btn" onclick={() => open(s.id)} disabled={s.status === "processing" && !s.duration}>{s.title}</button>
                {/if}
                <p class="mono faint">{sourceMeta(s)}</p>
                {#if app.jobs[s.id]}
                  <div class="progress">
                    <div class="bar"><i style="width: {app.jobs[s.id].progress}%"></i></div>
                    <span class="mono faint">{app.jobs[s.id].message}</span>
                  </div>
                {/if}
                {#if s.status === "failed" && s.error}<p class="hint err">{s.error}</p>{/if}
              </div>
              <div class="item-side">
                <span class="tag {statusTag[s.status] || ''}">{t("status." + s.status)}</span>
                {#if s.has_summary}<span class="tag accent">{t("status.summary")}</span>{/if}
                {#if s.status === "recorded" || (s.status === "failed" && s.audio_file)}
                  <button class="btn btn-sm" onclick={() => transcribeSaved(s.id)}>{t("sources.transcribe_now")}</button>
                {/if}
                <button class="btn btn-ghost btn-sm icon-btn" title={t("sources.rename")} aria-label={t("sources.rename")}
                        onclick={() => startRename(s)}><Icon name="pencil" /></button>
                <button class="btn btn-ghost btn-sm icon-btn" title={t("sources.delete")} aria-label={t("sources.delete")}
                        onclick={() => remove(s)}><Icon name="trash" /></button>
              </div>
            </li>
          {/each}
        </ul>
      {/if}
    </Block>
  </div>
</div>

<style>
  .rec-live { display: inline-flex; align-items: center; gap: var(--s-2); color: var(--danger); font-weight: 500; font-size: var(--t-sm); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--danger); animation: pulse 1.2s ease-in-out infinite; }
  @keyframes pulse { 50% { opacity: .3; } }

  .drop { position: relative; display: flex; flex-direction: column; align-items: center; gap: var(--s-1); text-align: center;
    border: 1px dashed var(--rule-2); border-radius: var(--r-md); padding: var(--s-5) var(--s-4); background: var(--sunk); cursor: pointer; }
  .drop:hover, .drop.dragging { border-color: var(--accent); background: var(--accent-bg); }
  .drop input { position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; }
  .drop-title { display: inline-flex; align-items: center; gap: var(--s-2); font-weight: 500; }
  .link { color: var(--accent); }
  .file { margin-top: var(--s-1); font-size: var(--t-sm); word-break: break-word; }

  .list { list-style: none; margin: 0; padding: 0; }
  .item { display: flex; gap: var(--s-3); align-items: flex-start; padding: var(--s-3) 0; border-bottom: 1px solid var(--rule); }
  .item:last-child { border-bottom: 0; padding-bottom: 0; }
  .item:first-child { padding-top: 0; }
  .item-main { flex: 1; min-width: 0; }
  .item-main .input { height: 30px; }
  .title-btn { border: 0; background: none; padding: 0; font-weight: 500; text-align: left; cursor: pointer; color: var(--ink);
    max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: block; }
  .title-btn:hover:not(:disabled) { color: var(--accent); }
  .item-side { display: flex; align-items: center; gap: var(--s-2); flex-wrap: wrap; justify-content: flex-end; }
  .progress { display: flex; align-items: center; gap: var(--s-2); margin-top: var(--s-2); }
  .progress .bar { flex: 0 0 160px; }
  .err { color: var(--danger); margin-top: var(--s-1); }
  @media (max-width: 600px) {
    .item { flex-direction: column; }
    .item-side { justify-content: flex-start; }
  }
</style>
