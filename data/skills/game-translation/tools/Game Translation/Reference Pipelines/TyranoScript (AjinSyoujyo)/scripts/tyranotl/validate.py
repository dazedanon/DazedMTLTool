"""Post-translation checks. Hard failures block injection; soft ones want eyes.

Hard
  1. missing or empty translation
  2. identical to the source (nothing was translated)
  3. residual Japanese - censor glyphs and the standalone dakuten do not count
  4. placeholder set changed
  5. a stray sentinel bracket - a dropped half, or an invented named one, which
     the set comparison in 4 cannot see
  6. a first character that makes the parser read the line as a label, comment
     or tag instead of as dialogue

Soft
  * layout overflow (see ``layout.py``)
  * a female character rendered with he/him
  * stranded cosmetic kana
  * extreme expansion
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import codes, layout
from .store import Glossary, Store, Unit

MALE_RE = re.compile(r"\b(he|him|his|himself)\b", re.I)
STRANDED_KANA_RE = re.compile(r"[ぁ-ゖァ-ヺ]")


@dataclass
class Finding:
    unit: str
    kind: str
    severity: str
    message: str
    src: str
    en: str


def run(store: Store, glossary: Glossary, app_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    female = {meta.get("en", "").lower()
              for meta in glossary.names.values()
              if isinstance(meta, dict) and meta.get("gender", "").lower().startswith("f")}

    for unit in store.all_units():
        if unit.status in ("manual", "blank"):
            continue
        if not unit.en:
            findings.append(Finding(unit.id, unit.kind, "hard", "not translated",
                                    unit.src, ""))
            continue
        if not unit.en.strip():
            findings.append(Finding(unit.id, unit.kind, "hard", "empty translation",
                                    unit.src, unit.en))
            continue
        if unit.en.strip() == unit.src.strip():
            findings.append(Finding(unit.id, unit.kind, "hard", "identical to source",
                                    unit.src, unit.en))
            continue
        leftovers = codes.residual_jp(unit.en)
        if leftovers:
            findings.append(Finding(unit.id, unit.kind, "hard",
                                    f"residual Japanese: {''.join(leftovers)}",
                                    unit.src, unit.en))
            continue
        if not codes.placeholders_ok(unit.src, unit.en):
            findings.append(Finding(
                unit.id, unit.kind, "hard",
                f"placeholder mismatch {codes.sentinels(unit.src)} -> {codes.sentinels(unit.en)}",
                unit.src, unit.en))
            continue
        stray = codes.stray_sentinel(unit.en)
        if stray:
            findings.append(Finding(unit.id, unit.kind, "hard",
                                    f"stray sentinel bracket near {stray!r}",
                                    unit.src, unit.en))
            continue
        opener = _hijacked_line(unit, app_root)
        if opener:
            findings.append(Finding(
                unit.id, unit.kind, "hard",
                f"starts a line with {opener!r}: the parser would read it as a "
                f"label/comment/tag, not as text",
                unit.src, unit.en))
            continue

        for warning in layout.check(unit, app_root):
            findings.append(Finding(unit.id, unit.kind, "soft", warning, unit.src, unit.en))

        if female and MALE_RE.search(unit.en) and unit.kind == "dialogue":
            for name in female:
                if name and name in unit.en.lower():
                    findings.append(Finding(unit.id, unit.kind, "soft",
                                            f"possible misgender near '{name}'",
                                            unit.src, unit.en))
                    break

        stranded = STRANDED_KANA_RE.findall(unit.en)
        if stranded:
            findings.append(Finding(unit.id, unit.kind, "soft",
                                    f"stranded kana {''.join(stranded)}", unit.src, unit.en))
    return findings


_LINES: dict[str, list[str]] = {}


def _hijacked_line(unit: Unit, app_root: Path) -> str:
    """The character that would hijack the line, or "" if the unit is safe.

    Only a unit that *starts* its line can do this, so the site's span has to
    have nothing but whitespace in front of it.
    """
    for site in unit.sites:
        if site.form != "bare":
            continue
        lines = _LINES.get(site.file)
        if lines is None:
            path = app_root / site.file
            if not path.exists():
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
            _LINES[site.file] = lines
        if site.line - 1 >= len(lines):
            continue
        if lines[site.line - 1][:site.start].strip():
            continue
        head = unit.en.lstrip()[:1]
        if head and head in codes.LINE_SPECIAL:
            return head
    return ""


def summarise(findings: list[Finding]) -> dict[str, int]:
    out = {"hard": 0, "soft": 0}
    for finding in findings:
        out[finding.severity] += 1
    return out


def flag(store: Store, findings: list[Finding]) -> int:
    """Mark hard failures so ``retry`` picks them up."""
    units = store.by_id()
    flagged = 0
    for finding in findings:
        if finding.severity != "hard":
            continue
        unit = units.get(finding.unit)
        if unit is None or unit.status == "manual":
            continue
        unit.status = "flagged"
        unit.note = finding.message
        flagged += 1
    return flagged


def blocking(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "hard"]
