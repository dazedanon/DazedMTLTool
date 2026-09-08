#!/usr/bin/env python3
import argparse
import base64
import csv
import hashlib
import json
import re
import shutil
import struct
import unicodedata
from pathlib import Path

REAL_JP_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
JP_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\uff00-\uffef]")
KANA_RE = re.compile(r"[\u3040-\u30ff]")
KANA_OR_FULLWIDTH_RE = re.compile(r"[\u3040-\u30ff\uff00-\uffef]")
HEX_ID_RE = re.compile(r"^[0-9A-Fa-f]{16,}$")
SINGLE_CHAR_LABELS = set("左右上下前後奥手指脚足口胸尻俺蓮え横縦目首膣")
INTERNAL_NAME_RE = re.compile(
    r"(BndEvt|K2Node|DelegateSignature|Clicked|Pressed|Released|Hovered|Unhovered|Button_|_イベント|__)",
    re.IGNORECASE,
)
# DataTable assets whose RawExport blobs may be safely resized (sequential
# length-prefixed rows, no absolute offsets into the blob)
RESIZABLE_RAW_RE = re.compile(r"/DT_[^/]+\.json$")

KISMET_EX_STRING_CONST = 0x1F
KISMET_EX_UNICODE_STRING_CONST = 0x34
KISMET_ABSOLUTE_TARGET_TOKENS = {
    0x06: "jump",          # EX_Jump CodeOffset
    0x07: "jump_if_not",   # EX_JumpIfNot CodeOffset
    0x4C: "push_flow",     # EX_PushExecutionFlow PushingAddress
}
# EX_SwitchValue (0x69) embeds two kinds of absolute iCode targets:
#   * OffsetToEndOffset  -> "switch_end"  (used after a matching case body)
#   * OffsetToNextCase   -> "switch_next" (used when a case does not match)
# Both are read by the runtime as `Stack.Code = &Stack.Node->Script[Offset]`,
# so they must be relocated like any other absolute jump target.
KISMET_ABSOLUTE_TARGET_KINDS = {"jump", "jump_if_not", "push_flow", "switch_end", "switch_next"}
KISMET_RELATIVE_SKIP_KINDS = {"skip"}
# context_skip is the EX_Context / EX_Context_FailSilent / EX_ClassContext
# "skip past the property access if the object is null" operand. Its semantics
# are a relative skip whose anchor is *after* the RValuePointer: the iCode body
# starts at icode_operand + 4 + KISMET_CONTEXT_RVALUE_ICODE_SIZE and the operand
# value is the body's iCode size. When edits change the body size, the operand
# is adjusted by the icode delta of edits landing inside the body span, and the
# post-edit validator confirms the new landing is an opcode boundary.
KISMET_CONTEXT_SKIP_KINDS = {"context_skip"}
KISMET_LITERAL_KINDS = {"skip_offset_const"}
KISMET_RELOCATED_TARGET_KINDS = KISMET_ABSOLUTE_TARGET_KINDS | KISMET_RELATIVE_SKIP_KINDS | KISMET_CONTEXT_SKIP_KINDS
# iCode size of the inline RValuePointer slot that follows context_skip.
KISMET_CONTEXT_RVALUE_ICODE_SIZE = 8
SPEAKER_BY_VOICE_FOLDER = {
    "Zirai": "Zirai",
}
SPEAKER_BY_FILE = {
    "DT_InteractMontagebak.json": "Ive",
}
GAME_MASTER_PHRASES = (
    "ゲームマスター",
    "イヴさん",
    "イブ。",
    "お目覚め",
    "選ばれました",
    "拒否権",
    "首輪がついている限り",
    "お待ちしています",
    "始めましょう",
    "試練の場",
    "私の用意した",
    "元気がいいですね",
    "いいですよ",
    "そうでなくては",
    "観察",
    "見届けている",
    "楽しみにしています",
    "楽しみですね",
    "できませんね",
    "おやおや",
    "してください",
    "ください",
    "下さい",
    "リラックスして",
    "彼が相手",
    "罰を与えよう",
    "勘違いしてもらっちゃ",
    "その表情",
    "ごゆっくり",
    "おやすみ、イヴ",
    "次に目覚める",
    "運び方は手荒",
    "参加者の皆様",
    "ここでの暮らし",
)
IVE_PHRASES = (
    "誰よアンタ",
    "誰よアンタ",
    "アンタ",
    "あんた",
    "何よ",
    "は？",
    "はぁ？",
    "冗談キツい",
    "ここ、どこよ",
    "ふざけ",
    "帰して",
    "出してよ",
    "突破してやる",
    "思い通り",
    "勝手に",
    "やだ",
    "何なの",
    "なんなの",
    "何よそれ",
    "モルモットみたい",
    "私はイヴ",
    "イヴよ",
)
MARY_PHRASES = (
    "メアリーよ",
    "また会ったわね",
    "あなたがまたここにいる",
    "出口はない",
    "出口、見つかりそう",
    "そんなことない",
    "あなたも、すぐにわかる",
    "私は....いいの",
    "あなたは、行く理由",
    "慣れると",
    "今日は、少し疲れてる",
    "もし、全部忘れられるなら",
    "イヴ……。歩み続ける",
    "あなたが“進む”",
    "ここに来た人は",
    "“出たい”って",
    "覚えておくわ",
    "気をつけて",
    "最初の部屋",
    "ええ。動くだけ",
    "あなたは、出られる",
    "あなたみたいな人",
    "音を聴いてる",
    "この場所、ひとつだけ",
    "あなた....、怖くない",
    "羨ましいわ",
    "そういうところ",
    "怖かった。汚くて",
    "ここが当たり前",
    "そう思ってるうちは",
    "自分の居場所",
    "もう覚えてない",
    "分からないわ",
)
MOB_PHRASES = (
    "お前",
    "咥えろ",
    "オラ",
    "オラァ",
    "射精",
    "中古品",
    "名器",
    "ボスのお気に入り",
    "かわいい娘",
    "泣くなよ",
    "喉奥",
    "ぬきたり",
    "やめとけ",
    "命拾い",
    "ありがとな",
    "三日間",
    "こいつ",
    "でるでる",
    "獣だな",
)
UI_TEXT_EXACT = {
    "キャンセル",
    "タイトルに戻る",
    "ゲームに戻る",
    "ステータスを上げる",
    "脱出を試みる",
    "挑戦する",
    "信頼度イベント 必要EXP:0",
    "これ以上進むとロビーへは戻れなくなります。",
    "本当に進んでもいいですか？",
    "保存されていない進行は破棄されます。",
    "タイトルに戻ってよろしいですか？",
}
UI_TEXT_PHRASES = (
    "保存されていない進行",
    "タイトルに戻",
    "ロビーへは戻れなくなります",
    "本当に進んでもいいですか",
)
ACTION_LABELS = {
    "こする",
    "のぞく",
    "ふれる",
    "ふれる2",
    "もちあげる",
    "もちあげる2",
    "シャワーを浴びる",
    "咥える",
    "挟む",
    "見る3",
    "見る２",
    "バイブ練習",
    "ポーズ画面",
    "調べる",
    "探る",
    "話す",
    "座る",
    "服装切替",
    "シーン終了",
    "ズーム",
    "パン",
    "カメラ移動",
    "カメラ",
    "シネマティック",
    "絶頂",
}
SKIP_KEYS = {
    "ObjectName",
    "ObjectPath",
    "PackageName",
    "ClassName",
    "OuterName",
    "Name",
    "Type",
}


def pointer_escape(part):
    return str(part).replace("~", "~0").replace("/", "~1")


def pointer_unescape(part):
    return part.replace("~1", "/").replace("~0", "~")


def iter_strings(node, pointer=""):
    if isinstance(node, dict):
        for key, value in node.items():
            child = pointer + "/" + pointer_escape(key)
            if isinstance(value, str):
                yield child, key, value
            else:
                yield from iter_strings(value, child)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            child = pointer + "/" + str(index)
            if isinstance(value, str):
                yield child, "", value
            else:
                yield from iter_strings(value, child)


def should_extract(key, value):
    if key in SKIP_KEYS:
        return False
    return is_human_text(value)


def is_internal_identifier(value):
    if value.startswith(("/Game/", "/Script/", "BlueprintGeneratedClass ")):
        return True
    if value.endswith((".uasset", ".uexp", ".umap", ".ubulk")):
        return True
    if INTERNAL_NAME_RE.search(value):
        return True
    if "_" in value and re.search(r"[A-Za-z]", value):
        return True
    return False


def has_bad_control_chars(value):
    for ch in value:
        if ch in "\r\n\t":
            continue
        if unicodedata.category(ch)[0] == "C":
            return True
    return False


