"""Speaker handling for the WolfDawn translation module.

WolfDawn attributes a speaker to every extracted line (``speaker`` /
``speaker_src`` fields). For the two "first-line" formats the speaker name is
baked into line 1 of the ``source`` text, e.g.::

    "市民\nおぉっ！来た！帰ってきたぞ！"        speaker_src = literal_line1_lowconf
    "セルリア\nほーら、ローザも手を振って。"    speaker_src = literal_line1

The shared translation prompt (``data/prompt.txt``) is built around the RPG
Maker ``[Speaker]: line`` convention and already knows to translate the speaker
tag ("Always translate speaker tags to English: ``[クロネ]:`` -> ``[Kurone]:``").
So when translating we reshape those lines into ``[Speaker]: body`` and, on
write-back, restore WOLF's native ``Speaker\nbody`` structure so injection stays
byte-faithful to the original layout.

Which formats are reshaped is configurable (``data/wolf_speakers.json``) so the
workflow can toggle the high-confidence nameplate format and the lower-confidence
first-line guess independently.
"""

from __future__ import annotations

import json
import re

from util.paths import DATA_DIR
from util.speaker_prefix import SPEAKER_TAG_RE, strip_speaker_prefix

# speaker_src values whose name is baked into line 1 of the source text.
FIRSTLINE_SRCS = ("literal_line1", "literal_line1_lowconf")

# Default: reshape both first-line formats. WolfDawn already gates the
# low-confidence one (short line 1, no control codes, no sentence punctuation),
# so it is safe enough to enable by default.
DEFAULT_CONFIG = {
    "literal_line1": True,
    "literal_line1_lowconf": True,
}

CONFIG_PATH = DATA_DIR / "wolf_speakers.json"

# Optional leading window-option prefix (``@<option>\n``) that WolfDawn keeps in
# the raw source; preserved verbatim so the reshaped/restored text still matches.
_WINDOW_PREFIX_RE = re.compile(r"^@[^\n]*\n")


def load_config() -> dict:
    """Return the speaker-format config, filling in defaults for missing keys."""
    cfg = dict(DEFAULT_CONFIG)
    try:
        if CONFIG_PATH.is_file():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in DEFAULT_CONFIG:
                    if key in data:
                        cfg[key] = bool(data[key])
    except Exception:
        pass
    return cfg


def save_config(config: dict) -> None:
    """Persist the speaker-format config (only known keys are written)."""
    out = {key: bool(config.get(key, DEFAULT_CONFIG[key])) for key in DEFAULT_CONFIG}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(out, indent=4), encoding="utf-8")


def is_firstline_enabled(speaker_src: str, config: dict | None = None) -> bool:
    """True if *speaker_src* is a first-line format that is enabled in *config*."""
    if speaker_src not in FIRSTLINE_SRCS:
        return False
    cfg = config if config is not None else DEFAULT_CONFIG
    return bool(cfg.get(speaker_src, DEFAULT_CONFIG.get(speaker_src, False)))


def split_source(source: str, speaker_src: str, config: dict | None = None):
    """Split a first-line-speaker source into (prefix, speaker, body).

    Returns ``None`` when the line is not an enabled first-line-speaker format or
    cannot be split (no body after the name).
    """
    if not isinstance(source, str) or not is_firstline_enabled(speaker_src, config):
        return None
    prefix = ""
    rest = source
    m = _WINDOW_PREFIX_RE.match(source)
    if m:
        prefix = m.group(0)
        rest = source[m.end():]
    if "\n" not in rest:
        return None
    line1, body = rest.split("\n", 1)
    if not line1.strip():
        return None
    return prefix, line1, body


def to_prefixed(speaker: str, body: str) -> str:
    """Build the ``[Speaker]: body`` transport string sent to the model."""
    return f"[{speaker}]: {body}"


def parse_prefixed(text: str):
    """Parse a translated ``[Speaker]: body`` string.

    Returns (speaker, body). ``speaker`` is ``None`` when the model did not emit a
    ``[Speaker]:`` prefix, in which case ``body`` is the whole string.
    """
    if not isinstance(text, str):
        return None, text
    m = SPEAKER_TAG_RE.match(text)
    if not m:
        return None, text
    return m.group(1).strip(), strip_speaker_prefix(text)


def restore_source(prefix: str, speaker: str, body: str) -> str:
    """Rebuild WOLF's native ``Speaker\nbody`` layout (with any window prefix)."""
    return f"{prefix}{speaker}\n{body}"
