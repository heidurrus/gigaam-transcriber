<script>
  let { name, size = 16 } = $props();
  const PATHS = {
    chevron: "M6 3.5 10.5 8 6 12.5",
    play: "M5 3.5v9l7.5-4.5z",
    pause: "M5 3.5v9M11 3.5v9",
    back: "M10 3.5 5.5 8 10 12.5",
    plus: "M8 3.5v9M3.5 8h9",
    close: "m4 4 8 8M12 4l-8 8",
    pencil: "M11 2.5l2.5 2.5-8 8H3v-2.5z",
    trash: "M3.5 4.5h9M6.5 4.5V3h3v1.5M5 4.5l.5 8h5l.5-8",
    copy: "M5.5 5.5h7v7h-7zM3.5 10.5v-7h7",
    download: "M8 3v7M5 7.5 8 10.5 11 7.5M3.5 12.5h9",
    check: "M3 8.5l3.5 3.5L13 5",
    mic: "M8 2.5a2 2 0 0 1 2 2V8a2 2 0 0 1-4 0V4.5a2 2 0 0 1 2-2ZM4.5 8a3.5 3.5 0 0 0 7 0M8 11.5v2",
    upload: "M8 11V3.5M5 6.5 8 3.5 11 6.5M3.5 12.5h9",
    lock: "M4.5 7.5h7v5h-7zM6 7.5V5.5a2 2 0 0 1 4 0v2",
  };
</script>

<svg class="icon" width={size} height={size} viewBox="0 0 16 16" aria-hidden="true">
  <path d={PATHS[name] || ""} fill={name === "play" ? "currentColor" : "none"} stroke="currentColor"
        stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" />
</svg>

<style>
  .icon { flex: none; display: block; }
</style>
