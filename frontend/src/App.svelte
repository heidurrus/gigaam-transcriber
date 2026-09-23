<script>
  import Rail from "./components/Rail.svelte";
  import Toast from "./components/Toast.svelte";
  import Sources from "./screens/Sources.svelte";
  import Transcript from "./screens/Transcript.svelte";
  import Settings from "./screens/Settings.svelte";
  import { api } from "./lib/api.js";
  import { app, t, loadProjects, loadSources, setLang } from "./lib/state.svelte.js";

  let ready = $state(false);
  let error = $state("");

  async function boot() {
    setLang(app.lang);
    try {
      const [device, models, health] = await Promise.all([
        api("/device-info"), api("/models"), api("/health").catch(() => null)]);
      app.device = device;
      app.models = models;
      app.health = health;
      if (!models.includes(app.options.model)) app.options.model = models[0];
      if (app.options.device !== "cpu" && !device.cuda && !device.mps) app.options.device = "cpu";
      if (app.options.device === "cuda" && !device.cuda && device.mps) app.options.device = "mps";
      await loadProjects();
      await loadSources();
      ready = true;
    } catch (err) {
      error = err.message;
    }
  }
  boot();
</script>

{#if error}
  <div class="boot-error note danger">{t("err.generic", { error })}</div>
{:else if ready}
  <div class="shell">
    <Rail />
    <main class="screen">
      {#if app.route.name === "transcript"}
        {#key app.route.id}<Transcript id={app.route.id} autoSummarize={app.route.summarize} />{/key}
      {:else if app.route.name === "settings"}
        <Settings />
      {:else}
        <Sources />
      {/if}
    </main>
  </div>
  <Toast />
{/if}

<style>
  .boot-error { margin: var(--s-6) auto; width: min(560px, 90vw); }
</style>
