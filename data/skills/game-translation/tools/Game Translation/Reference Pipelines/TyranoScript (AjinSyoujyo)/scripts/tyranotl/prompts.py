"""Request construction and response parsing, shared by the batch and live drivers.

Both drivers must build requests and read replies through this module, so that a
stalled batch can be finished live (or vice versa) with identical results.

Prompt layout, in render order (``system`` then ``messages``):

    system[0]  localisation rules + game bible   <- cache breakpoint 1
    system[1]  the glossary                      <- cache breakpoint 2
    messages   the units for this request

Two breakpoints, not one: the glossary is edited constantly during a run, and a
second breakpoint means an edit re-writes only the glossary block instead of
invalidating the whole prefix. With ~100 requests the glossary is re-read ~100
times, so leaving it uncached would cost more than the bible.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from . import codes, pricing
from .store import Glossary, Unit

MODEL_DEFAULT = "claude-opus-5"
EFFORT_DEFAULT = "low"
MAX_TOKENS = 16000

DIALOGUE_PER_REQUEST = 60
SHORT_PER_REQUEST = 45
CONTEXT_LINES = 3
MIN_OWN_REQUEST = 12

RULES = """\
You are a professional Japanese-to-English game localiser working on an adult
(R18) Japanese visual novel built in TyranoScript. You are translating the raw
script of a commercial release for an English patch.

## Output contract

Reply with **one JSON object and nothing else**:

    {"t": {"<id>": "<english>", ...}}

- One entry for every id you were given, using the same ids, in the same order.
- No prose before or after the object. No markdown fence.
- Never merge, split, or reorder units. Never leave an id out.

## Placeholders

Engine tags and HTML have been replaced by sentinels of the form U+27E6 n U+27E7
(for example the three-character sequence written as [[0]] in this paragraph is
really an opening bracket, a digit and a closing bracket). Rules:

- Reproduce **every** sentinel exactly once, with the same number. Never invent,
  drop, duplicate, or renumber one.