def has_cjk_extension_chars(value):
    return any("\u3400" <= ch <= "\u4dbf" for ch in value)


def has_hangul_chars(value):
    return any("\u1100" <= ch <= "\u11ff" or "\u3130" <= ch <= "\u318f" or "\uac00" <= ch <= "\ud7af" for ch in value)


RICH_TEXT_MARKUP_RE = re.compile(r"<img[^<>]*/?>|<[A-Za-z][A-Za-z0-9_]*>|</>")


def is_human_text(value):
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped or not REAL_JP_RE.search(stripped):
        return False
    # styled UI strings like <vividpink_dot>死の期限ボーナス</> or embedded
    # <img id="..."/> icons would otherwise be rejected as internal names by
    # the underscore/Latin heuristics below; judge the markup-stripped text
    if "<" in stripped and RICH_TEXT_MARKUP_RE.search(stripped):
        without_markup = RICH_TEXT_MARKUP_RE.sub("", stripped)
        if without_markup != stripped:
            return is_human_text(without_markup)
    if stripped.startswith("_"):
        # leading "___" typewriter pauses; make_text_rows peels them into
        # segment_prefix, here they just must not disqualify the text
        bare = stripped.lstrip("_ 　\t")
        if bare and bare != stripped:
            return is_human_text(bare)
    if HEX_ID_RE.fullmatch(stripped):
        return False
    if has_bad_control_chars(stripped):
        return False
    if has_cjk_extension_chars(stripped):
        return False
    if has_hangul_chars(stripped):
        return False
    if is_internal_identifier(stripped):
        return False
    if len(stripped) == 1:
        if "\uff61" <= stripped <= "\uff9f":
            return False
        if stripped not in SINGLE_CHAR_LABELS:
            return False
    return True


def is_raw_display_text(value):
    return is_human_text(value)


def row_id(rel, pointer, source, kind="json", offset=""):
    h = hashlib.sha1()
    h.update(kind.encode("utf-8"))
    h.update(b"\0")
    h.update(rel.encode("utf-8"))
    h.update(b"\0")
    h.update(pointer.encode("utf-8"))
    h.update(b"\0")
    h.update(str(offset).encode("utf-8"))
    h.update(b"\0")
    h.update(source.encode("utf-8"))
    return h.hexdigest()[:16]


def segment_row_id(group_id, segment_index, source):
    h = hashlib.sha1()
    h.update(b"segment")
    h.update(b"\0")
    h.update(group_id.encode("utf-8"))
    h.update(b"\0")
    h.update(str(segment_index).encode("utf-8"))
    h.update(b"\0")
    h.update(source.encode("utf-8"))
    return h.hexdigest()[:16]


def split_text_segments(value):
    parts = re.split(r"(\s*\r?\n\s*)", value)
    segments = []
    for index in range(0, len(parts), 2):
        text = parts[index]
        separator = parts[index + 1] if index + 1 < len(parts) else ""
        segments.append((text, separator))
    if not segments:
        return [(value, "")]
    return segments


def encode_segment_separator(separator):
    return json.dumps(separator, ensure_ascii=False)


def decode_segment_separator(separator):
    if not separator:
        return ""
    return json.loads(separator)


def make_text_rows(base_row, source):
    segments = split_text_segments(source)
    group_id = base_row["id"]
    rows = []
    pending_prefix = ""
    for segment_source, separator in segments:
        if not is_human_text(segment_source):
            # hidden affixes such as "___" typewriter pauses make the whole
            # segment look like an internal name; peel them into the prefix
            affix = re.match(r"^([_\s　]+)(.*)$", segment_source, re.S)
            if affix and is_human_text(affix.group(2)):
                pending_prefix += affix.group(1)
                segment_source = affix.group(2)
            else:
                pending_prefix += segment_source + separator
                continue
        row = dict(base_row)
        row["source"] = segment_source
        row["translation"] = ""
        row["group_id"] = group_id
        row["segment_index"] = str(len(rows))
        row["segment_separator"] = encode_segment_separator(separator)
        row["segment_prefix"] = encode_segment_separator(pending_prefix)
        pending_prefix = ""
        rows.append(row)

    if pending_prefix and rows:
        rows[-1]["segment_separator"] = encode_segment_separator(
            decode_segment_separator(rows[-1].get("segment_separator") or "") + pending_prefix
        )

    segment_count = len(rows)
    for index, row in enumerate(rows):
        if segment_count > 1:
            row["id"] = segment_row_id(group_id, index, row["source"])
        row["segment_index"] = str(index)
        row["segment_count"] = str(segment_count)
    return rows


def segment_sort_key(row):
    return int(row.get("segment_index") or 0)


def compose_segment_source(rows):
    parts = []
    for row in sorted(rows, key=segment_sort_key):
        parts.append(decode_segment_separator(row.get("segment_prefix") or ""))
        parts.append(row["source"])
        parts.append(decode_segment_separator(row.get("segment_separator") or ""))
    return "".join(parts)


def compose_segment_translation(rows):
    parts = []
    for row in sorted(rows, key=segment_sort_key):
        translation = row.get("translation") or ""
        parts.append(decode_segment_separator(row.get("segment_prefix") or ""))
        parts.append(translation if translation.strip() else row["source"])
        parts.append(decode_segment_separator(row.get("segment_separator") or ""))
    return "".join(parts)


def logical_row_key(row):
    return (
        row.get("kind") or "json",
        row.get("json_pointer") or "",
        row.get("raw_offset") or "",
        row.get("encoding") or "",
        row.get("group_id") or row.get("id") or "",
    )


def load_json(path):
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def looks_like_base64_data(key, value):
    if key != "Data" or not isinstance(value, str) or len(value) < 16:
        return False
    try:
        base64.b64decode(value, validate=True)
        return True
    except Exception:
        return False


def get_pointer(data, pointer):
    if pointer == "":
        return data
    node = data
    for part in [pointer_unescape(p) for p in pointer.split("/")[1:]]:
        if isinstance(node, list):
            node = node[int(part)]
        else:
            node = node[part]
    return node


def set_serial_size_for_data_pointer(data, data_pointer, size):
    parent_pointer = data_pointer.rsplit("/", 1)[0]
    parent = get_pointer(data, parent_pointer)
    if isinstance(parent, dict) and "SerialSize" in parent:
        parent["SerialSize"] = size


def try_read_unreal_string(blob, offset):
    if offset + 8 > len(blob):
        return None
    n = struct.unpack_from("<i", blob, offset)[0]
    if n < 0:
        chars = -n
        if chars <= 0 or chars > 2000:
            return None
        end = offset + 4 + chars * 2
        if end > len(blob):
            return None
        raw = blob[offset + 4:end]
        if raw[-2:] != b"\x00\x00":
            return None
        try:
            source = raw[:-2].decode("utf-16le")
        except UnicodeDecodeError:
            return None
        return {
            "offset": offset,
            "end": end,
            "encoding": "utf16le",
            "length_units": chars,
            "source": source,
        }
    if n > 0:
        if n > 4000:
            return None
        end = offset + 4 + n
        if end > len(blob) or blob[end - 1] != 0:
            return None
        raw = blob[offset + 4:end - 1]
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return {
            "offset": offset,
            "end": end,
            "encoding": "utf-8",
            "length_units": n,
            "source": source,
        }
    return None


def try_read_utf16le_null_string(blob, offset):
    if offset <= 0 or blob[offset - 1] != KISMET_EX_UNICODE_STRING_CONST:
        return None
    pos = offset
    max_pos = min(len(blob), offset + 2000)
    while pos + 1 < max_pos:
        if blob[pos:pos + 2] == b"\x00\x00":
            raw = blob[offset:pos]
            if len(raw) % 2 != 0:
                return None
            try:
                source = raw.decode("utf-16le")
            except UnicodeDecodeError:
                return None
            if len(source) > 1000:
                return None
            return {
                "offset": offset,
                "end": pos + 2,
                "encoding": "utf16le-null",
                "length_units": len(source) + 1,
                "source": source,
            }
        pos += 2
    return None


def try_read_raw_string(blob, offset, encoding):
    if encoding == "utf16le-null":
        return try_read_utf16le_null_string(blob, offset)
    return try_read_unreal_string(blob, offset)


def encode_unreal_string(value, encoding):
    if encoding == "utf16le":
        chars = len(value) + 1
        payload = value.encode("utf-16le") + b"\x00\x00"
        return struct.pack("<i", -chars) + payload
    if encoding == "utf16le-null":
        return value.encode("utf-16le") + b"\x00\x00"
    payload = value.encode(encoding) + b"\x00"
    return struct.pack("<i", len(payload)) + payload


