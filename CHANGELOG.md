# Changelog

## 2.2.0 (2026-09-23): Increment 1, source library (part 1)

- **Everything is saved.** Recordings, uploaded audio, imported transcripts and summaries
  are kept in a local library per project, with their files. Close the app and it's all
  still there. Deleting is recoverable (Undo).
- **Projects.** Create and switch projects from the top of the left rail, rename or
  archive them in Settings. **Local only** per project: its summaries always use the local
  model, never the cloud.
- **New multi-screen interface** (the prototype's layout, Russian by default, English in
  Settings):
  - **Sources**: record or upload, live progress, the list of everything saved, with
    status, duration and speakers; rename and delete in place.
  - **Transcript**: audio player; click a timestamp to jump there, and the playing line is
    highlighted. Rename speakers once and the name appears everywhere, including the
    summary. Summary alongside, copy, download .txt, transcribe again.
  - **Settings**: a full screen for the project, AI summaries, speaker separation,
    language and environment status.
  - Steps 3–6 (Atoms, Document, Decomposition, Export) are shown as "later".
  - The previous single page is still at `/classic` while the new one settles.
- Recordings are named in the interface language; Russian plurals are correct everywhere.
- Fixed: project names differing only in Cyrillic letter case counted as different.

## 2.1.0 (2026-09-23)

- **Redesigned interface.**
  - Three collapsible sections: **Source** (upload or record), **Transcription options**
    (shared by both, collapsed to a one-line summary) and **Result** (summary, transcript,
    segments, word timestamps, each collapsible). The app remembers what you collapsed.
  - One spacing scale and one type scale across the page, Settings and the Setup screen.
    One set of components: section, panel, field, button, status.
  - Scales from phones (360 px) to wide screens: panels sit side by side when there's
    room and stack when there isn't; tables scroll instead of breaking the layout;
    Settings becomes a full-screen sheet on small windows.
  - Light and dark themes follow the system and use the prototype's palette.
    System fonts only, so nothing is fetched from the internet.
- **Fixed: recording on the Mac captured nothing ("No audio captured").**
  - The Mac app now runs Python inside its own process, so macOS asks for microphone
    and system-audio access *for Requirements Workbench*. Before, the app handed over to
    a separate Python program, which macOS silently refused without ever asking.
  - The app asks for the microphone before recording and, if access is off, says where
    to turn it on (System Settings → Privacy & Security → Microphone).
  - System audio no longer stalls when nothing is playing: silences are filled, so both
    channels stay in sync and Stop always works. A channel that delivers nothing, or
    system audio that stayed silent throughout, is reported with the likely reason.
- **Fixed:** the microphone list could be empty, and it offered "System audio" as a
  microphone (system audio is always recorded on its own).

- **AI summaries.** A **Summarize** button under every transcript (recorded, uploaded
  or imported) writes a summary in the transcript's language: overview, key points,
  requirements mentioned, decisions, open questions and action items. Each point
  cites the speaker and timestamp it came from. The text streams in live.
  - **Claude** (default: Claude Opus 5; Sonnet 5 or Haiku 4.5 selectable): add your
    Anthropic API key in **Settings → AI summaries**. Only the transcript text is sent,
    never audio.
  - **Local model via Ollama** (e.g. `qwen3:8b`): nothing leaves your computer.
  - Clear messages for a wrong key, rate limits, overload, no internet, or Ollama not running.
- Attaching a transcript file now says **Summarize**, and summarises right away.
- The **Summarize** button and the summary sit at the top of the results (the summary
  used to appear below a long transcript, out of sight). The page scrolls to the summary,
  shows elapsed time while waiting, and long transcripts scroll in their own box.
- If Summarize needs a key, entering it in Settings continues the summary automatically.
- Summary headings are written in the transcript's language too.
- **Fixed:** PDFs and transcript files were greyed out in the macOS desktop file picker.
- **Fixed:** keys and tokens from Settings are now stored in your user folder
  (private to you), not inside the app, where saving could break the macOS app or be
  lost on update. Existing tokens keep working.
