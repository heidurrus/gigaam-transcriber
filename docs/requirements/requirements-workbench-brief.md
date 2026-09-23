# Requirements Workbench — Requirements Brief
Date: 2026-09-23 · Interviewed: product owner / author · Status: Pending confirmation
Feeds: `docs/specs/requirements-workbench-spec.md` v0.4 (spec IDs in brackets)

Status legend: ✅ confirmed by user · 🔶 assumed default · ❓ open

## 1. Goal
A local-first tool that takes a BA from recorded client calls and documents to a traceable FRD and Jira backlog. It is built by evolving the existing **gigaam-transcriber** app. The success metric is not stated yet (❓ R-Q1).

## 2. Users & roles
| Role | Needs / permissions | Status |
|---|---|---|
| Business analyst | Sole user of an install; full access to their projects | ✅ single user in v1 |
| Future team members | Shared projects later. v1 data model must not block this | ✅ "single now, team later" |

## 3. Scope
- **In scope (v1):** desktop app on **macOS and Windows** (browser mode optional); fully automatic dependency installation; multiple projects (create, rename, switch, archive); recording and import; local ASR + diarization; atom extraction and review; conflict resolution; FRD build, versions and DOCX; decomposition and INVEST; Jira export through the Atlassian Remote MCP; RU/EN UI; baseline features kept (mic selector, CPU/GPU toggle, download recording, copy/export transcript).
- **Out of scope (v1):** multi-user sync, server deployment, Jira Data Center/Server, editing document prose directly.
- **Later:** team mode (sharing, sync), possibly Confluence export through the same Atlassian MCP.

## 4. Main flow
Record/import → transcribe (queued, 1 GPU job at a time) → extract atoms (cloud or local per project) → review (accept / reject / edit; resolve conflicts) → build FRD (built-in or GOST template) → decompose → Jira preview → push through MCP.

## 5. Decisions → requirements
| ID | Requirement | Priority | Status | Spec refs |
|---|---|---|---|---|
| R-01 | Single-user local app. Every record carries a stable UUID, `created_by` and timestamps so team sync can be added later | Must | ✅ | A-01, NFR-MAINT-02 |
| R-02 | Transcript text may be sent to cloud LLM stages. Audio never leaves the machine | Must | ✅ | NFR-DATA-01 |
| R-03 | A per-project **"Local only"** switch forces every LLM stage onto Ollama and blocks cloud calls | Must | ✅ | FR-PRJ-05 |
| R-04 | Frontend rebuilt with a JS framework compiled into `static/`, served by the existing Flask + pywebview shell | Must | ✅ (framework choice 🔶 tech lead) | §12, Q-01 |
| R-05 | Basic project management: create, rename, switch, archive | Must | ✅ | FR-PRJ-03 |
| R-06 | Jira integration through the **Atlassian Remote MCP server (Rovo)**, Jira Cloud only, OAuth sign-in | Must | ✅ | FR-JIRA-*, FR-SET-05 |
| R-07 | The app calls the MCP tools **directly and deterministically** from the preview. No LLM in the push path | Must | ✅ | FR-JIRA-04 |
| R-08 | Conflict resolution: keep one side / merge into an edited atom / convert to a client question. Open conflicts warn but don't block the FRD build | Must | ✅ | FR-ATM-04, FR-DOC-01 |
| R-09 | The BA edits atoms and backlog items/AC directly. Document prose changes only through atoms or pinned free-text blocks | Must | ✅ | FR-ATM-07, FR-DEC-05, FR-DOC-04 |
| R-10 | Local audit log of review decisions (who, when, action, old → new), stored with the project | Must | ✅ | NFR-AUD-02 |
| R-11 | UI in Russian (default) and English, with a switch | Must | ✅ | NFR-I18N-01 |
| R-12 | Keep the baseline mic selector, CPU/GPU toggle, recording download, and transcript copy/export | Should | ✅ | FR-SRC-01a/01b/05a, FR-TR-07 |
| R-13 | Record mic and system audio as separate channels. The mic channel is labelled "BA"; diarization runs on the system channel | Must | ✅ | FR-SRC-01, gap #21 |
| R-14 | Job queue: 1 GPU transcription at a time; LLM stages may run in parallel; recording is always allowed | Must | ✅ | FR-SRC-06, NFR-REL-04 |
| R-15 | FRD templates: a neutral built-in template plus GOST through the `write-frd-gost` skill. DOCX source refs as footnotes | Must | ✅ | FR-DOC-09 |
| R-16 | Development evolves the `gigaam-transcriber` repo in place (rebrand, keep history) | — | ✅ | §12, Q-27 |
| R-17 | Runs as a native desktop app (not a browser tab) on **both Windows 10/11 and macOS 13+ (Apple Silicon)** with full feature parity, including system-audio + mic recording on macOS. Browser mode is an optional extra | Must | ✅ | FR-PLAT-01/02/03/06, NFR-COMPAT-01 |
| R-18 | **All dependencies install automatically.** No preinstalled Python/git/ffmpeg/brew/winget; an embedded runtime in the installer, a first-run Setup screen, a dependency check on every startup, and optional parts (Ollama, extra models) installed on demand | Must | ✅ (design 🔶 §12.4) | FR-PLAT-04/05, NFR-COMPAT-03 |

