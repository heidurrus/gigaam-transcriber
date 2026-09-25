"""Requirement atoms: extract, verify, de-duplicate (spec increment 2, FR-ATM-*).

A source's segments are sent in chunks, each line labelled `[S<idx>]`, so the
model can cite where every atom came from. Quotes are then checked against the
real segment text: an atom with no verifiable quote is dropped (BR-02, "no
evidence, no atom"). A final pass compares the new atoms with the project's
existing ones to fold duplicates in and flag contradictions (BR-03, D-06).
"""
import re
import unicodedata

from core.llm import LLMError, complete_json
from core.transcripts import format_time

CHUNK_CHARS = 12000
MAX_EXISTING_FOR_DEDUP = 400

EXTRACT_SYSTEM = """You are a senior business analyst. You read one source of a software project
(a call transcript, an email or a document) and pull out requirement atoms: small, self-contained,
testable statements of what the system must do or how well it must do it.

Types:
- functional: behaviour the system must have ("The operator sees the client's order history when a call comes in").
- nfr: a quality or constraint (performance, security, availability, compliance, localisation…), with the number if one was said.
- question: something left open, contradictory or vague that the BA must clarify with the client.

Rules:
- One requirement per atom. Split compound statements.
- Write each statement in the language of the source, as a clear requirement ("The system must…" / "Система должна…").
  Resolve pronouns ("it", "this screen") using the context.
- Only what the participants actually asked for or agreed on. Skip small talk, greetings,
  the BA's own questions (unless they were confirmed), and ideas that were explicitly rejected.
- Every atom cites evidence: the number from the [S…] label of the line it came from, and a quote copied
  character for character from that line (a short contiguous fragment, not a paraphrase, no ellipses).
- If nothing in the text is a requirement, return an empty list."""

DEDUP_SYSTEM = """You compare requirement atoms of one software project.
Items marked N are new; items marked E already exist.
- duplicates: a new item that says the same thing as another item (same behaviour, same limits) — even
  if worded differently. Report the new item and the item it duplicates (prefer an E item, else an earlier N item).
- conflicts: two items that cannot both be true (different numbers, opposite rules, incompatible behaviour).
  Describe the contradiction in one short sentence in the language of the atoms.
Only report clear cases. At least one side of every pair must be a new (N) item. Do not report items that merely overlap."""

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "atoms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["functional", "nfr", "question"]},
                    "statement": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"segment": {"type": "integer"}, "quote": {"type": "string"}},
                            "required": ["segment", "quote"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["type", "statement", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["atoms"],
    "additionalProperties": False,
}

DEDUP_SCHEMA = {
    "type": "object",
    "properties": {
        "duplicates": {
            "type": "array",
            "items": {"type": "object", "properties": {"new": {"type": "string"}, "same_as": {"type": "string"}},
                      "required": ["new", "same_as"], "additionalProperties": False},
        },
        "conflicts": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"a": {"type": "string"}, "b": {"type": "string"}, "description": {"type": "string"}},
                      "required": ["a", "b", "description"], "additionalProperties": False},
        },
    },
    "required": ["duplicates", "conflicts"],
    "additionalProperties": False,
}

_QUOTE_CHARS = str.maketrans({"«": '"', "»": '"', "“": '"', "”": '"', "„": '"', "‘": "'", "’": "'",
                              "—": "-", "–": "-", "ё": "е", "Ё": "Е"})


def normalize(text):
    """Compare quotes loosely: case, whitespace, quote styles, dashes and ё don't matter."""
    text = unicodedata.normalize("NFC", text or "").translate(_QUOTE_CHARS).casefold()
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" .,;:!?\"'")


def segment_line(seg):
    who = seg.get("speaker_name") or seg.get("speaker")
    parts = [p for p in (who, format_time(seg["start"]) if seg.get("start") is not None else None) if p]
    return f"[S{seg['idx']}] " + (f"[{', '.join(parts)}] " if parts else "") + seg["text"]


def chunk_segments(segments, limit=None):
    limit = limit or CHUNK_CHARS
    chunks, current, size = [], [], 0
    for seg in segments:
        line = len(segment_line(seg)) + 1
        if current and size + line > limit:
            chunks.append(current)
            current, size = [], 0
        current.append(seg)
        size += line
    if current:
        chunks.append(current)
    return chunks


def verify_evidence(raw_evidence, chunk, source_id):
    """Keep only quotes that really occur in the transcript (BR-02).

    A quote attributed to the wrong line is re-attached to the line it is in,
    if that line is in the same chunk."""
    by_idx = {s["idx"]: s for s in chunk}
    kept, seen = [], set()
    for ev in raw_evidence or []:
        quote = (ev.get("quote") or "").strip()
        needle = normalize(quote)
        if len(needle) < 3:
            continue
        cited = by_idx.get(ev.get("segment"))
        candidates = ([cited] if cited else []) + [s for s in chunk if s is not cited]
        seg = next((s for s in candidates if needle in normalize(s["text"])), None)
        if seg is None or (seg["idx"], needle) in seen:
            continue
        seen.add((seg["idx"], needle))
        kept.append({"source_id": source_id, "segment_idx": seg["idx"], "start": seg.get("start"),
                     "speaker": seg.get("speaker"), "quote": quote})
    return kept


