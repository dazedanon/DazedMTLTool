"""The translation store: one JSON file per bucket, plus the glossary.

A unit id is ``sha1(kind + "\\x00" + source)[:16]`` so re-extracting after a game
patch keeps every finished translation that still has an identical source.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

SCHEMA = 1


def unit_id(kind: str, source: str) -> str:
    return hashlib.sha1(f"{kind}\x00{source}".encode("utf-8")).hexdigest()[:16]


@dataclass
class Site:
    """Where one occurrence of a unit lives, precisely enough to inject it.

    ``start``/``end`` delimit the span in the *original* line that injection
    replaces. For ``attr`` and ``jsstr`` forms the span includes the surrounding
    quotes, so the delimiter can be re-chosen when English introduces an
    apostrophe. ``raw`` is that span verbatim and is what makes the identity
    round-trip byte-exact.
    """
    file: str
    line: int
    start: int
    end: int
    form: str = "bare"      # bare | attr | jsstr
    raw: str = ""
    tokens: list[str] = field(default_factory=list)
    #: nested translatable attributes living inside one of ``tokens``:
    #: ``[token_index, start, end, child_unit_id]`` with offsets inside the token.
    nested: list[list] = field(default_factory=list)
    context: str = ""
    tag: str = ""
    param: str = ""
    label: str = ""
    quote: str = ""
    order: int = 0

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Unit:
    id: str
    kind: str
    src: str                       # masked source shown to the model
    sites: list[Site] = field(default_factory=list)
    en: str | None = None
    status: str = "new"            # new | done | flagged | manual
    note: str = ""
    speaker: str = ""
    scene: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "src": self.src,
            "sites": [s.to_json() for s in self.sites],
            "en": self.en,
            "status": self.status,
            "note": self.note,
            "speaker": self.speaker,
            "scene": self.scene,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> "Unit":
        return cls(
            id=raw["id"],
            kind=raw["kind"],
            src=raw["src"],
            sites=[Site(**s) for s in raw.get("sites", [])],
            en=raw.get("en"),
            status=raw.get("status", "new"),
            note=raw.get("note", ""),
            speaker=raw.get("speaker", ""),
            scene=raw.get("scene", ""),
        )


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.buckets: dict[str, list[Unit]] = {}

    # ------------------------------------------------------------------ io

    def load(self) -> "Store":
        self.buckets.clear()
        for path in sorted(self.root.glob("*.json")):
            if path.name.startswith("_") or path.name in ("glossary.json",):
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("schema") != SCHEMA:
                raise SystemExit(f"{path.name}: schema {raw.get('schema')} != {SCHEMA}; re-run extract")
            self.buckets[path.stem] = [Unit.from_json(u) for u in raw["units"]]
        return self

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for name, units in self.buckets.items():
            payload = {"schema": SCHEMA, "bucket": name, "count": len(units),
                       "units": [u.to_json() for u in units]}
            path = self.root / f"{name}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(path)

    # --------------------------------------------------------------- access

    def all_units(self) -> list[Unit]:
        out: list[Unit] = []
        for name in sorted(self.buckets):
            out.extend(self.buckets[name])
        return out

    def by_id(self) -> dict[str, Unit]:
        return {u.id: u for u in self.all_units()}

    def merge_previous(self, previous: "Store") -> tuple[int, int]:
        """Carry finished translations from an older extraction into this one."""
        old = {u.id: u for u in previous.all_units()}
        kept = lost = 0
        for unit in self.all_units():
            prior = old.pop(unit.id, None)
            if prior is not None and prior.en:
                unit.en = prior.en
                unit.status = prior.status
                unit.note = prior.note
                kept += 1
        lost = sum(1 for u in old.values() if u.en)
        return kept, lost

    def stats(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for unit in self.all_units():
            row = out.setdefault(unit.kind, {"total": 0, "done": 0, "flagged": 0})
            row["total"] += 1
            if unit.status in ("done", "blank"):
                row["done"] += 1
            elif unit.status == "flagged":
                row["flagged"] += 1
        return out


# ------------------------------------------------------------------ glossary


class Glossary:
    """Locked names and terms. Hand-edited; the names phase writes back into it."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = {"names": {}, "terms": {}, "notes": []}

    def load(self) -> "Glossary":
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        self.data.setdefault("names", {})
        self.data.setdefault("terms", {})
        self.data.setdefault("notes", [])
        return self

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @property
    def names(self) -> dict[str, Any]:
        return self.data["names"]

    @property
    def terms(self) -> dict[str, str]:
        return self.data["terms"]

    def render(self) -> str:
        """The prompt tail. Deliberately *not* part of the cached prefix, so that
        editing the glossary never invalidates the cache."""
        lines = ["## Locked glossary", "",
                 "Use these renderings exactly. Never invent an alternative.", "",
                 "### Characters"]
        for jp, meta in self.names.items():
            if isinstance(meta, str):
                lines.append(f"- {jp} -> {meta}")
                continue
            bits = [f"- {jp} -> **{meta['en']}**"]
            if meta.get("gender"):
                bits.append(f"({meta['gender']})")
            if meta.get("role"):
                bits.append(f"- {meta['role']}")
            if meta.get("register"):
                bits.append(f"| speech: {meta['register']}")
            if meta.get("aliases"):
                bits.append(f"| also written {', '.join(meta['aliases'])}")
            lines.append(" ".join(bits))
        lines += ["", "### Terms"]
        for jp, en in self.terms.items():
            lines.append(f"- {jp} -> {en}")
        if self.data.get("notes"):
            lines += ["", "### Glossary notes"]
            lines += [f"- {n}" for n in self.data["notes"]]
        return "\n".join(lines)


def iter_chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]