Key acceptance criteria:
- R-03 AC1 Given a project with "Local only" on When any LLM stage runs Then no request goes to a cloud endpoint, and a cloud model chosen in Settings is shown as overridden.
- R-03 AC2 (negative) Given "Local only" is on and Ollama is not running When extraction starts Then the job is blocked with "Ollama не запущена" (Ollama not running). It never falls back to the cloud.
- R-07 AC1 Given the preview When "Выгрузить" (Push) is pressed Then only `createJiraIssue` / `editJiraIssue` / `createIssueLink` calls are made for the checked rows, in parent-before-child order.
- R-07 AC2 (negative) Given a retry after a partial failure Then items that already have a key are not created again (checked by the stored key, plus a JQL lookup of the workbench label).
- R-17 AC1 Given a Mac When I open the app from Applications Then a native window opens with no Terminal, and recording captures system audio + mic with permission prompts naming the app.
- R-18 AC1 Given a clean Windows or macOS machine with nothing preinstalled When I install and open the app Then setup completes automatically (except the guided Hugging Face licence step) and I can transcribe, with no terminal and no admin rights.
- R-18 AC2 Given a dependency goes missing or changes after an update When the app starts Then it reinstalls just that part automatically.
- R-13 AC1 Given a recorded call Then every segment from the mic channel is labelled "BA" without diarization, and the remote speakers are "Спикер 1…N".

## 6. Business rules
| ID | Rule | Status |
|---|---|---|
| BR-15 | Each pushed issue gets the label `rw-<item-uuid>` for idempotent lookup | 🔶 |
| BR-16 | The "Local only" setting is saved per project and overrides the global stage model settings | ✅ |
| BR-17 | Conflict → question: the new question atom links to both conflicting atoms, and they stay flagged until the question is answered | ✅ (link rule 🔶) |

## 7. Non-functional requirements (changed)
| Category | Requirement | Status |
|---|---|---|
| Security | OAuth tokens for the Atlassian MCP stored in the OS keychain, or `.env` with restricted file permissions | 🔶 |
| Compatibility | Jira Cloud only in v1 | ✅ |
| Maintainability | Data model ready for sync: UUID keys, no auto-increment IDs exposed across projects, change log per entity | ✅ (design 🔶) |
| Performance | Jira push handles the MCP server's rate limits with backoff; ≥ 50 issues per push | 🔶 |

