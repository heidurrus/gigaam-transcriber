<script>
  import { app } from "../lib/state.svelte.js";
</script>

{#if app.toast}
  <div class="toast {app.toast.kind}" role="status">
    <span>{app.toast.message}</span>
    {#if app.toast.action}
      <button class="btn btn-sm" onclick={() => { const f = app.toast.onAction; app.toast = null; f && f(); }}>
        {app.toast.action}
      </button>
    {/if}
  </div>
{/if}

<style>
  .toast {
    position: fixed; left: 50%; bottom: var(--s-5); transform: translateX(-50%); z-index: 200;
    display: flex; align-items: center; gap: var(--s-3); max-width: calc(100vw - 2 * var(--s-4));
    padding: var(--s-2) var(--s-2) var(--s-2) var(--s-4); border-radius: var(--r-md);
    background: var(--ink); color: var(--paper); font-size: var(--t-sm); box-shadow: 0 8px 24px rgba(0,0,0,.18);
  }
  .toast.danger { background: var(--danger); color: #fff; }
  .toast .btn { background: transparent; color: inherit; border-color: currentColor; }
</style>
