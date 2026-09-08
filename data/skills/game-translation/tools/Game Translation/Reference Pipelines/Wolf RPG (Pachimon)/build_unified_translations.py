#!/usr/bin/env python3
"""Build a single, strict, byte-safe translation patch JSONL for WOLF 3 injection.

Rules:
 - Source of truth for offsets/source bytes: TextExport_original_db_command_scan/
 - Translation memory: TextExport/mistral_fullgame_translations.before_protected_filter_*.jsonl
   plus any --extra-translations passed in
 - DO NOT translate any string that is used elsewhere as a runtime lookup key.
   The danger set is built from CID 250 string[1]/[2]/[3] (DB lookup) and
   CID 300 string[0] (CommonEventByName). Anywhere those identifiers appear
   in DBs OR in event commands, they stay original.
 - Translatable command slots:
     CID 101 string[0]                                : Show Message
     CID 102 string[0..N]                             : Show Choice labels
     CID 150 string[0]                                : Picture text (when not an asset path / engine marker)
 - Translatable DB strings (CDataBase/DataBase/SysDatabase .dat):
     anything that is not an asset path, not an engine marker,
     not in the danger set, not editor-only (`【以下、サンプル...】` etc.)
 - Translatable Game.dat: only the title field at offset 0x38

The output file can be passed straight to wolf_text_inject.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, OrderedDict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = (SCRIPT_DIR / ".." / "..").resolve()
DEFAULT_SCAN_DIR = ROOT_DIR / "TextExport_original_db_command_scan"
# A second scan that includes the .project files (for the .dat / .mps strings
# the primary scan covers, just `strings_all.csv` is enough; the .project
# coverage is what we get out of this second one).
DEFAULT_PROJECT_SCAN_DIR = ROOT_DIR / "TextExport_original_full_v2"
DEFAULT_EXTRA_SCAN_CSV = ROOT_DIR / "TextExport_original_db_command_scan" / "extra_scan_ce.csv"
DEFAULT_TRANSLATION = (
    ROOT_DIR
    / "TextExport"
    / "mistral_fullgame_translations.before_protected_filter_20260510T141817Z.jsonl"
)
DEFAULT_EXTRA_TRANSLATIONS = [
    ROOT_DIR / "TextExport" / "strict_safe_dialogue_event_translations.recovered.jsonl",
    ROOT_DIR / "TextExport" / "mistral_fullgame_translations.synced.jsonl",
    # Common-event remainder translations the first pass missed because the
    # structured parser failed; these are picked up by the byte-level scanner
    # and only injected into safe slots (per-CID rules + danger set).
    ROOT_DIR / "TextExport_injected" / "mistral_remaining_translations.jsonl",
]
DEFAULT_GLOSSARY = SCRIPT_DIR / "ui_glossary.jsonl"
DEFAULT_OUTPUT = ROOT_DIR / "TextExport" / "unified_translations.jsonl"

CTRL_CODE_HINTS = (
    "\\cself[", "\\v[", "\\s[", "\\c[", "\\i[", "\\m[", "\\f[", "\\r[",
    "\\name[", "\\n[", "\\sysS[", "\\space[",
)
CID122_COUNTER_BLOCKLIST = {
    "個", "枚", "本", "人", "匹", "体", "回", "発", "名", "番", "件",
    "時", "分", "秒", "円", "歳", "点", "GB", "MB",
}
CID122_FRAGMENT_RE = re.compile(r"^[ぁ-んァ-ヶー]{1,3}$")  # short kana fragment

DB_FILES = {
    "BasicData/CDataBase.dat",
    "BasicData/DataBase.dat",
    "BasicData/SysDatabase.dat",
}
# Single-character glyph tables: the game's name-input keyboard reads these
# from DataBase.dat as one-glyph-per-slot. Kana/punctuation stay original so
# the keyboard layout remains Japanese. Fullwidth Latin letters are normalized
# to halfwidth ASCII so English names render as `Stelle`, not `S t e l l e`.
# The two contiguous clusters (regular kana + voiced kana + special
# punctuation) live between 0x59195 and 0x59930 in the original decoded
# DataBase.dat.
DATABASE_GLYPH_TABLE_RANGE = (0x59100, 0x59a00)
# A second glyph table lives in `CommonEvent.dat` as CID 150 mode 2 picture
# text — the per-button labels for the in-game name-input keyboard. Each
# button is a single hiragana / katakana / small-kana / punctuation glyph.
# Translating these turns the keyboard buttons into ASCII ("A I U E O / Ka
# Ki Ku ..."), which the user explicitly does NOT want. We block the whole
# offset range so all single-kana picture-text labels stay Japanese, but we
# leave dialog choices like はい/いいえ (which live before this range) free
# to translate.
COMMONEVENT_KEYBOARD_GLYPH_RANGE = (0x2b9000, 0x2cb000)
PROJECT_FILES = {
    "BasicData/CDataBase.project",
    "BasicData/DataBase.project",
    "BasicData/SysDatabase.project",
}
GAME_FILE = "BasicData/Game.dat"
GAME_TITLE_OFFSET = 0x38
FORCED_CONTROL_PATCHES = [
    {
        "file": "BasicData/CommonEvent.dat",
        # All exact occurrences are Bokkun/cry-bubble renderers. The original
        # game used tight spacing for fullwidth kana/fullwidth Latin; after we
        # normalize Latin input to halfwidth, this crushes English cries.
        # Current rebuilt offsets include 0x148a34, 0x1493bc, 0x149e60,
        # 0x2c53a3; original-scan offsets are slightly earlier.
        "offset_range": (0x140000, 0x2c6000),
        "source": r"\f[16]\E\-[6]",
        "target": r"\f[16]\E\-[0]",
        "note": "cry-bubble-halfwidth-spacing",
    },
]

ASSET_PATH_RE = re.compile(
    r"^[A-Za-z0-9_./\\ \-()]+\.(?:png|jpg|jpeg|bmp|webp|ogg|wav|mp3|mid|midi|mps|dat|ttf|txt|json|wolf)$",
    re.I,
)
ASSET_PREFIX_RE = re.compile(
    r"^(?:Picture|SystemFile|CharaChip|EnemyGraphic|BattleEffect|MapChip|SE|BGM|window|Icon|animation|Fog_BackGround|tatie|battlEFF|Sentou|VC)/",
    re.I,
)
ENGINE_MARKER_RE = re.compile(r"^<(?:SQUARE|SCREENSHOT|NONE)>$")
JAPANESE_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿＀-￯]")

EDITOR_ONLY_PATTERNS = [
    re.compile(r"^【.*サンプル.*】$"),
    re.compile(r"^[-]{5,}$"),
    re.compile(r"^[=]{5,}$"),
]


def normalize_file(value: str) -> str:
    return str(value or "").replace("\\", "/").strip()


def has_japanese(text: str) -> bool:
    return bool(JAPANESE_RE.search(text or ""))


def looks_like_asset(text: str) -> bool:
    value = (text or "").strip()
    return bool(ASSET_PATH_RE.search(value) or ASSET_PREFIX_RE.search(value))


def looks_like_engine_marker(text: str) -> bool:
    return bool(ENGINE_MARKER_RE.search((text or "").strip()))


_KEYBOARD_GLYPH_RE = re.compile(
    r"^[぀-ゟ゠-ヿ０-｟ー～・…。？！☆♪]$"
)
FULLWIDTH_LATIN_TO_ASCII = str.maketrans(
    "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
)


def filter_translation_collisions(rows: list[dict]) -> list[dict]:
    """For every `.dat` / `.project` file, ensure that no two rows translate
    DIFFERENT source strings to the SAME target — that would create
    duplicate row names in the DB and break runtime name lookups.

    Strategy:
      * Group rows by (file, translation_template).
      * Within each group, if multiple distinct source_template values
        exist, keep the one with the LONGEST source (most specific
        Japanese text) and drop the rest.
      * Drop rows in `.project` whose source we just dropped from the
        matching `.dat`, so the two stay in lockstep.
    """
    if not rows:
        return rows

    # Filter applies only to .dat / .project files. Map / event commands can
    # legitimately have many copies of the same translated dialogue line.
    SCOPED_FILES = {
        "BasicData/CDataBase.dat", "BasicData/DataBase.dat",
        "BasicData/SysDatabase.dat", "BasicData/Game.dat",
        "BasicData/CDataBase.project", "BasicData/DataBase.project",
        "BasicData/SysDatabase.project",
    }

    # Group sources per (file, target).
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        if row.get("file") not in SCOPED_FILES:
            continue
        key = (row["file"], row["translation_template"])
        groups.setdefault(key, []).append(row)

    # Decide a winning source per (file, target) and which sources to revert.
    # We track reverts per file family (DB pair: .dat + .project).
    reverted_sources: dict[str, set[str]] = {}
    collision_count = 0
    for (file, target), members in groups.items():
        unique_sources = {row["source_template"] for row in members}
        if len(unique_sources) <= 1:
            continue
        collision_count += len(unique_sources) - 1
        # Keep the longest unique source; drop the rest.
        winning = max(unique_sources, key=lambda s: (len(s), s))
        family = file.replace(".project", ".dat")
        reverted = reverted_sources.setdefault(family, set())
        for src in unique_sources:
            if src == winning:
                continue
            reverted.add(src)

    if collision_count:
        print(f"collision filter: reverted {collision_count} duplicate-target sources")

    # Drop rows that touch any reverted source in the matching family.
    def is_reverted(row: dict) -> bool:
        file = row.get("file", "")
        if file not in SCOPED_FILES:
            return False
        family = file.replace(".project", ".dat")
        return row["source_template"] in reverted_sources.get(family, set())

    return [row for row in rows if not is_reverted(row)]


def is_keyboard_glyph_text(text: str) -> bool:
    """True when the string is a single glyph from the name-input keyboard:
    one hiragana, katakana, small kana, fullwidth alphabet, or punctuation
    glyph. Excludes multi-character mode labels (`かな`, `カナ`, `Aa`) and
    action buttons (`一字消す`, `おわる`)."""
    return bool(_KEYBOARD_GLYPH_RE.match(text or ""))


def is_fullwidth_latin_glyph(text: str) -> bool:
    """Single fullwidth Latin glyph used by the name-input DB table."""
    return len(text or "") == 1 and (
        "Ａ" <= text <= "Ｚ" or "ａ" <= text <= "ｚ"
    )


def halfwidth_latin_glyph(text: str) -> str:
    return (text or "").translate(FULLWIDTH_LATIN_TO_ASCII)


def looks_like_editor_only(text: str) -> bool:
    value = (text or "").strip()
    if not value:
        return True
    if value[0] in "×┣┗┏":
        return True
    return any(p.search(value) for p in EDITOR_ONLY_PATTERNS)


def convert_export_text(value: str) -> str:
    if value is None:
        return ""
    text = str(value)
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
            if nxt == "r":
                out.append("\r")
                i += 2
                continue
            if nxt == "t":
                out.append("\t")
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def restore_tokens(template: str, tokens: dict | None) -> str:
    text = str(template or "")
    if not tokens:
        return text
    for key, value in sorted(tokens.items(), key=lambda kv: len(kv[0]), reverse=True):
        key_str = str(key)
        value_str = str(value)
        if key_str.startswith("{") and key_str.endswith("}"):
            text = text.replace(key_str, value_str)
        else:
            text = text.replace("{" + key_str + "}", value_str)
            text = text.replace(key_str, value_str)
    return text


def maybe_repair_mojibake(text: str) -> str:
    value = str(text or "")
    if not any(m in value for m in ("ã", "å", "æ", "ç", "è", "é", "ï¼", "ï½")):
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except UnicodeError:
        return value


def read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"bad JSONL at {path}:{line_no}: {e}") from e


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.replace(path)


def build_danger_set(command_rows: list[dict]) -> tuple[set[str], dict[str, Counter]]:
    """Strings that are LOOKUP KEYS used by the engine. Anywhere these appear,
    they must remain byte-identical to the original.

    - CID 250 string_index in {1, 2, 3}: DB lookup type/data/field name
    - CID 300 string_index 0: CommonEventByName lookup key
    """
    danger: set[str] = set()
    sources: dict[str, Counter] = {}
    for row in command_rows:
        cid = str(row.get("command_id", "")).strip()
        idx = str(row.get("string_index", "")).strip()
        text = convert_export_text(row.get("text", ""))
        if not text:
            continue
        if cid == "250" and idx in {"1", "2", "3"}:
            danger.add(text)
            sources.setdefault(text, Counter())[f"cid250_str{idx}"] += 1
        elif cid == "300" and idx == "0":
            danger.add(text)
            sources.setdefault(text, Counter())["cid300_name"] += 1
    return danger, sources


def build_slot_use_index(command_rows: list[dict]) -> dict[str, set[tuple[str, str]]]:
    """Map each runtime-identifier string to the set of (cid, slot_idx) it
    appears in. We build a single index and let callers pick the syncable
    subsets out of it."""
    by_text: dict[str, set[tuple[str, str]]] = {}
    for row in command_rows:
        cid = str(row.get("command_id", "")).strip()
        idx = str(row.get("string_index", "")).strip()
        text = convert_export_text(row.get("text", ""))
        if not text:
            continue
        if cid == "250":
            by_text.setdefault(text, set()).add(("250", idx))
        elif cid == "300" and idx == "0":
            by_text.setdefault(text, set()).add(("300", "0"))
    return by_text


def build_syncable_all(slot_uses: dict[str, set[tuple[str, str]]]) -> set[str]:
    """Strings that appear EXCLUSIVELY as CID 250 slot 2 (data row name
    lookups). Translating these requires propagating the chosen target to the
    matching CID 250 slot 2 occurrences AND to the `.project` row-name slot
    that the engine reads at startup."""
    return {text for text, slots in slot_uses.items() if slots == {("250", "2")}}


def build_syncable_type_names(slot_uses: dict[str, set[tuple[str, str]]]) -> set[str]:
    """Strings that appear EXCLUSIVELY as CID 250 slot 1 (DB type names).
    The engine resolves type by numeric int-arg, so translating slot 1 is
    decorative — but we still keep `.project` in lockstep so the editor
    shows the same name."""
    return {text for text, slots in slot_uses.items() if slots == {("250", "1")}}


def build_syncable_field_names(slot_uses: dict[str, set[tuple[str, str]]]) -> set[str]:
    """Strings that appear EXCLUSIVELY as CID 250 slot 3 (field names)."""
    return {text for text, slots in slot_uses.items() if slots == {("250", "3")}}


def is_translatable_command_slot(row: dict, danger: set[str]) -> tuple[bool, str]:
    cid = str(row.get("command_id", "")).strip()
    idx = str(row.get("string_index", "")).strip()
    subtype = str(row.get("picture_subtype", "")).strip()
    text = convert_export_text(row.get("text", ""))
    if not text:
        return False, "empty"
    if not has_japanese(text):
        return False, "not-japanese"
    if looks_like_asset(text) or looks_like_engine_marker(text):
        return False, "asset-or-marker"
    if cid == "101" and idx == "0":
        return True, "show-message"
    if cid == "102":
        # Choice labels are display-only; the engine dispatches by index.
        return True, "show-choice"
    if cid == "150" and idx == "0":
        # Stricter: only translate when the subtype is "text" picture (mode 2),
        # OR when the subtype was not extracted (legacy maps where the structured
        # parser already screened out non-text pictures).
        if subtype and subtype != "2":
            return False, f"cid150-mode-{subtype}"
        # Block CommonEvent.dat keyboard glyph labels — but ONLY the single
        # per-glyph buttons. Mode labels (`かな`, `カナ`, `Aa`) and action
        # buttons (`一字消す`, `おわる`, `\E\f[16]キミの「なきごえ」を…`) live
        # in the same offset range but are full words, so we keep them
        # translatable. The discriminator: pure single-char kana / fullwidth
        # alpha / glyph-table punctuation.
        file_norm = normalize_file(row.get("file", ""))
        if file_norm == "BasicData/CommonEvent.dat":
            try:
                offset = int(str(row.get("string_offset_hex", "")), 16)
            except ValueError:
                offset = -1
            lo, hi = COMMONEVENT_KEYBOARD_GLYPH_RANGE
            if lo <= offset < hi and is_keyboard_glyph_text(text):
                return False, "keyboard-glyph-label"
        return True, "picture-text"
    if cid == "122" and idx == "0":
        # CID 122 SetString writes a string variable. In this game we verified:
        #   * No CID 250 slot 1/2/3 (DB lookup key) uses \cself[..] / \v[..] /
        #     \sysS[..] interpolation, so a translated SetString never flows
        #     into a runtime DB lookup as a key.
        #   * CID 111 (StringCondition) is unused, so SetString values are not
        #     compared back to their Japanese form.
        # Translations in the JSONL memory have been hand-vetted to preserve
        # control codes verbatim (e.g. `\sysS[2]=メニュー` -> `\sysS[2]=Menu`),
        # so we no longer reject strings that contain control codes.
        if text in CID122_COUNTER_BLOCKLIST:
            return False, "cid122-counter"
        if len(text) < 2:
            return False, "cid122-short"
        if len(text) >= 8 and text.endswith(("が", "に", "を", "は", "で", "から", "まで", "より")):
            return False, "cid122-long-particle-tail"
        return True, "cid122-display"
    return False, f"cid-{cid}-idx-{idx}"


def is_translatable_db_string(row: dict, danger: set[str], syncable: set[str]) -> tuple[bool, str]:
    """`danger` includes all strings used as CID 250 slot 1/2/3 and CID 300.
    `syncable` is the subset of `danger` we DO want to translate, with the
    caveat that we'll also translate every CID 250 slot 2 occurrence to keep
    the lookup consistent. So `syncable` strings ARE allowed in DB slots."""
    file = normalize_file(row.get("file", ""))
    text = convert_export_text(row.get("text", ""))
    kind = (row.get("kind") or "").strip()
    if not text:
        return False, "empty"
    if file == GAME_FILE:
        offset = int(row.get("offset_dec") or 0)
        if offset != GAME_TITLE_OFFSET:
            return False, "game-non-title"
        if not has_japanese(text):
            return False, "game-title-no-japanese"
        return True, "game-title"
    if file not in DB_FILES:
        return False, "not-db-file"
    # Block name-input glyphs from normal AI translation. A dedicated pass
    # below converts only fullwidth Latin glyphs to halfwidth ASCII while
    # keeping kana/punctuation byte-stable. The offset range catches original
    # scans; the glyph check catches already-rebuilt Data where earlier
    # variable-length edits shifted the table.
    if file == "BasicData/DataBase.dat":
        try:
            offset = int(str(row.get("offset_hex", "")), 16)
        except ValueError:
            offset = -1
        lo, hi = DATABASE_GLYPH_TABLE_RANGE
        if lo <= offset < hi or is_keyboard_glyph_text(text):
            return False, "kana-glyph-table"
    if not has_japanese(text):
        return False, "not-japanese"
    if kind in {"asset_path"}:
        return False, "asset-path"
    if looks_like_asset(text) or looks_like_engine_marker(text):
        return False, "asset-or-marker"
    if text in danger and text not in syncable:
        return False, "danger-set-not-syncable"
    if looks_like_editor_only(text):
        return False, "editor-only"
    if text in syncable:
        return True, "db-syncable-data-name"
    return True, "db-translatable"


def offset_key(row: dict) -> tuple[str, str]:
    return (
        normalize_file(row.get("file", "")),
        str(row.get("offset_hex", row.get("string_offset_hex", ""))).lower(),
    )


def load_translation_memory(paths: list[Path]) -> dict[tuple[str, str], dict]:
    memory: dict[tuple[str, str], dict] = {}
    for path in paths:
        if not path or not path.exists():
            continue
        for tr in iter_jsonl(path):
            file = normalize_file(tr.get("file", ""))
            ctx = str(tr.get("context", ""))
            if not ctx.startswith("offset:"):
                continue
            off = ctx.split(":", 1)[1].strip().lower()
            key = (file, off)
            memory.setdefault(key, tr)
    return memory


def restore_source(tr: dict) -> str:
    tokens = tr.get("tokens") if isinstance(tr.get("tokens"), dict) else {}
    return restore_tokens(tr.get("source_template", ""), tokens)


def restore_translation(tr: dict) -> str:
    tokens = tr.get("tokens") if isinstance(tr.get("tokens"), dict) else {}
    return restore_tokens(tr.get("translation_template", ""), tokens)


def make_output_row(row_id: str, file: str, offset_hex: str, source_text: str, translation: str, note: str) -> OrderedDict:
    return OrderedDict(
        [
            ("id", str(row_id)),
            ("file", file),
            ("source", "string"),
            ("context", f"offset:{offset_hex}"),
            ("event", OrderedDict([("id", ""), ("name", ""), ("page", "")])),
            ("speaker", ""),
            ("speaker_translation", ""),
            ("source_template", source_text),
            ("translation_template", translation),
            ("tokens", {}),
            ("model", "unified-builder"),
            ("batch_id", "unified"),
            ("usage", {}),
            ("note", note),
        ]
    )


def main() -> int:
    # Force stdout to UTF-8 so Japanese debug prints work on Windows.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan-dir", type=Path, default=DEFAULT_SCAN_DIR)
    ap.add_argument("--project-scan-dir", type=Path, default=DEFAULT_PROJECT_SCAN_DIR)
    ap.add_argument("--extra-scan-csv", type=Path, default=DEFAULT_EXTRA_SCAN_CSV)
    ap.add_argument("--translation-jsonl", action="append", default=[], type=Path)
    ap.add_argument("--glossary-jsonl", type=Path, default=DEFAULT_GLOSSARY)
    ap.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()

    if not args.translation_jsonl:
        args.translation_jsonl = [DEFAULT_TRANSLATION] + DEFAULT_EXTRA_TRANSLATIONS

    strings_all = read_csv_rows(args.scan_dir / "strings_all.csv")
    command_rows = read_csv_rows(args.scan_dir / "command_strings.csv")
    dialogue_rows = read_csv_rows(args.scan_dir / "dialogues.csv")
    # Pull in `.project` strings from the second scan if it's available. We
    # only need the `strings_all.csv` rows that target a `.project` file; the
    # primary scan typically misses these because it was run on the unpacked
    # workspace.
    if args.project_scan_dir and (args.project_scan_dir / "strings_all.csv").exists():
        seen_keys = {(normalize_file(r["file"]), str(r["offset_hex"]).lower()) for r in strings_all}
        for row in read_csv_rows(args.project_scan_dir / "strings_all.csv"):
            file = normalize_file(row.get("file", ""))
            if file not in PROJECT_FILES:
                continue
            key = (file, str(row.get("offset_hex", "")).lower())
            if key in seen_keys:
                continue
            strings_all.append(row)
            seen_keys.add(key)
    extra_rows = []
    if args.extra_scan_csv and Path(args.extra_scan_csv).exists():
        extra_rows = read_csv_rows(Path(args.extra_scan_csv))
        # Convert extra scan rows to look like command_strings rows (they already have
        # the same column names, just an extra picture_subtype column).
        # The extra scan finds CIDs the structured parser missed for CommonEvent.dat;
        # we want to consider these for danger set analysis too.

    # Use original command_strings for the danger set so we don't get fooled by
    # pattern-matching false positives from the byte scanner; CID 250 + CID 300
    # are the strongest signals and they all parse out of the structured parser
    # via the fallback scan.
    danger, danger_sources = build_danger_set(command_rows)
    slot_uses = build_slot_use_index(command_rows)
    syncable_data_names_only = build_syncable_all(slot_uses)
    # Type-name (slot 1) and field-name (slot 3) sync are mostly disabled —
    # they triggered a `Type 25 Data 332 does not exist` regression at
    # `MapEv 5 / CommonEv 700 line 191` when applied broadly. The user still
    # wants the two top-level menu type names translated though, so we add
    # JUST those two to the syncable set: their .project rows + every CID
    # 250 slot 1 occurrence get the same translation in lockstep.
    SAFE_TYPE_NAMES = {"モンスター", "アイテム"}
    syncable_safe_types = {t for t in SAFE_TYPE_NAMES
                           if t in slot_uses and slot_uses[t] == {("250", "1")}}
    syncable_all = syncable_data_names_only | syncable_safe_types
    print(f"syncable data-name strings: {len(syncable_data_names_only)}")
    print(f"syncable type names (allowlisted): {len(syncable_safe_types)}")
    print(f"(broad type-name + field-name sync disabled)")
    print(f"danger-set size: {len(danger)}")
    most_common = sorted(((s, sum(danger_sources[s].values())) for s in danger), key=lambda x: -x[1])[:5]
    for s, n in most_common:
        print(f"  {n} x {s!r}")

    # Build a (file, offset) -> source-row index for fast lookup. Each string in
    # the .dat / .mps appears once in strings_all.csv with `offset_hex` set.
    # Augment with extra_rows so command-only offsets resolve to a source row.
    strings_by_off: dict[tuple[str, str], dict] = {}
    for row in strings_all:
        key = (normalize_file(row["file"]), str(row["offset_hex"]).lower())
        strings_by_off.setdefault(key, row)
    for row in extra_rows:
        key = (normalize_file(row["file"]), str(row["string_offset_hex"]).lower())
        strings_by_off.setdefault(key, {
            "id": row.get("id", ""),
            "file": row["file"],
            "offset_hex": row["string_offset_hex"],
            "text": row["text"],
        })

    # 1) Translatable command slot keys (CID 101/102/150 anywhere we see them).
    translatable_command_offsets: dict[tuple[str, str], str] = {}
    cmd_skipped = Counter()
    for row in command_rows:
        ok, reason = is_translatable_command_slot(row, danger)
        if ok:
            key = (normalize_file(row["file"]), str(row["string_offset_hex"]).lower())
            translatable_command_offsets[key] = reason
        else:
            cmd_skipped[reason] += 1

    # 2) Dialogues.csv catches CID 101 messages from files where the structured
    #    parser fell back to message scanning (notably this game's CommonEvent.dat).
    #    Treat every dialogue offset as translatable.
    for row in dialogue_rows:
        key = (normalize_file(row["file"]), str(row["string_offset_hex"]).lower())
        translatable_command_offsets.setdefault(key, "dialogue-scan")

    # 3) Extra scan catches CID 102/122/150 in CommonEvent.dat which the
    #    structured parser misses. Apply the same translatable-slot rules.
    extra_skipped = Counter()
    for row in extra_rows:
        ok, reason = is_translatable_command_slot(row, danger)
        if ok:
            key = (normalize_file(row["file"]), str(row["string_offset_hex"]).lower())
            translatable_command_offsets.setdefault(key, f"extra:{reason}")
        else:
            extra_skipped[reason] += 1

    # 3) Translatable DB / Game.dat string keys
    db_candidates: list[dict] = []
    db_skipped = Counter()
    for row in strings_all:
        ok, reason = is_translatable_db_string(row, danger, syncable_all)
        if ok:
            db_candidates.append(row)
        else:
            db_skipped[reason] += 1

    # Load translation memory by (file, offset)
    memory = load_translation_memory(args.translation_jsonl)
    # Also a (file, source) fallback and a global source fallback
    by_file_source: dict[tuple[str, str], dict] = {}
    by_source: dict[str, dict] = {}
    for tr in memory.values():
        file = normalize_file(tr.get("file", ""))
        src = restore_source(tr)
        rep = maybe_repair_mojibake(src)
        for variant in {src, rep}:
            if not variant:
                continue
            by_file_source.setdefault((file, variant), tr)
            by_source.setdefault(variant, tr)

    # Hand glossary fallback: a JSONL of {"source": "...", "translation": "..."}.
    # Entries with "global": true mean "translate this string at every offset
    # in strings_all where it matches", not just at safe-slot offsets — used
    # for short speaker-name prefixes that appear in command structures the
    # byte-scanner misses (CID 102 with multiple slots, embedded payloads, etc).
    # Entries with "override": true beat the translation memory — for cases
    # where the model picked a translation we want to override (e.g. trailing
    # spaces for prefix concatenation).
    glossary: dict[str, str] = {}
    global_glossary: dict[str, str] = {}
    override_glossary: dict[str, str] = {}
    if args.glossary_jsonl and Path(args.glossary_jsonl).exists():
        with Path(args.glossary_jsonl).open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                obj = json.loads(line)
                src = obj.get("source", "")
                tr = obj.get("translation", "")
                if src and tr is not None:
                    glossary[src] = tr
                    if obj.get("global"):
                        global_glossary[src] = tr
                    if obj.get("override"):
                        override_glossary[src] = tr

    # Build output rows
    out_rows: list[dict] = []
    seen: dict[tuple[str, str], OrderedDict] = {}
    matched_exact = matched_file_source = matched_global = 0
    missing = 0

    def add_row(row_id, file, offset_hex, source_text, translation, note):
        nonlocal matched_exact, matched_file_source, matched_global, missing
        key = (file, offset_hex.lower())
        existing = seen.get(key)
        new_row = make_output_row(row_id, file, offset_hex.lower(), source_text, translation, note)
        if existing is None:
            seen[key] = new_row
            out_rows.append(new_row)
        else:
            if existing["source_template"] != source_text:
                raise RuntimeError(
                    f"conflicting source for {key}: "
                    f"{existing['source_template']!r} vs {source_text!r}"
                )
            if existing["translation_template"] != translation:
                # Keep first; warn.
                pass

    def lookup_translation(file: str, offset_hex: str, source_text: str) -> tuple[dict | None, str]:
        nonlocal matched_exact, matched_file_source, matched_global
        # Override-glossary wins over translation memory for the few entries
        # we manually corrected (spacing, capitalization, etc.).
        if source_text in override_glossary:
            return (
                {"source_template": source_text,
                 "translation_template": override_glossary[source_text],
                 "tokens": {}},
                "override-glossary",
            )
        key = (file, offset_hex.lower())
        tr = memory.get(key)
        if tr is not None:
            tr_src = restore_source(tr)
            if tr_src == source_text or maybe_repair_mojibake(tr_src) == source_text:
                matched_exact += 1
                return tr, "exact"
        tr = by_file_source.get((file, source_text))
        if tr is not None:
            matched_file_source += 1
            return tr, "file-source"
        tr = by_source.get(source_text)
        if tr is not None:
            matched_global += 1
            return tr, "global-source"
        if source_text in glossary:
            return {"source_template": source_text, "translation_template": glossary[source_text], "tokens": {}}, "glossary"
        return None, "missing"

    forced_control_count = 0
    for row in strings_all:
        file = normalize_file(row.get("file", ""))
        source_text = convert_export_text(row.get("text", ""))
        if not source_text:
            continue
        try:
            offset = int(str(row.get("offset_hex", "")), 16)
        except ValueError:
            continue
        for patch in FORCED_CONTROL_PATCHES:
            if file != patch["file"] or source_text != patch["source"]:
                continue
            lo, hi = patch["offset_range"]
            if not (lo <= offset <= hi):
                continue
            add_row(
                row.get("id", ""),
                file,
                str(row["offset_hex"]).lower(),
                source_text,
                patch["target"],
                patch["note"],
            )
            forced_control_count += 1
            break
    print(f"forced control-code rows added: {forced_control_count}")

    for (file, offset_hex), why_safe in translatable_command_offsets.items():
        source_row = strings_by_off.get((file, offset_hex))
        if not source_row:
            missing += 1
            continue
        source_text = convert_export_text(source_row["text"])
        if not source_text:
            missing += 1
            continue
        tr, how = lookup_translation(file, offset_hex, source_text)
        if tr is None:
            missing += 1
            continue
        # Don't strip whitespace — trailing/leading spaces are intentional for
        # speaker-prefix concatenation (e.g. `Ordinary ` + `Syrup` = `Ordinary Syrup`).
        translation = restore_translation(tr)
        if not translation.strip():
            missing += 1
            continue
        add_row(source_row.get("id", ""), file, offset_hex, source_text, translation, f"command:{why_safe}:{how}")

    # Translate DB strings, and remember the chosen translation for every
    # source we touch in a `.dat`. The `.project` sync pass below mirrors
    # those translations into the matching `.project` row-name slots, which
    # is required because the WOLF runtime sometimes resolves DB lookups
    # against `.project` (Heroine, Weak Glue, ...). syncable_all is a strict
    # subset that triggers the additional CID 250 slot sync; dat_translations
    # tracks everything translated in any `.dat` file.
    syncable_translations: dict[str, str] = {}
    dat_translations: dict[str, str] = {}
    latin_glyph_count = 0
    for row in strings_all:
        file = normalize_file(row.get("file", ""))
        if file != "BasicData/DataBase.dat":
            continue
        source_text = convert_export_text(row.get("text", ""))
        if not is_fullwidth_latin_glyph(source_text):
            continue
        add_row(
            row.get("id", ""),
            file,
            str(row["offset_hex"]).lower(),
            source_text,
            halfwidth_latin_glyph(source_text),
            "db:name-input-latin-halfwidth",
        )
        latin_glyph_count += 1
    print(f"name-input Latin glyph rows normalized: {latin_glyph_count}")

    for row in db_candidates:
        file = normalize_file(row["file"])
        offset_hex = str(row["offset_hex"]).lower()
        source_text = convert_export_text(row["text"])
        tr, how = lookup_translation(file, offset_hex, source_text)
        if tr is None:
            missing += 1
            continue
        translation = restore_translation(tr)
        if not translation.strip():
            missing += 1
            continue
        existing_dat = dat_translations.get(source_text)
        if existing_dat is None:
            dat_translations[source_text] = translation
        elif existing_dat != translation:
            # Conflicting translations for the same source text in different
            # .dat slots — keep the first one for sync purposes (the inject
            # tool still applies each per-offset translation independently
            # to the .dat itself).
            pass
        if source_text in syncable_all:
            existing = syncable_translations.get(source_text)
            if existing and existing != translation:
                continue
            syncable_translations.setdefault(source_text, translation)
        add_row(row["id"], file, offset_hex, source_text, translation, f"db:{how}")

    # Sync pass: for every CID 250 occurrence whose source text is in
    # `syncable_translations`, translate it to the same value. This keeps the
    # runtime lookup consistent with the translated DB row name AND with the
    # editor's view of type/field names. We sync slots 1/2/3 — the slot the
    # string actually appears in is implicit because `syncable_*` sets are
    # disjoint by construction (each string is exclusive to one slot).
    sync_count = 0
    for row in command_rows:
        cid = str(row.get("command_id", "")).strip()
        idx = str(row.get("string_index", "")).strip()
        if cid != "250" or idx not in {"1", "2", "3"}:
            continue
        source_text = convert_export_text(row.get("text", ""))
        target = syncable_translations.get(source_text)
        if not target:
            continue
        file = normalize_file(row["file"])
        offset_hex = str(row["string_offset_hex"]).lower()
        try:
            add_row(
                f"sync250-{sync_count}", file, offset_hex, source_text, target,
                f"sync-cid250-slot{idx}-to-translated-name",
            )
            sync_count += 1
        except RuntimeError:
            pass
    print(f"sync rows added (CID 250 slots 1/2/3): {sync_count}")

    # For syncable strings that aren't present in any `.dat` file (e.g. type
    # names that only live in `.project` and CID 250 slot 1), the db_candidates
    # loop above never had a chance to populate `syncable_translations`. Pick
    # them up from the translation memory directly so the sync passes below
    # can use them. We only accept translations that aren't identical to the
    # source — the memory sometimes contains "kept Japanese" entries which we
    # want to skip rather than treat as a translation.
    extra_syncable_count = 0
    for source_text in syncable_all:
        if source_text in syncable_translations:
            continue
        tr = by_source.get(source_text)
        if tr is None:
            continue
        target = restore_translation(tr)
        if not target.strip() or target == source_text:
            continue
        syncable_translations[source_text] = target
        extra_syncable_count += 1
    print(f"syncable translations picked up from memory (no .dat slot): {extra_syncable_count}")

    # Re-run the CID 250 slot 1/2/3 sync now that more syncable_translations
    # are available.
    extra_sync_count = 0
    for row in command_rows:
        cid = str(row.get("command_id", "")).strip()
        idx = str(row.get("string_index", "")).strip()
        if cid != "250" or idx not in {"1", "2", "3"}:
            continue
        source_text = convert_export_text(row.get("text", ""))
        target = syncable_translations.get(source_text)
        if not target:
            continue
        file = normalize_file(row["file"])
        offset_hex = str(row["string_offset_hex"]).lower()
        try:
            add_row(
                f"sync250b-{extra_sync_count}", file, offset_hex, source_text, target,
                f"sync-cid250-slot{idx}-to-translated-name",
            )
            extra_sync_count += 1
        except RuntimeError:
            pass
    print(f"extra sync rows added (CID 250 slot 1/2/3 from memory): {extra_sync_count}")

    # `.project` sync pass: WOLF stores per-type data row names (and other
    # default data values) in the matching `.project` file. The engine reads
    # them at runtime for string-keyed DB lookups. If we translated a row
    # name in `.dat` and the matching `CID 250` slot 2 lookup but left the
    # `.project` row name as the original, the lookup fails — exactly the
    # `[type25] Heroine does not exist` regression. So for every `.project`
    # length-prefixed string that exactly matches a syncable data name, mirror
    # the translation. We're conservative: only EXACT-equal strings, so type
    # names (`トレーナー`) and field names (`立ち絵`) — which are in `danger`
    # but not `syncable_all` — stay byte-identical.
    project_sync_count = 0
    for row in strings_all:
        file = normalize_file(row.get("file", ""))
        if file not in PROJECT_FILES:
            continue
        source_text = convert_export_text(row.get("text", ""))
        # Prefer the syncable-translation choice (engine-key-aware), fall back
        # to whatever target we used in `.dat`. Either way the `.dat` /
        # `.project` pair stays consistent for runtime name lookups.
        target = syncable_translations.get(source_text) or dat_translations.get(source_text)
        if not target:
            continue
        offset_hex = str(row["offset_hex"]).lower()
        try:
            add_row(
                f"projsync-{project_sync_count}", file, offset_hex, source_text, target,
                "sync-project-to-translated-data-name",
            )
            project_sync_count += 1
        except RuntimeError:
            pass
    print(f"sync rows added (.project): {project_sync_count}")

    # Global-glossary pass: for every string in `strings_all` whose text exactly
    # matches a global glossary entry, add a patch. This catches strings that
    # are inside command structures the byte-scanner couldn't recognize
    # (e.g. Show Choice with embedded sub-records). The danger-set check below
    # makes sure we never overwrite a runtime lookup key.
    global_count = 0
    for row in strings_all:
        text = convert_export_text(row.get("text", ""))
        if not text or text not in global_glossary:
            continue
        if text in danger:
            # Should never happen for our hand-listed entries, but belt and braces.
            continue
        target = global_glossary[text]
        file = normalize_file(row["file"])
        offset_hex = str(row["offset_hex"]).lower()
        try:
            add_row(
                f"glob-{global_count}", file, offset_hex, text, target,
                "global-glossary",
            )
            global_count += 1
        except RuntimeError:
            # Already added by another pass with the same translation; skip.
            pass
    print(f"global-glossary rows added: {global_count}")

    # "Memory-only" pass: translation memory has exact-offset entries at
    # positions our byte-scanner can't classify into a CID 122/101/150
    # slot — strings like `設定を反映しました。` live inside command
    # structures the parser misses. For each such entry, only apply if:
    #   * The (file, offset) is a real length-prefixed string slot in the
    #     original (i.e., shows up in `strings_all.csv`), AND
    #   * That slot's text exactly matches the memory's source, AND
    #   * The source isn't a danger-set runtime key, AND
    #   * The slot isn't a CID 103 (comment) / CID 300 (CommonEventByName)
    #     position we know to leave alone.
    danger_or_comment_offsets: set[tuple[str, str]] = set()
    for row in command_rows:
        cid = str(row.get("command_id", "")).strip()
        idx = str(row.get("string_index", "")).strip()
        if (cid in {"103", "300"}) or (cid == "250" and idx in {"0", "1", "2", "3"}):
            key = (
                normalize_file(row["file"]),
                str(row["string_offset_hex"]).lower(),
            )
            danger_or_comment_offsets.add(key)
    for row in extra_rows:
        cid = str(row.get("command_id", "")).strip()
        if cid in {"103", "300"}:
            key = (
                normalize_file(row["file"]),
                str(row["string_offset_hex"]).lower(),
            )
            danger_or_comment_offsets.add(key)

    # Memory-only fallback DISABLED. An earlier version of this pass caught
    # the rendering for `設定を反映しました。` but also leaked translations
    # into strings the engine uses as asset references / runtime keys —
    # the user reported missing UI / icons after that pass. The right way
    # to surface specific extra-but-safe strings is a hand-curated entry in
    # `ui_glossary.jsonl` with an explicit (file, offset) override; that
    # gives us per-string approval instead of a blanket sweep.
    print("memory-only fallback: disabled (use ui_glossary overrides instead)")

    # Collision filter: if the same target string is used for two DIFFERENT
    # source strings inside the same `.dat` / `.project` file, the WOLF
    # engine will see two DB rows with identical names. Lookups by name pick
    # the first match, which corrupts which row's fields the engine reads.
    # Symptom: `[DB operation] data number is negative => Data -1` after
    # using one of the two items. Drop translations for all but the source
    # we want to keep; reverting the others to the original Japanese keeps
    # those rows uniquely addressable.
    out_rows = filter_translation_collisions(out_rows)
    write_jsonl(args.output_jsonl, out_rows)
    print()
    print(f"command rows skipped:")
    for r, c in cmd_skipped.most_common():
        print(f"  {r}: {c}")
    print()
    print(f"db rows skipped:")
    for r, c in db_skipped.most_common():
        print(f"  {r}: {c}")
    print()
    print(f"translatable command slots: {len(translatable_command_offsets)}")
    print(f"translatable db candidates: {len(db_candidates)}")
    glossary_kept = sum(1 for r in out_rows if "glossary" in r.get("note", ""))
    print(f"  matched exact:       {matched_exact}")
    print(f"  matched file+source: {matched_file_source}")
    print(f"  matched global src:  {matched_global}")
    print(f"  glossary entries used: {glossary_kept}")
    print(f"  missing translations: {missing}")
    print(f"extra-scan skipped:")
    for r, c in extra_skipped.most_common(10):
        print(f"  {r}: {c}")
    print(f"output rows: {len(out_rows)}")
    print(f"wrote: {args.output_jsonl}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
