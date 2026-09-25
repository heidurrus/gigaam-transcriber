<script>
  import Block from "../components/Block.svelte";
  import Icon from "../components/Icon.svelte";
  import { api } from "../lib/api.js";
  import { extractAtoms } from "../lib/atoms.js";
  import { fmtTime, speakerDisplay } from "../lib/format.js";
  import { app, t, go, toast, loadSources, writePref } from "../lib/state.svelte.js";

  let atoms = $state([]);
  let stats = $state(null);
  let conflicts = $state([]);
  let loaded = $state(false);
  let error = $state("");

  function readFilter(key, fallback) {
    try { return JSON.parse(localStorage.getItem("wb.atoms." + key)) ?? fallback; } catch (_) { return fallback; }
  }
  let statusFilter = $state(readFilter("status", "all"));
  let typeFilter = $state(readFilter("type", "all"));
  $effect(() => { writePref("atoms.status", statusFilter); writePref("atoms.type", typeFilter); });

  let selectedId = $state(null);
  let editingId = $state(null);
  let draft = $state({ statement: "", type: "functional" });
  let mergingId = $state(null);
  let mergeDraft = $state("");
  let busy = $state(false);

  async function load() {
    const pid = app.currentProjectId;
    try {
      const [a, c] = await Promise.all([api(`/api/projects/${pid}/atoms`), api(`/api/projects/${pid}/conflicts`)]);
      if (pid !== app.currentProjectId) return;
      atoms = a.atoms;
      stats = a.stats;
      conflicts = c.conflicts;
      error = "";
    } catch (err) {
      error = err.message;
    } finally {
      loaded = true;
    }
  }

  // Reload on project switch and whenever an extraction finishes.
  $effect(() => { app.currentProjectId; app.atomsVersion; load(); });

  const sourceFilter = $derived(app.route.source || null);
  const sourceFilterTitle = $derived(app.sources.find(s => s.id === sourceFilter)?.title || "");
  const visible = $derived(atoms.filter(a =>
    (statusFilter === "all" || a.status === statusFilter) &&
    (typeFilter === "all" || a.type === typeFilter) &&
    (!sourceFilter || a.evidence.some(e => e.source_id === sourceFilter))));
  const manySources = $derived(new Set(atoms.flatMap(a => a.evidence.map(e => e.source_id))).size > 1);
  const readySources = $derived(app.sources.filter(s => s.status === "ready"));
  const statementOf = $derived(Object.fromEntries(atoms.map(a => [a.id, a.statement])));
  const openConflicts = $derived(conflicts.filter(c => c.status === "open"));

  $effect(() => {
    // Keep a valid selection while the list changes under the filters.
    if (!visible.length) selectedId = null;
    else if (!visible.some(a => a.id === selectedId)) selectedId = visible[0].id;
  });

  function select(id, scroll = true) {
    selectedId = id;
    if (scroll) requestAnimationFrame(() => document.getElementById(`atom-${id}`)?.scrollIntoView({ block: "nearest" }));
  }

  async function patch(atom, body) {
    const updated = await api(`/api/atoms/${atom.id}`, { method: "PATCH", body });
    stats = updated.stats;
    const { stats: _, ...fresh } = updated;
    atoms = atoms.map(a => (a.id === atom.id ? { ...a, ...fresh } : a));
    // Answering a conflict's question closes the conflict: refresh the flags on both atoms.
    if (atom.type === "question" && body.status && conflicts.some(c => c.question_atom === atom.id)) await load();
    return fresh;
  }

  // Buttons toggle (clicking again takes the decision back); keys only set it.
  async function decide(atom, status, { toggle = true } = {}) {
    const previous = atom.status;
    const next = toggle && previous === status ? "pending" : status;
    // Move on to the next atom still to review right away, so fast keyboard review never lands twice on one atom.
    const i = visible.findIndex(a => a.id === atom.id);
    const others = visible.filter(a => a.id !== atom.id && a.status === "pending");
    const after = next === "pending" ? null
      : visible.slice(i + 1).find(a => a.status === "pending") || others[0] || visible[i + 1];
    if (after) select(after.id);
    if (next === previous) return;
    try {
      await patch(atom, { status: next });
      if (next !== "pending") {
        toast(t(next === "accepted" ? "at.accepted_toast" : "at.rejected_toast"), {
          action: t("at.undo"), onAction: () => patch(atom, { status: previous }).then(() => select(atom.id)) });
      }
    } catch (err) {
      select(atom.id);
      toast(err.message, { kind: "danger" });
    }
  }

  function startEdit(atom) {
    editingId = atom.id;
    selectedId = atom.id;
    draft = { statement: atom.statement, type: atom.type };
  }

  async function saveEdit(atom) {
    const body = {};
    if (draft.statement.trim() !== atom.statement) body.statement = draft.statement;
    if (draft.type !== atom.type) body.type = draft.type;
    editingId = null;
    if (!Object.keys(body).length) return;
    try { await patch(atom, body); } catch (err) { toast(err.message, { kind: "danger" }); }
  }

  async function resolve(conflict, action, statement) {
    busy = true;
    try {
      const r = await api(`/api/conflicts/${conflict.id}/resolve`, { method: "POST", body: { action, statement } });
      mergingId = null;
      toast(t(r.status === "awaiting_answer" ? "at.question_toast" : "at.resolved_toast"));
      await load();
      loadSources();
    } catch (err) {
      toast(err.message, { kind: "danger" });
    } finally {
      busy = false;
    }
  }

  function onKey(e) {
    if (e.metaKey || e.ctrlKey || e.altKey || app.route.name !== "atoms") return;
    if (e.target.closest("input, textarea, select, [contenteditable]")) return;
    const i = visible.findIndex(a => a.id === selectedId);
    const atom = visible[i];
    if (e.key === "j" || e.key === "ArrowDown") { if (visible[i + 1]) select(visible[i + 1].id); }
    else if (e.key === "k" || e.key === "ArrowUp") { if (i > 0) select(visible[i - 1].id); }
    else if (e.key === "a" && atom) decide(atom, "accepted", { toggle: false });
    else if (e.key === "x" && atom) decide(atom, "rejected", { toggle: false });
    else if (e.key === "e" && atom) startEdit(atom);
    else return;
    e.preventDefault();
  }

  function evidenceLabel(ev) {
    const bits = [];
    if (ev.start != null) bits.push(fmtTime(ev.start));
    if (ev.speaker) bits.push(speakerDisplay(ev.speaker, ev.speaker_name, t));
    if (manySources) bits.push(ev.source_title);
    return bits.join(" · ");
  }

  const statusPills = ["all", "pending", "accepted", "rejected"];
  const typePills = ["all", "functional", "nfr", "question"];
  const typeClass = { functional: "accent", nfr: "", question: "warn" };
  const count = (key, value) => atoms.filter(a => a[key] === value).length;
