<script>
  import Block from "../components/Block.svelte";
  import { api } from "../lib/api.js";
  import { LANGS } from "../lib/i18n.js";
  import { app, t, setLang, currentProject, loadProjects, switchProject, toast } from "../lib/state.svelte.js";

  let s = $state(null);              // server settings payload
  let keyDraft = $state("");
  let hfDraft = $state("");
  let showKey = $state(false);
  let showHf = $state(false);
  let ollama = $state(null);
  let projectName = $state("");

  async function load() {
    s = await api("/settings");
    projectName = currentProject()?.name || "";
    if (s.llm_provider === "ollama") checkOllama();
  }
  $effect(() => { load(); });
  $effect(() => { projectName = currentProject()?.name || ""; });

  async function save(body) {
    try { s = await api("/settings", { method: "POST", body }); if (body.llm_provider === "ollama") checkOllama(); }
    catch (err) { toast(err.message, { kind: "danger" }); }
  }
  async function checkOllama() { ollama = (await api("/ollama/status").catch(() => ({ reachable: false }))).reachable; }

  async function saveKey() { if (!keyDraft.trim()) return; await save({ anthropic_api_key: keyDraft.trim() }); keyDraft = ""; }
  async function saveHf() { if (!hfDraft.trim()) return; await save({ hf_token: hfDraft.trim() }); hfDraft = ""; }

  async function updateProject(changes) {
    const p = currentProject();
    if (!p) return;
    try { await api(`/api/projects/${p.id}`, { method: "PATCH", body: changes }); await loadProjects(); }
    catch (err) { toast(err.message, { kind: "danger" }); projectName = p.name; }
  }
  async function archive() {
    await updateProject({ archived: true });
    await loadProjects();
    if (app.projects[0]) await switchProject(app.projects[0].id);
  }
  async function restore(id) {
    await api(`/api/projects/${id}`, { method: "PATCH", body: { archived: false } });
    await loadProjects();
  }

  const env = $derived(app.health ? [
    [t("env.ffmpeg"), app.health.ffmpeg ? t("env.found") : t("env.missing"), app.health.ffmpeg],
    [t("env.gpu"), app.health.gpu.gpu_name || (app.health.gpu.mps ? "Apple Silicon (MPS)" : t("env.cpu_only")),
      app.health.gpu.cuda || app.health.gpu.mps],
    [t("env.hf"), app.health.hf_token ? t("env.set") : t("env.missing"), app.health.hf_token],
    [t("env.ollama"), app.health.ollama ? t("env.running") : t("env.stopped"), app.health.ollama],
    [t("env.sysaudio"), app.health.system_audio_capture ? t("env.supported") : t("env.unsupported"), app.health.system_audio_capture],
  ] : []);
</script>