def encode_unreal_string_fixed_span(value, encoding, span_len):
    """Encode a non-bytecode FString without changing its serialized span."""
    if encoding == "utf16le":
        payload_len = span_len - 4
        if payload_len <= 0:
            return None
        try:
            payload = value.encode("ascii")
        except UnicodeEncodeError:
            payload = None
        if payload is not None and len(payload) + 1 <= payload_len:
            padding = b" " * (payload_len - len(payload) - 1)
            return struct.pack("<i", payload_len) + payload + padding + b"\x00"

    replacement = encode_unreal_string(value, encoding)
    if len(replacement) == span_len:
        return replacement
    return None


ASCII_REPLACEMENTS = str.maketrans({
    "\u201c": '"',
    "\u201d": '"',
    "\u2018": "'",
    "\u2019": "'",
    "\u2014": "-",
    "\u2013": "-",
    "\u2015": "-",
    "\u2026": "...",
    "\u3000": " ",
    "\uff01": "!",
    "\uff1f": "?",
    "\u3002": ".",
    "\u3001": ",",
    "\u300c": '"',
    "\u300d": '"',
    "\u300e": '"',
    "\u300f": '"',
    "\uff08": "(",
    "\uff09": ")",
    "\uff1a": ":",
    "\uff0f": "/",
    "\uff05": "%",
    "\uff0b": "+",
    "\uff0d": "-",
    "\u2661": "<3",
    "\u2665": "<3",
    "\u2764": "<3",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "―": "-",
    "–": "-",
    "—": "-",
    "…": "...",
    "　": " ",
})


def try_make_ansi_text(value):
    try:
        value.encode("ascii")
    except UnicodeEncodeError:
        return None
    return value


def encode_kismet_string_const(value, payload_len, allow_resize=True, preferred_token=None):
    """Encode a full Kismet string literal.

    The grow-allowed workflow keeps the translator's text intact. The original
    token is preserved where possible: Unicode source literals stay Unicode,
    and ANSI literals are upgraded to Unicode only if the translation needs it.
    If resizing is disabled, fail instead of compacting/truncating the
    translation.
    """
    ascii_text = try_make_ansi_text(value)
    if ascii_text is not None and len(ascii_text) + 1 <= payload_len:
        # Keep the original bytecode layout stable whenever the full ASCII
        # translation fits in the old payload span. Padding must be before the
        # NUL terminator because TextConst fields are laid out back-to-back.
        payload = ascii_text.encode("ascii")
        payload += b" " * (payload_len - len(payload) - 1)
        payload += b"\x00"
        return KISMET_EX_STRING_CONST, payload
    if preferred_token == KISMET_EX_UNICODE_STRING_CONST:
        token = KISMET_EX_UNICODE_STRING_CONST
        payload = value.encode("utf-16le") + b"\x00\x00"
    elif preferred_token == KISMET_EX_STRING_CONST and ascii_text is not None:
        token = KISMET_EX_STRING_CONST
        payload = ascii_text.encode("ascii") + b"\x00"
    elif ascii_text is not None:
        token = KISMET_EX_STRING_CONST
        payload = ascii_text.encode("ascii") + b"\x00"
    else:
        token = KISMET_EX_UNICODE_STRING_CONST
        payload = value.encode("utf-16le") + b"\x00\x00"

    if not allow_resize and len(payload) != payload_len:
        raise RuntimeError(
            "Kismet string literal changed size while resize mode is disabled; "
            "rerun with bytecode resize enabled"
        )
    return token, payload


def find_raw_script_bytecode_candidates(old_blob, changes):
    candidates = []
    for length_offset in range(0, len(old_blob) - 4):
        old_length = struct.unpack_from("<I", old_blob, length_offset)[0]
        if old_length < 32 or old_length > len(old_blob):
            continue

        start = length_offset + 4
        end = start + old_length
        if end > len(old_blob):
            continue

        covered = [
            change for change in changes
            if change["delta"] and start <= change["offset"] and change["end"] <= end
        ]
        if not covered:
            continue

        # In cooked UFunction exports the serialized script TArray is followed
        # by a small trailer. Prefer fields whose range reaches closest to the
        # end of the export, which avoids false positives from bytecode operands
        # and literal data that happen to look like lengths.
        trailer = len(old_blob) - end
        if trailer > 1024:
            continue

        candidates.append({
            "offset": length_offset,
            "old_length": old_length,
            "start": start,
            "end": end,
            "trailer": trailer,
            "covered": covered,
        })

    return candidates


def choose_script_bytecode_candidates(candidates, changes):
    selected = {}
    for change in changes:
        if not change["delta"]:
            continue
        covering = [
            candidate for candidate in candidates
            if candidate["start"] <= change["offset"] and change["end"] <= candidate["end"]
        ]
        if not covering:
            continue
        best = min(covering, key=lambda candidate: (candidate["trailer"], -candidate["old_length"]))
        selected[best["offset"]] = best
    return list(selected.values())


def select_raw_script_bytecode_candidates(old_blob, changes):
    return choose_script_bytecode_candidates(
        find_raw_script_bytecode_candidates(old_blob, changes),
        changes,
    )


def select_script_bytecode_candidates(old_blob, changes, require_structural=True):
    candidates = find_raw_script_bytecode_candidates(old_blob, changes)
    if not require_structural:
        return choose_script_bytecode_candidates(candidates, changes)

    structural_candidates = []
    for candidate in candidates:
        try:
            walker = walk_kismet_candidate(old_blob, candidate)
        except KismetWalkError:
            continue
        if not candidate_recognizes_resized_literals(walker, candidate):
            continue
        structural_candidates.append(candidate)
    structural_candidates = [
        candidate for candidate in structural_candidates
        if not any(
            other is not candidate
            and other["start"] <= candidate["offset"] < other["end"]
            for other in structural_candidates
        )
    ]
    return choose_script_bytecode_candidates(structural_candidates, changes)


def candidate_recognizes_resized_literals(walker, candidate):
    for change in candidate["covered"]:
        if change["offset"] not in walker.string_const_payload_positions:
            return False
    return True


def find_structural_script_bytecode_candidates(blob, min_length=3):
    candidates = []
    for length_offset in range(0, len(blob) - 4):
        old_length = struct.unpack_from("<I", blob, length_offset)[0]
        if old_length < min_length or old_length > len(blob):
            continue

        start = length_offset + 4
        end = start + old_length
        if end > len(blob):
            continue

        trailer = len(blob) - end
        if trailer > 1024:
            continue

        candidate = {
            "offset": length_offset,
            "old_length": old_length,
            "start": start,
            "end": end,
            "trailer": trailer,
            "covered": [],
        }
        try:
            walk_kismet_candidate(blob, candidate)
        except KismetWalkError:
            continue
        candidates.append(candidate)

    candidates = [
        candidate for candidate in candidates
        if not any(
            other is not candidate
            and other["start"] <= candidate["offset"] < other["end"]
            for other in candidates
        )
    ]
    return sorted(candidates, key=lambda candidate: (candidate["trailer"], -candidate["old_length"]))




def shifted_abs(old_abs, covered):
    shift = 0
    for change in covered:
        if change["end"] <= old_abs:
            shift += change["delta"]
    return old_abs + shift


def shifted_script_target(old_target, script_start, covered):
    shift = 0
    for change in covered:
        change_end_rel = change["end"] - script_start
        if change_end_rel <= old_target:
            shift += change.get("icode_delta", change["delta"])
    return old_target + shift


def candidate_icode_length(blob, candidate):
    if candidate["offset"] < 4:
        return None
    value = struct.unpack_from("<I", blob, candidate["offset"] - 4)[0]
    if not (0 < value <= candidate["old_length"]):
        return None

    # StructExport serializes ScriptBytecodeSize immediately before the on-disk
    # script storage size. Some raw byte blobs also contain length-like int32s
    # before nested byte arrays, so only trust this value when known absolute
    # Kismet flow targets all fit inside it. This keeps real cases like
    # WBP_PoseGet (iCode 438, jump target 435) while rejecting false candidates
    # like LVS_NormalEnd_Skit_Skit01 (nearby 256, jump targets around 1702).
    flow_targets = known_kismet_flow_targets(blob, candidate)
    if flow_targets and max(flow_targets) > value:
        return None
    return value


class KismetWalkError(RuntimeError):
    pass


