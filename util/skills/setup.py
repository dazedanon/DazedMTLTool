"""Load editable clipboard skills from data/skills/."""

from __future__ import annotations

from pathlib import Path

from util.paths import SKILLS_DIR
from util.rpgmaker_markers import SUPPORTED_CODE408_MARKERS

_ENGINE_MARKERS = {
    "rpgmaker": ("<!-- engine:rpgmaker -->", "<!-- /engine:rpgmaker -->"),
    "wolf": ("<!-- engine:wolf -->", "<!-- /engine:wolf -->"),
}

RPGMAKER_QA_FOCUSES = (
    ("release", "Full game — coverage & release gate"),
    ("database", "Targeted — database files"),
    ("risky-codes", "Targeted — risky event codes"),
    ("dialogue", "Targeted — dialogue, lore & wordplay"),
)

_RPGMAKER_QA_FILENAME = "rpgmaker_translation_qa.md"
_LOCALIZATION_INVESTIGATION_FILENAME = "localization_investigation.md"
_INVESTIGATION_PHASE_MARKERS = (
    "<!-- investigation-phase -->",
    "<!-- /investigation-phase -->",
)
_INVESTIGATION_PHASE_PLACEHOLDER = "{{LOCALIZATION_INVESTIGATION_PHASE}}"


def _read_skill_file(name: str) -> str:
    path = SKILLS_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"Skill file missing: {path}")
    return path.read_text(encoding="utf-8")


def _extract_engine_section(text: str, engine: str) -> str:
    """Keep shared body + the requested engine block; drop other engine blocks."""
    start_tag, end_tag = _ENGINE_MARKERS.get(engine, (None, None))
    if not start_tag:
        return text

    result_parts: list[str] = []
    pos = 0
    while pos < len(text):
        next_starts = [
            (text.find(marker[0], pos), eng, marker)
            for eng, marker in _ENGINE_MARKERS.items()
            if text.find(marker[0], pos) != -1
        ]
        if not next_starts:
            result_parts.append(text[pos:])
            break
        next_starts.sort(key=lambda x: x[0])
        idx, eng, (s_tag, e_tag) = next_starts[0]
        result_parts.append(text[pos:idx])
        end_idx = text.find(e_tag, idx)
        if end_idx == -1:
            raise ValueError(f"Unclosed engine block {s_tag} in skill file")
        block_body = text[idx + len(s_tag) : end_idx]
        if eng == engine:
            result_parts.append(block_body.strip("\n") + "\n")
        pos = end_idx + len(e_tag)
    return "".join(result_parts).strip() + "\n"


def _extract_required_section(text: str, markers: tuple[str, str]) -> str:
    """Return one marked section or reject an ambiguous skill."""
    start_marker, end_marker = markers
    start = text.find(start_marker)
    if start == -1 or text.find(start_marker, start + len(start_marker)) != -1:
        raise ValueError(f"Skill must contain exactly one marker: {start_marker}")
    end = text.find(end_marker, start + len(start_marker))
    if end == -1 or text.find(end_marker, end + len(end_marker)) != -1:
        raise ValueError(f"Skill must contain exactly one marker: {end_marker}")
    body = text[start + len(start_marker) : end].strip()
    if not body:
        raise ValueError(f"Skill section is empty: {start_marker}")
    return body


def load_project_setup(engine: str = "rpgmaker", *, prepend: str = "") -> str:
    """Load one Setup prompt with its shared investigation phase for *engine*."""
    raw = _read_skill_file("project_setup.md")
    body = _extract_engine_section(raw, engine)
    if body.count(_INVESTIGATION_PHASE_PLACEHOLDER) != 1:
        raise ValueError(
            "Project Setup skill must contain exactly one investigation phase placeholder"
        )
    investigation = _extract_required_section(
        _read_skill_file(_LOCALIZATION_INVESTIGATION_FILENAME),
        _INVESTIGATION_PHASE_MARKERS,
    )
    body = body.replace(_INVESTIGATION_PHASE_PLACEHOLDER, investigation)
    marker_list = ", ".join(
        f"`{marker}`" for marker in sorted(SUPPORTED_CODE408_MARKERS)
    )
    body = body.replace("{{SUPPORTED_CODE408_MARKERS}}", marker_list or "none")
    if prepend:
        return prepend.rstrip() + "\n\n" + body
    return body


def load_clipboard_skill(name: str) -> str:
    """Load a static clipboard prompt from ``data/skills``.

    Read on every copy so edits made in the Skills tab take effect immediately.
    Only a plain Markdown filename is accepted to keep callers inside the shipped
    skills directory.
    """
    path_name = Path(name)
    if path_name.name != name or path_name.suffix.casefold() != ".md":
        raise ValueError(f"Invalid clipboard skill filename: {name!r}")
    return _read_skill_file(name).strip() + "\n"


def load_rpgmaker_qa_skill(focus: str) -> str:
    """Load the shared RPG Maker QA rules plus one exhaustive-screen focus."""
    valid_focuses = {key for key, _label in RPGMAKER_QA_FOCUSES}
    if focus not in valid_focuses:
        raise ValueError(f"Unknown RPG Maker QA focus: {focus!r}")

    text = _read_skill_file(_RPGMAKER_QA_FILENAME)
    selected = ""
    sections: list[tuple[int, int]] = []
    for key, _label in RPGMAKER_QA_FOCUSES:
        start_marker = f"<!-- qa-focus:{key} -->"
        end_marker = f"<!-- /qa-focus:{key} -->"
        start = text.find(start_marker)
        if start == -1:
            raise ValueError(f"QA skill is missing focus marker: {start_marker}")
        end = text.find(end_marker, start + len(start_marker))
        if end == -1:
            raise ValueError(f"QA skill is missing focus marker: {end_marker}")
        if text.find(start_marker, start + len(start_marker)) != -1:
            raise ValueError(f"QA skill has duplicate focus marker: {start_marker}")
        body = text[start + len(start_marker) : end]
        if key == focus:
            selected = body.strip()
        sections.append((start, end + len(end_marker)))

    common_parts: list[str] = []
    pos = 0
    for start, end in sorted(sections):
        if start < pos:
            raise ValueError("QA focus sections must not overlap")
        common_parts.append(text[pos:start])
        pos = end
    common_parts.append(text[pos:])

    if not selected:
        raise ValueError(f"QA focus section is empty: {focus}")
    common = "".join(common_parts).strip()
    return f"{common}\n\n{selected}\n"


def skills_dir() -> Path:
    return SKILLS_DIR