<div class="screen-inner narrow">
  <header class="screen-head">
    <div>
      <h1 class="screen-title">{t("set.title")}</h1>
      <p class="screen-sub">{t("set.sub")}</p>
    </div>
  </header>

  <div class="stack">
    {#if currentProject()}
      <Block id="set-project" title={t("set.project")} meta={currentProject().name}>
        <div class="stack-sm">
          <div class="field">
            <label class="label" for="pname">{t("set.project_name")}</label>
            <input class="input" id="pname" bind:value={projectName}
                   onblur={() => projectName.trim() && projectName.trim() !== currentProject().name && updateProject({ name: projectName.trim() })}
                   onkeydown={e => e.key === "Enter" && e.currentTarget.blur()} />
          </div>
          <label class="check">
            <input type="checkbox" class="switch" checked={currentProject().local_only}
                   onchange={e => updateProject({ local_only: e.currentTarget.checked })} />
            {t("project.local_only")}
          </label>
          <p class="hint">{t("set.local_only_hint")}</p>
          <div class="actions">
            <button class="btn btn-sm" onclick={archive} disabled={app.projects.length < 2}>{t("set.archive")}</button>
          </div>
          {#if app.archivedProjects.length}
            <div class="archived">
              <span class="label">{t("project.archived")}</span>
              {#each app.archivedProjects as p (p.id)}
                <div class="archived-row"><span>{p.name}</span>
                  <button class="btn btn-ghost btn-sm" onclick={() => restore(p.id)}>{t("project.restore")}</button></div>
              {/each}
            </div>
          {/if}
        </div>
      </Block>
    {/if}

    {#if s}
      <Block id="set-ai" title={t("set.ai")} meta={s.llm_provider === "ollama" ? s.ollama_model : s.claude_model}>
        <div class="stack-sm">
          <div class="field">
            <label class="label" for="provider">{t("set.provider")}</label>
            <select class="select" id="provider" value={s.llm_provider} onchange={e => save({ llm_provider: e.currentTarget.value })}>
              <option value="claude">{t("set.provider.claude")}</option>
              <option value="ollama">{t("set.provider.ollama")}</option>
            </select>
          </div>
          {#if s.llm_provider === "claude"}
            <div class="field">
              <label class="label" for="akey">{t("set.anthropic_key")}</label>
              <div class="input-row">
                <input class="input code" id="akey" type={showKey ? "text" : "password"} bind:value={keyDraft} autocomplete="off"
                       placeholder={s.anthropic_key_set ? t("set.key_saved_placeholder") : "sk-ant-..."} />
                <button class="btn" onclick={() => (showKey = !showKey)}>{showKey ? t("set.hide") : t("set.show")}</button>
                <button class="btn btn-primary" onclick={saveKey} disabled={!keyDraft.trim()}>{t("set.save")}</button>
              </div>
              <span class="hint" class:ok={s.anthropic_key_set} class:bad={!s.anthropic_key_set}>
                {s.anthropic_key_set ? t("set.key_set") : t("set.key_unset")}</span>
            </div>
            <div class="field">
              <label class="label" for="cmodel">{t("set.claude_model")}</label>
              <select class="select" id="cmodel" value={s.claude_model} onchange={e => save({ claude_model: e.currentTarget.value })}>
                {#each s.claude_models as m (m.id)}<option value={m.id}>{t("model." + m.id) === "model." + m.id ? m.label : t("model." + m.id)}</option>{/each}
              </select>
            </div>
            <p class="note">{t("set.claude_note")}</p>
          {:else}
            <div class="field">
              <label class="label" for="omodel">{t("set.ollama_model")}</label>
              <input class="input code" id="omodel" value={s.ollama_model} placeholder="qwen3:8b"
                     onchange={e => save({ ollama_model: e.currentTarget.value.trim() || "qwen3:8b" })} />
              {#if ollama !== null}<span class="hint" class:ok={ollama} class:bad={!ollama}>
                {ollama ? t("set.ollama_running") : t("set.ollama_stopped")}</span>{/if}
            </div>
            <p class="note">{t("set.ollama_note")}</p>
          {/if}
        </div>
      </Block>

      <Block id="set-hf" title={t("set.hf")} meta={s.hf_token_set ? t("env.set") : t("env.missing")} open={!s.hf_token_set}>
        <div class="stack-sm">
          <div class="field">
            <label class="label" for="hf">{t("set.hf_token")}</label>
            <div class="input-row">
              <input class="input code" id="hf" type={showHf ? "text" : "password"} bind:value={hfDraft} autocomplete="off"
                     placeholder={s.hf_token_set ? t("set.key_saved_placeholder") : "hf_..."} />
              <button class="btn" onclick={() => (showHf = !showHf)}>{showHf ? t("set.hide") : t("set.show")}</button>
              <button class="btn btn-primary" onclick={saveHf} disabled={!hfDraft.trim()}>{t("set.save")}</button>
            </div>
            <span class="hint" class:ok={s.hf_token_set} class:bad={!s.hf_token_set}>{s.hf_token_set ? t("set.hf_set") : t("set.hf_unset")}</span>
          </div>
          <div class="note">
            {t("set.hf_note")}
            <ul>
              <li><a href="https://huggingface.co/settings/tokens" target="_blank" rel="noopener">huggingface.co/settings/tokens</a></li>
              <li><a href="https://huggingface.co/pyannote/segmentation-3.0" target="_blank" rel="noopener">pyannote/segmentation-3.0</a></li>
              <li><a href="https://huggingface.co/pyannote/speaker-diarization-3.1" target="_blank" rel="noopener">pyannote/speaker-diarization-3.1</a></li>
              <li><a href="https://huggingface.co/pyannote/speaker-diarization-community-1" target="_blank" rel="noopener">pyannote/speaker-diarization-community-1</a></li>
            </ul>
          </div>
        </div>
      </Block>
    {/if}

    <Block id="set-lang" title={t("set.language")} meta={LANGS.find(l => l.id === app.lang)?.label}>
      <div class="seg" role="group" aria-label={t("set.language")}>
        {#each LANGS as l (l.id)}
          <button aria-pressed={app.lang === l.id} onclick={() => setLang(l.id)}>{l.label}</button>
        {/each}
      </div>
    </Block>

    <Block id="set-env" title={t("set.env")} open={false}>
      <div class="env">
        {#each env as [name, value, ok] (name)}
          <div class="env-cell"><span class="label">{name}</span><span class:ok class:bad={!ok}>{value}</span></div>
        {/each}
      </div>
    </Block>
  </div>
</div>

<style>
  .narrow { width: min(720px, 100%); }
  .ok { color: var(--ok); }
  .bad { color: var(--danger); }
  .archived { border-top: 1px solid var(--rule); padding-top: var(--s-3); margin-top: var(--s-2); }
  .archived-row { display: flex; align-items: center; justify-content: space-between; gap: var(--s-2); padding: var(--s-1) 0; }
  .env { display: grid; gap: var(--s-2); grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
  .env-cell { display: flex; flex-direction: column; gap: 2px; padding: var(--s-2) var(--s-3); background: var(--sunk); border-radius: var(--r-md); }
</style>