class KismetStructuralWalker:
    """Parse Kismet bytecode by opcode layout and record real flow operands.

    Disk offsets and iCode offsets diverge for serialized pointer operands. UE
    jump targets use iCode offsets, while this patcher edits raw disk bytes, so
    the walker tracks both coordinate spaces.
    """

    END_TOKENS = {0x15, 0x16, 0x30, 0x32, 0x3A, 0x3C, 0x3E, 0x40, 0x53}
    NO_OPERAND_TOKENS = {
        0x0B, 0x15, 0x16, 0x17, 0x25, 0x26, 0x27, 0x28, 0x2A, 0x2D,
        0x30, 0x32, 0x3A, 0x3C, 0x3E, 0x40, 0x4A, 0x4D, 0x50,
        0x53, 0x5A, 0x5E, 0x70, 0x71,
    }

    def __init__(self, blob, start, end, prop_pointer_mode="fieldpath", lwc=True):
        self.blob = blob
        self.start = start
        self.end = end
        self.prop_pointer_mode = prop_pointer_mode
        self.lwc = lwc
        self.jump_operands = []
        self.call_operands = []
        self.string_const_payload_positions = set()
        self.disk_to_icode = {}

    def fail(self, pos, message):
        raise KismetWalkError(f"{message} at disk {pos} (rel {pos - self.start})")

    def require(self, pos, size):
        if pos + size > self.end:
            self.fail(pos, f"short read of {size} bytes")

    def u8(self, pos):
        self.require(pos, 1)
        return self.blob[pos]

    def u16(self, pos):
        self.require(pos, 2)
        return struct.unpack_from("<H", self.blob, pos)[0]

    def u32(self, pos):
        self.require(pos, 4)
        return struct.unpack_from("<I", self.blob, pos)[0]

    def i32(self, pos):
        self.require(pos, 4)
        return struct.unpack_from("<i", self.blob, pos)[0]

    def skip(self, pos, icode, disk_size, icode_size=None):
        self.require(pos, disk_size)
        return pos + disk_size, icode + (disk_size if icode_size is None else icode_size)

    def skip_name(self, pos, icode):
        return self.skip(pos, icode, 8, 12)

    def skip_pointer(self, pos, icode):
        return self.skip(pos, icode, 4, 8)

    def skip_prop_pointer(self, pos, icode):
        if self.prop_pointer_mode == "fieldpath":
            count = self.i32(pos)
            if count < 0 or count > 64:
                self.fail(pos, f"invalid FFieldPath entry count {count}")
            disk_size = 4 + (count * 8) + 4
            return self.skip(pos, icode, disk_size, 8)
        if self.prop_pointer_mode == "ptr8":
            return self.skip(pos, icode, 8, 8)
        return self.skip(pos, icode, 4, 8)

    def read_string(self, pos, icode):
        nul = self.blob.find(b"\x00", pos, self.end)
        if nul < 0:
            self.fail(pos, "unterminated EX_StringConst")
        return nul + 1, icode + (nul + 1 - pos)

    def read_unicode_string(self, pos, icode):
        scan = pos
        while scan + 1 < self.end:
            if self.blob[scan:scan + 2] == b"\x00\x00":
                return scan + 2, icode + (scan + 2 - pos)
            scan += 2
        self.fail(pos, "unterminated EX_UnicodeStringConst")

    def record_jump(self, pos, icode, kind):
        old_target = self.u32(pos)
        self.jump_operands.append({
            "disk_operand": pos,
            "icode_operand": icode,
            "target": old_target,
            "kind": kind,
        })
        return self.skip(pos, icode, 4, 4)

    def step_until(self, pos, icode, end_token):
        while True:
            if pos >= self.end:
                self.fail(pos, f"missing terminator 0x{end_token:02x}")
            if self.blob[pos] == end_token:
                return self.skip(pos, icode, 1, 1)
            pos, icode = self.step(pos, icode)

    def step(self, pos, icode):
        op_pos = pos
        op = self.u8(pos)
        self.disk_to_icode[op_pos] = icode
        pos, icode = self.skip(pos, icode, 1, 1)

        if op in {0x00, 0x01, 0x02, 0x48, 0x6C}:  # variable property pointer
            return self.skip_prop_pointer(pos, icode)
        if op == 0x04:  # EX_Return
            return self.step(pos, icode)
        if op == 0x06:
            return self.record_jump(pos, icode, "jump")
        if op == 0x07:
            pos, icode = self.record_jump(pos, icode, "jump_if_not")
            return self.step(pos, icode)
        if op == 0x09:  # EX_Assert
            pos, icode = self.skip(pos, icode, 3, 3)
            return self.step(pos, icode)
        if op == 0x0C:  # EX_NothingInt32
            return self.skip(pos, icode, 4, 4)
        if op == 0x0F:  # EX_Let
            pos, icode = self.skip_prop_pointer(pos, icode)
            pos, icode = self.step(pos, icode)
            return self.step(pos, icode)
        if op == 0x11:  # EX_BitFieldConst
            return self.skip_prop_pointer(pos, icode)
        if op == 0x12:  # EX_ClassContext
            pos, icode = self.step(pos, icode)
            pos, icode = self.record_jump(pos, icode, "context_skip")
            pos, icode = self.skip_prop_pointer(pos, icode)
            return self.step(pos, icode)
        if op in {0x13, 0x2E, 0x52, 0x54, 0x55}:  # cast + expression
            pos, icode = self.skip_pointer(pos, icode)
            return self.step(pos, icode)
        if op == 0x14:  # EX_LetBool
            pos, icode = self.step(pos, icode)
            return self.step(pos, icode)
        if op == 0x18:
            pos, icode = self.record_jump(pos, icode, "skip")
            return self.step(pos, icode)
        if op in {0x19, 0x1A}:  # EX_Context / EX_Context_FailSilent
            pos, icode = self.step(pos, icode)
            pos, icode = self.record_jump(pos, icode, "context_skip")
            pos, icode = self.skip_prop_pointer(pos, icode)
            return self.step(pos, icode)
        if op in {0x1B, 0x45}:  # virtual function name + params
            name_index = self.i32(pos)
            pos, icode = self.skip_name(pos, icode)
            entry_int_disk = None
            entry_value = None
            if pos < self.end and self.u8(pos) == 0x1D:
                self.require(pos + 1, 4)
                entry_int_disk = pos + 1
                entry_value = self.i32(pos + 1)
            self.call_operands.append({
                "kind": "virtual",
                "disk_opcode": op_pos,
                "name_index": name_index,
                "entry_int_disk": entry_int_disk,
                "entry_value": entry_value,
            })
            return self.step_until(pos, icode, 0x16)
        if op in {0x1C, 0x46, 0x68}:  # final function / local final / math
            stack_node = self.i32(pos)
            pos, icode = self.skip_pointer(pos, icode)
            entry_int_disk = None
            entry_value = None
            if pos < self.end and self.u8(pos) == 0x1D:
                self.require(pos + 1, 4)
                entry_int_disk = pos + 1
                entry_value = self.i32(pos + 1)
            self.call_operands.append({
                "kind": "final",
                "disk_opcode": op_pos,
                "stack_node": stack_node,
                "entry_int_disk": entry_int_disk,
                "entry_value": entry_value,
            })
            return self.step_until(pos, icode, 0x16)
        if op in {0x1D, 0x1E}:  # int32 / float
            return self.skip(pos, icode, 4, 4)
        if op == 0x1F:
            self.string_const_payload_positions.add(pos)
            return self.read_string(pos, icode)
        if op in {0x20, 0x33}:  # object/property const
            return self.skip_pointer(pos, icode)
        if op == 0x21:
            return self.skip_name(pos, icode)
        if op in {0x22, 0x23}:  # rotator/vector
            return self.skip(pos, icode, 24 if self.lwc else 12, 24 if self.lwc else 12)
        if op == 0x24:
            return self.skip(pos, icode, 1, 1)
        if op == 0x29:
            text_type = self.u8(pos)
            pos, icode = self.skip(pos, icode, 1, 1)
            if text_type == 0:
                return pos, icode
            if text_type == 1:
                pos, icode = self.step(pos, icode)
                pos, icode = self.step(pos, icode)
                return self.step(pos, icode)
            if text_type in {2, 3}:
                return self.step(pos, icode)
            if text_type == 4:
                pos, icode = self.skip_pointer(pos, icode)
                pos, icode = self.step(pos, icode)
                return self.step(pos, icode)
            self.fail(pos - 1, f"unknown EX_TextConst literal type {text_type}")
        if op == 0x2B:
            return self.skip(pos, icode, 80 if self.lwc else 40, 80 if self.lwc else 40)
        if op == 0x2C:
            return self.skip(pos, icode, 1, 1)
        if op == 0x2F:  # EX_StructConst
            pos, icode = self.skip_pointer(pos, icode)
            pos, icode = self.skip(pos, icode, 4, 4)
            return self.step_until(pos, icode, 0x30)
        if op == 0x31:  # EX_SetArray
            pos, icode = self.step(pos, icode)
            return self.step_until(pos, icode, 0x32)
        if op == 0x34:
            self.string_const_payload_positions.add(pos)
            return self.read_unicode_string(pos, icode)
        if op in {0x35, 0x36, 0x37}:  # int64 / uint64 / double
            return self.skip(pos, icode, 8, 8)
        if op == 0x38:
            pos, icode = self.skip(pos, icode, 1, 1)
            return self.step(pos, icode)
        if op in {0x39, 0x3B}:  # SetSet / SetMap
            pos, icode = self.step(pos, icode)
            pos, icode = self.skip(pos, icode, 4, 4)
            return self.step_until(pos, icode, 0x3A if op == 0x39 else 0x3C)
        if op == 0x3D:  # SetConst
            pos, icode = self.skip_prop_pointer(pos, icode)
            pos, icode = self.skip(pos, icode, 4, 4)
            return self.step_until(pos, icode, 0x3E)
        if op == 0x3F:  # MapConst
            pos, icode = self.skip_prop_pointer(pos, icode)
            pos, icode = self.skip_prop_pointer(pos, icode)
            pos, icode = self.skip(pos, icode, 4, 4)
            return self.step_until(pos, icode, 0x40)
        if op == 0x41:
            return self.skip(pos, icode, 12, 12)
        if op == 0x42:
            pos, icode = self.skip_prop_pointer(pos, icode)
            return self.step(pos, icode)
        if op in {0x43, 0x44}:  # Let delegate variants
            pos, icode = self.step(pos, icode)
            return self.step(pos, icode)
        if op == 0x4B:  # InstanceDelegate
            return self.skip_name(pos, icode)
        if op == 0x4C:
            return self.record_jump(pos, icode, "push_flow")
        if op == 0x4E:
            return self.step(pos, icode)
        if op == 0x4F:
            return self.step(pos, icode)
        if op == 0x51:
            return self.step(pos, icode)
        if op == 0x5B:
            return self.record_jump(pos, icode, "skip_offset_const")
        if op in {0x5C, 0x5D, 0x62}:  # multicast delegate operations
            pos, icode = self.step(pos, icode)
            return self.step(pos, icode)
        if op in {0x5F, 0x60}:  # LetObj / LetWeakObjPtr
            pos, icode = self.step(pos, icode)
            return self.step(pos, icode)
        if op == 0x61:  # BindDelegate
            pos, icode = self.skip_name(pos, icode)
            pos, icode = self.step(pos, icode)
            return self.step(pos, icode)
        if op == 0x63:  # CallMulticastDelegate
            pos, icode = self.skip_pointer(pos, icode)
            pos, icode = self.step_until(pos, icode, 0x16)
            return self.step(pos, icode)
        if op == 0x64:  # LetValueOnPersistentFrame
            pos, icode = self.skip_prop_pointer(pos, icode)
            return self.step(pos, icode)
        if op == 0x65:  # ArrayConst
            pos, icode = self.skip_prop_pointer(pos, icode)
            pos, icode = self.skip(pos, icode, 4, 4)
            return self.step_until(pos, icode, 0x66)
        if op == 0x67:  # SoftObjectConst
            if self.u8(pos) not in {0x1F, 0x34}:
                self.fail(pos, "expected soft object path string")
            pos, icode = self.step(pos, icode)
            if self.u8(pos) not in {0x27, 0x28}:
                self.fail(pos, "expected soft object const load flag")
            pos, icode = self.step(pos, icode)
            if self.u8(pos) not in {0x1F, 0x34}:
                self.fail(pos, "expected soft object subpath string")
            return self.step(pos, icode)
        if op == 0x69:
            cases = self.u16(pos)
            pos, icode = self.skip(pos, icode, 2, 2)
            pos, icode = self.record_jump(pos, icode, "switch_end")
            pos, icode = self.step(pos, icode)
            for _ in range(cases):
                pos, icode = self.step(pos, icode)
                pos, icode = self.record_jump(pos, icode, "switch_next")
                pos, icode = self.step(pos, icode)
            return self.step(pos, icode)
        if op == 0x6A:
            return self.skip(pos, icode, 1, 1)
        if op == 0x6B:
            return self.step(pos, icode)
        if op == 0x6D:
            return self.skip_prop_pointer(pos, icode)
        if op == 0x72:
            return self.step(pos, icode)
        if op in self.NO_OPERAND_TOKENS:
            return pos, icode
        self.fail(op_pos, f"unknown opcode 0x{op:02x}")

    def walk(self):
        pos = self.start
        icode = 0
        while pos < self.end:
            pos, icode = self.step(pos, icode)
            if self.blob[pos - 1] == 0x53:
                if any(self.blob[pos:self.end]):
                    self.fail(pos, "nonzero bytes after EX_EndOfScript")
                self.final_disk = pos
                self.final_icode = icode
                return pos, icode
        self.fail(pos, "missing EX_EndOfScript")


