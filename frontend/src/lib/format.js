export function fmtTime(seconds) {
  if (seconds === undefined || seconds === null || seconds === "" || Number.isNaN(Number(seconds))) return "";
  const total = Math.max(0, Math.floor(Number(seconds)));
  const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60;
  const mm = String(m).padStart(2, "0"), ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

export function fmtDuration(seconds, lang = "ru") {
  if (!seconds) return "";
  const m = Math.round(seconds / 60);
  const unit = lang === "en" ? { min: "min", s: "s" } : { min: "мин", s: "с" };
  return m >= 1 ? `${m} ${unit.min}` : `${Math.round(seconds)} ${unit.s}`;
}

export function fmtDate(epochSeconds, lang) {
  if (!epochSeconds) return "";
  return new Date(epochSeconds * 1000).toLocaleString(lang === "en" ? "en-GB" : "ru-RU",
    { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Minimal Markdown → HTML for summaries. Escapes first, so model output can never inject HTML.
export function renderMarkdown(md) {
  const inline = t => t
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/\[([^[\]]{1,60}?,\s*\d{1,2}:\d{2}(?::\d{2})?(?:\s*[–-]\s*\d{1,2}:\d{2}(?::\d{2})?)?)\]/g, '<span class="ref">[$1]</span>');
  let html = "", list = null;
  const close = () => { if (list) { html += `</${list}>`; list = null; } };
  for (const raw of esc(md).split("\n")) {
    const line = raw.trimEnd();
    let m;
    if ((m = line.match(/^#{1,6}\s+(.*)$/))) { close(); html += `<h3>${inline(m[1])}</h3>`; }
    else if ((m = line.match(/^\s*[-*•]\s+(.*)$/))) {
      if (list !== "ul") { close(); html += "<ul>"; list = "ul"; }
      html += `<li>${inline(m[1])}</li>`;
    } else if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) {
      if (list !== "ol") { close(); html += "<ol>"; list = "ol"; }
      html += `<li>${inline(m[1])}</li>`;
    } else if (!line.trim()) close();
    else { close(); html += `<p>${inline(line)}</p>`; }
  }
  close();
  return html;
}

const TRANSCRIPT_EXTS = [".vtt", ".srt", ".txt", ".docx", ".pdf", ".json", ".md"];
export const isTranscriptFile = name => TRANSCRIPT_EXTS.some(ext => (name || "").toLowerCase().endsWith(ext));

export function speakerClass(label, order) {
  const i = order.indexOf(label);
  return `spk-${(i < 0 ? 0 : i) % 5}`;
}

export function downloadText(filename, text) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
