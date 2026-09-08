"""Which ``(tag, param)`` pairs hold player-facing text, and which never do.

Classification is explicit, not heuristic. A Japanese-bearing attribute whose
site is not listed here is *excluded and logged* as ``unknown-site`` so that a
game update surfaces new sites instead of silently losing or breaking them.
"""
from __future__ import annotations

import re

#: kind produced for a translatable attribute, keyed by (tag, param).
EXPLICIT: dict[tuple[str, str], str] = {
    ("glink", "text"): "choice",
    ("button", "text"): "choice",
    ("link", "text"): "choice",
    ("ptext", "text"): "ptext",
    ("mtext", "text"): "ptext",
    ("notice", "text"): "notice",
    ("button", "hint"): "hint",
    ("glink", "hint"): "hint",
    ("title", "name"): "title",
    ("ruby", "text"): "ruby",
    ("edit", "initial"): "edit",
}

#: parameters that are code and get scanned for JS string literals instead.
CODE_PARAMS = frozenset({"exp", "cond"})

#: parameters that are never player-facing, on any tag. Asset paths, engine
#: identifiers, labels, geometry, styling.
NEVER: frozenset[str] = frozenset({
    "storage", "graphic", "enterimg", "clickimg", "src", "file", "folder", "video",
    "image", "frame", "bgcolor", "backimage", "mask",
    "target", "name", "label", "var", "key", "id", "class", "layer", "page",
    "face", "font", "css", "style", "color", "shadow", "edge", "linkcolor",
    "clickse", "enterse", "leavese", "se", "bgm", "sound", "voice", "vo",
    "x", "y", "top", "left", "right", "bottom", "width", "height", "size",
    "time", "delay", "wait", "speed", "opacity", "zindex", "z", "volume",
    "min", "max", "len", "from", "to", "index", "num", "count", "loop",
    "align", "valign", "margint", "marginl", "marginr", "marginb", "pos",
    "anim", "effect", "trans", "method", "cross", "vital", "next", "role",
    "type", "mode", "value", "cell", "column", "row", "maxchars", "bold",
    "visible", "fix", "auto", "reverse", "blend", "filter", "rule", "url",
})

# Anchored at both ends: the *whole* value has to be a path. An error message
# that merely ends in "(例)data/bgm/music.ogg" is prose, not an asset reference.
ASSET_RE = re.compile(
    r"^\S+\.(png|jpe?g|gif|webp|bmp|svg|mp3|ogg|m4a|wav|mp4|webm|ks|js|css|html?|otf|ttf|woff2?)$",
    re.I)

#: engine JS that carries player-facing strings and gets patched wholesale.
#: kag.js holds the default save caption, kag.menu.js the save-slot line,
#: libs.js the playtime units and the save-corruption dialogs, lang.js the
#: confirmation prompts. The kag.tag*.js files are mostly script-error text that
#: only shows with debugMenu.visible=true, but the update prompt in
#: kag.tag_system.js is shown to players, so they are all scanned.
ENGINE_JS: tuple[str, ...] = (
    "tyrano/lang.js",
    "tyrano/libs.js",
    "tyrano/plugins/kag/kag.js",
    "tyrano/plugins/kag/kag.menu.js",
    "tyrano/plugins/kag/kag.tag.js",
    "tyrano/plugins/kag/kag.tag_ext.js",
    "tyrano/plugins/kag/kag.tag_system.js",
    "tyrano/plugins/kag/kag.tag_audio.js",
    "tyrano/plugins/kag/kag.layer.js",
)

PLUGIN_ROOT = "data/others/plugin"

#: string literals in the JS targets that must never be translated even though
#: they contain Japanese - keys, filenames, selectors. Matched exactly.
JS_DENY: frozenset[str] = frozenset({
    "メイリオ",          # font-family fallback in a style string
})


def classify_attr(tag: str, param: str) -> tuple[str, str]:
    """Return ``(action, detail)``.

    action is one of ``text`` (translate as ``detail`` kind), ``code`` (scan for
    JS string literals), ``skip`` (known non-text) or ``unknown``.
    """
    key = (tag, param)
    if key in EXPLICIT:
        return "text", EXPLICIT[key]
    if param in CODE_PARAMS:
        return "code", "code"
    if param in NEVER:
        return "skip", param
    return "unknown", param


def looks_like_asset(value: str) -> bool:
    return bool(ASSET_RE.search(value.strip()))


#: bucket a script file lands in, for store sharding and prompt context.
def bucket_for(rel: str) -> str:
    parts = rel.split("/")
    if parts[:2] == ["data", "scenario"]:
        rest = parts[2:]
        if len(rest) > 1:
            return rest[0].capitalize()
        return "Root"
    if rel.startswith(PLUGIN_ROOT):
        return "Plugins"
    if rel.startswith("tyrano/"):
        return "Engine"
    return "Other"
