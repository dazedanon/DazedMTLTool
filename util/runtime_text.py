"""Pure runtime-code protection and validation, shared by translation and review."""

import re
import unicodedata
from collections import Counter

# ===== Placeholder Protection System =====
# Patterns to protect from translation (sound effects, control codes, etc.)
_GENERAL_CONTROL_PATTERN = (
    r'[\\]+(?:[A-Za-z_][A-Za-z0-9_]*(?:\[(?:[^\[\]]|\[[^\]]*\])*\])?'
    r'|[{}.!|^><#$@,\-])'
)
_ORPHAN_BACKSLASH_PATTERN = r'[\\]+(?=[^\W\d_])'

PROTECTED_PATTERNS = [
    r'\\SE\[[^\]]+\]',      # \SE[sound_effect_name]
    r'\\ME\[[^\]]+\]',      # \ME[music_effect_name]
    r'\\BGM\[[^\]]+\]',     # \BGM[background_music_name]
    r'\\BGS\[[^\]]+\]',     # \BGS[background_sound_name]
    r'_pum\[[^\]]+\]',      # _pum[name]
    r'\\VS\[[^\]]+\]',      # \VS[name]
    # General RPG Maker/plugin controls. Preserve the full spelling, parameter,
    # slash count, and order rather than asking the model to reproduce them.
    _GENERAL_CONTROL_PATTERN,
    # A backslash before a non-ASCII word is not recognized as a control code,
    # but translating that word can turn it into one (``\ヘレン`` ->
    # ``\Helen``). Protect the slash run separately; target restoration escapes
    # odd runs so they remain literal instead of becoming runtime commands.
    _ORPHAN_BACKSLASH_PATTERN,
]

_CONTROL_CODE_RE = re.compile(_GENERAL_CONTROL_PATTERN)
_ORPHAN_BACKSLASH_RE = re.compile(r'^[\\]+$')


def _escaped_orphan_backslash(code):
    """Return an even slash run so RPG Maker treats it as literal text."""
    value = str(code)
    if _ORPHAN_BACKSLASH_RE.fullmatch(value) and len(value) % 2:
        return value + "\\"
    return value


def extract_control_codes(text):
    """Return runtime control tokens in source order."""
    if not isinstance(text, str) or not text:
        return []
    return _CONTROL_CODE_RE.findall(text)


def _mask_mapped_control_codes(text, replacements):
    """Mask restored placeholder codes regardless of their translated order."""
    masked = str(text)
    missing = []

    # Match exact restored codes before using the generic parser. This matters
    # for unparameterized codes such as ``\vc``: once restored before English
    # text, ``\vcThat's`` would otherwise be greedily parsed as ``\vcThat``.
    # Orphan slash placeholders are also masked. Cached/final translations may
    # contain their even, literal-safe form, so prefer that form when present.
    # Search from the beginning for each occurrence so normal translation word
    # order may move standalone values/icons without making them look missing.
    for original in replacements.values():
        code = str(original)
        is_orphan_backslash = _ORPHAN_BACKSLASH_RE.fullmatch(code) is not None
        if _CONTROL_CODE_RE.fullmatch(code) is None and not is_orphan_backslash:
            continue
        matched_code = (
            _escaped_orphan_backslash(code) if is_orphan_backslash else code
        )
        index = masked.find(matched_code)
        if index < 0 and matched_code != code:
            matched_code = code
            index = masked.find(matched_code)
        if index < 0:
            missing.append(code)
            continue
        end = index + len(matched_code)
        masked = masked[:index] + (" " * len(matched_code)) + masked[end:]

    return masked, missing


_FORMAT_SCOPE_RE = re.compile(r"\\(?:[cC]\[[^\]]+\]|[{}><])")


def _format_scope_signature(text):
    """Return structural open/close order for known stateful formatting codes."""
    signatures = {"color": [], "font": [], "speed": []}
    for code in _FORMAT_SCOPE_RE.findall(str(text)):
        lowered = code.lower()
        if lowered.startswith(r"\c["):
            parameter = code[3:-1].strip()
            signatures["color"].append("close" if parameter == "0" else "open")
        elif code == r"\{":
            signatures["font"].append("open")
        elif code == r"\}":
            signatures["font"].append("close")
        elif code == r"\>":
            signatures["speed"].append("open")
        elif code == r"\<":
            signatures["speed"].append("close")
    return signatures