def walk_kismet_candidate(blob, candidate):
    errors = []
    for prop_mode in ("fieldpath", "ptr4", "ptr8"):
        walker = KismetStructuralWalker(blob, candidate["start"], candidate["end"], prop_pointer_mode=prop_mode)
        try:
            walker.walk()
            return walker
        except KismetWalkError as exc:
            errors.append(f"{prop_mode}: {exc}")
    raise KismetWalkError("; ".join(errors))


def kismet_literal_spans(blob, start, end):
    spans = []
    pos = start
    while pos < end:
        token = blob[pos]
        if token == KISMET_EX_STRING_CONST:
            nul = blob.find(b"\x00", pos + 1, end)
            if nul != -1:
                spans.append((pos, nul + 1))
                pos = nul + 1
                continue
        elif token == KISMET_EX_UNICODE_STRING_CONST:
            scan = pos + 1
            while scan + 1 < end:
                if blob[scan:scan + 2] == b"\x00\x00":
                    spans.append((pos, scan + 2))
                    pos = scan + 2
                    break
                scan += 2
            else:
                pos += 1
                continue
            continue
        pos += 1
    return spans


def containing_span(pos, spans):
    for start, end in spans:
        if start <= pos < end:
            return start, end
    return None


def known_kismet_flow_targets(blob, candidate):
    try:
        walker = walk_kismet_candidate(blob, candidate)
    except KismetWalkError:
        return []
    targets = []
    for operand in walker.jump_operands:
        kind = operand["kind"]
        if kind in KISMET_ABSOLUTE_TARGET_KINDS:
            targets.append(operand["target"])
        elif kind in KISMET_RELATIVE_SKIP_KINDS:
            targets.append(operand["icode_operand"] + 4 + operand["target"])
    return targets


def relative_skip_delta(operand, icode_change_bounds):
    skip_start_icode = operand["icode_operand"] + 4
    skip_end_icode = skip_start_icode + operand["target"]
    delta_within = 0
    for old_icode_end, delta in sorted(icode_change_bounds):
        if skip_start_icode < old_icode_end <= skip_end_icode:
            delta_within += delta
    return delta_within


def context_skip_delta(operand, icode_change_bounds):
    # EX_Context body starts after the 4-byte skip operand AND the RValuePointer
    # slot; the operand value is the body's iCode size.
    body_start_icode = operand["icode_operand"] + 4 + KISMET_CONTEXT_RVALUE_ICODE_SIZE
    body_end_icode = body_start_icode + operand["target"]
    delta_within = 0
    for old_icode_end, delta in sorted(icode_change_bounds):
        if body_start_icode < old_icode_end <= body_end_icode:
            delta_within += delta
    return delta_within


def kismet_icode_change_bounds(walker, candidate, covered):
    bounds = []
    sorted_opcode_positions = sorted(walker.disk_to_icode)
    for change in covered:
        change_end = change["end"]
        old_icode_end = None
        for disk_pos in sorted_opcode_positions:
            if disk_pos >= change_end:
                old_icode_end = walker.disk_to_icode[disk_pos]
                break
        if old_icode_end is None:
            old_icode_end = change_end - candidate["start"]
        bounds.append((old_icode_end, change.get("icode_delta", change["delta"])))
    return bounds


def shifted_icode_target(old_target, icode_change_bounds):
    shift = 0
    for old_icode_end, delta in sorted(icode_change_bounds):
        if old_icode_end <= old_target:
            shift += delta
    return old_target + shift