## 8. Constraints & dependencies
- Needs internet access plus an Atlassian Cloud account with Jira access that is allowed to use the Atlassian Remote MCP (admin may need to enable it).
- The MCP server acts only with the signed-in user's own Jira permissions.
- The existing Python/Flask/pywebview stack and Windows installer stay (the installer gains a JS build step at release time only).
- macOS system audio can't be captured by the baseline's `soundcard` loopback, so it needs a native ScreenCaptureKit / Core Audio module (spike in increment 0).
- macOS distribution needs an Apple Developer ID for signing + notarization; Windows signing is recommended (Q-29).
- Hugging Face licence acceptance for the pyannote models can't be automated; it is guided inside the Setup screen.

## 9. Assumptions (🔶)
| ID | Assumption | Risk if wrong |
|---|---|---|
| A-15 | Read calls to Jira (get issue, JQL) are allowed while building the preview; only writes wait for the push | If reads are forbidden, the preview must use cached state and can't detect remote edits |
| A-16 | The Atlassian MCP tool set (createJiraIssue, editJiraIssue, getJiraIssue, searchJiraIssuesUsingJql, getJiraProjectIssueTypesMetadata, createIssueLink) covers epic/story/sub-task creation with parent links | Missing capability → fallback to REST |
| A-17 | Recording consent: a reminder only, with nothing stored | Legal exposure in some jurisdictions |
| A-18 | Framework choice (Svelte/React/Vue) is up to the tech lead | Low |
| A-19 | macOS 13+ on Apple Silicon; Intel Macs best effort | Older/Intel Macs lack native audio capture or are too slow |
| A-20 | Signing certificates available | Gatekeeper/SmartScreen warnings; unreliable macOS permissions |
| A-21 | PyTorch CUDA build downloaded at first run, not bundled | A bundled build means a multi-GB installer |

## 10. Open questions (❓)
| ID | Question | Owner | Blocks? |
|---|---|---|---|
| R-Q1 | Success metric for v1 (e.g. hours saved per call → FRD; % of requirements with a source link)? | PO | No |
| R-Q2 | Import formats and size limits (Q-11) | PO | No |
| R-Q3 | Deleting a source that has used atoms (Q-13) | PO | No |
| R-Q4 | Re-extract / rebuild behaviour (Q-14, Q-15) — defaults assumed | PO | No |
| R-Q5 | Recording consent handling (Q-10) | Legal | No (assumed A-17) |
| R-Q6 | Apple Developer ID / Windows code-signing certificate: available, and who owns them? (Q-29) | PO | Blocks macOS release |
| R-Q7 | Intel Mac support (Q-28) and app self-update (Q-30)? | PO | No |

## 11. Decision log
All decisions were taken on 2026-09-23. IDs match spec §13.

| ID | Decision | Rationale |
|---|---|---|
| D-01 | Single user, team-ready data model | Faster v1 without closing off team mode |
| D-02 | Cloud text OK + per-project "Local only" switch | Balances quality with client NDAs |
| D-03 | Framework frontend compiled into `static/` | 7 stateful screens |
| D-04 | Basic multi-project | BAs juggle several engagements |
| D-05 | Jira through the Atlassian Remote MCP (Rovo), Cloud, OAuth | Uses the existing Atlassian MCP |
| D-06 | Three-way conflict resolution, non-blocking | Flexibility without stalling the document |
| D-07 | Edit atoms + stories; document only through free blocks | Keeps traceability intact |
| D-08 | App calls the MCP tools directly | Keeps the dry-run and idempotency guarantees |
| D-09 | Local audit log | Trust now, change feed for team mode later |
| D-10 | RU + EN UI | Baseline EN, prototype RU |
| D-11 | Separate mic/system channels | Reliable "BA" attribution |
| D-12 | GPU queue of 1 | Avoid GPU out-of-memory |
| D-13 | Built-in + GOST templates, footnote refs | Covers neutral and GOST clients |
| D-14 | Evolve the repo in place | Keeps history and installer |
| D-15 | Keep all 4 dropped baseline features | Avoid regression |
| D-16 | Desktop app on macOS + Windows, browser optional | Users expect a normal app on either OS |
| D-17 | Automatic dependency installation | Non-technical BAs must be able to install it |