</script>

<svelte:window onkeydown={onKey} />

<div class="screen-inner">
  <header class="screen-head">
    <div>
      <h1 class="screen-title">{t("at.title")}</h1>
      <p class="screen-sub">
        {#if stats && stats.total}{t("at.sub", stats)}{:else}{t("at.sub_empty")}{/if}
      </p>
    </div>
  </header>

  {#if error}<p class="note danger">{error}</p>{/if}

  <div class="stack">
    {#if conflicts.length}
      <Block id="at-conflicts" title={t("at.conflicts")} meta={String(openConflicts.length || "")}>
        <div class="stack-sm">
          {#each conflicts as c (c.id)}
            <div class="conflict" class:waiting={c.status === "awaiting_answer"}>
              <p class="c-desc">
                {c.description}
                {#if c.status === "awaiting_answer"}<span class="tag warn">{t("at.awaiting")}</span>{/if}
              </p>
              <div class="c-sides">
                {#each [["A", c.a], ["B", c.b]] as [side, atom] (side)}
                  <div class="c-side">
                    <span class="mono faint">{side}</span>
                    <p>{atom.statement}</p>
                    {#if atom.evidence[0]}
                      <button class="quote link" onclick={() => go(`/source/${atom.evidence[0].source_id}/seg/${atom.evidence[0].segment_idx}`)}>
                        {evidenceLabel(atom.evidence[0])} — «{atom.evidence[0].quote}»
                      </button>
                    {/if}
                  </div>
                {/each}
              </div>
              {#if c.status === "open"}
                {#if mergingId === c.id}
                  <div class="field merge">
                    <span class="label">{t("at.merge_hint")}</span>
                    <textarea class="input area" rows="2" bind:value={mergeDraft}></textarea>
                    <div class="actions">
                      <button class="btn btn-sm btn-primary" disabled={busy || !mergeDraft.trim()}
                              onclick={() => resolve(c, "merge", mergeDraft)}>{t("at.save")}</button>
                      <button class="btn btn-sm btn-ghost" onclick={() => (mergingId = null)}>{t("at.cancel")}</button>
                    </div>
                  </div>
                {:else}
                  <div class="actions">
                    <button class="btn btn-sm" disabled={busy} onclick={() => resolve(c, "keep_a")}>{t("at.keep", { side: "A" })}</button>
                    <button class="btn btn-sm" disabled={busy} onclick={() => resolve(c, "keep_b")}>{t("at.keep", { side: "B" })}</button>
                    <button class="btn btn-sm" disabled={busy} onclick={() => { mergingId = c.id; mergeDraft = c.a.statement; }}>{t("at.merge")}</button>
                    <button class="btn btn-sm btn-ghost" disabled={busy} onclick={() => resolve(c, "question")}>{t("at.to_question")}</button>
                  </div>
                {/if}
              {/if}
            </div>
          {/each}
        </div>
      </Block>
    {/if}

    <section class="panel list-panel">
      <div class="filters">
        <div class="pills" role="group" aria-label="Status">
          {#each statusPills as f (f)}
            <button class="pill" aria-pressed={statusFilter === f} onclick={() => (statusFilter = f)}>
              {t("at.f." + f)}{#if f !== "all" && stats}<span class="pill-n">{stats[f]}</span>{/if}
            </button>
          {/each}
        </div>
        <div class="pills" role="group" aria-label="Type">
          {#each typePills as f (f)}
            <button class="pill" aria-pressed={typeFilter === f} onclick={() => (typeFilter = f)}>
              {t("at.f." + f)}{#if f !== "all"}<span class="pill-n">{count("type", f)}</span>{/if}
            </button>
          {/each}
        </div>
      </div>

      {#if sourceFilter}
        <p class="note src-filter">
          {t("at.source_filter", { title: sourceFilterTitle })}
          <button class="btn btn-sm btn-ghost" onclick={() => go("/atoms")}>{t("at.clear_filter")}</button>
        </p>
      {/if}

      {#if loaded && !atoms.length}
        <div class="empty">
          <p class="panel-title">{t("at.none_title")}</p>
          <p>{t("at.none")}</p>
        </div>
      {:else if loaded && !visible.length}
        <p class="empty">{t("at.none_filtered")}</p>
      {:else}
        <ul class="atoms">
          {#each visible as atom (atom.id)}
            <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
            <li class="atom" id="atom-{atom.id}" class:sel={atom.id === selectedId} class:rejected={atom.status === "rejected"}
                onclick={() => select(atom.id, false)}>
              <span class="tag type {typeClass[atom.type]}">{t("at.type." + atom.type)}</span>
              <div class="body">
                {#if editingId === atom.id}
                  <!-- svelte-ignore a11y_autofocus -->
                  <textarea class="input area" rows="2" bind:value={draft.statement} autofocus
                            onkeydown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); saveEdit(atom); }
                                              if (e.key === "Escape") editingId = null; }}></textarea>
                  <div class="actions edit-row">
                    <div class="seg">
                      {#each ["functional", "nfr", "question"] as ty (ty)}
                        <button aria-pressed={draft.type === ty} onclick={() => (draft.type = ty)}>{t("at.type." + ty)}</button>
                      {/each}
                    </div>
                    <span class="spacer"></span>
                    <button class="btn btn-sm btn-ghost" onclick={() => (editingId = null)}>{t("at.cancel")}</button>
                    <button class="btn btn-sm btn-primary" disabled={!draft.statement.trim()} onclick={() => saveEdit(atom)}>{t("at.save")}</button>
                  </div>
                {:else}
                  <p class="stm">{atom.statement}</p>
                  {#if atom.statement !== atom.original_statement}
                    <p class="hint">{t("at.was", { text: atom.original_statement })}</p>
                  {/if}
                {/if}
                {#each atom.evidence as ev (ev.id)}
                  <button class="quote link" title={t("at.jump")} onclick={() => go(`/source/${ev.source_id}/seg/${ev.segment_idx}`)}>
                    {#if evidenceLabel(ev)}<span class="mono">{evidenceLabel(ev)}</span>{" — "}{/if}«{ev.quote}»
                  </button>
                {/each}
                {#each atom.conflicts as c (c.id)}
                  <p class="note danger c-note">{t("at.conflict_with", { text: c.description })}
                    {#if statementOf[c.other]}<span class="faint"> — {statementOf[c.other]}</span>{/if}</p>
                {/each}
              </div>
              <div class="acts">
                <button class="btn btn-ghost btn-sm icon-btn" class:on-ok={atom.status === "accepted"} aria-label={t("at.accept")}
                        title="{t('at.accept')} (a)" aria-pressed={atom.status === "accepted"}
                        onclick={e => { e.stopPropagation(); decide(atom, "accepted"); }}><Icon name="check" /></button>
                <button class="btn btn-ghost btn-sm icon-btn" aria-label={t("at.edit")} title="{t('at.edit')} (e)"
                        onclick={e => { e.stopPropagation(); startEdit(atom); }}><Icon name="pencil" /></button>
                <button class="btn btn-ghost btn-sm icon-btn" class:on-no={atom.status === "rejected"} aria-label={t("at.reject")}
                        title="{t('at.reject')} (x)" aria-pressed={atom.status === "rejected"}
                        onclick={e => { e.stopPropagation(); decide(atom, "rejected"); }}><Icon name="close" /></button>
              </div>
            </li>
          {/each}
        </ul>
      {/if}

      {#if stats && stats.total && !stats.pending}
        <p class="note ok done">{t("at.all_done")}</p>
      {/if}

      {#if atoms.length}
        <p class="keys mono faint">
          <span class="kb">j</span> <span class="kb">k</span>
          {@html t("at.keys", { a: '<span class="kb">a</span>', x: '<span class="kb">x</span>', e: '<span class="kb">e</span>' })}
        </p>
      {/if}
    </section>

    <Block id="at-sources" title={t("at.sources")} open={!atoms.length}
           meta={t("at.sources_meta", { n: readySources.length })}>
      {#if !readySources.length}
        <p class="muted">{t("at.no_ready")}</p>
      {:else}
        <ul class="sources">
          {#each readySources as s (s.id)}
            <li class="src">
              <button class="src-title link" onclick={() => go(`/source/${s.id}`)}>{s.title}</button>
              <span class="tag">{t("kind." + s.kind)}</span>
              {#if s.atom_count}
                <button class="tag accent link" onclick={() => go(`/atoms/source/${s.id}`)}>{t("at.count", { n: s.atom_count })}</button>
              {/if}
              <span class="spacer"></span>
              {#if app.extracting[s.id]}
                <span class="progress">
                  <span class="spinner"></span>
                  <span class="mono faint">{app.extracting[s.id].message}</span>
                </span>
              {:else}
                <button class="btn btn-sm" class:btn-primary={!s.atom_count}
                        title={s.atom_count ? t("at.reextract_hint") : ""} onclick={() => extractAtoms(s.id)}>
                  {s.atom_count ? t("at.reextract") : t("at.extract")}
                </button>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </Block>
  </div>
</div>

<style>
  .list-panel { padding: 0; }
  .filters { display: flex; flex-wrap: wrap; gap: var(--s-2) var(--s-4); padding: var(--s-3) var(--s-4); border-bottom: 1px solid var(--rule); }
  .pills { display: flex; flex-wrap: wrap; gap: var(--s-1); }
  .pill { display: inline-flex; align-items: center; gap: var(--s-1); height: 26px; padding: 0 var(--s-3); border-radius: 13px;
    border: 1px solid var(--rule-2); background: var(--panel); color: var(--ink-2); font-size: var(--t-sm); cursor: pointer; }
  .pill:hover { border-color: var(--ink-3); }
  .pill[aria-pressed="true"] { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }
  .pill-n { font-family: var(--mono); font-size: var(--t-xs); opacity: .75; }
  .src-filter { display: flex; align-items: center; gap: var(--s-2); margin: var(--s-3) var(--s-4) 0; }

  .atoms { list-style: none; margin: 0; padding: 0; }
  .atom { display: grid; grid-template-columns: 72px minmax(0, 1fr) auto; gap: var(--s-3); padding: var(--s-3) var(--s-4);
    border-bottom: 1px solid var(--rule); scroll-margin: var(--s-6); }
  .atom:last-child { border-bottom: 0; }
  .atom.sel { background: var(--sunk); box-shadow: inset 2px 0 0 var(--accent); }
  .atom.rejected .stm { text-decoration: line-through; color: var(--ink-3); }
  .atom.rejected .quote { opacity: .6; }
  .type { justify-self: start; align-self: start; margin-top: 2px; }
  .body { min-width: 0; }
  .stm { line-height: 1.5; }
  .body .hint { margin-top: 2px; }
  .quote { display: block; margin-top: var(--s-1); font-size: var(--t-sm); color: var(--ink-2); text-align: left; line-height: 1.5; }
  .quote .mono { color: var(--ink-3); }
  .link { border: 0; background: none; padding: 0; font: inherit; cursor: pointer; }
  button.quote:hover { color: var(--accent); }
  .c-note { margin-top: var(--s-2); }
  .acts { display: flex; align-items: flex-start; gap: 2px; }
  .on-ok { color: var(--ok); background: var(--ok-bg); }
  .on-no { color: var(--danger); background: var(--danger-bg); }
  .area { height: auto; padding: var(--s-2) var(--s-3); line-height: 1.5; resize: vertical; }
  .edit-row { margin-top: var(--s-2); }
  .edit-row .seg { height: 28px; }
  .edit-row .seg button { padding: 0 var(--s-3); font-size: var(--t-sm); }
  .done { margin: var(--s-3) var(--s-4) 0; }
  .keys { padding: var(--s-3) var(--s-4); border-top: 1px solid var(--rule); }
  .keys :global(.kb) { display: inline-block; padding: 0 5px; border: 1px solid var(--rule-2); border-radius: var(--r-sm); color: var(--ink-2); }

  .conflict { border: 1px solid var(--rule); border-left: 2px solid var(--danger); border-radius: var(--r-md); padding: var(--s-3); }
  .conflict.waiting { border-left-color: var(--warn); }
  .c-desc { font-weight: 500; display: flex; flex-wrap: wrap; align-items: center; gap: var(--s-2); }
  .c-sides { display: grid; gap: var(--s-3); grid-template-columns: repeat(auto-fit, minmax(min(100%, 240px), 1fr)); margin: var(--s-2) 0 var(--s-3); }
  .c-side { background: var(--sunk); border-radius: var(--r-md); padding: var(--s-2) var(--s-3); min-width: 0; }
  .c-side p { line-height: 1.5; }
  .merge { gap: var(--s-2); }

  .sources { list-style: none; margin: 0; padding: 0; }
  .src { display: flex; align-items: center; flex-wrap: wrap; gap: var(--s-2); padding: var(--s-2) 0; border-top: 1px solid var(--rule); }
  .src:first-child { border-top: 0; }
  .src-title { font-weight: 500; text-align: left; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }
  .src-title:hover { color: var(--accent); }
  .spacer { flex: 1; }
  .progress { display: inline-flex; align-items: center; gap: var(--s-2); }

  @media (max-width: 600px) {
    .atom { grid-template-columns: minmax(0, 1fr) auto; }
    .type { grid-column: 1 / -1; }
  }
</style>