def validate_post_edit_kismet(blob, candidate):
    try:
        walker = walk_kismet_candidate(blob, candidate)
    except KismetWalkError as exc:
        raise RuntimeError(f"post-edit Kismet validation failed: {exc}") from exc

    opcode_boundaries = set(walker.disk_to_icode.values())
    final_icode = getattr(walker, "final_icode", None)
    if final_icode is not None:
        opcode_boundaries.add(final_icode)

    for operand in walker.jump_operands:
        kind = operand["kind"]
        if kind in KISMET_ABSOLUTE_TARGET_KINDS:
            landing = operand["target"]
        elif kind in KISMET_RELATIVE_SKIP_KINDS:
            landing = operand["icode_operand"] + 4 + operand["target"]
        elif kind in KISMET_CONTEXT_SKIP_KINDS:
            landing = operand["icode_operand"] + 4 + KISMET_CONTEXT_RVALUE_ICODE_SIZE + operand["target"]
        else:
            continue
        if landing not in opcode_boundaries:
            raise RuntimeError(
                f"post-edit Kismet validation failed: {kind} operand at iCode "
                f"{operand['icode_operand']} lands at {landing}, not an opcode boundary"
            )
    return walker


def adjust_kismet_flow_targets(old_blob, new_blob, changes):
    """Adjust genuine Kismet iCode flow targets after bytecode string growth."""
    changed_fields = []
    for candidate in select_script_bytecode_candidates(old_blob, changes):
        covered = candidate["covered"]
        try:
            walker = walk_kismet_candidate(old_blob, candidate)
        except KismetWalkError as exc:
            raise RuntimeError(
                "Structural Kismet walker failed; refusing unsafe bytecode target rewrite: "
                f"{exc}"
            ) from exc

        icode_change_bounds = kismet_icode_change_bounds(walker, candidate, covered)

        for operand in walker.jump_operands:
            kind = operand["kind"]
            if kind in KISMET_LITERAL_KINDS:
                continue
            old_target = operand["target"]
            if kind in KISMET_ABSOLUTE_TARGET_KINDS:
                new_target = shifted_icode_target(old_target, icode_change_bounds)
            elif kind in KISMET_RELATIVE_SKIP_KINDS:
                new_target = old_target + relative_skip_delta(operand, icode_change_bounds)
            elif kind in KISMET_CONTEXT_SKIP_KINDS:
                new_target = old_target + context_skip_delta(operand, icode_change_bounds)
            else:
                continue
            if new_target == old_target:
                continue
            new_operand_pos = shifted_abs(operand["disk_operand"], covered)
            struct.pack_into("<I", new_blob, new_operand_pos, new_target)
            changed_fields.append((
                new_operand_pos,
                old_target,
                new_target,
                operand["kind"],
            ))
        disk_delta = sum(change["delta"] for change in covered)
        new_candidate = dict(candidate)
        new_candidate["old_length"] = candidate["old_length"] + disk_delta
        new_candidate["end"] = candidate["start"] + new_candidate["old_length"]
        validate_post_edit_kismet(new_blob, new_candidate)
    return changed_fields


def adjust_event_entrypoint_stubs(data, data_pointer, old_blob, changes):
    """Update event wrapper functions that jump into a resized ubergraph.

    Level sequence event functions often compile down to:
        EX_LocalFinalFunction ExecuteUbergraph(IntConst EntryPoint)
    If a localized FText literal earlier in the ubergraph grows, those
    EntryPoint values must move along with the bytecode or the next sequence
    event lands in the middle of an instruction.
    """
    match = re.fullmatch(r"/Exports/(\d+)/Data", data_pointer)
    if not match or "Exports" not in data:
        return []

    main_export_index = int(match.group(1))
    main_stack_node = main_export_index + 1  # FPackageIndex export references are 1-based.
    main_export = data["Exports"][main_export_index]
    main_name = main_export.get("ObjectName") if isinstance(main_export, dict) else None
    name_indexes = set()
    if main_name and isinstance(data.get("NameMap"), list):
        for index, name in enumerate(data["NameMap"]):
            if name == main_name:
                name_indexes.add(index)
    selected = select_script_bytecode_candidates(old_blob, changes)
    if not selected:
        return []

    changed_fields = []
    for candidate in selected:
        old_icode_limit = candidate_icode_length(old_blob, candidate) or candidate["old_length"]
        covered = candidate["covered"]
        try:
            main_walker = walk_kismet_candidate(old_blob, candidate)
        except KismetWalkError as exc:
            raise RuntimeError(
                "Structural Kismet walker failed; refusing unsafe event entrypoint rewrite: "
                f"{exc}"
            ) from exc
        icode_change_bounds = kismet_icode_change_bounds(main_walker, candidate, covered)
        for export_index, export in enumerate(data["Exports"]):
            if export_index == main_export_index or not isinstance(export, dict):
                continue
            raw = export.get("Data")
            if not isinstance(raw, str) or len(raw) < 16:
                continue
            try:
                blob = bytearray(base64.b64decode(raw, validate=True))
            except Exception:
                continue

            changed = False
            for stub_candidate in find_structural_script_bytecode_candidates(blob):
                try:
                    walker = walk_kismet_candidate(blob, stub_candidate)
                except KismetWalkError:
                    continue

                for call in walker.call_operands:
                    entry_int_disk = call.get("entry_int_disk")
                    if entry_int_disk is None:
                        continue
                    if call["kind"] == "final":
                        if call.get("stack_node") != main_stack_node:
                            continue
                    elif call["kind"] == "virtual":
                        if call.get("name_index") not in name_indexes:
                            continue
                    else:
                        continue

                    old_entrypoint = call["entry_value"]
                    if old_entrypoint < 0 or old_entrypoint > old_icode_limit:
                        continue
                    new_entrypoint = shifted_icode_target(old_entrypoint, icode_change_bounds)
                    if new_entrypoint == old_entrypoint:
                        continue
                    struct.pack_into("<i", blob, entry_int_disk, new_entrypoint)
                    changed = True
                    changed_fields.append((
                        f"/Exports/{export_index}/Data",
                        entry_int_disk,
                        old_entrypoint,
                        new_entrypoint,
                        "entrypoint",
                    ))

            if changed:
                export["Data"] = base64.b64encode(bytes(blob)).decode("ascii")

    return changed_fields


def adjust_script_bytecode_lengths(old_blob, new_blob, changes):
    """Update UFunction script bytecode sizes around resized Kismet literals.

    UAssetGUI exposes function bytecode as opaque export Data. Text literals in
    that bytecode can be resized safely only if the surrounding script byte
    sizes are adjusted too; otherwise UE's serializer stops before the resized
    export ends and crashes with a serial-size mismatch.
    """
    changed_fields = []
    changed_offsets = [change["offset"] for change in changes if change["delta"]]
    if not changed_offsets:
        return changed_fields

    for candidate in select_script_bytecode_candidates(old_blob, changes):
        disk_delta = sum(
            change["delta"] for change in changes
            if candidate["start"] <= change["offset"] and change["end"] <= candidate["end"]
        )
        icode_delta = sum(
            change.get("icode_delta", change["delta"]) for change in changes
            if candidate["start"] <= change["offset"] and change["end"] <= candidate["end"]
        )
        if disk_delta == 0:
            continue
        new_length = candidate["old_length"] + disk_delta
        if new_length <= 0:
            raise RuntimeError(f"Invalid resized bytecode length at offset {candidate['offset']}")
        old_icode_length = candidate_icode_length(old_blob, candidate)
        if old_icode_length is not None and icode_delta:
            icode_offset = candidate["offset"] - 4
            new_icode_length = old_icode_length + icode_delta
            if new_icode_length <= 0:
                raise RuntimeError(f"Invalid resized bytecode iCode length at offset {icode_offset}")
            struct.pack_into("<I", new_blob, icode_offset, new_icode_length)
            changed_fields.append((icode_offset, old_icode_length, new_icode_length, "icode"))
        struct.pack_into("<I", new_blob, candidate["offset"], new_length)
        changed_fields.append((candidate["offset"], candidate["old_length"], new_length, "disk"))

    return changed_fields


def iter_raw_strings(node, pointer=""):
    if isinstance(node, dict):
        for key, value in node.items():
            child = pointer + "/" + pointer_escape(key)
            if looks_like_base64_data(key, value):
                blob = base64.b64decode(value)
                matches = []
                for offset in range(max(0, len(blob) - 7)):
                    match = try_read_unreal_string(blob, offset)
                    if match and is_raw_display_text(match["source"]):
                        matches.append(match)
                for offset in range(1, len(blob) - 2):
                    if blob[offset - 1] != KISMET_EX_UNICODE_STRING_CONST:
                        continue
                    match = try_read_utf16le_null_string(blob, offset)
                    if match and is_human_text(match["source"]) and KANA_OR_FULLWIDTH_RE.search(match["source"]):
                        matches.append(match)
                matches.sort(key=lambda m: m["offset"])
                last_end = -1
                for match in matches:
                    if match["offset"] < last_end:
                        continue
                    last_end = match["end"]
                    yield child, match
            else:
                yield from iter_raw_strings(value, child)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from iter_raw_strings(value, pointer + "/" + str(index))