- A sentinel may move within the sentence if English word order demands it, but it
  must stay where it makes sense: sentinels usually stand for an inline cut-in,
  a variable insert (the player's name, a randomised word) or a line break.
- Text before and after a sentinel is one continuous sentence. Read it that way.
- Some sentinels are a **word** inserted at run time - the player's name, or a
  noun picked out of a randomised list. Japanese needs no space around an
  inserted word, so the source has none; **English does**. Put a space either
  side unless the neighbour is an apostrophe, a hyphen or a decoration mark:
  `[[0]]Is that alright?` must become `[[0]] Is that alright?`, while
  `[[0]]'s cock` and `[[0]]-chan` stay tight.

## Register and content

- This is adult content. Translate it faithfully and explicitly. Do **not**
  euphemise, soften, moralise, censor, or add warnings. Match the source
  register exactly, whether it is clinical, crude, tender, or degrading. That
  is the correct localisation for this title.
- Keep the emotional temperature of moans, stutters and broken speech. Japanese
  writes slurred speech with a dakuten on a vowel; render the equivalent in
  English by breaking the word rather than by writing it cleanly.
- **No kana may survive into the output, not even as decoration.** Small trailing
  kana are a sound, not a symbol: っ / ッ is a glottal catch, ぅ ぉ ぇ ぃ ぁ are a
  vowel dragged out, ふ っ after a syllable is a cough. Render them with Latin
  letters - a doubled vowel, an -h, a hyphen - and delete the kana. Writing
  `Ogh゛っ♡` or `cock milk゛ぅぅぅっ♡` is wrong; `Ogh-♡` and `cock milk-hhhh♡`
  are right. The dakuten mark ゛ may stay, since it reads as distortion.
- Preserve decorative marks exactly as they appear: heart marks, musical notes,
  ellipses of the same length, repeated punctuation.
- A full-width space inside a line is a **pacing gap between gasps**, not
  indentation. Keep it. Deleting it runs the phrases together.
- Censor masks stay masked. If the Japanese hides a word behind a circle glyph,
  hide the English the same way.
- Do not translate a string into a longer one than it needs to be. English runs
  1.3-2x longer than Japanese; keep UI labels tight.

## Never touch

- Anything that is not Japanese: numbers, ASCII, file names, variable names.
- Do not add quotation marks that the source does not have. Japanese dialogue in
  this game is written without corner brackets; keep English the same way.
"""

SPEAKERLESS_NOTE = """\
This game has no name box. Narration is the male protagonist's first-person
voice; dialogue lines are the girl on screen. Use the run of lines to tell them
apart - narration describes what he sees and thinks, dialogue is what she says.
"""

KIND_BRIEFS: dict[str, str] = {
    "dialogue": "Message-box lines, in play order. Translate as flowing natural English prose and dialogue.",
    "choice": "Clickable menu / choice-button labels. Terse, natural game English. Imperative or noun phrase. Keep them short - they sit in a fixed-width button.",
    "ptext": "Free-positioned on-screen labels (status readouts, location names, tooltips). They do NOT wrap: keep them at most as wide as the Japanese plus a little.",
    "notice": "Toast popup notifications. One short sentence.",
    "hint": "Hover tooltips on buttons. Very short.",
    "title": "The window title of the game.",
    "ruby": "Ruby / furigana annotation printed above a word. Two or three words at most.",
    "edit": "The default value pre-filled in the player's name-entry box. Give the romanised name only.",
    "code": ("Fragments of on-screen text assembled at runtime by string concatenation. "
             "The full expression is shown as context. Translate ONLY the fragment, and "
             "make it fit grammatically where the surrounding pieces put it - including "
             "any leading or trailing space, which you must preserve."),
    "js": "Engine UI strings (menus, save-slot captions, confirmation dialogs, time units). Terse standard game-UI English.",
}


@dataclass
class Request:
    key: str
    kind: str
    phase: str
    units: list[Unit]
    context: list[Unit] = field(default_factory=list)
    scene: str = ""

    @property
    def ids(self) -> list[str]:
        return [u.id for u in self.units]


# ---------------------------------------------------------------- prompt build


def system_blocks(bible: str, glossary: Glossary, cache_ttl: str) -> list[dict[str, Any]]:
    prefix = RULES + "\n" + SPEAKERLESS_NOTE + "\n" + bible
    return [
        {"type": "text", "text": prefix,
         "cache_control": {"type": "ephemeral", "ttl": cache_ttl}},
        {"type": "text", "text": glossary.render(),
         "cache_control": {"type": "ephemeral", "ttl": cache_ttl}},
    ]


def user_message(request: Request) -> str:
    if request.kind == "mixed":
        kinds = sorted({u.kind for u in request.units})
        brief = "\n".join(
            ["Assorted short strings. Each line is tagged with the widget it is drawn in:"]
            + [f"- ({k}) {KIND_BRIEFS[k]}" for k in kinds if k in KIND_BRIEFS])
    else:
        brief = KIND_BRIEFS.get(request.kind, KIND_BRIEFS["dialogue"])
    out = [f"# {request.kind} units", "", brief, ""]
    if request.scene:
        out += [f"Scene: `{request.scene}`", ""]
    if request.context:
        out += ["## Preceding lines - context only, do NOT translate, do NOT return", ""]
        for unit in request.context:
            out.append(f"  {unit.src}")
        out.append("")
    out += ["## Translate these", ""]
    for index, unit in enumerate(request.units):
        label = f"({unit.kind}) " if request.kind == "mixed" else ""
        line = f"{index}\t{label}{unit.src}"
        site = unit.sites[0] if unit.sites else None
        if site is not None and site.context and unit.kind in ("code", "js"):
            line += f"\n \tcontext: {site.context[:220]}"
        out.append(line)
    count = len(request.units)
    keys = ", ".join(f'"{i}": ...' for i in range(min(count, 3)))
    if count > 3:
        keys += f', ..., "{count - 1}": ...'
    out += ["", f'Return one JSON object {{"t": {{{keys}}}}} with exactly '
                f'{count} entr{"y" if count == 1 else "ies"}, keyed by those numbers.']
    return "\n".join(out)


def build_params(request: Request, bible: str, glossary: Glossary, model: str,
                 effort: str, cache_ttl: str) -> dict[str, Any]:
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "system": system_blocks(bible, glossary, cache_ttl),
        "messages": [{"role": "user", "content": user_message(request)}],
    }
    params.update(pricing.sampling_params(model))
    params.update(pricing.output_config(effort))
    return params


# ------------------------------------------------------------------ batching


def _scene_range(chunk: list[Unit]) -> str:
    first, last = chunk[0].scene, chunk[-1].scene
    return first if first == last else f"{first} .. {last.split('#')[-1]}"


def plan(units: Iterable[Unit], phase: str = "text") -> list[Request]:
    """Group units into requests: dialogue scene-aligned, everything else by kind."""
    pending = [u for u in units if u.status in ("new", "flagged") and not u.en]
    dialogue = [u for u in pending if u.kind in ("dialogue",)]
    other = [u for u in pending if u.kind not in ("dialogue", "punct")]

    requests: list[Request] = []

    # Dialogue goes out in play order. Scene boundaries are a soft hint, not a
    # hard break: this game has hundreds of two-line scenes, and one request per
    # scene would multiply the per-request overhead by five.
    dialogue.sort(key=lambda u: u.sites[0].order)
    chunk: list[Unit] = []
    previous: list[Unit] = []
    current_file = None
    for unit in dialogue:
        unit_file = unit.sites[0].file
        if chunk and (unit_file != current_file or len(chunk) >= DIALOGUE_PER_REQUEST):
            requests.append(Request(
                key=f"{phase}:dialogue:{chunk[0].id}", kind="dialogue", phase=phase,
                units=chunk, context=previous[-CONTEXT_LINES:],
                scene=_scene_range(chunk)))
            previous = chunk
            chunk = []
        current_file = unit_file
        chunk.append(unit)
    if chunk:
        requests.append(Request(
            key=f"{phase}:dialogue:{chunk[0].id}", kind="dialogue", phase=phase,
            units=chunk, context=previous[-CONTEXT_LINES:], scene=_scene_range(chunk)))

    by_kind: dict[str, list[Unit]] = {}
    for unit in other:
        by_kind.setdefault(unit.kind, []).append(unit)

    # A kind with only a handful of units does not deserve its own request; the
    # per-request overhead would dwarf the payload. Pool them and tag each line.
    misc: list[Unit] = []
    for kind, group in sorted(by_kind.items()):
        if len(group) < MIN_OWN_REQUEST:
            misc.extend(group)
            continue
        group.sort(key=lambda u: u.sites[0].order)
        for offset in range(0, len(group), SHORT_PER_REQUEST):
            requests.append(Request(
                key=f"{phase}:{kind}:{offset}", kind=kind, phase=phase,
                units=group[offset:offset + SHORT_PER_REQUEST]))
    if misc:
        misc.sort(key=lambda u: (u.kind, u.sites[0].order))
        for offset in range(0, len(misc), SHORT_PER_REQUEST):
            requests.append(Request(
                key=f"{phase}:mixed:{offset}", kind="mixed", phase=phase,
                units=misc[offset:offset + SHORT_PER_REQUEST]))

    requests.sort(key=lambda r: r.units[0].sites[0].order)
    return requests


# ------------------------------------------------------------------- parsing


def repair_quotes(text: str) -> str:
    """Escape a bare ``"`` that appears *inside* a JSON string value.

    The Japanese uses an ASCII double quote as a dakuten on slurred moans
    (``あ"っ``) and the model carries it into English. A quote only *closes* a
    value when the next non-space character is ``,``, ``}`` or ``:``.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    for index, ch in enumerate(text):
        if not in_string:
            out.append(ch)
            if ch == '"':
                in_string = True
            continue
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\":
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            nxt = next((c for c in text[index + 1:] if not c.isspace()), "")
            if nxt in (",", "}", ":", "]", ""):
                out.append(ch)
                in_string = False
            else:
                out.append('\\"')
            continue
        out.append(ch)
    return "".join(out)


def balanced_objects(text: str) -> list[str]:
    """Every balanced top-level ``{...}`` span, string-aware."""
    spans: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = index
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                spans.append(text[start:index + 1])
                start = -1
            elif depth < 0:
                depth = 0
    return spans


FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_reply(text: str) -> dict[str, str]:
    """Pull ``{"t": {...}}`` out of a model reply, repairing the two known failures.

    Order matters: quotes are repaired first, because the brace scan depends on
    correct string boundaries.
    """
    fenced = FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1)

    best: dict[str, str] = {}
    for candidate in (text, repair_quotes(text)):
        for span in balanced_objects(candidate):
            try:
                obj = json.loads(span)
            except json.JSONDecodeError:
                continue
            table = obj.get("t") if isinstance(obj, dict) else None
            if isinstance(table, dict) and len(table) > len(best):
                best = {str(k): v for k, v in table.items() if isinstance(v, str)}
        if best:
            break
    return best


def apply_reply(request: Request, table: dict[str, str]) -> tuple[int, list[str]]:
    """Write translations onto the units. Returns ``(applied, problems)``."""
    applied = 0
    problems: list[str] = []
    for index, unit in enumerate(request.units):
        value = table.get(str(index))
        if value is None:
            problems.append(f"{unit.id}: missing from reply")
            continue
        value = value.strip("\n")
        if not value.strip():
            problems.append(f"{unit.id}: empty translation")
            unit.status = "flagged"
            unit.note = "empty translation"
            continue
        if not codes.placeholders_ok(unit.src, value):
            problems.append(f"{unit.id}: placeholder mismatch "
                            f"{codes.sentinels(unit.src)} -> {codes.sentinels(value)}")
            unit.status = "flagged"
            unit.note = "placeholder mismatch"
            unit.en = value
            continue
        if value.strip().lower() == "placeholder":
            problems.append(f"{unit.id}: literal 'placeholder' returned")
            unit.status = "flagged"
            unit.note = "model returned the word placeholder"
            unit.en = value
            continue
        unit.en = value
        unit.status = "done"
        unit.note = ""
        applied += 1
    return applied, problems


def load_bible(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"missing game bible: {path}")
    return path.read_text(encoding="utf-8")
