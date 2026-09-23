<script>
  import Block from "../components/Block.svelte";
  import Icon from "../components/Icon.svelte";
  import { api, pollJob } from "../lib/api.js";
  import { fmtTime, fmtDate, fmtDuration, renderMarkdown, speakerClass, speakerDisplay, downloadText } from "../lib/format.js";
  import { app, t, go, loadSources, toast, rememberSource } from "../lib/state.svelte.js";

  let { id, autoSummarize = false } = $props();

  let source = $state(null);
  let loadError = $state("");
  let audio = $state(null);
  let playing = $state(false);
  let now = $state(0);
  let duration = $state(0);

  let summaryText = $state("");
  let summaryMeta = $state("");
  let summaryError = $state("");
  let summarizing = $state(false);
  let summaryStarted = $state(0);
  let tick = $state(0);

  let editingTitle = $state(false);
  let titleDraft = $state("");
  let names = $state({});
  let copied = $state(false);

  async function load() {
    loadError = "";
    try {
      source = await api(`/api/sources/${id}`);
      names = { ...source.speaker_names };
      summaryText = source.summary?.text || "";
      summaryMeta = source.summary ? t("tr.summarised_with", { model: source.summary.model }) : "";
      rememberSource(id);
    } catch (err) {
      source = null;
      loadError = err.message;
    }
  }

  // Reload when the route points at another source; keep polling while it's being processed.
  $effect(() => {
    const current = id;
    let stop = false;
    load().then(async () => {
      if (autoSummarize && source?.status === "ready" && !summaryText) summarize();
      while (!stop && source && source.id === current && source.status === "processing") {
        await new Promise(r => setTimeout(r, 2000));
        if (!stop) await load();
      }
    });
    return () => { stop = true; };
  });

  const speakerOrder = $derived(source ? [...new Set(source.segments.map(s => s.speaker).filter(Boolean))] : []);
  // Documents and emails have no timing: shown as paragraphs, without the time column.
  const isText = $derived(source ? !source.segments.some(s => s.start != null) : false);
  const blockTitle = $derived(source?.kind === "email" ? t("tr.block.email")
    : source?.kind === "document" ? t("tr.block.document") : t("nav.transcript"));
  const email = $derived(source?.meta?.email || null);
  const activeIdx = $derived.by(() => {
    if (!source || !playing && !now) return -1;
    const segs = source.segments;
    for (let i = segs.length - 1; i >= 0; i--) if (segs[i].start != null && segs[i].start <= now + 0.05) return i;
    return -1;
  });

  function seek(seconds) {
    if (!audio || seconds == null) return;
    audio.currentTime = seconds;
    audio.play();
  }
  function togglePlay() { if (!audio) return; audio.paused ? audio.play() : audio.pause(); }

  $effect(() => {
    // Keep the playing line in view.
    if (activeIdx < 0 || !playing) return;
    document.getElementById(`seg-${activeIdx}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });

  async function saveTitle() {
    editingTitle = false;
    const title = titleDraft.trim();
    if (!title || title === source.title) return;
    try { source = { ...source, ...(await api(`/api/sources/${id}`, { method: "PATCH", body: { title } })) }; loadSources(); }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function renameSpeaker(label) {
    const name = (names[label] || "").trim();
    if ((source.speaker_names[label] || "") === name) return;
    try {
      await api(`/api/sources/${id}/speakers/${encodeURIComponent(label)}`, { method: "PUT", body: { name } });
      await load();
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function summarize() {
    summarizing = true;
    summaryError = "";
    summaryText = "";
    summaryStarted = Date.now();
    const timer = setInterval(() => (tick = Math.round((Date.now() - summaryStarted) / 1000)), 500);
    try {
      const { job_id } = await api("/summarize", { method: "POST", body: { source_id: id } });
      const job = await pollJob(job_id, j => { if (j.partial) summaryText = j.partial; }, { interval: 600 });
      summaryText = job.result.summary;
      summaryMeta = t("tr.summarised_with", { model: job.result.model });
      loadSources();
    } catch (err) {
      summaryError = err.message;
      if (err.body?.needs_setup || /API key|Settings/.test(err.message)) {
        toast(err.message, { action: t("nav.settings"), onAction: () => go("/settings"), kind: "danger" });
      }
    } finally {
      clearInterval(timer);
      summarizing = false;
    }
  }

  async function retranscribe() {
    const o = app.options;
    try {
      const res = await api(`/api/sources/${id}/transcribe`, { method: "POST", body: {
        model: o.model, device: o.device, diarize: String(o.diarize), word_timestamps: String(!o.diarize && o.word_timestamps) } });
      await load();
      pollJob(res.job_id).finally(() => { load(); loadSources(); });
    } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function copyText() {
    await navigator.clipboard.writeText(source.text);
    copied = true;
    setTimeout(() => (copied = false), 1500);
  }

  const meta = $derived(source ? [fmtDate(source.created_at, app.lang), t("kind." + source.kind), fmtDuration(source.duration, app.lang),
    source.speakers && !["email", "document"].includes(source.kind) ? t("meta.speakers", { n: source.speakers }) : null,
    source.asr_model || source.import_format]
    .filter(Boolean).join(" · ") : "");
</script>

<div class="screen-inner">
  {#if !id}
    <div class="empty panel"><p>{t("tr.none")}</p>
      <button class="btn" style="margin-top: var(--s-3)" onclick={() => go("/sources")}>{t("tr.back")}</button></div>
  {:else if loadError}
    <div class="note danger">{loadError}</div>
  {:else if source}
    <header class="screen-head">
      <div class="head-main">
        <button class="btn btn-ghost btn-sm back" onclick={() => go("/sources")}><Icon name="back" /> {t("tr.back")}</button>
        {#if editingTitle}
          <!-- svelte-ignore a11y_autofocus -->
          <input class="input title-input" bind:value={titleDraft} autofocus onblur={saveTitle}
                 onkeydown={e => { if (e.key === "Enter") saveTitle(); if (e.key === "Escape") editingTitle = false; }} />
        {:else}
          <h1 class="screen-title">
            <button class="title-btn" title={t("tr.edit_title")} onclick={() => { titleDraft = source.title; editingTitle = true; }}>
              {source.title} <span class="pen"><Icon name="pencil" size={14} /></span>
            </button>
          </h1>
        {/if}
        <p class="screen-sub mono">{meta}</p>
        {#if email && (email.from || email.to)}
          <p class="screen-sub">{#if email.from}{t("tr.email_from")}: {email.from}{/if}{email.from && email.to ? " · " : ""}{#if email.to}{t("tr.email_to")}: {email.to}{/if}</p>
        {/if}
      </div>
      <div class="actions">
        {#if source.status === "ready"}
          <button class="btn btn-primary" onclick={summarize} disabled={summarizing}>
            {#if summarizing}<span class="spinner"></span>{/if}{summaryText ? t("tr.resummarize") : t("tr.summarize")}
          </button>
          <button class="btn" onclick={copyText}><Icon name={copied ? "check" : "copy"} /> {copied ? t("tr.copied") : t("tr.copy")}</button>
          <button class="btn" onclick={() => downloadText(`${source.title}.txt`, source.text)}><Icon name="download" /> {t("tr.export")}</button>
        {/if}
        {#if source.audio_url && source.status !== "processing"}
          <button class="btn btn-ghost" onclick={retranscribe}>{source.status === "ready" ? t("tr.retranscribe") : t("tr.transcribe")}</button>
        {/if}
      </div>
    </header>

    {#if source.status === "processing"}
      <p class="note"><span class="spinner"></span> {t("tr.processing")}</p>
    {:else if source.status === "recorded"}
      <p class="note warn">{t("tr.recorded")}</p>
    {:else if source.status === "failed"}
      <p class="note danger">{t("tr.failed", { error: source.error || "" })}</p>
    {/if}

    {#if source.audio_url}
      <div class="player panel">
        <audio bind:this={audio} src={source.audio_url} preload="metadata"
               ontimeupdate={() => (now = audio.currentTime)} onloadedmetadata={() => (duration = audio.duration)}
               onplay={() => (playing = true)} onpause={() => (playing = false)}></audio>
        <button class="btn btn-primary icon-btn" onclick={togglePlay} aria-label={playing ? t("tr.pause") : t("tr.play")}>
          <Icon name={playing ? "pause" : "play"} />
        </button>
        <span class="mono">{fmtTime(now)}</span>
        <input class="scrub" type="range" min="0" max={duration || 0} step="0.1" value={now}
               oninput={e => { audio.currentTime = Number(e.currentTarget.value); }} aria-label="Seek" />
        <span class="mono faint">{fmtTime(duration)}</span>
      </div>
    {/if}

    {#if source.status === "ready"}
      <div class="layout">
        <div class="stack main-col">
          {#if speakerOrder.length && !isText}
            <Block id="tr-speakers" title={t("tr.speakers")} meta={String(speakerOrder.length)}>
              <p class="hint" style="margin-bottom: var(--s-3)">{t("tr.speaker_hint")}</p>
              <div class="speakers">
                {#each speakerOrder as label (label)}
                  <label class="speaker">
                    <span class="chip {speakerClass(label, speakerOrder)}">{speakerDisplay(label, null, t)}</span>
                    <input class="input" bind:value={names[label]} placeholder={speakerDisplay(label, null, t)}
                           onblur={() => renameSpeaker(label)} onkeydown={e => e.key === "Enter" && e.currentTarget.blur()} />
                  </label>
                {/each}
              </div>
            </Block>
          {/if}

          <Block id="tr-transcript" title={blockTitle}
                 meta={isText ? t("meta.paragraphs", { n: source.segments.length }) : t("meta.segments", { n: source.segments.length })}>
            {#if !source.segments.length}
              <p class="muted">{t("tr.no_segments")}</p>
            {:else}
              <div class="segments" class:prose={isText}>
                {#each source.segments as seg, i (seg.idx)}
                  {#if isText}
                    <p class="para">{seg.text}</p>
                  {:else}
                  <div class="seg-row" class:active={i === activeIdx} id="seg-{i}">
                    <div class="seg-meta">
                      {#if seg.start != null}
                        <button class="time" disabled={!source.audio_url} onclick={() => seek(seg.start)}>{fmtTime(seg.start)}</button>
                      {/if}
                      {#if seg.speaker}<span class="chip {speakerClass(seg.speaker, speakerOrder)}">{speakerDisplay(seg.speaker, seg.speaker_name, t)}</span>{/if}
                    </div>
                    <p class="seg-text">{seg.text}</p>
                  </div>
                  {/if}
                {/each}
              </div>
            {/if}
          </Block>
        </div>

        <div class="side-col">
          <Block id="tr-summary" title={t("tr.summary")} meta={summaryMeta}>
            {#if summaryText}
              <div class="md">{@html renderMarkdown(summaryText)}</div>
            {:else if !summarizing && !summaryError}
              <p class="muted">{t("tr.no_summary")}</p>
            {/if}
            {#if summarizing && !summaryText}<p class="hint"><span class="spinner"></span> {t("tr.writing", { s: tick })}</p>{/if}
            {#if summaryError}<p class="note danger">{summaryError}</p>{/if}
          </Block>
        </div>
      </div>
    {/if}
  {/if}
</div>

<style>
  .head-main { min-width: 0; flex: 1; }
  .back { margin: 0 0 var(--s-2) calc(-1 * var(--s-3)); }
  .title-btn { border: 0; background: none; padding: 0; font: inherit; color: inherit; cursor: text; text-align: left; }
  .title-btn .pen { color: var(--ink-3); opacity: 0; display: inline-block; vertical-align: middle; }
  .title-btn:hover .pen { opacity: 1; }
  .title-input { font-size: var(--t-xl); font-weight: 600; height: 40px; max-width: 640px; }

  .player { display: flex; align-items: center; gap: var(--s-3); margin-bottom: var(--s-4); padding: var(--s-2) var(--s-3);
    position: sticky; top: 0; z-index: 10; }
  .scrub { flex: 1; min-width: 80px; accent-color: var(--accent); }

  .layout { display: grid; gap: var(--s-4); grid-template-columns: minmax(0, 1.6fr) minmax(280px, 1fr); align-items: start; }
  .side-col { position: sticky; top: calc(var(--control-h) + var(--s-5)); }
  @media (max-width: 1100px) { .layout { grid-template-columns: 1fr; } .side-col { position: static; order: -1; } }

  .speakers { display: grid; gap: var(--s-2); grid-template-columns: repeat(auto-fill, minmax(min(100%, 260px), 1fr)); }
  .speaker { display: flex; align-items: center; gap: var(--s-2); }
  .speaker .input { height: 30px; }
  .chip { display: inline-block; padding: 1px var(--s-2); border-radius: var(--r-sm); font-size: var(--t-xs); font-weight: 500;
    white-space: nowrap; max-width: 180px; overflow: hidden; text-overflow: ellipsis; flex: none; }

  .segments { display: flex; flex-direction: column; }
  .seg-row { display: grid; grid-template-columns: 120px minmax(0, 1fr); gap: var(--s-3); padding: var(--s-2) var(--s-2);
    border-radius: var(--r-md); scroll-margin: 80px; }
  .seg-row + .seg-row { border-top: 1px solid var(--rule); border-radius: 0; }
  .seg-row.active { background: var(--accent-bg); border-radius: var(--r-md); }
  .seg-meta { display: flex; flex-direction: column; align-items: flex-start; gap: var(--s-1); min-width: 0; }
  .time { border: 0; background: none; padding: 0; font-family: var(--mono); font-size: var(--t-xs); color: var(--accent); cursor: pointer; }
  .time:disabled { color: var(--ink-3); cursor: default; }
  .seg-text { line-height: 1.65; }
  .prose { max-width: 72ch; }
  .para { line-height: 1.7; margin: 0 0 var(--s-3); }
  .para:last-child { margin-bottom: 0; }
  @media (max-width: 600px) { .seg-row { grid-template-columns: 1fr; gap: var(--s-1); } .seg-meta { flex-direction: row; align-items: center; } }
</style>