- **Fixed:** pressing Save with an empty Hugging Face token field no longer deletes the saved token.
- **Import a transcript you already have.** Drop it where you drop audio: no speech
  recognition, it opens instantly with speakers and timestamps kept. Supported:
  - Microsoft Teams: `.vtt` or `.docx` transcript export (speaker names kept)
  - PDF with a text layer: Teams/Otter PDF exports or any document; page headers
    like "Page 2 of 5" are dropped. Scanned PDFs get a clear message (no OCR yet)
  - Zoom / Google Meet: `.vtt`
  - Subtitles: `.srt`
  - Plain text: `Name: text` lines, timestamped lines, or text copied from this app
  - This app's own `.json` result
  - Russian text in any common encoding (UTF-8, UTF-16, Windows-1251)
- Transcript tables show times as `mm:ss`, and file content is always shown as text,
  never interpreted as HTML (important for files from outside).
- Results appear without the 1.5 s polling delay.

## 1.1.1 (2026-09-23), published in release v2.0

- **Fixed: "Access to 127.0.0.1 was denied / HTTP ERROR 403" on startup.** The app used
  port 5000, which the macOS AirPlay Receiver (and sometimes other software) already
  uses. The app mistook it for an already-running copy of itself and showed that
  server's error page. It now uses its own port (47823), falls back to any free port
  when that's taken, and recognises a running copy only when it identifies itself.
- **Fixed: in browser mode the app quit right after first-run setup** instead of
  opening the app.
- Closing or killing the app always cleans up its instance record.

## 1.1.0 — Increment 0: stable base (2026-09-23), published in release v2.0

First step from GigaAM Transcriber towards Requirements Workbench
(`docs/specs/requirements-workbench-spec.md`, §12.2 increment 0). No new
end-user features yet: this makes the existing transcriber safe, installable
without prerequisites, and a native app on both Windows and macOS.

### Renamed: GigaAM Transcriber → Requirements Workbench
The app, installers and macOS bundle now carry the product's name. The Windows
installer upgrades an existing GigaAM Transcriber 1.0 in place and removes its
old shortcuts. GigaAM remains the speech-recognition engine.

### Install & platform
- **No prerequisites.** Installers bundle Python 3.12; the app's **Setup screen**
  installs PyTorch (CUDA / Apple GPU / CPU, picked for the machine), GigaAM (pinned),
  ffmpeg and the speech model on first launch, with progress, automatic retries and
  resume. Every later start re-checks in ~0.01 s and repairs anything missing.
- **macOS app** (`.dmg`, Apple Silicon, macOS 13+) with a native launcher, so the
  Dock and permission prompts show the app's name.
- **Windows installer**: per-user, no admin rights, installs WebView2 if missing,
  asks before deleting your data on uninstall.
- Desktop window by default on both OSes; `--browser` / "Browser Mode" shortcut optional.
  Falls back to the browser if the window can't open.
- Downloaded components, models and recordings live in
  `%LOCALAPPDATA%\RequirementsWorkbench` / `~/Library/Application Support/RequirementsWorkbench`.

### Recording
- **macOS desktop app records call audio** (macOS 14.2+, Core Audio process taps):
  no browser, screen sharing or virtual audio driver needed.
- Mic and system audio are recorded as **separate channels**, streamed to disk while
  recording (constant memory; a crash no longer loses the call).
- Problems with a channel (device missing, permission denied) are shown live and after
  recording instead of being silently dropped.

### Reliability & security
- The local server accepts only local connections in every mode (browser mode used to
  be reachable from the whole LAN, including the settings endpoint).
- Transcriptions are queued and run one at a time, showing the queue position.
- Fixed: temp upload leaked after ffmpeg conversion; desktop recordings downloaded
  as `.webm` although they were WAV; recording start ignored server errors.

### Test checklist for this increment
Windows 10/11 PC (ideally with an NVIDIA GPU) and a Mac (Apple Silicon, macOS 14.2+):
1. Install from the installer / `.dmg` on a machine **without Python** → app opens.
   *Mac: first open via right-click → Open (not notarized yet).*
2. Setup screen runs by itself and opens the app (few minutes, first run only).
   On NVIDIA check the console summary / GPU button shows the GPU.
3. Settings → paste a Hugging Face token (see README) → speaker separation works.
4. Upload an audio file → transcript (with and without speaker separation, a file > 1 min).
5. Record a short Teams/Zoom/YouTube call in the **desktop window**: both your voice and
   the other side are in the recording. Allow the microphone / system audio prompts.
6. Unplug the mic mid-recording (or deny a permission) → the app says which channel failed
   and still saves the other one.
7. Close and reopen the app → starts straight into the app (no setup), in a few seconds.
8. From another device on your network, open `http://<your-PC-IP>:47823` → must not connect.