def _source_header(source):
    kind = {"email": "an email", "document": "a document"}.get(source["kind"], "a call or meeting transcript")
    return f"Source: {kind} titled “{source['title']}”."


def extract_atoms(store, source_id, prefs, api_key, ollama_url, progress=None, complete=complete_json):
    """Extract atoms from one source into the store; returns counts for the UI.

    Re-extraction drops the source's atoms still pending review and keeps the
    reviewed ones, so no decision is lost."""
    source = store.get_source(source_id)
    project = store.get_project(source["project_id"])
    segments, _ = store.transcript(source_id)
    if not segments:
        raise LLMError("This source has no text yet.")
    if project["local_only"]:
        prefs = {**prefs, "llm_provider": "ollama"}           # FR-PRJ-05: nothing leaves the machine
    model = prefs["ollama_model"] if prefs["llm_provider"] == "ollama" else prefs["claude_model"]
    report = progress or (lambda done, total, message: None)

    chunks = chunk_segments(segments)
    steps = len(chunks) + 1
    candidates, dropped = [], 0
    for i, chunk in enumerate(chunks):
        report(i, steps, f"Reading part {i + 1} of {len(chunks)}…" if len(chunks) > 1 else "Reading the source…")
        user = _source_header(source) + "\n\n" + "\n".join(segment_line(s) for s in chunk)
        reply = complete(EXTRACT_SYSTEM, user, EXTRACT_SCHEMA, prefs, api_key, ollama_url)
        for atom in reply.get("atoms") or []:
            statement = (atom.get("statement") or "").strip()
            if atom.get("type") not in ("functional", "nfr", "question") or not statement:
                dropped += 1
                continue
            evidence = verify_evidence(atom.get("evidence"), chunk, source_id)
            if not evidence:
                dropped += 1                                   # no evidence, no atom
                continue
            candidates.append({"type": atom["type"], "statement": statement, "evidence": evidence})

    report(len(chunks), steps, "Checking for duplicates and conflicts…")
    cleared = store.delete_pending_atoms_for_source(source_id)
    new_ids = store.add_atoms(project["id"], candidates, model=model) if candidates else []
    merged, conflicts = _dedup(store, project["id"], new_ids, prefs, api_key, ollama_url, complete)
    report(steps, steps, "Done")
    return {"extracted": len(new_ids) - merged, "merged": merged, "conflicts": conflicts,
            "dropped": dropped, "replaced": cleared, "provider": prefs["llm_provider"], "model": model}


def _dedup(store, project_id, new_ids, prefs, api_key, ollama_url, complete):
    if not new_ids:
        return 0, 0
    new_set = set(new_ids)
    atoms = [a for a in store.list_atoms(project_id) if a["status"] in ("pending", "accepted")]
    new = [a for a in atoms if a["id"] in new_set]
    existing = [a for a in atoms if a["id"] not in new_set][-MAX_EXISTING_FOR_DEDUP:]
    if len(new) + len(existing) < 2:
        return 0, 0
    labelled = [(f"N{i + 1}", a) for i, a in enumerate(new)] + [(f"E{i + 1}", a) for i, a in enumerate(existing)]
    ids = {key: a["id"] for key, a in labelled}
    lines = [f"{key} [{a['type']}] {a['statement']}" for key, a in labelled]
    try:
        reply = complete(DEDUP_SYSTEM, "\n".join(lines), DEDUP_SCHEMA, prefs, api_key, ollama_url)
    except LLMError:
        return 0, 0          # the atoms are saved; a failed comparison just means no suggestions

    merged_away, merged = set(), 0
    for d in reply.get("duplicates") or []:
        dup, target = ids.get(d.get("new")), ids.get(d.get("same_as"))
        if (not dup or not target or dup == target or dup not in new_set
                or dup in merged_away or target in merged_away):
            continue
        store.merge_atoms(dup, target)
        merged_away.add(dup)
        merged += 1

    conflicts, pairs = 0, set()
    for c in reply.get("conflicts") or []:
        a, b = ids.get(c.get("a")), ids.get(c.get("b"))
        pair = frozenset((a, b))
        if (not a or not b or a == b or not (pair & new_set) or pair & merged_away
                or pair in pairs or not (c.get("description") or "").strip()):
            continue
        pairs.add(pair)
        store.add_conflict(project_id, a, b, c["description"])
        conflicts += 1
    return merged, conflicts
