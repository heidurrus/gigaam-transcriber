<script>
  import Icon from "./Icon.svelte";
  import { api } from "../lib/api.js";
  import { app, t, go, currentProject, switchProject, loadProjects, toast } from "../lib/state.svelte.js";

  let menuOpen = $state(false);
  let newName = $state("");
  let creating = $state(false);

  const steps = [
    { n: 1, key: "nav.sources", route: "sources", path: "/sources" },
    { n: 2, key: "nav.transcript", route: "transcript", path: null },
    { n: 3, key: "nav.atoms", soon: true },
    { n: 4, key: "nav.document", soon: true },
    { n: 5, key: "nav.decomposition", soon: true },
    { n: 6, key: "nav.export", soon: true },
  ];

  function open(step) {
    if (step.soon) return;
    if (step.route === "transcript") go(app.lastSourceId ? `/source/${app.lastSourceId}` : "/transcript");
    else go(step.path);
  }

  async function createProject(e) {
    e.preventDefault();
    if (!newName.trim()) return;
    creating = true;
    try {
      const p = await api("/api/projects", { method: "POST", body: { name: newName.trim() } });
      newName = "";
      await loadProjects();
      await switchProject(p.id);
      menuOpen = false;
    } catch (err) {
      toast(err.message, { kind: "danger" });
    } finally {
      creating = false;
    }
  }

  async function pick(id) {
    menuOpen = false;
    if (id !== app.currentProjectId) await switchProject(id);
  }
</script>

<nav class="rail" aria-label="Main">
  <div class="brand">
    <b>{t("app.name")}</b>
    <span>{t("app.local")}</span>
  </div>

  <div class="proj-wrap">
    <button class="proj" onclick={() => (menuOpen = !menuOpen)} aria-expanded={menuOpen}>
      <em>{t("project.label")}</em>
      <b>{currentProject()?.name || "…"}</b>
      {#if currentProject()?.local_only}<span class="tag ok lock"><Icon name="lock" size={12} /> {t("project.local_only")}</span>{/if}
    </button>
    {#if menuOpen}
      <div class="menu">
        {#each app.projects as p (p.id)}
          <button class="menu-item" class:on={p.id === app.currentProjectId} onclick={() => pick(p.id)}>
            <span>{p.name}</span>
            {#if p.local_only}<Icon name="lock" size={12} />{/if}
          </button>
        {/each}
        <form class="menu-new" onsubmit={createProject}>
          <input class="input" bind:value={newName} placeholder={t("project.new_placeholder")} aria-label={t("project.new")} />
          <button class="btn btn-sm btn-primary" disabled={creating || !newName.trim()}>{t("project.create")}</button>
        </form>
      </div>
    {/if}
  </div>

  <div class="steps">
    {#each steps as s (s.n)}
      <button class="navitem" class:on={!s.soon && app.route.name === s.route} class:soon={s.soon}
              disabled={s.soon} onclick={() => open(s)} title={s.soon ? t("nav.soon") : ""}>
        <span class="n">{s.n}</span>
        <span class="lbl">{t(s.key)}</span>
        {#if s.soon}<span class="soon-tag">{t("nav.soon")}</span>{/if}
      </button>
    {/each}
  </div>
  <div class="gap"></div>
  <button class="navitem" class:on={app.route.name === "settings"} onclick={() => go("/settings")}>
    <span class="n"></span><span class="lbl">{t("nav.settings")}</span>
  </button>
</nav>

<style>
  .rail { border-right: 1px solid var(--rule); padding: var(--s-5) 0 var(--s-6); position: sticky; top: 0; height: 100vh; overflow-y: auto; }
  .brand { padding: 0 var(--s-4) var(--s-4); }
  .brand b { display: block; font-weight: 600; font-size: var(--t-md); }
  .brand span { display: block; font-size: var(--t-xs); color: var(--ink-3); margin-top: 2px; }
  .proj-wrap { position: relative; margin: 0 var(--s-3) var(--s-4); }
  .proj { display: block; width: 100%; text-align: left; padding: var(--s-2) var(--s-3); background: var(--sunk);
    border: 1px solid var(--rule); border-radius: var(--r-md); cursor: pointer; }
  .proj:hover { border-color: var(--rule-2); }
  .proj em { display: block; font-style: normal; font-size: var(--t-xs); color: var(--ink-3); }
  .proj b { display: block; font-weight: 500; font-size: var(--t-sm); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .lock { display: inline-flex; align-items: center; gap: 3px; margin-top: var(--s-1); }
  .menu { position: absolute; z-index: 50; left: 0; right: 0; top: calc(100% + var(--s-1)); background: var(--panel);
    border: 1px solid var(--rule-2); border-radius: var(--r-md); box-shadow: 0 8px 24px rgba(0,0,0,.12); padding: var(--s-1); }
  .menu-item { display: flex; align-items: center; justify-content: space-between; gap: var(--s-2); width: 100%;
    padding: var(--s-2) var(--s-3); border: 0; background: none; border-radius: var(--r-sm); cursor: pointer; text-align: left; }
  .menu-item:hover, .menu-item.on { background: var(--sunk); }
  .menu-item.on { font-weight: 500; }
  .menu-new { display: flex; gap: var(--s-1); padding: var(--s-2) var(--s-1) var(--s-1); border-top: 1px solid var(--rule); margin-top: var(--s-1); }
  .menu-new .input { height: 28px; font-size: var(--t-sm); }
  .steps { display: flex; flex-direction: column; }
  .navitem { display: flex; gap: var(--s-3); align-items: baseline; width: 100%; text-align: left; padding: var(--s-2) var(--s-4);
    background: none; border: 0; border-left: 2px solid transparent; color: var(--ink-2); cursor: pointer; }
  .navitem:hover:not(:disabled) { color: var(--ink); background: var(--sunk); }
  .navitem.on { color: var(--ink); border-left-color: var(--accent); background: var(--sunk); font-weight: 500; }
  .navitem.soon { color: var(--ink-3); cursor: default; }
  .n { font-family: var(--mono); font-size: var(--t-xs); color: var(--ink-3); width: 12px; flex: none; }
  .navitem.on .n { color: var(--accent); }
  .lbl { flex: 1; min-width: 0; }
  .soon-tag { font-size: 10px; text-transform: uppercase; letter-spacing: .04em; color: var(--ink-3); }
  .gap { height: var(--s-4); border-bottom: 1px solid var(--rule); margin: var(--s-2) var(--s-4) var(--s-2); }

  @media (max-width: 820px) {
    .rail { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--rule); padding: var(--s-3) 0 0;
      display: flex; flex-wrap: wrap; align-items: center; gap: 0 var(--s-2); }
    .brand { padding: 0 var(--s-4) var(--s-2); flex: 1 1 auto; }
    .proj-wrap { margin: 0 var(--s-3) var(--s-2); flex: 1 1 220px; }
    .steps { flex-direction: row; overflow-x: auto; width: 100%; }
    .navitem { width: auto; border-left: 0; border-bottom: 2px solid transparent; padding: var(--s-2) var(--s-3); white-space: nowrap; }
    .navitem.on { border-bottom-color: var(--accent); }
    .navitem.soon { display: none; }
    .gap { display: none; }
    .rail > .navitem { width: auto; }
  }
</style>