def extract(json_dir, out_csv):
    json_dir = Path(json_dir)
    rows = []
    for path in sorted(json_dir.rglob("*.json")):
        rel = path.relative_to(json_dir).as_posix()
        data = load_json(path)
        for pointer, key, value in iter_strings(data):
            if "/NameMap/" in pointer:
                # NameMap entries are FName identifiers; renaming them corrupts the asset
                continue
            if should_extract(key, value):
                base_row = {
                    "id": row_id(rel, pointer, value),
                    "json_file": rel,
                    "kind": "json",
                    "json_pointer": pointer,
                    "raw_offset": "",
                    "encoding": "json",
                    "source": value,
                    "translation": "",
                    "key": key,
                }
                rows.extend(make_text_rows(base_row, value))
        for pointer, match in iter_raw_strings(data):
            source = match["source"]
            base_row = {
                "id": row_id(rel, pointer, source, "raw", match["offset"]),
                "json_file": rel,
                "kind": "raw",
                "json_pointer": pointer,
                "raw_offset": str(match["offset"]),
                "encoding": match["encoding"],
                "source": source,
                "translation": "",
                "key": "RawExport.Data",
            }
            rows.extend(make_text_rows(base_row, source))

    out_csv = Path(out_csv)
    previous_translations = {}
    previous_segment_translations = {}
    previous_whole_translations = {}
    if out_csv.exists():
        with out_csv.open("r", encoding="utf-8-sig", newline="") as f:
            for old_row in csv.DictReader(f):
                translation = old_row.get("translation") or ""
                if translation:
                    old_id = old_row.get("id")
                    group_id = old_row.get("group_id") or old_id
                    segment_index = old_row.get("segment_index") or "0"
                    segment_count = int(old_row.get("segment_count") or 1)
                    previous_translations[old_id] = translation
                    previous_segment_translations[(group_id, segment_index)] = translation
                    if segment_count == 1:
                        previous_whole_translations[group_id] = translation

    for row in rows:
        if row["id"] in previous_translations:
            row["translation"] = previous_translations[row["id"]]
            continue
        segment_key = (row.get("group_id") or row["id"], row.get("segment_index") or "0")
        if segment_key in previous_segment_translations:
            row["translation"] = previous_segment_translations[segment_key]
            continue
        group_id = row.get("group_id") or row["id"]
        if int(row.get("segment_count") or 1) > 1 and group_id in previous_whole_translations:
            translated_segments = split_text_segments(previous_whole_translations[group_id])
            index = int(row.get("segment_index") or 0)
            if len(translated_segments) == int(row.get("segment_count") or 1) and index < len(translated_segments):
                row["translation"] = translated_segments[index][0]

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "id", "json_file", "kind", "json_pointer", "raw_offset", "encoding",
                "source", "translation", "key", "group_id", "segment_index",
                "segment_count", "segment_prefix", "segment_separator",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"extracted {len(rows)} strings")


def normalize_plain_text(value):
    return re.sub(r"\s+", " ", value.strip())


def is_action_or_label(value):
    stripped = value.strip()
    if stripped in ACTION_LABELS:
        return True
    if stripped in UI_TEXT_EXACT:
        return True
    if any(phrase in stripped for phrase in UI_TEXT_PHRASES):
        return True
    if not re.search(r"[。！？!?\u2026「」『』（）()]|\.{2,}|\r|\n", stripped):
        if re.search(r"(シーン|ゲーム|メモ|記録|手記|置き手紙|パスワード|報酬|オーダー|チュートリアル|セクション|について|プレゼント|より)$", stripped):
            return True
    if re.search(r"(Floor\d|Stage\d|取得|獲得|画面|練習|設定|戻る|次へ|購入)", stripped, re.IGNORECASE):
        return True
    return False


def is_dialogue_like(value):
    stripped = value.strip()
    if is_action_or_label(stripped):
        return False
    if re.search(r"[。！？!?…♡♥♪「」『』（）()]|\.{2,}|ーー|――|\r|\n", stripped):
        return True
    return len(stripped) >= 9 and not is_action_or_label(stripped)


def is_dialogue_candidate(row):
    source = row["source"]
    rel = row["json_file"].replace("\\", "/")
    filename = rel.rsplit("/", 1)[-1]
    if row.get("kind") != "raw":
        return False
    if "ゲームマスター" in source:
        return True
    if "/Datatables/VoiceLine/" in rel:
        return not is_action_or_label(source)
    if "/LevelSequence/" in rel and is_dialogue_like(source):
        return True
    if "/Map/" in rel and is_dialogue_like(source):
        return True
    if "/Blueprint/DataAsset/" in rel and is_dialogue_like(source):
        return True
    if filename in SPEAKER_BY_FILE:
        return not is_action_or_label(source)
    if "/DataTable/" in rel and is_dialogue_like(source):
        return True
    return False


def is_ui_candidate(row):
    return not is_dialogue_candidate(row)


def speaker_tag(row):
    source = row["source"]
    rel = row["json_file"].replace("\\", "/")
    stripped = source.strip()
    narration_prefixes = ("---", "ーー", "――", "—", "・・・", "…")
    voice_match = re.search(r"/VoiceLine/([^/]+)/", rel)
    if voice_match:
        return SPEAKER_BY_VOICE_FOLDER.get(voice_match.group(1), voice_match.group(1))
    filename = rel.rsplit("/", 1)[-1]
    if filename in SPEAKER_BY_FILE:
        return SPEAKER_BY_FILE[filename]
    if any(phrase in stripped for phrase in MARY_PHRASES):
        return "Mary"
    if any(phrase in stripped for phrase in MOB_PHRASES):
        return "Mob"
    if any(phrase in stripped for phrase in IVE_PHRASES):
        return "Ive"
    if any(phrase in stripped for phrase in GAME_MASTER_PHRASES):
        return "GameMaster"
    if "OpeningNarration" in rel or stripped.startswith(narration_prefixes):
        return "Narration"
    if re.search(r"(メモ|記録|ログ|番号|備考|コード|ステータス|条件)", stripped):
        return "Narration"
    if "Mobuko" in rel:
        return "Mobuko"
    if "/R18_IkiSaw/" in rel:
        return "Ive"
    return "Narration"


def write_plain(rows, plain_path):
    plain_rows = [row for row in rows if is_dialogue_candidate(row)]
    plain_path = Path(plain_path)
    plain_path.parent.mkdir(parents=True, exist_ok=True)
    with plain_path.open("w", encoding="utf-8-sig", newline="\n") as f:
        for row in plain_rows:
            f.write(f"[{speaker_tag(row)}]: {normalize_plain_text(row['source'])}\n")
    print(f"wrote {len(plain_rows)} dialogue plain text lines")


def write_ui_plain(rows, plain_path):
    plain_rows = [row for row in rows if is_ui_candidate(row)]
    plain_path = Path(plain_path)
    plain_path.parent.mkdir(parents=True, exist_ok=True)
    with plain_path.open("w", encoding="utf-8-sig", newline="\n") as f:
        for row in plain_rows:
            f.write(f"{normalize_plain_text(row['source'])}\n")
    print(f"wrote {len(plain_rows)} ui/other plain text lines")


def sort_context_rows(rows):
    def key(row):
        raw_offset = row.get("raw_offset") or ""
        try:
            raw_offset_key = int(raw_offset)
        except ValueError:
            raw_offset_key = -1
        try:
            segment_index = int(row.get("segment_index") or 0)
        except ValueError:
            segment_index = 0
        return (row.get("json_file") or "", row.get("json_pointer") or "", raw_offset_key, segment_index)

    return sorted(rows, key=key)


def write_all_context(rows, out_path):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        f.write("# Ikisaw combined text export for AI review.\n")
        f.write("# This file intentionally has no speaker labels.\n")
        f.write("# Columns: id, bucket, json_file, raw_offset, segment_index, segment_count, text\n")
        f.write("# Keep ids unchanged if you ask an AI to return speaker or translation decisions.\n")
        writer = csv.writer(f, delimiter="\t", lineterminator="\n")
        writer.writerow(["id", "bucket", "json_file", "raw_offset", "segment_index", "segment_count", "text"])
        for row in sort_context_rows(rows):
            writer.writerow([
                row["id"],
                "dialogue" if is_dialogue_candidate(row) else "ui",
                row["json_file"],
                row.get("raw_offset") or "",
                row.get("segment_index") or "0",
                row.get("segment_count") or "1",
                normalize_plain_text(row["source"]),
            ])
    print(f"wrote {len(rows)} combined context text rows")