def validate_control_codes(original_items, translated_items, replacements_by_line=None):
    """Require exact control tokens while allowing translation-driven movement.

    ``replacements_by_line`` is the per-line placeholder mapping produced by
    :func:`protect_script_codes`. Known restored codes are matched exactly and
    masked before the generic control-code regex runs. This avoids treating
    adjacent English letters as part of an unparameterized code name. Token
    spelling, parameters, and counts remain strict, while standalone tokens may
    move with translated grammar. Known formatting scopes must retain their
    open/close structure.
    """
    originals = original_items if isinstance(original_items, list) else [original_items]
    translations = translated_items if isinstance(translated_items, list) else [translated_items]
    if len(originals) != len(translations):
        return False, [f"line count differs ({len(originals)} source, {len(translations)} translated)"]

    errors = []
    for index, (original, translated) in enumerate(zip(originals, translations), start=1):
        replacements = (
            replacements_by_line.get(index - 1, {})
            if replacements_by_line
            else {}
        )
        source_text, source_mapping_missing = _mask_mapped_control_codes(
            original, replacements
        )
        target_text, target_mapping_missing = _mask_mapped_control_codes(
            translated, replacements
        )
        source_sequence = extract_control_codes(source_text)
        target_sequence = extract_control_codes(target_text)

        if source_mapping_missing:
            errors.append(
                f"Line{index}: protected-code mapping absent from source "
                f"{source_mapping_missing}"
            )
            continue
        if target_mapping_missing:
            errors.append(
                f"Line{index}: missing protected codes {target_mapping_missing}"
            )
            continue

        source_codes = Counter(source_sequence)
        target_codes = Counter(target_sequence)
        if source_codes != target_codes:
            missing = list((source_codes - target_codes).elements())
            extra = list((target_codes - source_codes).elements())
            details = []
            if missing:
                details.append(f"missing {missing}")
            if extra:
                details.append(f"extra/altered {extra}")
            errors.append(f"Line{index}: " + "; ".join(details))
            continue

        source_scopes = _format_scope_signature(original)
        target_scopes = _format_scope_signature(translated)
        changed_scopes = [
            name for name in source_scopes
            if source_scopes[name] != target_scopes[name]
        ]
        if changed_scopes:
            errors.append(
                f"Line{index}: formatting scope order changed for "
                + ", ".join(changed_scopes)
            )
    return not errors, errors

def protect_script_codes(text):
    """
    Replace script codes (like \\SE[タイプライター]) with unique placeholders before translation.
    Returns: (protected_text, replacements_dict)
    """
    if not text or not isinstance(text, str):
        return text, {}

    # Normalize curly/smart quotes to ASCII equivalents BEFORE building the JSON
    # payload.  When these characters appear inside a JSON string value the AI
    # tends to treat them as regular ASCII double-quotes, which makes the value
    # appear empty (e.g. `"スキルを"リセットする` → AI sees empty + stray text).
    # This mirrors the identical normalization already applied to the AI's OUTPUT
    # inside extractTranslation's translation_table.
    quote_norm_table = str.maketrans({
        '\u201C': "'",  # " left double quotation mark
        '\u201D': "'",  # " right double quotation mark
        '\uFF02': "'",  # ＂ fullwidth quotation mark
        '\u2018': "'",  # ' left single quotation mark
        '\u2019': "'",  # ' right single quotation mark
        '\u201B': "'",  # ‛ single high-reversed-9 quotation mark
        '\u02BC': "'",  # ʼ modifier letter apostrophe
        '\uFF07': "'",  # ＇ fullwidth apostrophe
    })
    text = text.translate(quote_norm_table)

    # Convert half-width katakana (U+FF61–U+FF9F) to full-width katakana so the
    # AI recognises them as Japanese text and translates them correctly.
    # NFKC is applied only to matched half-width kana spans to avoid altering
    # intentional fullwidth Latin/digit characters elsewhere in the string.
    text = re.sub(r'[\uFF61-\uFF9F]+', lambda m: unicodedata.normalize('NFKC', m.group(0)), text)

    replacements = {}
    protected_text = text
    counter = 0

    # Combine all patterns
    combined_pattern = '|'.join(f'({pattern})' for pattern in PROTECTED_PATTERNS)

    def replace_match(match):
        nonlocal counter
        original = match.group(0)
        # Create a unique placeholder that won't be translated
        placeholder = f"__PROTECTED_{counter}__"
        replacements[placeholder] = original
        counter += 1
        return placeholder

    if combined_pattern:
        protected_text = re.sub(combined_pattern, replace_match, protected_text)

    return protected_text, replacements


def restore_script_codes(text, replacements, escape_orphan_backslashes=False):
    """
    Restore protected script codes from placeholders after translation.

    When ``escape_orphan_backslashes`` is true, odd slash-only replacements are
    made even. This preserves a literal backslash without allowing translated
    ASCII text immediately after it to become a new RPG Maker control code.
    """
    if not text or not replacements:
        return text

    if isinstance(text, str):
        result = text
        for placeholder, original in replacements.items():
            restored = (
                _escaped_orphan_backslash(original)
                if escape_orphan_backslashes
                else original
            )
            result = result.replace(placeholder, restored)
        return result
    elif isinstance(text, list):
        return [
            restore_script_codes(
                item,
                replacements,
                escape_orphan_backslashes=escape_orphan_backslashes,
            )
            for item in text
        ]
    else:
        return text


def _reprotect_cached_codes(text, replacements):
    """Reapply known placeholders before validating a restored cache value."""
    protected = str(text)
    for placeholder, original in replacements.items():
        code = str(original)
        cached_code = _escaped_orphan_backslash(code)
        index = protected.find(cached_code)
        if index < 0 and cached_code != code:
            cached_code = code
            index = protected.find(cached_code)
        if index < 0:
            continue
        end = index + len(cached_code)
        protected = protected[:index] + placeholder + protected[end:]
    return protected
