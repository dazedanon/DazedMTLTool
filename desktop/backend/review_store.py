"""Indexed review of production output; edits overlay immutable engine files."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from util.rpgmaker_qa_manifest import build_manifest, resolve_pointer, _mechanical_evidence
from .project import atomic_json, digest, review_flags


class ReviewStore:
    def __init__(self, job_dir: Path):
        self.root = job_dir
        self.path = job_dir / "review.sqlite3"

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                db.execute("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, file TEXT, source TEXT, live TEXT, paths TEXT, category TEXT, code INTEGER, flags TEXT, override TEXT, reviewed INTEGER NOT NULL DEFAULT 0)")
                db.execute("CREATE INDEX IF NOT EXISTS review_status ON records(reviewed,file)")
                yield db
        finally:
            db.close()

    def index(self):
        manifest = build_manifest(self.root / "translated", "release")
        inputs = {}
        changed = []
        for row in manifest["records"]:
            if row["file"] not in inputs:
                inputs[row["file"]] = json.loads((self.root / "inputs" / row["file"]).read_text(encoding="utf-8-sig"))
            original = inputs[row["file"]]
            try:
                resolve_pointer(original, row["source_pointer"])
                if "\n".join(resolve_pointer(original, pointer) for pointer in row["live_pointers"]) == row["live"]:
                    continue
            except (KeyError, IndexError, TypeError, ValueError):
                pass
            changed.append(row)
        with self.connect() as db:
            db.execute("DELETE FROM records")
            db.executemany("INSERT INTO records(id,file,source,live,paths,category,code,flags) VALUES (?,?,?,?,?,?,?,?)", [
                (row["identity"], row["file"], row["source"], row["live"], json.dumps(row["live_pointers"]), row["classification"],
                 row["event_code"], json.dumps(review_flags(row["source"], row["live"], row["event_code"]))) for row in changed
            ])
        atomic_json(self.root / "output-manifest.json", {"files": manifest["files"], "unresolved": manifest["unresolved"],
                                                       "schema": manifest["schema"], "source": "production-adapter"})
        return self.summary()

    def summary(self):
        if not self.path.exists() or not (self.root / "output-manifest.json").exists():
            return {"total": 0, "reviewed": 0, "flagged": 0, "unresolved": 0}
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*), COALESCE(SUM(reviewed),0), COALESCE(SUM(flags != '[]'),0) FROM records").fetchone()
        manifest = json.loads((self.root / "output-manifest.json").read_text(encoding="utf-8"))
        return {"total": row[0], "reviewed": row[1], "flagged": row[2], "unresolved": len(manifest["unresolved"])}

    def page(self, offset=0, query="", pending=False):
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0 or not isinstance(query, str):
            raise ValueError("Invalid review page.")
        if not self.path.exists():
            return {"records": [], "results": {}, "matching": 0, "offset": offset, **self.summary()}
        where, values = ["(instr(lower(file),lower(?))>0 OR instr(lower(source),lower(?))>0 OR instr(lower(COALESCE(override,live)),lower(?))>0)"], [query, query, query]
        if pending:
            where.append("reviewed=0")
        with self.connect() as db:
            matching = db.execute("SELECT COUNT(*) FROM records WHERE " + " AND ".join(where), values).fetchone()[0]
            rows = db.execute("SELECT * FROM records WHERE " + " AND ".join(where) + " ORDER BY file,id LIMIT 100 OFFSET ?", [*values, offset]).fetchall()
        records, results = [], {}
        for row in rows:
            records.append({"id": row["id"], "file": row["file"], "source": row["source"], "pointer": ", ".join(json.loads(row["paths"])), "category": row["category"]})
            results[row["id"]] = {"text": row["override"] if row["override"] is not None else row["live"],
                                  "flags": json.loads(row["flags"]), "reviewed": bool(row["reviewed"])}
        return {"records": records, "results": results, "matching": matching, "offset": offset, **self.summary()}

    def approve(self, record_id, text):
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > 100_000:
            raise ValueError("Enter non-empty translation text below 100 KB.")
        with self.connect() as db:
            row = db.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
            if row is None:
                raise ValueError("This result does not belong to the selected run.")
            paths = json.loads(row["paths"])
            if len(paths) > 1 and len(text.split("\n")) != len(paths):
                raise ValueError(f"Keep {len(paths)} lines in this message group so its event structure stays intact.")
            flags = review_flags(row["source"], text, row["code"])
            if "runtime-token-mismatch" in flags:
                raise ValueError("Restore the original runtime codes before approving this text.")
            db.execute("UPDATE records SET override=?, flags=?, reviewed=1 WHERE id=?", (text, json.dumps(flags), record_id))
        return self.summary()

    def write_export(self, target: Path, data_relative: str):
        summary = self.summary()
        if summary["reviewed"] != summary["total"] or summary["unresolved"]:
            raise ValueError("Review every generated entry and resolve unmapped source records before export.")
        manifest = json.loads((self.root / "output-manifest.json").read_text(encoding="utf-8"))
        documents = {}
        for entry in manifest["files"]:
            name = entry["path"]
            source = self.root / "translated" / name
            raw = source.read_bytes()
            if source.is_symlink() or not source.resolve().is_relative_to((self.root / "translated").resolve()) or digest(raw) != entry["sha256"]:
                raise ValueError("A generated output changed after review. Create a new review index before exporting.")
            documents[name] = json.loads(raw.decode("utf-8-sig"))
        with self.connect() as db:
            for row in db.execute("SELECT * FROM records WHERE override IS NOT NULL"):
                document = documents[row["file"]]
                pointers = json.loads(row["paths"])
                existing = "\n".join(resolve_pointer(document, p) for p in pointers)
                if existing != row["live"]:
                    raise ValueError("The generated event structure changed after review.")
                replacements = [row["override"]] if len(pointers) == 1 else row["override"].split("\n")
                for pointer, replacement in zip(pointers, replacements):
                    parent, _, key = pointer.rpartition("/")
                    owner = resolve_pointer(document, parent)
                    key = key.replace("~1", "/").replace("~0", "~")
                    owner[int(key) if isinstance(owner, list) else key] = replacement
        for name, document in documents.items():
            atomic_json(target / data_relative / name, document)
        return sorted(documents)