def set_pointer(data, pointer, value):
    parts = [pointer_unescape(p) for p in pointer.split("/")[1:]]
    node = data
    for part in parts[:-1]:
        if isinstance(node, list):
            node = node[int(part)]
        else:
            node = node[part]
    last = parts[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


def load_id_file(path):
    ids = set()
    if not path.exists():
        return ids
    with path.open("r", encoding="utf-8-sig") as f:
        for line in f:
            value = line.split("#", 1)[0].strip()
            if value:
                ids.add(value)
    return ids


def apply_translations(json_dir, csv_path, out_dir, resize_overflow_bytecode=True):
    json_dir = Path(json_dir)
    csv_path = Path(csv_path)
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(json_dir, out_dir)

    grouped_rows = {}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            grouped_rows.setdefault((row["json_file"], logical_row_key(row)), []).append(row)

    by_file = {}
    for (json_file, _group_key), group_rows in grouped_rows.items():
        if any((row.get("translation") or "").strip() for row in group_rows):
            by_file.setdefault(json_file, []).extend(group_rows)

    changed = []
    for rel, rows in sorted(by_file.items()):
        path = out_dir / rel
        data = load_json(path)
        json_groups = {}
        for row in [r for r in rows if (r.get("kind") or "json") == "json"]:
            json_groups.setdefault(logical_row_key(row), []).append(row)
        for group_rows in json_groups.values():
            row = group_rows[0]
            current = get_pointer(data, row["json_pointer"])
            source = compose_segment_source(group_rows)
            if current != source:
                raise RuntimeError(f"JSON source mismatch in {rel} at {row['json_pointer']}")
            set_pointer(data, row["json_pointer"], compose_segment_translation(group_rows))

        raw_rows_by_pointer = {}
        for row in [r for r in rows if (r.get("kind") or "json") == "raw"]:
            raw_rows_by_pointer.setdefault(row["json_pointer"], []).append(row)

        for pointer, raw_rows in raw_rows_by_pointer.items():
            old_blob = base64.b64decode(get_pointer(data, pointer))
            blob = bytearray(old_blob)
            raw_changes = []
            raw_groups = {}
            for row in raw_rows:
                raw_groups.setdefault(logical_row_key(row), []).append(row)
            for group_rows in sorted(raw_groups.values(), key=lambda rs: int(rs[0]["raw_offset"]), reverse=True):
                row = group_rows[0]
                offset = int(row["raw_offset"])
                current = try_read_raw_string(blob, offset, row["encoding"])
                source = compose_segment_source(group_rows)
                if not current or current["source"] != source:
                    raise RuntimeError(f"Raw source mismatch in {rel} at offset {offset}")
                if not any(is_human_text(r["source"]) for r in group_rows):
                    # judge on the visible text only: hidden segment prefixes such
                    # as "___" would otherwise make real dialogue look internal
                    continue
                translation = compose_segment_translation(group_rows)
                if row["encoding"] == "utf16le-null":
                    token, replacement = encode_kismet_string_const(
                        translation,
                        current["end"] - offset,
                        allow_resize=resize_overflow_bytecode,
                        preferred_token=blob[offset - 1],
                    )
                    blob[offset - 1] = token
                elif row["encoding"] == "utf16le":
                    # Length-prefixed FStrings in property data (DataTable rows,
                    # DataAsset/widget default properties) serialize sequentially
                    # with no absolute offsets into the export, so writing the
                    # exact-size encoding and shifting the rest of the blob is
                    # safe as long as the export SerialSize is updated (done
                    # below via set_serial_size_for_data_pointer). Prefer an ANSI
                    # FString when the translation is pure ASCII (half the size,
                    # no padding) and fall back to UTF-16 otherwise. This keeps
                    # every translation pristine and untruncated.
                    try:
                        translation.encode("ascii")
                        replacement = encode_unreal_string(translation, "ascii")
                    except UnicodeEncodeError:
                        replacement = encode_unreal_string(translation, "utf16le")
                else:
                    replacement = encode_unreal_string(translation, row["encoding"])
                delta = len(replacement) - (current["end"] - offset)
                if delta:
                    raw_changes.append({
                        "offset": offset,
                        "end": current["end"],
                        "delta": delta,
                        "icode_delta": delta,
                        "encoding": row["encoding"],
                    })
                blob[offset:current["end"]] = replacement

            resized_bytecode_literals = [
                change for change in raw_changes
                if change["encoding"] == "utf16le-null" and change["delta"]
            ]
            if resized_bytecode_literals:
                bytecode_candidates = select_script_bytecode_candidates(old_blob, resized_bytecode_literals)
                if not bytecode_candidates:
                    print(
                        f"skipped unsafe bytecode resize in {rel} at {pointer}: "
                        "no structurally parseable Kismet script covered the resized literal"
                    )
                    blob = bytearray(old_blob)
                    resized_bytecode_literals = []
                else:
                    try:
                        adjusted = adjust_script_bytecode_lengths(old_blob, blob, resized_bytecode_literals)
                        adjusted.extend(adjust_kismet_flow_targets(old_blob, blob, resized_bytecode_literals))
                        adjusted.extend(adjust_event_entrypoint_stubs(data, pointer, old_blob, resized_bytecode_literals))
                    except RuntimeError as exc:
                        print(f"skipped unsafe bytecode resize in {rel} at {pointer}: {exc}")
                        blob = bytearray(old_blob)
                    else:
                        for adjustment in adjusted:
                            if len(adjustment) == 4:
                                offset, old_length, new_length, length_kind = adjustment
                                location = f"Data+{offset}"
                            else:
                                export_pointer, offset, old_length, new_length, length_kind = adjustment
                                location = f"{export_pointer}+{offset}"
                            if length_kind in {"icode", "disk"}:
                                print(f"adjusted bytecode {length_kind} length in {rel} at {location}: {old_length} -> {new_length}")
                            elif length_kind == "entrypoint":
                                print(f"adjusted bytecode event entrypoint in {rel} at {location}: {old_length} -> {new_length}")
                            elif length_kind in KISMET_ABSOLUTE_TARGET_TOKENS.values():
                                print(f"adjusted bytecode {length_kind} target in {rel} at {location}: {old_length} -> {new_length}")
                            else:
                                print(f"adjusted bytecode {length_kind} target in {rel} at {location}: {old_length} -> {new_length}")

            set_pointer(data, pointer, base64.b64encode(bytes(blob)).decode("ascii"))
            set_serial_size_for_data_pointer(data, pointer, len(blob))

        write_json(path, data)
        changed.append(path)

    changed_list = out_dir / "_changed-json.txt"
    with changed_list.open("w", encoding="utf-8", newline="\n") as f:
        for path in changed:
            f.write(str(path.resolve()) + "\n")
    print(f"applied translations to {len(changed)} json assets")


def main():
    parser = argparse.ArgumentParser(description="Extract/apply Japanese strings in UAssetGUI JSON.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract")
    p_extract.add_argument("--json-dir", required=True)
    p_extract.add_argument("--out", required=True)
    p_extract.add_argument("--plain")
    p_extract.add_argument("--ui-plain")
    p_extract.add_argument("--all-context")

    p_apply = sub.add_parser("apply")
    p_apply.add_argument("--json-dir", required=True)
    p_apply.add_argument("--csv", required=True)
    p_apply.add_argument("--out-dir", required=True)
    p_apply.add_argument(
        "--resize-overflow-bytecode",
        action="store_true",
        default=True,
        help="Expand overflowing utf16le-null Kismet strings instead of truncating to the fixed ANSI span.",
    )
    p_apply.add_argument(
        "--no-resize-overflow-bytecode",
        dest="resize_overflow_bytecode",
        action="store_false",
        help="Disable Kismet bytecode resizing and fail if a translated literal changes byte size.",
    )

    args = parser.parse_args()
    if args.command == "extract":
        extract(args.json_dir, args.out)
        if args.plain or args.ui_plain or args.all_context:
            with Path(args.out).open("r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            if args.plain:
                write_plain(rows, args.plain)
            if args.ui_plain:
                write_ui_plain(rows, args.ui_plain)
            if args.all_context:
                write_all_context(rows, args.all_context)
    elif args.command == "apply":
        apply_translations(
            args.json_dir,
            args.csv,
            args.out_dir,
            resize_overflow_bytecode=args.resize_overflow_bytecode,
        )


if __name__ == "__main__":
    main()
