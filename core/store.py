"""Local project store: SQLite database + one folder per source (spec increment 1).

Spec refs: FR-PRJ-01…05 (projects, "Local only"), FR-SRC-07 (sources list),
FR-TR-01/05 (stored transcript, speaker names), NFR-DATA-03 (persistence),
NFR-MAINT-02 (team-ready: UUID keys, created/updated by/at on every row, the
audit log doubles as a change feed), NFR-AUD-02 (audit log of changes).

Stdlib only. One connection per call keeps it safe across Flask's threads;
WAL mode lets readers and a writer work at the same time.
"""
import getpass
import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

from core.paths import app_data_dir

SCHEMA_VERSION = 1
SOURCE_KINDS = {"recording", "audio", "transcript", "document"}
SOURCE_STATUSES = {"recorded", "processing", "ready", "failed"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, local_only INTEGER NOT NULL DEFAULT 0,
  archived INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL, created_by TEXT NOT NULL, updated_at REAL NOT NULL, updated_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  kind TEXT NOT NULL, title TEXT NOT NULL, original_filename TEXT,
  status TEXT NOT NULL, error TEXT, duration REAL, speakers INTEGER, asr_model TEXT,
  diarized INTEGER NOT NULL DEFAULT 0, import_format TEXT, audio_file TEXT, text TEXT, words_json TEXT,
  deleted_at REAL,
  created_at REAL NOT NULL, created_by TEXT NOT NULL, updated_at REAL NOT NULL, updated_by TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS sources_by_project ON sources(project_id, deleted_at, created_at);
CREATE TABLE IF NOT EXISTS segments (
  source_id TEXT NOT NULL REFERENCES sources(id), idx INTEGER NOT NULL,
  speaker TEXT, start REAL, "end" REAL, text TEXT NOT NULL, PRIMARY KEY (source_id, idx));
CREATE TABLE IF NOT EXISTS speakers (
  source_id TEXT NOT NULL REFERENCES sources(id), label TEXT NOT NULL, name TEXT NOT NULL,
  updated_at REAL NOT NULL, updated_by TEXT NOT NULL, PRIMARY KEY (source_id, label));
CREATE TABLE IF NOT EXISTS summaries (
  id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
  provider TEXT NOT NULL, model TEXT NOT NULL, text TEXT NOT NULL,
  created_at REAL NOT NULL, created_by TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS summaries_by_source ON summaries(source_id, created_at);
CREATE TABLE IF NOT EXISTS audit_log (
  id TEXT PRIMARY KEY, entity TEXT NOT NULL, entity_id TEXT NOT NULL, action TEXT NOT NULL,
  before_json TEXT, after_json TEXT, at REAL NOT NULL, by TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS audit_by_entity ON audit_log(entity, entity_id, at);
"""

PROJECT_FIELDS = ("id", "name", "local_only", "archived", "created_at", "created_by", "updated_at", "updated_by")
SOURCE_FIELDS = ("id", "project_id", "kind", "title", "original_filename", "status", "error", "duration",
                 "speakers", "asr_model", "diarized", "import_format", "audio_file", "deleted_at",
                 "created_at", "created_by", "updated_at", "updated_by")


class StoreError(ValueError):
    """A request the store refuses (unknown id, duplicate name, …)."""


def current_user():
    try:
        return getpass.getuser()
    except Exception:
        return "local"


class Store:
    def __init__(self, root=None, user=None, clock=time.time):
        self.root = root or os.path.join(app_data_dir(), "library")
        os.makedirs(self.root, exist_ok=True)
        self.db_path = os.path.join(self.root, "workbench.db")
        self.user = user or current_user()
        self._clock = clock
        self._write_lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)
            c.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))

    # ── plumbing ─────────────────────────────────────────────────────────────
    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def _write(self):
        with self._write_lock, self._conn() as c:
            yield c

    def _audit(self, c, entity, entity_id, action, before=None, after=None):
        c.execute("INSERT INTO audit_log VALUES (?,?,?,?,?,?,?,?)",
                  (str(uuid.uuid4()), entity, entity_id, action,
                   json.dumps(before, ensure_ascii=False) if before is not None else None,
                   json.dumps(after, ensure_ascii=False) if after is not None else None,
                   self._clock(), self.user))

    def _stamp(self):
        now = self._clock()
        return now, self.user

    @staticmethod
    def _row(row, fields):
        if row is None:
            return None
        d = {f: row[f] for f in fields}
        for flag in ("local_only", "archived", "diarized"):
            if flag in d and d[flag] is not None:
                d[flag] = bool(d[flag])
        return d

    # ── projects ─────────────────────────────────────────────────────────────
    def list_projects(self, include_archived=False):
        q = "SELECT * FROM projects" + ("" if include_archived else " WHERE archived = 0") + " ORDER BY created_at"
        with self._conn() as c:
            return [self._row(r, PROJECT_FIELDS) for r in c.execute(q)]

    def get_project(self, project_id):
        with self._conn() as c:
            p = self._row(c.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone(), PROJECT_FIELDS)
        if p is None:
            raise StoreError("project not found")
        return p

    def _check_name(self, c, name, exclude_id=None):
        name = (name or "").strip()
        if not name:
            raise StoreError("project name must not be empty")
        if len(name) > 100:
            raise StoreError("project name is too long (max 100 characters)")
        # Compare in Python: SQLite's lower() only folds ASCII, so Cyrillic names would slip through.
        folded = name.casefold()
        clash = any(r["name"].casefold() == folded
                    for r in c.execute("SELECT id, name FROM projects WHERE id != ?", (exclude_id or "",)))
        if clash:
            raise StoreError(f"a project called “{name}” already exists")
        return name

    def create_project(self, name, local_only=False):
        with self._write() as c:
            name = self._check_name(c, name)
            now, by = self._stamp()
            pid = str(uuid.uuid4())
            c.execute("INSERT INTO projects VALUES (?,?,?,?,?,?,?,?)", (pid, name, int(local_only), 0, now, by, now, by))
            project = self._row(c.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone(), PROJECT_FIELDS)
            self._audit(c, "project", pid, "create", after=project)
        return project

    def update_project(self, project_id, **changes):
        allowed = {"name", "local_only", "archived"}
        unknown = set(changes) - allowed
        if unknown:
            raise StoreError(f"cannot change {sorted(unknown)}")
        with self._write() as c:
            before = self._row(c.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone(), PROJECT_FIELDS)
            if before is None:
                raise StoreError("project not found")
            if "name" in changes:
                changes["name"] = self._check_name(c, changes["name"], exclude_id=project_id)
            for flag in ("local_only", "archived"):
                if flag in changes:
                    changes[flag] = int(bool(changes[flag]))
            if changes:
                now, by = self._stamp()
                sets = ", ".join(f"{k} = ?" for k in changes)
                c.execute(f"UPDATE projects SET {sets}, updated_at = ?, updated_by = ? WHERE id = ?",
                          (*changes.values(), now, by, project_id))
            after = self._row(c.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone(), PROJECT_FIELDS)
            if after != before:
                self._audit(c, "project", project_id, "update", before, after)
        return after

    def ensure_default_project(self, name="My project"):
        projects = self.list_projects()
        return projects[0] if projects else self.create_project(name)

    def current_project(self):
        """The project the app shows; falls back to the first active one (created if none)."""
        with self._conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key = 'current_project'").fetchone()
        if row:
            try:
                p = self.get_project(row["value"])
                if not p["archived"]:
                    return p
            except StoreError:
                pass
        return self.ensure_default_project()

    def set_current_project(self, project_id):
        p = self.get_project(project_id)
        if p["archived"]:
            raise StoreError("that project is archived; restore it first")
        with self._write() as c:
            c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('current_project', ?)", (project_id,))
        return p

    # ── sources ──────────────────────────────────────────────────────────────
    def source_dir(self, source):
        return os.path.join(self.root, "projects", source["project_id"], "sources", source["id"])

    def create_source(self, project_id, kind, title, original_filename=None, status="processing", **fields):
        if kind not in SOURCE_KINDS:
            raise StoreError(f"unknown source kind {kind}")
        self.get_project(project_id)
        with self._write() as c:
            now, by = self._stamp()
            sid = str(uuid.uuid4())
            c.execute("""INSERT INTO sources (id, project_id, kind, title, original_filename, status, asr_model,
                         import_format, created_at, created_by, updated_at, updated_by)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (sid, project_id, kind, (title or "Untitled").strip()[:200], original_filename, status,
                       fields.get("asr_model"), fields.get("import_format"), now, by, now, by))
            source = self._row(c.execute("SELECT * FROM sources WHERE id = ?", (sid,)).fetchone(), SOURCE_FIELDS)
            self._audit(c, "source", sid, "create", after=source)
        os.makedirs(self.source_dir(source), exist_ok=True)
        return source

    def get_source(self, source_id, include_deleted=False):
        with self._conn() as c:
            row = c.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        s = self._row(row, SOURCE_FIELDS)
        if s is None or (s["deleted_at"] and not include_deleted):
            raise StoreError("source not found")
        return s

    def list_sources(self, project_id):
        with self._conn() as c:
            rows = c.execute("""SELECT s.*, (SELECT COUNT(*) FROM summaries m WHERE m.source_id = s.id) AS summary_count
                                FROM sources s WHERE s.project_id = ? AND s.deleted_at IS NULL
                                ORDER BY s.created_at DESC""", (project_id,)).fetchall()
        out = []
        for r in rows:
            s = self._row(r, SOURCE_FIELDS)
            s["has_summary"] = r["summary_count"] > 0
            out.append(s)
        return out

    def update_source(self, source_id, audit=True, **changes):
        allowed = {"title", "status", "error", "duration", "speakers", "asr_model", "diarized",
                   "import_format", "audio_file", "text", "words_json"}
        unknown = set(changes) - allowed
        if unknown:
            raise StoreError(f"cannot change {sorted(unknown)}")
        if "status" in changes and changes["status"] not in SOURCE_STATUSES:
            raise StoreError(f"unknown status {changes['status']}")
        if "title" in changes:
            changes["title"] = (changes["title"] or "").strip()[:200]
            if not changes["title"]:
                raise StoreError("title must not be empty")
        with self._write() as c:
            before = self._row(c.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone(), SOURCE_FIELDS)
            if before is None:
                raise StoreError("source not found")
            now, by = self._stamp()
            if "diarized" in changes:
                changes["diarized"] = int(bool(changes["diarized"]))
            sets = ", ".join(f"{k} = ?" for k in changes)
            c.execute(f"UPDATE sources SET {sets}, updated_at = ?, updated_by = ? WHERE id = ?",
                      (*changes.values(), now, by, source_id))
            after = self._row(c.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone(), SOURCE_FIELDS)
            if audit:
                self._audit(c, "source", source_id, "update", before, after)
        return after

    def delete_source(self, source_id):
        """Soft delete: hidden everywhere, files kept, recoverable with restore_source()."""
        with self._write() as c:
            before = self._row(c.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone(), SOURCE_FIELDS)
            if before is None or before["deleted_at"]:
                raise StoreError("source not found")
            now, by = self._stamp()
            c.execute("UPDATE sources SET deleted_at = ?, updated_at = ?, updated_by = ? WHERE id = ?",
                      (now, now, by, source_id))
            self._audit(c, "source", source_id, "delete", before)

    def restore_source(self, source_id):
        with self._write() as c:
            now, by = self._stamp()
            n = c.execute("UPDATE sources SET deleted_at = NULL, updated_at = ?, updated_by = ? "
                          "WHERE id = ? AND deleted_at IS NOT NULL", (now, by, source_id)).rowcount
            if not n:
                raise StoreError("nothing to restore")
            self._audit(c, "source", source_id, "restore")

    def save_transcript(self, source_id, result, asr_model=None):
        """Store a transcription or import result (the shape produced by app._transcribe
        and core.transcripts) and mark the source ready."""
        segments = result.get("segments") or []
        if not segments and result.get("text"):
            segments = [{"text": result["text"]}]
        ends = [s["end"] for s in segments if s.get("end") is not None]
        speakers = {s.get("speaker") for s in segments if s.get("speaker")}
        with self._write() as c:
            c.execute("DELETE FROM segments WHERE source_id = ?", (source_id,))
            c.executemany('INSERT INTO segments (source_id, idx, speaker, start, "end", text) VALUES (?,?,?,?,?,?)',
                          [(source_id, i, s.get("speaker"), s.get("start"), s.get("end"), s.get("text", ""))
                           for i, s in enumerate(segments)])
        changes = dict(status="ready", error=None, text=result.get("text", ""),
                       diarized=bool(result.get("diarized")), speakers=len(speakers) or None,
                       words_json=json.dumps(result["words"], ensure_ascii=False) if result.get("words") else None)
        if ends:
            changes["duration"] = max(ends)
        if asr_model:
            changes["asr_model"] = asr_model
        if result.get("imported"):
            changes["import_format"] = result["imported"].get("format")
        return self.update_source(source_id, **changes)

    def fail_source(self, source_id, error):
        return self.update_source(source_id, status="failed", error=str(error)[:1000])

    def transcript(self, source_id):
        """Segments with display names applied, plus the speaker map."""
        with self._conn() as c:
            names = {r["label"]: r["name"] for r in c.execute(
                "SELECT label, name FROM speakers WHERE source_id = ?", (source_id,))}
            segs = [dict(idx=r["idx"], speaker=r["speaker"], start=r["start"], end=r["end"], text=r["text"])
                    for r in c.execute('SELECT idx, speaker, start, "end", text FROM segments '
                                       'WHERE source_id = ? ORDER BY idx', (source_id,))]
        for s in segs:
            s["speaker_name"] = names.get(s["speaker"], s["speaker"])
        return segs, names

    def rename_speaker(self, source_id, label, name):
        name = (name or "").strip()[:80]
        self.get_source(source_id)
        with self._write() as c:
            exists = c.execute("SELECT 1 FROM segments WHERE source_id = ? AND speaker = ? LIMIT 1",
                               (source_id, label)).fetchone()
            if not exists:
                raise StoreError(f"no speaker {label!r} in this source")
            old = c.execute("SELECT name FROM speakers WHERE source_id = ? AND label = ?", (source_id, label)).fetchone()
            now, by = self._stamp()
            if name and name != label:
                c.execute("INSERT OR REPLACE INTO speakers VALUES (?,?,?,?,?)", (source_id, label, name, now, by))
            else:
                c.execute("DELETE FROM speakers WHERE source_id = ? AND label = ?", (source_id, label))
            self._audit(c, "speaker", f"{source_id}:{label}", "rename",
                        {"name": old["name"] if old else label}, {"name": name or label})

    def transcript_text(self, source_id):
        """Plain text for summaries, with renamed speakers and timestamps."""
        from core.transcripts import format_time
        segs, _ = self.transcript(source_id)
        lines = []
        for s in segs:
            prefix = f"[{s['speaker_name']}] " if s.get("speaker_name") else ""
            if s.get("start") is not None:
                end = f" - {format_time(s['end'])}" if s.get("end") is not None else ""
                prefix += f"[{format_time(s['start'])}{end}] "
            lines.append(prefix + s["text"])
        return "\n".join(lines)

    # ── summaries ────────────────────────────────────────────────────────────
    def add_summary(self, source_id, provider, model, text):
        self.get_source(source_id)
        with self._write() as c:
            now, by = self._stamp()
            mid = str(uuid.uuid4())
            c.execute("INSERT INTO summaries VALUES (?,?,?,?,?,?,?)", (mid, source_id, provider, model, text, now, by))
            self._audit(c, "summary", mid, "create", after={"source_id": source_id, "provider": provider, "model": model})
        return {"id": mid, "source_id": source_id, "provider": provider, "model": model, "text": text,
                "created_at": now, "created_by": by}

    def latest_summary(self, source_id):
        with self._conn() as c:
            r = c.execute("SELECT * FROM summaries WHERE source_id = ? ORDER BY created_at DESC LIMIT 1",
                          (source_id,)).fetchone()
        return dict(r) if r else None

    # ── audit ────────────────────────────────────────────────────────────────
    def audit(self, entity=None, entity_id=None, limit=200):
        q, args = "SELECT * FROM audit_log", []
        conds = []
        if entity:
            conds.append("entity = ?")
            args.append(entity)
        if entity_id:
            conds.append("entity_id = ?")
            args.append(entity_id)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY at DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            rows = c.execute(q, args).fetchall()
        return [dict(r, before=json.loads(r["before_json"]) if r["before_json"] else None,
                     after=json.loads(r["after_json"]) if r["after_json"] else None) for r in rows]

    # ── files ────────────────────────────────────────────────────────────────
    def attach_file(self, source, src_path, name, move=False):
        """Copy (or move) a file into the source's folder; returns the stored path."""
        dest_dir = self.source_dir(source)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, os.path.basename(name))
        (shutil.move if move else shutil.copy2)(src_path, dest)
        return dest
