<script>
  // Collapsible section; remembers open/closed per viewer when `id` is given.
  import Icon from "./Icon.svelte";
  import { writePref } from "../lib/state.svelte.js";

  let { id = null, title, meta = "", open = true, children, actions } = $props();

  function initial() {
    if (!id) return open;
    try { const v = localStorage.getItem("wb.open." + id); return v === null ? open : v === "1"; }
    catch (_) { return open; }
  }
  let isOpen = $state(initial());
  function toggled(e) {
    isOpen = e.currentTarget.open;
    if (id) writePref("open." + id, isOpen ? 1 : 0);
  }
</script>

<details class="block" open={isOpen} ontoggle={toggled}>
  <summary>
    <span class="chevron"><Icon name="chevron" /></span>
    <span class="block-title">{title}</span>
    {#if meta}<span class="block-meta">{meta}</span>{/if}
    {#if actions}<span class="block-actions" onclick={e => e.preventDefault()} role="presentation">{@render actions()}</span>{/if}
  </summary>
  <div class="block-body">{@render children()}</div>
</details>

<style>
  .block-actions { display: flex; gap: var(--s-2); margin-left: var(--s-2); }
  .block-meta + .block-actions { margin-left: var(--s-3); }
</style>
