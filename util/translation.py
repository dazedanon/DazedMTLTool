"""
Shared translation utilities for DazedTL.
Centralized translation function used across all modules.
"""

import os
import re
import json
import time
import random
import unicodedata
import tiktoken
import openai
import anthropic
import urllib.request
from openai import APIError, APIConnectionError, RateLimitError, APIStatusError
import hashlib
import threading
from collections import Counter
from contextlib import contextmanager
from dotenv import load_dotenv
from pathlib import Path
from retry import retry
from util.paths import read_active_glossary
from util.sfx_reference import build_sfx_reference_text

# Set to True to enable debug logging (token counts, cache costs, etc.)
DEBUG = True
_debug_request_log_lock = threading.Lock()

# Set to True to disable Claude prompt caching for baseline cost comparison.
DISABLE_CACHE = False

# Thread-local per-file token breakdown; read by calculateCost() for Claude.
_thread_local = threading.local()

# Cross-thread running total of accurate cache-discounted cost (protected by lock).
_global_accurate_cost      = 0.0
_global_accurate_cost_lock = threading.Lock()


def _usage_to_debug_dict(usage):
    """Extract token counts from provider usage objects for request debugging."""
    if not usage:
        return {}

    usage_dict = {}
    for field in (
        "prompt_tokens",
        "completion_tokens",
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ):
        value = getattr(usage, field, None)
        if value is not None:
            usage_dict[field] = value

    extra = getattr(usage, "model_extra", None)
    if isinstance(extra, dict):
        for field in ("cache_read_input_tokens", "cache_creation_input_tokens"):
            value = extra.get(field)
            if value is not None and field not in usage_dict:
                usage_dict[field] = value

    return usage_dict


def _write_request_debug_log(provider, request_payload, usage):
    """Write the exact SDK payload text and returned token usage."""
    if not DEBUG:
        return

    try:
        log_dir = Path("log")
        log_dir.mkdir(parents=True, exist_ok=True)
        usage_dict = _usage_to_debug_dict(usage)
        payload_text = json.dumps(request_payload, indent=2, ensure_ascii=False, default=str)
        usage_text = json.dumps(usage_dict, indent=2, ensure_ascii=False, default=str)

        with _debug_request_log_lock:
            with open(log_dir / "request_debug.log", "a", encoding="utf-8") as debug_file:
                debug_file.write("\n=== API Request ===\n")
                debug_file.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                debug_file.write(f"Provider: {provider}\n")
                debug_file.write("Usage:\n")
                debug_file.write(f"{usage_text}\n")
                debug_file.write("Payload:\n")
                debug_file.write(f"{payload_text}\n")
                debug_file.flush()
    except Exception:
        pass

def _normalize_openai_base_url(url: str) -> str:
    """Ensure OpenAI SDK global base_url has a trailing slash."""
    _url = (url or "").strip()
    if _url and not _url.endswith("/"):
        _url += "/"
    return _url


def isClaudeModel(model):
    """True when the model name looks like an Anthropic Claude model."""
    return bool(model) and any(x in model.lower() for x in ("claude", "sonnet", "haiku", "opus"))


def isClaudeNative(model, api_url=None):
    """True when this model routes to the native Anthropic SDK.

    Mirrors the routing check in translateText: the model must look like Claude
    AND the configured API URL must be unset or point at anthropic.com.  Any
    other custom URL (e.g. DeepSeek, OpenAI proxy) uses the OpenAI-compatible
    path even for Claude-named models.
    """
    live_api = os.getenv("api", "").strip() if api_url is None else str(api_url).strip()
    return isClaudeModel(model) and (not live_api or "anthropic" in live_api.lower())


def getBatchProvider(model=None, api_url=None, api_provider=None):
    """Return the configured asynchronous batch backend, if supported."""
    from util.batch_providers import detect_batch_provider

    return detect_batch_provider(
        model if model is not None else os.getenv("model", ""),
        api_url=api_url,
        api_provider=api_provider,
    )


def isBatchSupported(model=None, api_url=None, api_provider=None):
    """Whether Batch Translate can preserve the normal request semantics."""
    return getBatchProvider(model, api_url, api_provider) is not None


def isMistralAPI():
    """True when requests go to the Mistral platform API (la Plateforme).

    Detection is URL-based: the adaptive rate limiter keys off x-ratelimit-*
    headers that only api.mistral.ai sends. Mistral models served through other
    OpenAI-compatible providers (Nvidia, OpenRouter, ...) use the generic path.
    """
    live_api = os.getenv("api", "").strip().lower()
    if "mistral.ai" in live_api:
        return True
    return not live_api and os.getenv("API_PROVIDER", "").strip().lower() == "mistral"


# Models that REJECT sampling params (temperature/top_p/top_k) with a 400 —
# Claude Opus 4.7 and up retired them in favour of adaptive thinking. Matches
# opus-4-7, opus-4-8, opus-4-10+ and fable, but NOT opus-4-6 or Sonnet/Haiku.
_NO_SAMPLING_RE = re.compile(r"opus-4-(?:[7-9]\b|[1-9]\d)|fable", re.I)

# Tracks which distinct batch sizes have already been cache-written during this estimate run.
# Each unique numLines value maps to a distinct output_config schema → one write per size.
# Persisted to disk so sequential GUI subprocesses share state.
_estimate_written_sizes: set = set()
_ESTIMATE_SIZES_FILE = Path("log/estimate_written_sizes.json")

def _load_estimate_written_sizes():
    """Load persisted written-sizes set from disk (for GUI subprocess sharing)."""
    global _estimate_written_sizes
    try:
        if _ESTIMATE_SIZES_FILE.exists():
            with open(_ESTIMATE_SIZES_FILE, "r", encoding="utf-8") as f:
                _estimate_written_sizes = set(json.load(f))
    except Exception:
        _estimate_written_sizes = set()

def _save_estimate_written_sizes():
    """Persist written-sizes set to disk."""
    try:
        _ESTIMATE_SIZES_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_ESTIMATE_SIZES_FILE, "w", encoding="utf-8") as f:
            json.dump(list(_estimate_written_sizes), f)
    except Exception:
        pass

def clear_estimate_written_sizes():
    """Reset the written-sizes file at the start of a new estimate run."""
    global _estimate_written_sizes
    _estimate_written_sizes = set()
    try:
        if _ESTIMATE_SIZES_FILE.exists():
            _ESTIMATE_SIZES_FILE.unlink()
    except Exception:
        pass


# ===== Placeholder Protection System =====
# Patterns to protect from translation (sound effects, control codes, etc.)
PROTECTED_PATTERNS = [
    r'\\SE\[[^\]]+\]',      # \SE[sound_effect_name]
    r'\\ME\[[^\]]+\]',      # \ME[music_effect_name]
    r'\\BGM\[[^\]]+\]',     # \BGM[background_music_name]
    r'\\BGS\[[^\]]+\]',     # \BGS[background_sound_name]
    r'_pum\[[^\]]+\]',      # _pum[name]
    r'\\VS\[[^\]]+\]',      # \VS[name]
    # General RPG Maker/plugin controls. Preserve the full spelling, parameter,
    # slash count, and order rather than asking the model to reproduce them.
    r'[\\]+(?:[A-Za-z_][A-Za-z0-9_]*(?:\[(?:[^\[\]]|\[[^\]]*\])*\])?|[{}.!|^><#$@,\-])',
]

_CONTROL_CODE_RE = re.compile(PROTECTED_PATTERNS[-1])


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
    # Search from the beginning for each occurrence so normal translation word
    # order may move standalone values/icons without making them look missing.
    for original in replacements.values():
        code = str(original)
        if _CONTROL_CODE_RE.fullmatch(code) is None:
            continue
        index = masked.find(code)
        if index < 0:
            missing.append(code)
            continue
        end = index + len(code)
        masked = masked[:index] + (" " * len(code)) + masked[end:]

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


def restore_script_codes(text, replacements):
    """
    Restore protected script codes from placeholders after translation.
    """
    if not text or not replacements:
        return text
    
    if isinstance(text, str):
        result = text
        for placeholder, original in replacements.items():
            result = result.replace(placeholder, original)
        return result
    elif isinstance(text, list):
        return [restore_script_codes(item, replacements) for item in text]
    else:
        return text


def _reprotect_cached_codes(text, replacements):
    """Reapply known placeholders before validating a restored cache value."""
    protected = str(text)
    for placeholder, original in replacements.items():
        index = protected.find(str(original))
        if index < 0:
            continue
        end = index + len(str(original))
        protected = protected[:index] + placeholder + protected[end:]
    return protected


def validate_placeholders(original_text, translated_text, replacements):
    """
    Validate that all placeholders from the original text appear in the translation.
    Returns: (is_valid, missing_placeholders, extra_placeholders)
    """
    if not replacements:
        return True, [], []
    
    # Get all placeholders
    all_placeholders = set(replacements.keys())
    
    # Count placeholders in original
    original_counts = {}
    for placeholder in all_placeholders:
        if isinstance(original_text, str):
            original_counts[placeholder] = original_text.count(placeholder)
        elif isinstance(original_text, list):
            original_counts[placeholder] = sum(str(item).count(placeholder) for item in original_text)
    
    # Count placeholders in translation
    translated_counts = {}
    for placeholder in all_placeholders:
        if isinstance(translated_text, str):
            translated_counts[placeholder] = translated_text.count(placeholder)
        elif isinstance(translated_text, list):
            translated_counts[placeholder] = sum(str(item).count(placeholder) for item in translated_text)
    
    # Find mismatches
    missing = []
    extra = []
    for placeholder in all_placeholders:
        orig_count = original_counts.get(placeholder, 0)
        trans_count = translated_counts.get(placeholder, 0)
        
        if trans_count < orig_count:
            missing.append(f"{placeholder} (expected {orig_count}, found {trans_count})")
        elif trans_count > orig_count:
            extra.append(f"{placeholder} (expected {orig_count}, found {trans_count})")
    
    is_valid = len(missing) == 0 and len(extra) == 0
    return is_valid, missing, extra


def validate_translation_content(original_items, translated_items, langRegex):
    """
    Validate hard content failures that make a translation unsafe or unusable.
    Returns: (is_valid, invalid_indices, reasons)

    Outputs that are too short to carry the source meaning or contain runaway
    character repetition are hard failures.  Accepting either result would
    cache and write visibly corrupt player text.
    """
    if not isinstance(original_items, list):
        original_items = [original_items]
        translated_items = [translated_items]
    
    invalid_indices = []
    reasons = []
    
    for i, (orig, trans) in enumerate(zip(original_items, translated_items)):
        orig_str = str(orig).strip()
        trans_str = str(trans).strip()
        
        # Skip if original is empty or placeholder
        if not orig_str or orig_str == "Placeholder Text":
            continue
        
        # Check if original has content that needs translation
        has_source_text = bool(re.search(langRegex, orig_str))
        
        if has_source_text:
            # Original has Japanese text - translation must be substantial
            
            # Check 1: Translation is empty or just whitespace
            if not trans_str:
                invalid_indices.append(i)
                reasons.append(f"Line{i+1}: Empty translation for '{orig_str[:50]}...'")
                continue

            # Check 2: A substantial source cannot validly collapse to one
            # punctuation mark.  This used to be only a warning, which meant
            # the result was cached and written without entering the retry path.
            has_bracketed_control = bool(re.search(r'\\[A-Z]\[', trans_str))
            if len(trans_str) <= 1 and len(orig_str) > 3 and not has_bracketed_control:
                invalid_indices.append(i)
                reasons.append(
                    f"Line{i+1}: Translation unusually short ('{trans_str}') for "
                    f"'{orig_str[:50]}...'"
                )
                continue
            if (
                len(orig_str) > 10
                and len(trans_str) <= 2
                and not has_bracketed_control
                and not trans_str.isalnum()
            ):
                invalid_indices.append(i)
                reasons.append(
                    f"Line{i+1}: Translation suspiciously short ('{trans_str}') for "
                    f"'{orig_str[:50]}...'"
                )
                continue

            # Check 3: Long runs of one character are model degeneration, not
            # meaningful translation output.
            if re.search(r"(.)\1{44,}", trans_str):
                invalid_indices.append(i)
                reasons.append(
                    f"Line{i+1}: Excessive character repetition (possible model glitch)"
                )
                continue
            
            # Check 4: Runaway translation - translation is excessively long relative to original
            # Catches cases where the model repeats words endlessly (e.g. "it hurts it hurts it hurts...")
            ratio_limit = max(len(orig_str) * 8, 120)
            if len(orig_str) > 10 and len(trans_str) > ratio_limit:
                invalid_indices.append(i)
                reasons.append(f"Line{i+1}: Runaway translation (output {len(trans_str)} chars vs input {len(orig_str)} chars) for '{orig_str[:50]}...'")
                continue
            # Absolute cap: garbage outputs that are not caught by ratio alone
            if len(trans_str) > 4000 and len(trans_str) > len(orig_str) * 3:
                invalid_indices.append(i)
                reasons.append(f"Line{i+1}: Runaway translation (output {len(trans_str)} chars exceeds cap) for '{orig_str[:50]}...'")
                continue

            # Check 5: Source-language residue must not survive in player text.
            # Japanese inside protected runtime-code parameters is absent here
            # and is restored only after validation. Ignore ideographic spaces:
            # RPG Maker choice lists commonly use U+3000 as intentional visual
            # padding, and preserving that layout is not untranslated content.
            residue_text = trans_str.replace("\u3000", "")
            if re.search(langRegex, residue_text):
                invalid_indices.append(i)
                reasons.append(f"Line{i+1}: Source-language text remains in translation")
                continue

            # Check 6: Reject leaked structured-response scaffolding such as
            # `}Line1:` that can otherwise become a speaker label.
            if re.search(r"(?:^|[}\]])\s*Line\d+\s*:", trans_str, re.IGNORECASE):
                invalid_indices.append(i)
                reasons.append(f"Line{i+1}: Structured response marker leaked into translation")
                continue

    is_valid = len(invalid_indices) == 0
    return is_valid, invalid_indices, reasons


def translation_content_warnings(original_items, translated_items, langRegex):
    """Return non-blocking content concerns that should remain reviewable."""
    if not isinstance(original_items, list):
        original_items = [original_items]
        translated_items = [translated_items]

    warning_indices = []
    warnings = []
    for i, (orig, trans) in enumerate(zip(original_items, translated_items)):
        orig_str = str(orig).strip()
        trans_str = str(trans).strip()
        if not orig_str or orig_str == "Placeholder Text":
            continue
        if not re.search(langRegex, orig_str):
            continue

        line_warnings = []
        has_bracketed_control = bool(re.search(r'\\[A-Z]\[', trans_str))
        if len(trans_str) <= 1 and len(orig_str) > 3 and not has_bracketed_control:
            line_warnings.append(
                f"Line{i+1}: Translation unusually short ('{trans_str}') for "
                f"'{orig_str[:50]}...'"
            )
        elif (
            len(orig_str) > 10
            and len(trans_str) <= 2
            and not has_bracketed_control
            and not trans_str.isalnum()
        ):
            line_warnings.append(
                f"Line{i+1}: Translation suspiciously short ('{trans_str}') for "
                f"'{orig_str[:50]}...'"
            )
        if re.search(r"(.)\1{44,}", trans_str):
            line_warnings.append(
                f"Line{i+1}: Excessive character repetition (possible model glitch)"
            )

        if line_warnings:
            warning_indices.append(i)
            warnings.extend(line_warnings)

    return warning_indices, warnings

# Load .env, strip accidental whitespace, set base URL / org / API key.
# Gemini/Mistral use their endpoints only when no custom API URL is set.
load_dotenv()
api_provider = os.getenv("API_PROVIDER", "openai").lower()
env_api = os.getenv("api", "").strip()
if api_provider == "gemini" and not env_api:
    # Use Google Generative Language compatibility endpoint only as fallback.
    openai.base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    openai.organization = None
elif api_provider == "mistral" and not env_api:
    openai.base_url = "https://api.mistral.ai/v1/"
    openai.organization = None
else:
    if env_api:
        openai.base_url = _normalize_openai_base_url(env_api)
    # Support both 'organization' (gui/.env.example) and legacy 'org' names
    org = os.getenv("organization") or os.getenv("org")
    if org:
        openai.organization = org.strip()

# The SDK itself requires a non-empty value even when a local compatible server
# does not authenticate requests. Only use the placeholder for an explicitly
# keyless vault entry so missing cloud credentials still fail normally.
_env_key = os.getenv("key", "").strip()
_key_optional = os.getenv("API_KEY_OPTIONAL", "").strip().lower() in ("1", "true", "yes")
openai.api_key = _env_key or ("not-needed" if _key_optional else "")

# Translation cache management
CACHE_FILE = Path("log/translation_cache.json")
CACHE_LOCK_FILE = Path("log/translation_cache.lock")
CACHE_LOCK = threading.RLock()
CACHE_PENDING_MARKER = "__translation_pending__"
CACHE_PENDING_TTL = 600
CACHE_WAIT_INTERVAL = 0.25
_cache = None

@contextmanager
def _translation_cache_file_lock():
    """Cross-process lock for translation_cache.json."""
    CACHE_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_LOCK_FILE, "a+b") as lock_file:
        if os.name == "nt":
            import msvcrt
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

def _read_cache_from_disk():
    """Read the disk cache; return an empty dict if it is unavailable."""
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}

def _write_cache_to_disk(cache):
    """Atomically write the cache using a process/thread-unique temp file."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = CACHE_FILE.with_name(
        f"{CACHE_FILE.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    tmp_file.replace(CACHE_FILE)

def _is_pending_cache_entry(value):
    return isinstance(value, dict) and value.get(CACHE_PENDING_MARKER) is True

def _is_stale_pending_cache_entry(value):
    if not _is_pending_cache_entry(value):
        return False
    try:
        return time.time() - float(value.get("time", 0)) > CACHE_PENDING_TTL
    except Exception:
        return True

def _is_own_pending_cache_entry(value):
    return (
        _is_pending_cache_entry(value)
        and value.get("pid") == os.getpid()
        and value.get("thread") == threading.get_ident()
    )

def _pending_cache_entry():
    return {
        CACHE_PENDING_MARKER: True,
        "pid": os.getpid(),
        "thread": threading.get_ident(),
        "time": time.time(),
    }

def _merge_translation_caches(base, overlay):
    """Merge cache dictionaries while never replacing a translation with pending."""
    merged = dict(base or {})
    for key, value in (overlay or {}).items():
        existing = merged.get(key)
        if _is_pending_cache_entry(value) and existing is not None:
            if not _is_pending_cache_entry(existing):
                continue
            if not _is_stale_pending_cache_entry(existing):
                continue
        merged[key] = value
    return merged

def clear_cache():
    """Clear the translation cache (called at start of each run)"""
    global _cache
    with CACHE_LOCK:
        _cache = {}
        with _translation_cache_file_lock():
            try:
                if CACHE_FILE.exists():
                    CACHE_FILE.unlink()
            except Exception:
                pass

def load_cache():
    """Load the translation cache from disk."""
    global _cache
    with CACHE_LOCK:
        with _translation_cache_file_lock():
            disk_cache = _read_cache_from_disk()
            if _cache:
                disk_cache = _merge_translation_caches(disk_cache, _cache)
            _cache = disk_cache
        return _cache

def save_cache():
    """Save the translation cache to disk, preserving entries from other workers."""
    global _cache
    if _cache is None:
        return
    
    with CACHE_LOCK:
        try:
            with _translation_cache_file_lock():
                disk_cache = _read_cache_from_disk()
                disk_cache = _merge_translation_caches(disk_cache, _cache)
                _cache = disk_cache
                _write_cache_to_disk(_cache)
        except Exception:
            pass

def expand_clean_to_batch(clean_values, tItem, corrupted_map, no_japanese_map):
    """Re-insert skipped originals around AI-translated (clean) values.

    The cache key is built from the Japanese-only payload, so cached values hold
    only the translatable items. corrupted_map / no_japanese_map hold the skipped
    originals keyed by their position in the full batch. Returns a list aligned
    1:1 with tItem. Falls back to the source line if clean_values runs short.
    """
    expanded = []
    clean_idx = 0
    for j in range(len(tItem)):
        if j in corrupted_map:
            expanded.append(corrupted_map[j])
        elif j in no_japanese_map:
            expanded.append(no_japanese_map[j])
        elif clean_idx < len(clean_values):
            expanded.append(clean_values[clean_idx])
            clean_idx += 1
        else:
            expanded.append(tItem[j])
    return expanded

def get_cache_key(payload, language, cache_context=None):
    """Generate a cache key for a payload and its matched dynamic context.

    ``cache_context`` is normally the subset of the active glossary matched to
    this payload. Keeping it in the key prevents a translation produced with an
    old spelling from surviving a relevant glossary edit, without invalidating
    unrelated payloads when some other glossary entry changes.
    """
    # Use hash to keep keys short but unique
    payload_str = str(payload) if payload is not None else ""
    combined = f"{payload_str}|{language}"
    # Preserve legacy keys when this payload matches no glossary entries. Those
    # translations are unaffected by glossary edits, so invalidating them would
    # only waste cache/batch work during an upgrade.
    if cache_context:
        context_hash = hashlib.sha256(
            str(cache_context).encode("utf-8")
        ).hexdigest()
        combined += f"|context:{context_hash}"
    return hashlib.md5(combined.encode("utf-8")).hexdigest()

def get_cached_translation(payload, language, cache_context=None):
    """Get cached translation if it exists"""
    global _cache
    key = get_cache_key(payload, language, cache_context)
    while True:
        with CACHE_LOCK:
            with _translation_cache_file_lock():
                cache = _read_cache_from_disk()
                if _cache:
                    cache = _merge_translation_caches(cache, _cache)

                entry = cache.get(key)
                if (
                    entry is None
                    or _is_stale_pending_cache_entry(entry)
                    or _is_own_pending_cache_entry(entry)
                ):
                    cache[key] = _pending_cache_entry()
                    _cache = cache
                    _write_cache_to_disk(cache)
                    return None

                _cache = cache
                if not _is_pending_cache_entry(entry):
                    return entry

        time.sleep(CACHE_WAIT_INTERVAL)

def cache_translation(payload, translation, language, cache_context=None):
    """Cache a translation payload and its response"""
    global _cache
    key = get_cache_key(payload, language, cache_context)
    
    with CACHE_LOCK:
        with _translation_cache_file_lock():
            cache = _read_cache_from_disk()
            if _cache:
                cache = _merge_translation_caches(cache, _cache)
            cache[key] = translation
            _cache = cache
            _write_cache_to_disk(cache)


# Variable translation map (code 122 <-> code 111 consistency)
VAR_MAP_FILE = Path("log/var_translation_map.json")
VAR_MAP_LOCK = threading.Lock()
_var_map = None

def clear_var_map():
    """Clear the variable translation map (called at start of each run)"""
    global _var_map
    with VAR_MAP_LOCK:
        _var_map = {}
        try:
            if VAR_MAP_FILE.exists():
                VAR_MAP_FILE.unlink()
        except Exception:
            pass

def _load_var_map():
    """Load the variable translation map from disk (always re-reads to pick up
    entries written by other subprocesses)."""
    global _var_map
    _var_map = {}
    try:
        if VAR_MAP_FILE.exists():
            with open(VAR_MAP_FILE, "r", encoding="utf-8") as f:
                _var_map = json.load(f)
    except Exception:
        _var_map = {}
    return _var_map

def _save_var_map():
    """Save the variable translation map to disk.
    Re-reads the file first and merges so entries from other subprocesses
    are never lost."""
    global _var_map
    if _var_map is None:
        return
    try:
        VAR_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Re-read the on-disk version and merge our entries on top
        disk_map = {}
        try:
            if VAR_MAP_FILE.exists():
                with open(VAR_MAP_FILE, "r", encoding="utf-8") as f:
                    disk_map = json.load(f)
        except Exception:
            disk_map = {}
        disk_map.update(_var_map)
        _var_map = disk_map
        tmp_file = VAR_MAP_FILE.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(_var_map, f, ensure_ascii=False, indent=2)
        tmp_file.replace(VAR_MAP_FILE)
    except Exception:
        pass

def get_var_translation(original):
    """Look up a cached variable translation. Returns the translation or None."""
    with VAR_MAP_LOCK:
        m = _load_var_map()
        return m.get(original)

def set_var_translation(original, translated):
    """Store a variable translation and persist to disk.
    Skips if the translation is identical to the original (untranslated).
    """
    if original == translated:
        return
    with VAR_MAP_LOCK:
        m = _load_var_map()
        m[original] = translated
        _save_var_map()

def set_var_translations_batch(pairs):
    """Store multiple variable translations at once and persist to disk.
    pairs: list of (original, translated) tuples
    Skips pairs where the translation is identical to the original (untranslated).
    """
    with VAR_MAP_LOCK:
        m = _load_var_map()
        for original, translated in pairs:
            if original != translated:
                m[original] = translated
        _save_var_map()


# ===== Asynchronous provider batches (50% off all token usage) =====
# Batch integration by Len — two-pass collect/consume flow; see README Credits.
# Batch translation is a two-pass flow driven by the batch phase (kept in the
# BATCH_PHASE env var so GUI subprocesses inherit it):
#   collect: translateAI builds each cache-missed request (byte-identical to a
#            live request, including the cached system block) and queues it
#            instead of calling the API. Text is left untranslated.
#   consume: translateAI feeds fetched responses through the normal validation
#            and restore path; missing or invalid results fail closed without a
#            surprise full-price live request.
# Between the passes, submit/poll/fetch the queue with runTranslationBatches().
BATCH_QUEUE_FILE   = Path("log/batch_requests.json")
BATCH_STATE_FILE   = Path("log/batch_state.json")
BATCH_RESULTS_FILE = Path("log/batch_results.json")
BATCH_LOCK_FILE    = Path("log/batch_files.lock")
BATCH_LOCK = threading.RLock()
# Legacy public constants retained for extensions/tests. Submission uses the
# stricter provider-specific limits from util.batch_providers.
BATCH_MAX_REQUESTS = 100_000
BATCH_MAX_BYTES    = 200 * 1024 * 1024

_batch_phase = None
_batch_results = None      # in-memory copy of BATCH_RESULTS_FILE (read-only during consume)
_batch_queue_pending = {}  # process-local queue entries not yet flushed to disk


def set_batch_phase(phase):
    """Set the batch phase ('collect', 'consume' or None) for this process and
    any subprocesses it spawns (the GUI runs one per file)."""
    global _batch_phase, _batch_results
    _batch_phase = phase if phase in ("collect", "consume") else None
    if _batch_phase:
        os.environ["BATCH_PHASE"] = _batch_phase
    else:
        os.environ.pop("BATCH_PHASE", None)
    _batch_results = None  # phase change invalidates the in-memory results copy


def get_batch_phase():
    """Current batch phase, or None when batch translation is off."""
    if _batch_phase:
        return _batch_phase
    phase = os.getenv("BATCH_PHASE", "").strip().lower()
    return phase if phase in ("collect", "consume") else None


@contextmanager
def _batch_file_lock():
    """Cross-process lock for the batch queue/state/results files."""
    BATCH_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BATCH_LOCK_FILE, "a+b") as lock_file:
        if os.name == "nt":
            import msvcrt
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class BatchFileCorruptionError(RuntimeError):
    """A durable batch file exists but cannot be trusted for paid recovery."""


def _read_batch_file(path, *, strict=False):
    """Read a batch JSON object.

    Missing files remain equivalent to an empty object. ``strict`` is used at
    paid submission/recovery boundaries, where treating corruption as an empty
    run could submit the same work twice.
    """
    error = None
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
                error = "document is not a JSON object"
    except Exception as exc:
        error = str(exc)
    if error is not None:
        message = f"Batch recovery file is corrupt: {path} ({error})"
        print(f"[BATCH] {message}", flush=True)
        if strict:
            raise BatchFileCorruptionError(
                message
                + ". The operation was blocked to preserve recovery data and "
                "prevent duplicate paid work. Restore or inspect the file before "
                "clearing the batch run."
            )
    return {}


def _write_batch_file(path, data):
    """Atomically write a batch JSON file (no indent — queues can be large)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    tmp_file.replace(path)


def peek_cached_translation(payload, language, cache_context=None):
    """Cache lookup that never blocks or writes a pending marker.

    The collect pass uses this instead of get_cached_translation so abandoned
    pending markers can't stall the consume pass for CACHE_PENDING_TTL."""
    key = get_cache_key(payload, language, cache_context)
    with CACHE_LOCK:
        with _translation_cache_file_lock():
            cache = _read_cache_from_disk()
            if _cache:
                cache = _merge_translation_caches(cache, _cache)
    entry = cache.get(key)
    if entry is None or _is_pending_cache_entry(entry):
        return None
    return entry


def queue_batch_request(payload, language, params, cache_context=None, provider=None):
    """Queue one Batches API request during the collect pass.

    Deduped by the same key the translation cache uses, so identical payloads
    across files are only paid for once. Entries are buffered in memory and
    merged to disk by flush_batch_queue() at the end of each translateAI call.
    """
    key = get_cache_key(payload, language, cache_context)
    with BATCH_LOCK:
        _batch_queue_pending[key] = {
            "payload": payload,
            "language": language,
            "params": params,
            "provider": provider or getBatchProvider(params.get("model", "")),
        }
    return key


def flush_batch_queue():
    """Merge this process's pending queue entries into the on-disk queue."""
    global _batch_queue_pending
    with BATCH_LOCK:
        if not _batch_queue_pending:
            return
        pending, _batch_queue_pending = _batch_queue_pending, {}
        try:
            with _batch_file_lock():
                queue = _read_batch_file(BATCH_QUEUE_FILE, strict=True)
                for key, entry in pending.items():
                    queue.setdefault(key, entry)
                _write_batch_file(BATCH_QUEUE_FILE, queue)
        except BatchFileCorruptionError:
            _batch_queue_pending.update(pending)
            raise
        except Exception:
            _batch_queue_pending.update(pending)  # keep entries for the next flush


def batchQueueStaleContextCount(vocab_text=None, use_sfx_reference=None):
    """Return ``(stale, total)`` for queued requests under current dynamic context.

    This is used before resuming an unsubmitted queue. Submitted/fetched results
    are protected by the same context-aware result key; a mismatch stops consume
    rather than making an unapproved full-price live request.
    """
    flush_batch_queue()
    if vocab_text is None:
        try:
            vocab_text = read_active_glossary()
        except OSError:
            vocab_text = ""
    vocab_pairs = parseVocabWithCategories(vocab_text or "")
    if use_sfx_reference is None:
        use_sfx_reference = os.getenv("useSfxReference", "true").strip().lower() in (
            "true", "1", "yes",
        )

    with _batch_file_lock():
        queue = _read_batch_file(BATCH_QUEUE_FILE)

    stale = 0
    for recorded_key, entry in queue.items():
        payload = entry.get("payload", "")
        language = entry.get("language", "")
        matched_glossary = buildMatchedVocabText(vocab_pairs, payload)
        matched_sfx = build_sfx_reference_text(
            payload, enabled=bool(use_sfx_reference)
        )
        matched_context = matched_glossary + matched_sfx
        current_key = get_cache_key(payload, language, matched_context)
        if current_key != recorded_key:
            stale += 1
    return stale, len(queue)


def take_batch_result(payload, language, cache_context=None):
    """Return the fetched batch response dict for a payload, or None.

    The results file is loaded once per process — it is written before the
    consume pass starts and never changes mid-consume."""
    global _batch_results
    if _batch_results is None:
        with BATCH_LOCK:
            if _batch_results is None:
                with _batch_file_lock():
                    _batch_results = _read_batch_file(BATCH_RESULTS_FILE)
    return _batch_results.get(get_cache_key(payload, language, cache_context))


class BatchResultUnavailableError(RuntimeError):
    """A consume pass could not safely match a fetched provider result."""


def require_batch_result(payload, language, cache_context=None):
    """Return one fetched result or stop before an unapproved live API call."""
    result = take_batch_result(payload, language, cache_context)
    if result is None:
        raise BatchResultUnavailableError(
            "[BATCH] No fetched result matches this request and its current "
            "glossary/SFX context. The consume pass was stopped without making "
            "a full-price live request. Re-collect the batch, or run normal "
            "Translate explicitly if live pricing is acceptable."
        )
    return result


def pendingBatchRequests():
    """Number of queued batch requests (call after the collect pass)."""
    flush_batch_queue()
    with _batch_file_lock():
        return len(_read_batch_file(BATCH_QUEUE_FILE))


def batchRunState():
    """Resume detector for an interrupted batch run.

    Returns:
      'partially_submitted' - at least one split job exists, with requests left
      'submitted' - provider batch(es) in flight (or ended but not fetched)
      'fetched'   - results on disk waiting for consume
      'queued'    - collect finished / submit declined; queue still on disk
      'corrupt'   - a recovery document exists but cannot be trusted
      None        - nothing to resume
    """
    try:
        with _batch_file_lock():
            state = _read_batch_file(BATCH_STATE_FILE, strict=True)
            results = _read_batch_file(BATCH_RESULTS_FILE, strict=True)
            queue = _read_batch_file(BATCH_QUEUE_FILE, strict=True)
            if state.get("status") == "partially_submitted" and state.get("batches"):
                return "partially_submitted"
            if state.get("batches"):
                return "submitted"
            if state.get("status") == "fetched" or results:
                return "fetched"
            if queue:
                return "queued"
    except BatchFileCorruptionError:
        return "corrupt"
    return None


def batchRunMetadata():
    """Return a copy of the active batch state used to validate safe resumes."""
    with _batch_file_lock():
        return dict(_read_batch_file(BATCH_STATE_FILE))


def saveQueuedBatchMetadata(file_set=None):
    """Persist the file scope of an unsubmitted queue for safe resume."""
    with BATCH_LOCK:
        with _batch_file_lock():
            state = _read_batch_file(BATCH_STATE_FILE)
            state.update({
                "status": "queued",
                "file_set": list(file_set or []),
                "model": os.getenv("model", ""),
                "provider": getBatchProvider(os.getenv("model", "")),
            })
            _write_batch_file(BATCH_STATE_FILE, state)


def clearBatchFiles():
    """Remove active queue/state/results. Never deletes durable batch history."""
    global _batch_results, _batch_queue_pending
    with BATCH_LOCK:
        fetched_ids = []
        had_results = False
        with _batch_file_lock():
            state = _read_batch_file(BATCH_STATE_FILE)
            had_results = bool(_read_batch_file(BATCH_RESULTS_FILE)) or state.get("status") == "fetched"
            if had_results:
                fetched_ids = list(state.get("batch_ids") or [])
                if not fetched_ids:
                    fetched_ids = [b.get("id") for b in (state.get("batches") or []) if b.get("id")]
            for path in (BATCH_QUEUE_FILE, BATCH_STATE_FILE, BATCH_RESULTS_FILE):
                try:
                    if path.exists():
                        path.unlink()
                except Exception:
                    pass
        _batch_results = None
        _batch_queue_pending = {}
    # Only mark history consumed when clearing after a successful fetch/consume,
    # never when discarding a still-submitted or queued run.
    if had_results:
        try:
            from util.batch_history import on_clear_active_files
            on_clear_active_files(had_results=True, fetched_ids=fetched_ids or None)
        except Exception as exc:
            print(f"[BATCH] history consume mark failed: {exc}", flush=True)


def _get_anthropic_client():
    key = os.getenv("key", "").strip()
    if not key:
        raise Exception("Batch translation requires the 'key' env var (see .env).")
    return anthropic.Anthropic(api_key=key)


def _estimate_openai_cache_reads(prompt_token_sequences):
    """Estimate automatic OpenAI prefix-cache hits for an ordered request set.

    OpenAI caches exact prompt prefixes automatically once they reach 1,024
    tokens and reports hits in 128-token increments.  Track fingerprints at
    those boundaries so the estimate stays linear in the number of prompt
    tokens instead of comparing every request with every earlier request.

    This is deliberately an estimate: a matching prefix must also be routed to
    a machine holding that prefix, so the no-cache figure remains the safe
    upper bound shown to the user.
    """
    import hashlib

    seen = set()
    cached_tokens = 0
    for tokens in prompt_token_sequences:
        hasher = hashlib.blake2b(digest_size=16)
        fingerprints = []
        request_cached_tokens = 0
        for index, token in enumerate(tokens, 1):
            hasher.update(int(token).to_bytes(4, "little", signed=False))
            if index >= 1024 and index % 128 == 0:
                fingerprint = (index, hasher.digest())
                fingerprints.append(fingerprint)
                if fingerprint in seen:
                    request_cached_tokens = index
        cached_tokens += request_cached_tokens
        seen.update(fingerprints)
    return cached_tokens


def estimateBatchCost(model=None):
    """Print a cost estimate for the queued batch requests and return it.

    For Claude, cached-prefix accounting mirrors what Anthropic bills: each distinct cached
    prefix is written once (2x input rate at the 1h TTL) and read by every other
    request that shares it (0.10x); everything is then halved by the batch
    discount. Cache hits inside a batch are best-effort, so the no-cache batch
    figure is the worst-case bound. OpenAI automatic cache reuse is estimated
    from repeated 1,024+ token prefixes. Gemini estimates exclude unpredictable
    thinking output and do not assume an implicit cache hit.
    """
    flush_batch_queue()
    with _batch_file_lock():
        queue = _read_batch_file(BATCH_QUEUE_FILE)
    if not queue:
        print("[BATCH] No batch requests queued.", flush=True)
        return None

    enc = tiktoken.encoding_for_model("gpt-4")
    prefix_count = {}   # cached prefix text -> how many requests reuse it
    prefix_tokens = {}  # cached prefix text -> token count
    dynamic_tokens = 0
    prompt_token_sequences = []
    output_tokens = 0
    models = set()
    providers = set()
    for entry in queue.values():
        params = entry.get("params", {})
        if params.get("model"):
            models.add(params["model"])
        if entry.get("provider"):
            providers.add(entry["provider"])
        blocks = params.get("system") or []
        cut = 0  # split system blocks at the cache breakpoint (0 = nothing cached)
        for i, b in enumerate(blocks):
            if "cache_control" in b:
                cut = i + 1
                break
        prefix = "".join(b.get("text", "") for b in blocks[:cut])
        dyn = "".join(b.get("text", "") for b in blocks[cut:])
        if prefix:
            prefix_count[prefix] = prefix_count.get(prefix, 0) + 1
            if prefix not in prefix_tokens:
                prefix_tokens[prefix] = len(enc.encode(prefix))
        msg_text = "\n".join(str(m.get("content", "")) for m in params.get("messages", []))
        message_tokens = enc.encode(msg_text)
        prompt_token_sequences.append(message_tokens)
        dynamic_tokens += len(enc.encode(dyn)) + len(message_tokens) + 8
        # Output heuristic mirrors countTokens(): payload tokens x 2.5 covers
        # the echoed JSON scaffold plus EN expansion.
        output_tokens += round(len(enc.encode(str(entry.get("payload", "")))) * 2.5)

    est_model = model or next(iter(models), None) or os.getenv("model", "")
    est_provider = next(iter(providers), getBatchProvider(est_model))
    # Use Anthropic's count_tokens for the exact cached-prefix size when possible.
    if prefix_tokens:
        try:
            client = _get_anthropic_client()
            for prefix in list(prefix_tokens.keys()):
                resp = client.messages.count_tokens(
                    model=est_model,
                    system=[{"type": "text", "text": prefix}],
                    messages=[{"role": "user", "content": "x"}],
                )
                prefix_tokens[prefix] = resp.input_tokens
        except Exception:
            pass  # tiktoken estimate already in place

    cache_write_tok = sum(prefix_tokens.values())
    cache_read_tok = sum(prefix_tokens[p] * (prefix_count[p] - 1) for p in prefix_count)
    raw_input_tok = sum(prefix_tokens[p] * prefix_count[p] for p in prefix_count) + dynamic_tokens

    pricing = getPricingConfig(est_model)
    in_rate = pricing["inputAPICost"] / 1_000_000
    out_rate = pricing["outputAPICost"] / 1_000_000

    batch_nocache = (raw_input_tok * in_rate + output_tokens * out_rate) * 0.50
    live_cost = raw_input_tok * in_rate + output_tokens * out_rate
    cache_kind = None
    if est_provider == "anthropic" and cache_write_tok > 0:
        # Claude's explicit 1-hour cache writes the prefix once at 2x input
        # price, then reads it at 0.10x. Batch pricing halves both charges.
        batch_cached = (cache_write_tok * in_rate * 2.00
                        + cache_read_tok * in_rate * 0.10
                        + dynamic_tokens * in_rate
                        + output_tokens * out_rate) * 0.50
        cache_kind = "explicit"
    elif est_provider == "openai":
        # OpenAI prompt caching is automatic. Cached inputs for the supported
        # GPT models are currently 10% of standard input price; Batch then
        # applies its own 50% discount.
        cache_write_tok = 0
        cache_read_tok = min(
            raw_input_tok,
            _estimate_openai_cache_reads(prompt_token_sequences),
        )
        uncached_input_tok = raw_input_tok - cache_read_tok
        batch_cached = (
            uncached_input_tok * in_rate
            + cache_read_tok * in_rate * 0.10
            + output_tokens * out_rate
        ) * 0.50
        if cache_read_tok:
            cache_kind = "automatic"
    else:
        # We do not create Gemini explicit cache resources for these jobs.
        # Implicit hits are not guaranteed, so only expose the worst case.
        cache_write_tok = 0
        cache_read_tok = 0
        batch_cached = batch_nocache
    uses_prompt_cache = cache_kind is not None
    normalized_model = str(est_model or "").lower().removeprefix("models/")
    unestimated_thinking = (
        est_provider == "gemini" and normalized_model.startswith("gemini-3")
    )

    n_reread = sum(prefix_count.values()) - len(prefix_count)
    print(f"[BATCH] {len(queue)} requests queued for {est_model}", flush=True)
    if cache_kind == "explicit":
        print(
            f"[BATCH] cached prefix: {cache_write_tok:,} tokens "
            f"(written once, re-read by {n_reread:,} requests)",
            flush=True,
        )
    elif cache_kind == "automatic":
        print(
            f"[BATCH] estimated OpenAI automatic cache reads: "
            f"{cache_read_tok:,} tokens (best-effort prefix routing)",
            flush=True,
        )
    print(
        f"[BATCH] estimated input: {raw_input_tok:,} tokens | "
        f"estimated visible output: {output_tokens:,} tokens",
        flush=True,
    )
    if cache_kind == "explicit":
        print(f"[BATCH] estimated cost: ${batch_cached:.4f} (batch + prompt cache)", flush=True)
        print(f"[BATCH]                 ${batch_nocache:.4f} (batch, no cache hits)", flush=True)
    elif cache_kind == "automatic":
        print(f"[BATCH] estimated cost: ${batch_cached:.4f} (batch + automatic cache)", flush=True)
        print(f"[BATCH]                 ${batch_nocache:.4f} (batch, no cache hits)", flush=True)
    else:
        print(f"[BATCH] estimated cost: ${batch_nocache:.4f} (batch)", flush=True)
    print(f"[BATCH]                 ${live_cost:.4f} (live API)", flush=True)
    if unestimated_thinking:
        print(
            "[BATCH] NOTE: Gemini thinking tokens are billed as output and cannot "
            "be predicted before the run; they are not included above.",
            flush=True,
        )
    return {
        "requests": len(queue),
        "model": est_model,
        "provider": est_provider,
        "cache_write_tokens": cache_write_tok,
        "cache_read_tokens": cache_read_tok,
        "dynamic_tokens": dynamic_tokens,
        "input_tokens": raw_input_tok,
        "output_tokens": output_tokens,
        "batch_cached_cost": batch_cached,
        "batch_nocache_cost": batch_nocache,
        "live_cost": live_cost,
        "uses_prompt_cache": uses_prompt_cache,
        "cache_kind": cache_kind,
        "unestimated_thinking_tokens": unestimated_thinking,
    }


def submitTranslationBatches(file_set=None, cost_estimate=None):
    """Submit queued requests to the configured provider's Batch API.

    Splits at the API limits and saves the custom_id -> cache-key mapping so
    fetchTranslationBatches can route results back. Also appends durable
    history entries (custom_ids survive later fetch/clear). Returns the batch ids.
    """
    flush_batch_queue()
    with _batch_file_lock():
        queue = _read_batch_file(BATCH_QUEUE_FILE, strict=True)
        previous_state = _read_batch_file(BATCH_STATE_FILE, strict=True)
    if not queue:
        print("[BATCH] No batch requests queued.", flush=True)
        return []

    from util.batch_providers import batch_limits, submit_batch

    batches = list(previous_state.get("batches") or [])
    submitted_keys = {
        key
        for batch in batches
        for key in (batch.get("custom_ids") or {}).values()
    }
    requests, id_map, size = [], {}, 0
    models = set()
    providers = set()
    for entry in queue.values():
        m = (entry.get("params") or {}).get("model")
        if m:
            models.add(m)
        p = entry.get("provider") or getBatchProvider(m)
        if p:
            providers.add(p)
    if len(models) != 1 or len(providers) != 1:
        raise ValueError(
            "A batch queue must contain exactly one model and one provider; "
            f"found models={sorted(models)} providers={sorted(providers)}"
        )
    provider = next(iter(providers))
    max_requests, max_bytes = batch_limits(provider)
    from util.batch_history import (
        active_key_name_for_environment,
        key_name_for_batch,
    )

    current_key_name = active_key_name_for_environment()
    existing_key_names = {
        str(info.get("key_name") or key_name_for_batch(info.get("id", "")))
        for info in batches
    } - {""}
    if existing_key_names and (
        len(existing_key_names) != 1 or current_key_name not in existing_key_names
    ):
        expected = ", ".join(sorted(existing_key_names))
        raise ValueError(
            "Remaining split requests must use the same saved API key as the "
            f"already submitted batches. Select {expected!r} and resume again."
        )
    client = _get_anthropic_client() if provider == "anthropic" else None
    model = (
        (cost_estimate or {}).get("model")
        or previous_state.get("model")
        or next(iter(models), None)
        or os.getenv("model", "")
    )
    effective_file_set = list(
        file_set if file_set is not None else previous_state.get("file_set") or []
    )
    effective_estimate = (
        cost_estimate
        if cost_estimate is not None
        else previous_state.get("cost_estimate")
    )

    def _checkpoint(new_info, *, complete):
        """Persist each paid provider job before attempting the next split."""
        state_doc = {
            "status": "submitted" if complete else "partially_submitted",
            "batches": batches,
            "submitted_at": previous_state.get("submitted_at")
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "model": model,
            "provider": provider,
            "file_set": effective_file_set,
            "cost_estimate": effective_estimate,
            "request_count": sum(
                len(batch.get("custom_ids") or {}) for batch in batches
            ),
        }
        with BATCH_LOCK:
            with _batch_file_lock():
                _write_batch_file(BATCH_STATE_FILE, state_doc)
        try:
            from util.batch_history import record_submit

            record_submit(
                [new_info],
                model=model,
                provider=provider,
                file_set=effective_file_set,
                cost_estimate=effective_estimate,
                key_name=current_key_name,
            )
        except Exception as exc:
            print(f"[BATCH] history record_submit failed: {exc}", flush=True)

    def _submit():
        nonlocal requests, id_map, size
        if not requests:
            return
        submitted = submit_batch(provider, requests, client=client)
        info = {
            **submitted,
            "custom_ids": id_map,
            "provider": provider,
            "key_name": current_key_name,
        }
        batches.append(info)
        submitted_keys.update(id_map.values())
        complete = len(submitted_keys) == len(queue)
        _checkpoint(info, complete=complete)
        print(f"[BATCH] submitted {info['id']} ({len(requests)} requests)", flush=True)
        requests, id_map, size = [], {}, 0

    for i, (key, entry) in enumerate(queue.items()):
        if key in submitted_keys:
            continue
        custom_id = f"req-{i:06d}"
        params = entry["params"]
        request_size = len(json.dumps(params, ensure_ascii=False).encode("utf-8")) + 128
        if request_size > max_bytes:
            raise ValueError(
                f"Batch request {custom_id} is {request_size:,} bytes, above the "
                f"{max_bytes:,}-byte provider limit."
            )
        if requests and (
            len(requests) >= max_requests or size + request_size > max_bytes
        ):
            _submit()
        requests.append({"custom_id": custom_id, "params": params})
        id_map[custom_id] = key
        size += request_size
    _submit()

    # A retry after the final provider job was checkpointed has no new work, but
    # older state files may still carry the partial marker. Normalize it.
    if batches and len(submitted_keys) == len(queue):
        with BATCH_LOCK:
            with _batch_file_lock():
                state_doc = _read_batch_file(BATCH_STATE_FILE)
                if state_doc.get("status") != "submitted":
                    state_doc["status"] = "submitted"
                    _write_batch_file(BATCH_STATE_FILE, state_doc)
    return [b["id"] for b in batches]


def checkTranslationBatches():
    """Print the processing status of submitted batches. True when all ended.

    Also returns a structured status list as the second value when called as
    ``ended, statuses = checkTranslationBatchStatuses()`` - prefer that helper
    for UI work. Kept for CLI/print compatibility.
    """
    ended, _statuses = checkTranslationBatchStatuses(print_status=True)
    return ended


def checkTranslationBatchStatuses(print_status=True):
    """Return (all_ended, statuses) for submitted batches.

    Each status dict: id, api_status, counts{processing,succeeded,errored,canceled,expired}.
    """
    with _batch_file_lock():
        state = _read_batch_file(BATCH_STATE_FILE)
    if not state.get("batches"):
        if print_status:
            print("[BATCH] No submitted batches - submit the queue first.", flush=True)
        return False, []
    from util.batch_history import client_for_batch
    from util.batch_providers import retrieve_batch

    all_ended = True
    statuses = []
    for info in state["batches"]:
        bid = info["id"]
        provider = info.get("provider") or state.get("provider") or "anthropic"
        client = client_for_batch(
            bid, provider, str(info.get("key_name") or "")
        )
        normalized = retrieve_batch(provider, bid, client=client)
        api_status = normalized["api_status"]
        counts = normalized["counts"]
        statuses.append({
            "id": bid,
            "provider": provider,
            "api_status": api_status,
            "counts": counts,
            "request_count": len(info.get("custom_ids") or {}),
        })
        if print_status:
            parts = [f"{k[:4]}={v}" for k, v in counts.items() if v]
            suffix = ("  " + " ".join(parts)) if parts else ""
            print(
                f"[BATCH] {time.strftime('%H:%M:%S')}  {bid}: {api_status}{suffix}",
                flush=True,
            )
        if not normalized["ended"]:
            all_ended = False
    return all_ended, statuses


def fetchTranslationBatches(batches=None):
    """Download finished batch results into the local results store.

    Successes are stored keyed by the payload cache key for the consume pass;
    errored/expired requests are reported; consume stops rather than silently
    switching to the live API
    during consume. Durable history retains custom_ids for later redownload.

    batches: optional list of {id, custom_ids} (defaults to active batch_state).
    Returns (succeeded, errored) counts.
    """
    global _batch_results
    with _batch_file_lock():
        state = _read_batch_file(BATCH_STATE_FILE)
    batch_list = batches if batches is not None else (state.get("batches") or [])
    if not batch_list:
        print("[BATCH] No submitted batches - nothing to fetch.", flush=True)
        return 0, 0

    try:
        from util.batch_history import (
            _price_usage,
            client_for_batch,
            download_batch_results,
            record_fetch,
        )
    except Exception:
        client_for_batch = None
        download_batch_results = None
        record_fetch = None
        _price_usage = None

    results, errored = {}, []
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "thinking_tokens": 0,
    }
    batch_ids = []
    history_parts = []
    for info in batch_list:
        bid = info.get("id")
        provider = info.get("provider") or state.get("provider") or "anthropic"
        if bid:
            batch_ids.append(bid)
        id_map = info.get("custom_ids", {})
        client = (
            client_for_batch(
                bid, provider, str(info.get("key_name") or "")
            )
            if client_for_batch
            else None
        )
        if download_batch_results is not None:
            part, err_part, usage_part = download_batch_results(
                bid, id_map, client=client, provider=provider
            )
        else:
            from util.batch_providers import download_results
            part, err_part, usage_part = download_results(
                provider, bid, id_map, client=client
            )
        results.update(part)
        errored.extend(err_part)
        for k, v in usage_part.items():
            usage_totals[k] = usage_totals.get(k, 0) + (v or 0)
        history_parts.append((bid, provider, part, err_part, usage_part))

    model = state.get("model") or os.getenv("model", "")
    aggregate_provider = state.get("provider") or (
        batch_list[0].get("provider") if batch_list else "anthropic"
    )
    actual_cost = None
    if _price_usage is not None and model:
        try:
            actual_cost = _price_usage(
                usage_totals, model, aggregate_provider or "anthropic"
            )
        except Exception:
            actual_cost = None

    with BATCH_LOCK:
        with _batch_file_lock():
            merged = _read_batch_file(BATCH_RESULTS_FILE)
            merged.update(results)
            _write_batch_file(BATCH_RESULTS_FILE, merged)
            # Drop the queue; keep a lightweight fetched marker (ids for consume→history).
            # custom_ids stay in durable history - do not destroy recovery maps.
            try:
                if BATCH_QUEUE_FILE.exists():
                    BATCH_QUEUE_FILE.unlink()
            except Exception:
                pass
            _write_batch_file(
                BATCH_STATE_FILE,
                {
                    "status": "fetched",
                    "batch_ids": batch_ids,
                    "batches": [],
                    "model": model,
                    "provider": state.get("provider") or (
                        batch_list[0].get("provider") if batch_list else None
                    ),
                    "file_set": state.get("file_set") or [],
                    "cost_estimate": state.get("cost_estimate"),
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
            )
        _batch_results = None

    if record_fetch is not None:
        for bid, provider, part, err_part, usage_part in history_parts:
            try:
                part_cost = None
                if _price_usage is not None and model:
                    part_cost = _price_usage(usage_part, model, provider)
                record_fetch(
                    [bid],
                    succeeded=len(part),
                    errored=len(err_part),
                    usage=usage_part,
                    actual_cost=part_cost,
                )
            except Exception as exc:
                print(
                    f"[BATCH] history record_fetch failed for {bid}: {exc}",
                    flush=True,
                )

    print(f"[BATCH] fetched {len(results)} results ({len(errored)} errored).", flush=True)
    if actual_cost is not None:
        print(f"[BATCH] actual batch usage cost (est.): ${actual_cost:.4f}", flush=True)
    for cid, why in errored[:20]:
        print(f"[BATCH]   ! {cid}: {why}", flush=True)
    if len(errored) > 20:
        print(f"[BATCH]   ... ({len(errored) - 20} more)", flush=True)
    return len(results), len(errored)


def runTranslationBatches(poll=60):
    """Submit the queue (unless already submitted), poll to completion, fetch."""
    with _batch_file_lock():
        state = _read_batch_file(BATCH_STATE_FILE)
    if not state.get("batches"):
        if not submitTranslationBatches():
            return 0, 0
    print(f"[BATCH] polling every {poll}s (Ctrl-C is safe — resume later with fetchTranslationBatches)...", flush=True)
    while not checkTranslationBatches():
        time.sleep(poll)
    return fetchTranslationBatches()


# ===== Mistral (la Plateforme) adaptive rate limiting =====
# Mistral enforces per-minute request and token limits that vary by tier/model.
# The limiter starts from a conservative seed, then pins itself to the real
# limits read from the live x-ratelimit-* response headers. One limiter is
# shared across file threads. Override seeds via
# mistralReqPerSec / mistralTokPerMin / mistralTokenHeadroom.
_mistral_limiter = None
_mistral_limiter_lock = threading.Lock()


def _estimate_mistral_tokens(text):
    # JP ~1 token/char with Mistral tokenizers; EN ~1 per 3.5 chars. Be pessimistic.
    return int(len(str(text)) * 1.1) + 8


def _header_int(headers, *names):
    """First present header among names parsed as int, else None."""
    for n in names:
        v = headers.get(n)
        if v is not None and str(v).strip() != "":
            try:
                return int(float(v))
            except (TypeError, ValueError):
                pass
    return None


def _header_float(headers, *names):
    """First present header among names parsed as float, else None.

    Used for the RPS limit header, which per-model is often FRACTIONAL
    (e.g. 0.08, 0.42, 0.83) — parsing it as int would floor those to 0."""
    for n in names:
        v = headers.get(n)
        if v is not None and str(v).strip() != "":
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return None


class AdaptiveLimiter:
    """Paces requests off live ratelimit headers.

    acquire() enforces two gates together:
      * requests: spaced >= min_interval (1/RPS) apart, so bursts can't overrun
        the per-minute request cap.
      * tokens: a minute-windowed input+output budget with a headroom margin.
    """

    def __init__(self, req_per_sec, tok_per_min, headroom):
        self.lock = threading.Lock()
        self.req_per_sec = max(0.001, float(req_per_sec))
        self.tok_per_min = tok_per_min
        self.headroom = headroom  # margin left under the TPM cap
        self.min_interval = 1.0 / self.req_per_sec
        self.next_request_at = time.monotonic()
        self.tokens_remaining = tok_per_min
        self.window_reset = time.monotonic() + 60

    def acquire(self, est_tokens):
        """Block until the request clears both the RPS pace and the TPM budget."""
        while True:
            with self.lock:
                now = time.monotonic()
                if now >= self.window_reset:
                    self.tokens_remaining = self.tok_per_min
                    self.window_reset = now + 60
                # token gate
                if self.tokens_remaining - est_tokens <= self.headroom:
                    sleep_for = max(0.05, self.window_reset - now)
                # request-pace gate
                elif now < self.next_request_at:
                    sleep_for = self.next_request_at - now
                else:
                    # both gates clear — reserve this slot
                    self.next_request_at = max(now, self.next_request_at) + self.min_interval
                    self.tokens_remaining -= est_tokens
                    return
            time.sleep(min(sleep_for, 5))

    def update(self, headers):
        """Sync budgets from the live ratelimit headers."""
        if not headers:
            return
        with self.lock:
            # Mistral's documented request cap is x-ratelimit-limit-requests
            # (RPM); accept alternate spellings too and /60 to a pacing interval.
            # A true per-second header, if present, is used undivided.
            limit_rps = _header_float(headers, "x-ratelimit-limit-req-second",
                                      "x-ratelimit-limit-requests-second")
            if limit_rps is None:
                limit_rpm = _header_float(headers, "x-ratelimit-limit-requests",
                                          "x-ratelimit-limit-req-minute",
                                          "x-ratelimit-limit-requests-minute")
                if limit_rpm is not None:
                    limit_rps = limit_rpm / 60.0
            if limit_rps and limit_rps > 0:
                self.req_per_sec = limit_rps
                self.min_interval = 1.0 / self.req_per_sec
            limit_tok = _header_int(headers, "x-ratelimit-limit-tokens",
                                    "x-ratelimit-limit-tokens-minute")
            if limit_tok and limit_tok > 0:
                self.tok_per_min = limit_tok
            rem_tok = _header_int(headers, "x-ratelimit-remaining-tokens",
                                  "x-ratelimit-remaining-tokens-minute")
            if rem_tok is not None:
                self.tokens_remaining = rem_tok
            # If the minute's request budget is already spent, hold off ~a minute.
            rem_req = _header_int(headers, "x-ratelimit-remaining-requests",
                                  "x-ratelimit-remaining-req-minute",
                                  "x-ratelimit-remaining-requests-minute")
            if rem_req is not None and rem_req <= 0:
                self.next_request_at = max(self.next_request_at, time.monotonic() + 60.0)


def _get_mistral_limiter():
    global _mistral_limiter
    with _mistral_limiter_lock:
        if _mistral_limiter is None:
            # mistralReqPerMin is a deprecated per-minute alias, converted to RPS.
            rps_env = os.getenv("mistralReqPerSec")
            if rps_env:
                req_per_sec = float(rps_env)
            elif os.getenv("mistralReqPerMin"):
                req_per_sec = max(0.05, float(os.getenv("mistralReqPerMin")) / 60.0)
            else:
                # Conservative seed; the first response's headers correct it.
                req_per_sec = 0.5
            _mistral_limiter = AdaptiveLimiter(
                req_per_sec,
                int(os.getenv("mistralTokPerMin", "50000") or 50000),
                int(os.getenv("mistralTokenHeadroom", "4000") or 4000),
            )
        return _mistral_limiter


def callMistral(params, retries=6):
    """Call the Mistral chat completions endpoint with adaptive pacing.

    Acquires from the shared limiter before each attempt, syncs budgets from
    the live x-ratelimit headers after each response, honours Retry-After on
    429, backs off with jitter on 5xx/network errors, and downgrades
    json_schema -> json_object for models without structured-output support.
    """
    limiter = _get_mistral_limiter()
    est = sum(_estimate_mistral_tokens(m.get("content", "")) for m in params.get("messages", []))
    est += params.get("max_tokens", 0) // 2
    last_error = None
    for attempt in range(retries + 1):
        limiter.acquire(est)
        try:
            raw = openai.chat.completions.with_raw_response.create(**params)
            response = raw.parse()
            limiter.update(raw.headers)
            return response
        except RateLimitError as e:
            last_error = e
            resp = getattr(e, "response", None)
            limiter.update(getattr(resp, "headers", None))
            retry_after = None
            try:
                retry_after = float(resp.headers.get("retry-after"))
            except (AttributeError, TypeError, ValueError):
                pass
            time.sleep(retry_after if retry_after is not None else min(60, 2 ** attempt + random.random() * 2))
        except APIStatusError as e:
            last_error = e
            # Mistral rejects unsupported params with 400/422 — downgrade the
            # structured-output format once and retry immediately.
            if e.status_code in (400, 422) and (params.get("response_format") or {}).get("type") == "json_schema":
                params = dict(params)
                params["response_format"] = {"type": "json_object"}
                continue
            if e.status_code >= 500 and attempt < retries:
                time.sleep(min(45, 2 ** attempt + random.random()))
                continue
            raise Exception(f"Mistral API error ({e.status_code}): {e}")
        except APIConnectionError as e:
            last_error = e
            if attempt < retries:
                time.sleep(min(45, 2 ** attempt + random.random()))
                continue
            raise Exception(f"Mistral connection error: {e}")
    raise Exception(f"Mistral API failed after {retries + 1} attempts: {last_error}")


class TranslationConfig:
    """Configuration class to hold all translation settings"""
    
    def __init__(self, 
                 model=None,
                 language=None,
                 prompt=None,
                 vocab=None,
                 langRegex=None,
                 batchSize=None,
                 maxHistory=10,
                 estimateMode=False,
                 logFilePath="log/translationHistory.txt",
                 mismatchLogPath="log/mismatchHistory.txt",
                 convertQuotes=None,
                 useSfxReference=None):
        
        # Load from environment if not provided
        self.model = model or os.getenv("model")
        self.language = (language or os.getenv("language", "english")).capitalize()
        
        # Load prompt and vocab files if not provided
        if prompt is None:
            try:
                from util.skills import load_system_prompt
                self.prompt = load_system_prompt()
            except FileNotFoundError:
                self.prompt = ""
        else:
            self.prompt = prompt
            
        if vocab is None:
            try:
                self.vocab = read_active_glossary()
            except OSError:
                self.vocab = ""
        else:
            self.vocab = vocab
        
        # Set language regex (default is Japanese)
        self.langRegex = langRegex or r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+"
        
        # Set batch size — derive from pricing config unless explicitly supplied
        if batchSize is None:
            self.batchSize = getPricingConfig(self.model)["batchSize"]
        else:
            self.batchSize = batchSize
            
        self.maxHistory = maxHistory
        self.estimateMode = estimateMode
        self.logFilePath = logFilePath
        self.mismatchLogPath = mismatchLogPath
        if convertQuotes is None:
            self.convertQuotes = os.getenv("convertQuotes", "true").strip().lower() in (
                "true", "1", "yes",
            )
        else:
            self.convertQuotes = bool(convertQuotes)
        if useSfxReference is None:
            self.useSfxReference = os.getenv(
                "useSfxReference", "true"
            ).strip().lower() in ("true", "1", "yes")
        else:
            self.useSfxReference = bool(useSfxReference)


def convert_corner_brackets(text, enabled=True):
    """Replace Japanese corner brackets 「」『』 with ASCII double quotes when enabled."""
    if not enabled or not isinstance(text, str):
        return text
    return (
        text.replace("「", '"')
        .replace("」", '"')
        .replace("『", '"')
        .replace("』", '"')
    )


_LITELLM_PRICING_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main"
    "/model_prices_and_context_window.json"
)
_PRICING_CACHE_FILE = Path("log/litellm_pricing.json")
_PRICING_CACHE_TTL  = 86_400  # 24 hours
_pricing_db: dict | None = None
_pricing_db_fetched_at: float = 0.0
_pricing_db_lock = threading.Lock()
_pricing_fetch_warned: bool = False  # print fetch-failure warning at most once per session


def _load_litellm_pricing() -> dict | None:
    """Return the LiteLLM pricing DB, using a 24-hour disk cache."""
    global _pricing_db, _pricing_db_fetched_at, _pricing_fetch_warned

    with _pricing_db_lock:
        now = time.time()

        # In-memory cache still fresh
        if _pricing_db is not None and (now - _pricing_db_fetched_at) < _PRICING_CACHE_TTL:
            return _pricing_db

        # Try disk cache
        if _PRICING_CACHE_FILE.exists():
            try:
                disk = json.loads(_PRICING_CACHE_FILE.read_text(encoding="utf-8"))
                if (now - disk.get("fetched_at", 0)) < _PRICING_CACHE_TTL:
                    _pricing_db = disk["prices"]
                    _pricing_db_fetched_at = disk["fetched_at"]
                    return _pricing_db
            except Exception:
                pass

        # Fetch from GitHub
        try:
            with urllib.request.urlopen(_LITELLM_PRICING_URL, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            _pricing_db = data
            _pricing_db_fetched_at = now
            _pricing_fetch_warned = False  # reset if a later fetch succeeds
            try:
                _PRICING_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                _PRICING_CACHE_FILE.write_text(
                    json.dumps({"fetched_at": now, "prices": data}),
                    encoding="utf-8",
                )
            except Exception:
                pass
            return _pricing_db
        except Exception as fetch_err:
            # No internet / GitHub unreachable — warn once, then fall back
            if not _pricing_fetch_warned:
                _pricing_fetch_warned = True
                print(
                    f"[PRICING] Warning: Could not fetch live model pricing "
                    f"({fetch_err}). Cost estimates may be inaccurate — "
                    f"using built-in fallback prices.",
                    flush=True,
                )
            # Use stale disk cache if available
            if _pricing_db is not None:
                return _pricing_db
            try:
                disk = json.loads(_PRICING_CACHE_FILE.read_text(encoding="utf-8"))
                _pricing_db = disk["prices"]
                return _pricing_db
            except Exception:
                return None


def _lookup_model_price(model: str):
    """Look up (input_per_1M, output_per_1M) from the LiteLLM pricing DB.

    Returns a (float, float) tuple or None if not found.
    Matching priority:
      1. Exact key match
      2. Exact match on the model portion after a provider prefix (e.g. "deepseek/deepseek-chat")
      3. The user's model name is a prefix of a DB key (handles dated suffixes like -20241022)
      4. A DB key model-part is a prefix of the user's model name
    """
    db = _load_litellm_pricing()
    if not db:
        return None

    model_lower = str(model or "").strip().lower()
    # Google APIs and the Gen AI SDK may return resource-style model names
    # (``models/gemini-...``), while pricing catalogs use the bare model id.
    # Leaving the resource prefix in place can accidentally prefix-match an
    # unrelated generic catalog entry with incomplete prices.
    if model_lower.startswith("models/"):
        model_lower = model_lower.removeprefix("models/")

    def _extract(entry):
        inp = entry.get("input_cost_per_token")
        out = entry.get("output_cost_per_token")
        if inp is not None and out is not None:
            return round(inp * 1_000_000, 6), round(out * 1_000_000, 6)
        return None

    # Pass 1: exact key
    if model_lower in db:
        result = _extract(db[model_lower])
        if result:
            return result

    # Build a lookup of (stripped_key → original_key) for passes 2-4
    stripped: list[tuple[str, str]] = []
    for key in db:
        stripped.append((key.split("/")[-1].lower(), key))

    # Pass 2: exact match on stripped key
    for skey, orig in stripped:
        if skey == model_lower:
            result = _extract(db[orig])
            if result:
                return result

    # Pass 3: model name is a prefix of the DB key (e.g. "claude-3-5-sonnet" matches
    #          "claude-3-5-sonnet-20241022")
    candidates = [(skey, orig) for skey, orig in stripped if skey.startswith(model_lower)]
    if candidates:
        # Prefer the shortest (most generic) key
        skey, orig = min(candidates, key=lambda x: len(x[0]))
        result = _extract(db[orig])
        if result:
            return result

    # Pass 4: DB key is a prefix of the model name (e.g. "gemini-2.0-flash" matches
    #          "gemini-2.0-flash-exp")
    candidates = [(skey, orig) for skey, orig in stripped if model_lower.startswith(skey)]
    if candidates:
        skey, orig = max(candidates, key=lambda x: len(x[0]))  # longest = most specific
        result = _extract(db[orig])
        if result:
            return result

    return None


def getPricingConfig(model):
    """
    Get pricing configuration for a given model.
    
    Args:
        model: The model name string
        
    Returns:
        dict: Dictionary containing inputAPICost, outputAPICost, batchSize, and frequencyPenalty
    """
    # Try to resolve pricing from the LiteLLM community pricing DB first.
    # This keeps costs accurate as providers update their prices without requiring
    # a code change.  Falls back to the hardcoded table below on failure.
    live_price = _lookup_model_price(model)
    if live_price:
        inp, out = live_price
        # Preserve model-specific batch / penalty overrides from the hardcoded table
        # by still running through the if-chain but replacing the cost fields.
        _live_override = {"inputAPICost": inp, "outputAPICost": out}
    else:
        _live_override = None

    # Hardcoded fallback table — used for batchSize / frequencyPenalty tuning and
    # as a cost fallback when the LiteLLM DB is unavailable.
    # Batch Size: GPT-3.5 struggles past 15 lines; GPT-4 struggles past 50.
    # If you get a MISMATCH LENGTH error, lower the batch size.
    if "gpt-3.5" in model:
        cfg = {"inputAPICost": 3.00,  "outputAPICost": 5.00,  "batchSize": 10, "frequencyPenalty": 0.2}
    elif "gpt-4.1-mini" in model:
        cfg = {"inputAPICost": 0.40,  "outputAPICost": 1.60,  "batchSize": 30, "frequencyPenalty": 0.05}
    elif "gpt-4.1" in model:
        cfg = {"inputAPICost": 2.00,  "outputAPICost": 8.00,  "batchSize": 30, "frequencyPenalty": 0.05}
    elif "gpt-5" in model:
        cfg = {"inputAPICost": 1.25,  "outputAPICost": 10.00, "batchSize": 30, "frequencyPenalty": 0.05}
    elif "deepseek" in model:
        cfg = {"inputAPICost": 0.27,  "outputAPICost": 1.10,  "batchSize": 30, "frequencyPenalty": 0.05}
    # Mistral — system prompt is resent per request (no prompt caching), so
    # throughput/cost favor larger batches. Live LiteLLM pricing overrides these.
    elif "mistral-large" in model or "pixtral-large" in model:
        cfg = {"inputAPICost": 2.00,  "outputAPICost": 6.00,  "batchSize": 40, "frequencyPenalty": 0.0}
    elif "magistral-medium" in model:
        cfg = {"inputAPICost": 2.00,  "outputAPICost": 5.00,  "batchSize": 40, "frequencyPenalty": 0.0}
    elif "mistral-medium-3.5" in model or "mistral-medium-3-5" in model or "mistral-medium-26" in model:
        # Medium 3.5 (v26.04) — also matches dated 26xx ids
        cfg = {"inputAPICost": 1.50,  "outputAPICost": 7.50,  "batchSize": 40, "frequencyPenalty": 0.0}
    elif "mistral-medium" in model:
        # Medium 3 / 3.1 (what -latest still points at)
        cfg = {"inputAPICost": 0.40,  "outputAPICost": 2.00,  "batchSize": 40, "frequencyPenalty": 0.0}
    elif "magistral-small" in model:
        cfg = {"inputAPICost": 0.50,  "outputAPICost": 1.50,  "batchSize": 40, "frequencyPenalty": 0.0}
    elif "mistral-small" in model:
        cfg = {"inputAPICost": 0.10,  "outputAPICost": 0.30,  "batchSize": 40, "frequencyPenalty": 0.0}
    elif "ministral" in model or "open-mistral" in model or "mistral-nemo" in model:
        cfg = {"inputAPICost": 0.10,  "outputAPICost": 0.10,  "batchSize": 40, "frequencyPenalty": 0.0}
    elif "codestral" in model:
        cfg = {"inputAPICost": 0.30,  "outputAPICost": 0.90,  "batchSize": 40, "frequencyPenalty": 0.0}
    elif "mistral" in model or "pixtral" in model:
        cfg = {"inputAPICost": 2.00,  "outputAPICost": 6.00,  "batchSize": 40, "frequencyPenalty": 0.0}
    elif "claude-opus-4-5" in model or "claude-opus-4-6" in model:
        cfg = {"inputAPICost": 5.00,  "outputAPICost": 25.00, "batchSize": 30, "frequencyPenalty": 0.05}
    elif "claude-opus" in model or model == "claude-3-opus":
        # Opus 4, 4.1, 3 — $15/$75
        cfg = {"inputAPICost": 15.00, "outputAPICost": 75.00, "batchSize": 30, "frequencyPenalty": 0.05}
    elif "claude-haiku-4-5" in model or "claude-haiku-4-6" in model:
        cfg = {"inputAPICost": 1.00,  "outputAPICost": 5.00,  "batchSize": 30, "frequencyPenalty": 0.05}
    elif "claude-haiku-3-5" in model:
        cfg = {"inputAPICost": 0.80,  "outputAPICost": 4.00,  "batchSize": 30, "frequencyPenalty": 0.05}
    elif "claude-3-haiku" in model:
        cfg = {"inputAPICost": 0.25,  "outputAPICost": 1.25,  "batchSize": 30, "frequencyPenalty": 0.05}
    elif "haiku" in model:
        # Unknown haiku version — use current flagship pricing as best guess
        cfg = {"inputAPICost": 1.00,  "outputAPICost": 5.00,  "batchSize": 30, "frequencyPenalty": 0.05}
    elif "sonnet" in model or "claude" in model:
        cfg = {"inputAPICost": 3.00,  "outputAPICost": 15.00, "batchSize": 30, "frequencyPenalty": 0.05}
    elif "gemini-3.6-flash" in model:
        # Google AI Developer API standard rates. Batch is applied separately
        # by estimateBatchCost/_price_usage at the provider's 50% discount.
        cfg = {"inputAPICost": 1.50, "outputAPICost": 7.50, "batchSize": 30, "frequencyPenalty": 0.0}
    elif "gemini-3.5-flash-lite" in model:
        cfg = {"inputAPICost": 0.30, "outputAPICost": 2.50, "batchSize": 30, "frequencyPenalty": 0.0}
    elif "gemini-3.5-flash" in model:
        cfg = {"inputAPICost": 1.50, "outputAPICost": 9.00, "batchSize": 30, "frequencyPenalty": 0.0}
    elif "gemini-2.0-flash-lite" in model:
        cfg = {"inputAPICost": 0.075, "outputAPICost": 0.30,  "batchSize": 30, "frequencyPenalty": 0.0}
    elif "gemini-2.0-flash" in model:
        cfg = {"inputAPICost": 0.10,  "outputAPICost": 0.40,  "batchSize": 30, "frequencyPenalty": 0.0}
    elif "gemini-2.5-flash-lite" in model:
        cfg = {"inputAPICost": 0.10,  "outputAPICost": 0.40,  "batchSize": 30, "frequencyPenalty": 0.0}
    elif "gemini-2.5-flash" in model:
        cfg = {"inputAPICost": 0.30,  "outputAPICost": 2.50,  "batchSize": 30, "frequencyPenalty": 0.0}
    elif "gemini-2.5-pro" in model:
        cfg = {"inputAPICost": 1.25,  "outputAPICost": 10.00, "batchSize": 30, "frequencyPenalty": 0.0}
    else:
        cfg = {
            "inputAPICost":    float(os.getenv("input_cost", 3.00)),
            "outputAPICost":   float(os.getenv("output_cost", 6.00)),
            "batchSize":       int(os.getenv("batchsize", 10)),
            "frequencyPenalty": float(os.getenv("frequency_penalty", 0.2)),
        }

    # Apply live pricing from LiteLLM if available — keeps costs up-to-date
    # without requiring code changes when providers reprice their models.
    if _live_override:
        cfg.update(_live_override)

    # Config / .env overrides win over model defaults so the Batch Size and
    # Frequency Penalty controls actually affect translation batching.
    env_batch = os.getenv("batchsize")
    if env_batch not in (None, ""):
        try:
            cfg["batchSize"] = max(1, int(env_batch))
        except (TypeError, ValueError):
            pass
    env_penalty = os.getenv("frequency_penalty")
    if env_penalty not in (None, ""):
        try:
            cfg["frequencyPenalty"] = float(env_penalty)
        except (TypeError, ValueError):
            pass

    return cfg


def batchList(inputList, batchSize):
    """Split a list into batches of specified size"""
    if not isinstance(batchSize, int) or batchSize <= 0:
        raise ValueError("batchSize must be a positive integer")
    
    return [inputList[i : i + batchSize] for i in range(0, len(inputList), batchSize)]


def parseVocabWithCategories(vocabText):
    """Parse vocabulary text and extract terms with their categories."""
    pairs = []
    seen = set()
    currentCategory = None
    
    for line in vocabText.splitlines():
        line = line.strip()
        if (
            not line
            or line.startswith('```')
            or line.startswith(('Here are some vocabulary', 'Here are glossary entries'))
        ):
            continue
        
        # Check if this is a category header
        if line.startswith('#'):
            currentCategory = line
            continue
            
        # Parse vocabulary term - extract both Japanese and English parts.
        # Rich entries may continue after the first parenthesized translation,
        # e.g. "サンク (Sank) - Male; protagonist..."; only "Sank" is the match key.
        paren_match = re.match(r'^(.+?)\s*\(([^()]*)\)', line)
        dash_match = re.match(r'^(.+?)\s+[–-]\s+(.+)$', line)
        if paren_match:
            japanese_term = paren_match.group(1).strip()
            english_term = paren_match.group(2).strip()
            
            # Create a tuple with both terms for matching
            term_pair = (japanese_term, english_term)
            if term_pair not in seen:
                pairs.append((term_pair, line, currentCategory))
                seen.add(term_pair)
        elif dash_match:
            japanese_term = dash_match.group(1).strip()
            english_term = dash_match.group(2).strip()
            
            # Create a tuple with both terms for matching
            term_pair = (japanese_term, english_term)
            if term_pair not in seen:
                pairs.append((term_pair, line, currentCategory))
                seen.add(term_pair)
        elif line and not line.startswith('#'):
            # Fallback for lines without parentheses - treat as single term
            term = line.strip()
            if term and term not in seen:
                pairs.append((term, line, currentCategory))
                seen.add(term)
    
    return pairs


def _japanese_term_in_text(term, text):
    """
    Check if a Japanese term appears in text as a standalone word, not as a
    substring of a longer run of the same script (katakana/hiragana/kanji).
    E.g. 'キス' will NOT match inside 'テキスト' because both neighbours are katakana.
    Falls back to plain substring check for non-Japanese or mixed terms.
    """
    if term not in text:
        return False
    KATAKANA = r'ァ-ヴーｦ-ﾟ'
    HIRAGANA = r'ぁ-ゔ'
    KANJI = r'一-龠'
    if re.search(rf'[{KATAKANA}]', term) and not re.search(rf'[{HIRAGANA}{KANJI}]', term):
        pattern = rf'(?<![{KATAKANA}]){re.escape(term)}(?![{KATAKANA}])'
    elif re.search(rf'[{HIRAGANA}]', term) and not re.search(rf'[{KATAKANA}{KANJI}]', term):
        pattern = rf'(?<![{HIRAGANA}]){re.escape(term)}(?![{HIRAGANA}])'
    elif re.search(rf'[{KANJI}]', term) and not re.search(rf'[{KATAKANA}{HIRAGANA}]', term):
        pattern = rf'(?<![{KANJI}]){re.escape(term)}(?![{KANJI}])'
    else:
        return True  # mixed-script term: plain substring match already confirmed above
    return bool(re.search(pattern, text))


def _vocab_term_in_text(term, text):
    """Match any vocab term variant against the current batch text."""
    if not term:
        return False

    variants = [str(term).strip()]
    if isinstance(term, str):
        variants.extend(part.strip() for part in re.split(r"[,、]", term) if part.strip())

    for variant in variants:
        if not variant:
            continue
        if re.search(r'[一-龠ぁ-ゔァ-ヴーｦ-ﾟ｡-ﾟ]', variant):
            if _japanese_term_in_text(variant, text):
                return True
        elif variant in text:
            return True

    return False


def _collect_json_string_values(value):
    """Collect only translatable string values from a parsed JSON payload."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        values = []
        for item in value:
            values.extend(_collect_json_string_values(item))
        return values
    if isinstance(value, dict):
        values = []
        for item in value.values():
            values.extend(_collect_json_string_values(item))
        return values
    return []


def _text_for_vocab_search(subbedText):
    """Return text that should participate in vocab matching."""
    text = str(subbedText)
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r'^```(?:json)?\s*', '', stripped, flags=re.IGNORECASE)
        stripped = re.sub(r'\s*```$', '', stripped)

    try:
        parsed = json.loads(stripped)
    except (TypeError, json.JSONDecodeError):
        return text

    values = _collect_json_string_values(parsed)
    return "\n".join(values) if values else text


def buildMatchedVocabText(vocabPairs, subbedText, history=None):
    """Build formatted vocabulary text for terms found in the current batch."""
    matchedCategories = {}

    # Generated # Speakers entries can overlap hand-curated character entries.
    # Keep only the highest-authority spelling for each character source.
    character_authority = {}
    for candidate_term, candidate_line, candidate_category in vocabPairs:
        if not isinstance(candidate_term, tuple) or len(candidate_term) != 2:
            continue
        candidate_name = str(candidate_category or "").lstrip("#").strip().casefold()
        candidate_primary = re.split(
            r"\s*[·・|/]\s*", candidate_name, maxsplit=1
        )[0]
        priority = {"game characters": 2, "speakers": 1}.get(candidate_primary, 0)
        if not priority:
            continue
        source = candidate_term[0]
        previous = character_authority.get(source)
        if previous is None or priority > previous[0]:
            character_authority[source] = (priority, candidate_line)

    # Only match against the current request text. History is deliberately not
    # searched so stale terms are not resent in unrelated batches.
    textToSearch = _text_for_vocab_search(subbedText)

    # Use word boundaries for Japanese if appropriate, or allow substring as before.
    for term, line, category in vocabPairs:
        # Check if term is a tuple (Japanese, English) or a single term
        term_found = False
        if isinstance(term, tuple):
            # Check both Japanese and English terms
            japanese_term, english_term = term
            category_name = str(category or "").lstrip("#").strip().casefold()
            category_primary = re.split(
                r"\s*[·・|/]\s*", category_name, maxsplit=1
            )[0]
            authoritative = character_authority.get(japanese_term)
            if authoritative is not None and authoritative[1] != line:
                continue
            japanese_match = _vocab_term_in_text(japanese_term, textToSearch)
            # Character names often appear inside compound event/map labels,
            # e.g. ユウイベント. For character sections only, a substring is
            # intentional and should still attach the authoritative spelling.
            if (
                not japanese_match
                and category_primary in {"game characters", "speakers"}
                and japanese_term in textToSearch
            ):
                japanese_match = True
            if japanese_match or _vocab_term_in_text(english_term, textToSearch):
                term_found = True
        else:
            # Single term check
            if _vocab_term_in_text(term, textToSearch):
                term_found = True
        
        if term_found:
            if category not in matchedCategories:
                matchedCategories[category] = []
            matchedCategories[category].append(line)

    # Format matched vocabulary with categories
    if matchedCategories:
        formattedLines = [
            "Here are glossary entries with the approved spelling and translation.\n"
        ]
        for category, lines in matchedCategories.items():
            if category:  # Only add category header if it exists
                formattedLines.append(category)
            formattedLines.extend(lines)
            formattedLines.append("")  # Add blank line between categories
        matchedVocabText = f"\n{chr(10).join(formattedLines).rstrip()}\n"
    else:
        matchedVocabText = ""
    
    return matchedVocabText


def createContextParts(config, subbedText, formatType, history=None):
    """Create separate glossary, SFX-reference, system, and user context.

    Returns ``(static_system, glossary_text, sfx_text, user)``. Both dynamic
    blocks stay outside Claude's cached static prefix, while remaining
    distinguishable for evaluation and review exports.

    Cached in static_system:
      - data/skills/system.md content (plus optional game Translation Frame / quirks / custom overlays)

    Dynamic:
      - only glossary terms found in the current batch text
      - only SFX reference records found in the current batch text
    """
    vocabPairs = parseVocabWithCategories(config.vocab)
    matchedVocabText = buildMatchedVocabText(vocabPairs, subbedText, history)
    matchedSfxText = build_sfx_reference_text(
        subbedText,
        enabled=bool(getattr(config, "useSfxReference", True)),
    )

    static_system = config.prompt.replace("English", config.language)

    if formatType == "json":
        user = f"```json\n{subbedText}\n```"
    else:
        user = subbedText

    return static_system, matchedVocabText, matchedSfxText, user


def createContext(config, subbedText, formatType, history=None):
    """Backward-compatible combined dynamic-context wrapper."""
    static_system, glossary_text, sfx_text, user = createContextParts(
        config, subbedText, formatType, history
    )
    return static_system, glossary_text + sfx_text, user


def createTranslationSchema(numLines):
    """Create a JSON schema for translation response based on number of lines."""
    properties = {}
    required = []
    for i in range(1, numLines + 1):
        line_key = f"Line{i}"
        properties[line_key] = {"type": "string"}
        required.append(line_key)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _anthropic_content_text(content) -> str:
    """Join text from Anthropic message content blocks.

    Newer Claude models often return a ThinkingBlock (no ``.text``) before the
    TextBlock. Only blocks that expose ``.text`` contribute to the result.
    """
    if not content:
        return ""
    return "".join(getattr(b, "text", "") or "" for b in content)


class _AnthropicCompat:
    """OpenAI-shaped wrapper around an Anthropic response (text + usage)."""
    class _Usage:
        def __init__(self, prompt, completion, cr, cw):
            self.prompt_tokens               = prompt
            self.completion_tokens           = completion
            self.cache_read_input_tokens     = cr
            self.cache_creation_input_tokens = cw
        @property
        def model_extra(self):
            return {
                "cache_read_input_tokens":     self.cache_read_input_tokens,
                "cache_creation_input_tokens": self.cache_creation_input_tokens,
            }
    class _Choice:
        class _Msg:
            def __init__(self, c): self.content = c
        def __init__(self, c):
            self.message = _AnthropicCompat._Choice._Msg(c)
    def __init__(self, text, prompt, output, cr, cw):
        self.choices = [_AnthropicCompat._Choice(text)]
        self.usage   = _AnthropicCompat._Usage(prompt, output, cr, cw)


def buildClaudeRequest(system, user, history, formatType, model, numLines=None, vocab_text=""):
    """Build the native Anthropic request kwargs.

    Shared by live calls (translateText) and batch collection (translateAI) so
    both produce byte-identical requests and share the same prompt cache. Only
    the static prompt is cached — 1h TTL so async batch requests processed
    minutes apart still hit it; vocab and history ride in messages so they
    never bust the prefix cache (the entire system parameter is the cache key).
    """
    if DISABLE_CACHE:
        # No cache_control — sends as a plain content block for a real uncached run.
        combined_system = system + vocab_text
        ant_system = [{"type": "text", "text": f"```\n{combined_system}\n```"}]
    else:
        ant_system = [{"type": "text", "text": f"```\n{system}\n```", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]

    native_msgs = [{"role": "user", "content": f"```\n{user}\n```"}]

    # Vocab goes into messages as a user turn so it doesn't bust the prefix cache.
    if vocab_text and vocab_text.strip():
        native_msgs.insert(0, {"role": "user", "content": vocab_text.strip()})
        native_msgs.insert(1, {"role": "assistant", "content": "Understood."})

    # History also goes into messages, NOT ant_system.
    if isinstance(history, list):
        history_items = [str(h) for h in history if h and str(h).strip()]
    else:
        history_items = [str(history)] if history and str(history).strip() else []
    if history_items:
        history_block = "Translation History:\n```\n" + "\n".join(history_items) + "\n```"
        native_msgs.insert(0, {"role": "user", "content": history_block})
        native_msgs.insert(1, {"role": "assistant", "content": "Understood."})

    ant_kwargs = dict(
        model=model,
        max_tokens=16384,
        system=ant_system,
        messages=native_msgs,
    )
    if formatType == "json" and numLines is not None:
        ant_kwargs["output_config"] = {
            "format": {
                "type": "json_schema",
                "schema": createTranslationSchema(numLines),
            }
        }
    elif not _NO_SAMPLING_RE.search(model or ""):
        # Plain completions still allow explicit sampling params (except on
        # Opus 4.7+ which rejects them with a 400).
        ant_kwargs["temperature"] = 0
    # Do not pass temperature with output_config: newer Claude (e.g. Opus 4.7)
    # returns errors such as "temperature is not supported" for structured outputs.
    return ant_kwargs


def buildOpenAIRequest(system, user, history, penalty, formatType, model,
                       numLines=None, vocab_text="", api_provider=None):
    """Build OpenAI-compatible kwargs shared by live and batch requests."""
    if not system or not str(system).strip():
        raise ValueError("System content cannot be empty")
    if not user or not str(user).strip():
        raise ValueError("User content cannot be empty")

    provider = (api_provider or os.getenv("API_PROVIDER", "openai")).lower()
    model_l = str(model or "").lower()
    is_deepseek = "deepseek" in model_l
    is_mistral = provider == "mistral" or isMistralAPI()
    messages = [{"role": "system", "content": f"```\n{system + vocab_text}\n```"}]
    if isinstance(history, list):
        valid_history = [h for h in history if h and str(h).strip()]
        if valid_history:
            messages.append({"role": "system", "content": "Translation History:\n```"})
            messages.extend({"role": "assistant", "content": h} for h in valid_history)
            messages.append({"role": "system", "content": "```"})
    elif history and str(history).strip():
        messages.append({"role": "assistant", "content": history})
    messages.append({"role": "user", "content": f"```\n{user}\n```"})

    params = {"model": model, "messages": messages}
    if formatType == "json" and numLines is not None:
        params["response_format"] = (
            {"type": "json_object"}
            if is_deepseek else {
                "type": "json_schema",
                "json_schema": {
                    "name": "translation_response",
                    "strict": True,
                    "schema": createTranslationSchema(numLines),
                },
            }
        )

    if provider == "gemini":
        params["temperature"] = 0
        thinking_budget_str = os.getenv("GEMINI_THINKING_BUDGET")
        if thinking_budget_str:
            try:
                params["extra_body"] = {
                    "extra_body": {
                        "google": {
                            "thinking_config": {
                                "thinking_budget": int(thinking_budget_str)
                            }
                        }
                    }
                }
            except (ValueError, TypeError):
                pass
    elif is_mistral:
        params["temperature"] = 0
        params["max_tokens"] = min(
            16000, max(1500, int(len(str(user)) * 1.2) + 40 * (numLines or 1))
        )
    elif "gpt-5" in model_l:
        params["reasoning_effort"] = "none" if "gpt-5.6" in model_l else "minimal"
    else:
        params["temperature"] = 0
        params["frequency_penalty"] = penalty
    return params


def translateText(system, user, history, penalty, formatType, model, numLines=None, vocab_text=""):
    """Send translation request to the selected API.

    system:     Static system prompt (data/skills/system.md). Cached by Claude.
    vocab_text: Per-batch vocabulary (dynamic, never cached to avoid cache busting).
    """
    # Ensure system content is not empty
    if not system or not str(system).strip():
        raise ValueError("System content cannot be empty")
    
    _live_api_check = os.getenv("api", "").strip()
    # Only route to the native Anthropic SDK when the model looks like Claude AND
    # the configured API URL is either unset (implying default Anthropic usage) or
    # explicitly points at anthropic.com.  Any other custom URL (e.g. DeepSeek,
    # OpenAI proxy) should use the OpenAI-compatible path even for Claude-named models.
    _is_claude = (
        model
        and any(x in model.lower() for x in ("claude", "sonnet", "haiku", "opus"))
        and (not _live_api_check or "anthropic" in _live_api_check.lower())
    )
    _is_deepseek = model and "deepseek" in model.lower()
    _is_mistral = not _is_claude and isMistralAPI()

    # Build message list.
    # Claude: static prompt gets cache_control; vocab appended uncached so it
    # never busts the cache. Requires ≥2048 tokens for Sonnet 4.6 to qualify.
    # Other providers: combine into one plain string.
    if _is_claude or getattr(_thread_local, 'file_cost_ready', False):
        if DISABLE_CACHE:
            # No cache_control — sends as a plain content block for a real uncached run.
            combined_system = system + vocab_text
            content_blocks = [{"type": "text", "text": f"```\n{combined_system}\n```"}]
        else:
            # Only the static prompt goes in the system content blocks.
            # Vocab and history are moved to messages so they don't bust the
            # Anthropic prefix cache (the entire system parameter is part of
            # the cache key, not just blocks up to cache_control).
            content_blocks = [{"type": "text", "text": f"```\n{system}\n```", "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
        msg = [{"role": "system", "content": content_blocks}]
    else:
        combined_system = system + vocab_text
        msg = [{"role": "system", "content": f"```\n{combined_system}\n```"}]

    # History
    if isinstance(history, list):
        # Filter out empty or None history items to prevent API errors
        valid_history = [h for h in history if h and str(h).strip()]
        if valid_history:
            msg.append({"role": "system", "content": "Translation History:\n```"})
            msg.extend([{"role": "assistant", "content": h} for h in valid_history])
            msg.append({"role": "system", "content": "```"})
    else:
        if history and str(history).strip():
            msg.append({"role": "assistant", "content": history})

    # Response format per provider:
    # OpenAI/Gemini: json_schema  |  Deepseek: json_object  |  text: omit entirely

    if formatType == "json" and numLines is not None:
        if _is_deepseek:
            # Deepseek: use json_object (no strict schema support)
            responseFormat = {"type": "json_object"}
        else:
            # OpenAI, Claude, Gemini: use json_schema with strict enforcement
            responseFormat = {
                "type": "json_schema",
                "json_schema": {"name": "translation_response", "strict": True, "schema": createTranslationSchema(numLines)}
            }
    else:
        responseFormat = {"type": "text"}

    # Content to TL - ensure user content is not empty
    if not user or not str(user).strip():
        raise ValueError("User content cannot be empty")
    msg.append({"role": "user", "content": f"```\n{user}\n```"})

    # Debug: Check for any empty messages before API call
    for i, message in enumerate(msg):
        if not message.get("content") or not str(message.get("content")).strip():
            raise ValueError(f"Message {i} has empty content: {message}")

    # --- API Call Logic ---
    # Re-apply env vars here so that GUI config changes (which update os.environ
    # but cannot re-run module-level code) are always reflected at call time.
    _live_api = os.getenv("api", "").strip()
    _live_key = os.getenv("key", "").strip()
    _live_provider = os.getenv("API_PROVIDER", "openai").lower()
    if _live_provider == "gemini" and not _live_api:
        openai.base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    elif _live_provider == "mistral" and not _live_api:
        openai.base_url = "https://api.mistral.ai/v1/"
    elif _live_api:
        openai.base_url = _normalize_openai_base_url(_live_api)
    _live_key_optional = os.getenv("API_KEY_OPTIONAL", "").strip().lower() in ("1", "true", "yes")
    openai.api_key = _live_key or ("not-needed" if _live_key_optional else "")

    api_provider = _live_provider

    # Omit response_format for plain text — some providers reject {"type": "text"}.
    params = {
        "model": model,
        "messages": msg,
    }
    if responseFormat.get("type") != "text":
        params["response_format"] = responseFormat

    # Provider-specific parameters
    if api_provider == "gemini":
        params["temperature"] = 0
        
        # Handle thinking budget for Gemini
        thinking_budget_str = os.getenv("GEMINI_THINKING_BUDGET")
        if thinking_budget_str:
            try:
                thinking_budget = int(thinking_budget_str)
                params["extra_body"] = {
                    'google': {
                        'thinking_config': {
                            'thinking_budget': thinking_budget
                        }
                    }
                }
            except (ValueError, TypeError):
                pass
        
    # frequency_penalty is unsupported on the Gemini OpenAI compat layer
    elif _is_claude:
        params["temperature"] = 0
        # cache_control is set on the system message content block above.
    elif _is_mistral:
        params["temperature"] = 0
        # max_tokens caps the response AND feeds the limiter's token estimate
        # (input+output count against the per-minute budget). Sized from the
        # payload: JP ~1 token/char, output echoes the JSON scaffold + EN.
        params["max_tokens"] = min(16000, max(1500, int(len(str(user)) * 1.2) + 40 * (numLines or 1)))
    else:  # Default to OpenAI behavior
        if "gpt-5" in model:
            params["reasoning_effort"] = "none" if "gpt-5.6" in model else "minimal"
        else:
            params["temperature"] = 0
            params["frequency_penalty"] = penalty

    # One canonical OpenAI-compatible builder feeds both live requests and
    # JSONL batch rows. Keep responseFormat in sync for the existing live
    # compatibility fallback below.
    if not _is_claude:
        params = buildOpenAIRequest(
            system, user, history, penalty, formatType, model, numLines,
            vocab_text=vocab_text, api_provider=api_provider,
        )
        responseFormat = params.get("response_format", {"type": "text"})

    # Use native Anthropic SDK — the OpenAI compat endpoint strips cache_control
    # and never returns cache_read/creation_input_tokens.
    if _is_claude:
        # Built by the shared builder so live and batch requests are
        # byte-identical and share the same prompt cache.
        ant_kwargs = buildClaudeRequest(system, user, history, formatType, model, numLines, vocab_text=vocab_text)

        ant_client = anthropic.Anthropic(api_key=openai.api_key)
        try:
            ant_resp = ant_client.messages.create(**ant_kwargs)
        except Exception as e:
            raise Exception(f"Anthropic API error: {e}")

        _ant_text = _anthropic_content_text(ant_resp.content)
        _u = ant_resp.usage
        _cr  = getattr(_u, "cache_read_input_tokens",     0) or 0
        _cw  = getattr(_u, "cache_creation_input_tokens", 0) or 0
        _inp = getattr(_u, "input_tokens",  0) or 0
        _out = getattr(_u, "output_tokens", 0) or 0

        # input_tokens (native SDK) = non-cached portion; add cache fields for true total.
        _total_prompt = _inp + _cr + _cw

        compat_response = _AnthropicCompat(_ant_text, _total_prompt, _out, _cr, _cw)
        _write_request_debug_log("anthropic", ant_kwargs, compat_response.usage)
        return compat_response

    # Mistral (la Plateforme): same OpenAI-compatible request, but routed
    # through the adaptive rate limiter so the per-minute request/token
    # budgets are paced off the live response headers instead of tripping 429s.
    if _is_mistral:
        response = callMistral(params)
        if not response or not hasattr(response, 'choices') or not response.choices:
            raise Exception("API returned invalid or empty response - retrying...")
        _write_request_debug_log("mistral", params, getattr(response, "usage", None))
        return response

    # Call API (reaches here only for non-Claude providers)
    try:
        response = openai.chat.completions.create(**params)
    except APIStatusError as e:
        # Handle HTTP status errors (404, 500, etc.)
        if e.status_code == 404:
            raise Exception(f"API endpoint not found (404) - check your API_PROVIDER and base URL settings. Error: {e}")
        elif e.status_code >= 500:
            raise Exception(f"API server error ({e.status_code}) - retrying... Error: {e}")
        elif e.status_code == 400 and formatType == "json" and "json_schema" in str(responseFormat):
            # Only fall back to json_object if the error is NOT "Input should be 'json_schema'"
            # (that message means json_schema IS required and json_object would also be rejected)
            if "input should be 'json_schema'" in str(e).lower() or "input should be \"json_schema\"" in str(e).lower():
                raise Exception(f"API status error ({e.status_code}): {e}")
            # Provider doesn't support json_schema (e.g. Claude) — fall back to json_object
            responseFormat = {"type": "json_object"}
            params["response_format"] = responseFormat
            try:
                response = openai.chat.completions.create(**params)
            except APIStatusError as fallback_error:
                if fallback_error.status_code == 400 and "input should be 'json_schema'" in str(fallback_error).lower():
                    raise Exception(f"API requires json_schema response format but rejected the schema. Original error: {e}")
                raise Exception(f"API call failed: {e}. Fallback also failed: {fallback_error}")
            except Exception as fallback_error:
                raise Exception(f"API call failed: {e}. Fallback also failed: {fallback_error}")
        elif e.status_code == 400 and "input should be 'json_schema'" in str(e).lower():
            # response_format.type was rejected (e.g. sent "text" or "json_object" to a model
            # that only accepts json_schema). Remove response_format and retry with no constraint.
            params.pop("response_format", None)
            try:
                response = openai.chat.completions.create(**params)
            except Exception as fallback_error:
                raise Exception(f"API call failed: {e}. Fallback also failed: {fallback_error}")
        else:
            raise Exception(f"API status error ({e.status_code}): {e}")
    except (APIConnectionError, RateLimitError) as e:
        # These should always be retried
        raise Exception(f"API connection/rate limit error - retrying... Error: {e}")
    except Exception as e:
        # Check if it's a 404 error or other HTTP error that should be retried
        error_str = str(e).lower()
        if "404" in error_str or "not found" in error_str:
            raise Exception(f"API returned 404 Not Found - check your API configuration. Original error: {e}")
        
        # If structured output fails, fallback to json_object (unless the error
        # explicitly states json_schema is required — falling back would just fail again)
        if formatType == "json" and "json_schema" in str(responseFormat) and \
                "input should be 'json_schema'" not in error_str:
            responseFormat = {"type": "json_object"}
            params["response_format"] = responseFormat
            try:
                response = openai.chat.completions.create(**params)
            except Exception as fallback_error:
                # If fallback also fails, raise the original error for retry
                raise Exception(f"API call failed: {e}. Fallback also failed: {fallback_error}")
        else:
            raise e
    
    # Validate response before returning
    if not response or not hasattr(response, 'choices') or not response.choices:
        raise Exception("API returned invalid or empty response - retrying...")

    _write_request_debug_log(api_provider, params, getattr(response, "usage", None))
    return response


def cleanTranslatedText(translatedText, language):
    """Clean and format translated text"""
    placeholders = {
        f"{language} Translation: ": "",
        "Translation: ": "",
        "っ": "",
        "〜": "~",
        "ッ": "",
        "。": ".",
        # Note: 「 and 」 are NOT replaced here — replacing them with ASCII " would
        # corrupt raw JSON strings before extraction.  They are handled per-line
        # in _clean_extracted_line() after JSON parsing (when convertQuotes is on).
        "—": "―",
        "】": "]",
        "【": "[",
        "é": "e",
        "’": "'",
        "this guy": "this bastard",
        "This guy": "This bastard",
        "```json": "",
        "```": "",
    }
    
    for target, replacement in placeholders.items():
        translatedText = translatedText.replace(target, replacement)

    # Remove Repeating Characters
    pattern = re.compile(r"(.)\s*\1(?:\s*\1){" + str(20 - 1) + r",}")
    translatedText = pattern.sub(lambda match: match.group(0).replace(" ", "")[:20], translatedText)

    # Elongate Long Dashes (Since GPT Ignores them...)
    translatedText = elongateCharacters(translatedText)
    return translatedText


def elongateCharacters(text):
    """Replace ー sequences with elongated characters"""
    # Define a pattern to match one character followed by two or more ー characters.
    # The lookbehind is restricted to non-ー Japanese/CJK characters so that:
    #   - standalone ー separators (e.g. "ーーーーーーーーーー") are left untouched
    #   - ー sequences preceded by a JSON quote or other non-Japanese char are not corrupted
    pattern = r"(?<=([\u3040-\u309F\u30A0-\u30FB\u30FD-\u30FF\u4E00-\u9FEF\uFF61-\uFF9F]))ー{2,}"

    # Define a replacement function that elongates the captured character
    def repl(match):
        char = match.group(1)  # The character before the ー sequence
        count = len(match.group(0)) - 1  # Number of ー characters
        return char * count  # Replace ー sequence with the character repeated

    # Use re.sub() to replace the pattern in the text
    return re.sub(pattern, repl, text)


def extractTranslation(translatedTextList, isList, pbar=None):
    """Extract translation from JSON response.

    This function is resilient to a few common model mistakes:
    - Wraps output in code fences or outer quotes
    - Uses smart quotes instead of straight quotes
    - Inserts an extra leading quote in values (e.g. :""Word" -> :"Word")
    - Trailing commas before } or ]

    If strict JSON parsing fails, falls back to a regex-based extractor that
    captures LineN values in numeric order.
    """
    s = str(translatedTextList or "").strip()

    # Fast exit
    if not s:
        return None

    # Remove code fences if present
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)

    # Trim wrapping quotes around the whole JSON blob (common in logs)
    if len(s) >= 2 and s[0] == s[-1] and s[0] in {'"', "'"}:
        # Only strip if it still looks like JSON inside
        if s[1:2] == "{" and s[-2:-1] == "}":
            s = s[1:-1]

    # Normalize a broad set of Unicode “smart” quotes to ASCII equivalents.
    translation_table = {
        0x201C: "'",  # “ left double quotation mark
        0x201D: "'",  # ” right double quotation mark
        0xFF02: "'",  # ＂ fullwidth quotation mark

        0x2018: "'",  # ‘ left single quotation mark
        0x2019: "'",  # ’ right single quotation mark
        0x201B: "'",  # ‛ single high-reversed-9 quotation mark
        0x02BC: "'",  # ʼ modifier letter apostrophe
        0xFF07: "'",  # ＇ fullwidth apostrophe
    }
    s = s.translate(translation_table)

    # Remove trailing commas before object/array closures
    s = re.sub(r",(\s*[}\]])", r"\1", s)

    # Repair common doubled leading quote in values: :""Word" -> :"Word"
    # Ensure we don't alter legitimate empty strings (:"")
    s = re.sub(r":\s*\"\"(?=[^\",}\]\s])", r':"', s)

    # Attempt strict parse first
    try:
        lineDict = json.loads(s)

        # Handle array-based schema: {"translations": ["...", ...]}
        if isinstance(lineDict, dict) and "translations" in lineDict and isinstance(lineDict["translations"], list):
            stringList = [str(v) for v in lineDict["translations"]]
            return stringList if isList else (stringList[0] if stringList else None)

        # Build list in numeric order if keys are LineN
        numeric_keys = []
        for k in lineDict.keys():
            m = re.fullmatch(r"Line(\d+)", str(k))
            if m:
                numeric_keys.append(int(m.group(1)))

        if numeric_keys:
            stringList = [lineDict.get(f"Line{n}", "") for n in sorted(numeric_keys)]
        else:
            # Fallback to values order if no LineN keys found
            stringList = list(lineDict.values())

        return stringList if isList else (stringList[0] if stringList else None)

    except Exception as e:
        # Fallback: regex-based extraction tolerant to one or two opening quotes
        # Captures escaped quotes within values too
        try:
            pairs = re.findall(r'"Line(\d+)"\s*:\s*"{1,2}((?:\\.|[^"\\])*)"', s)
            if not pairs:
                raise ValueError("No LineN pairs found")

            # Sort numerically and unescape JSON string content
            items = []
            for n_str, v in sorted(((int(n), v) for n, v in pairs), key=lambda x: x[0]):
                try:
                    # Decode JSON escapes reliably by round-tripping as a JSON string
                    decoded = json.loads(f'"{v}"')
                except Exception:
                    decoded = v
                items.append(decoded)

            return items if isList else (items[0] if items else None)
        except Exception as e2:
            if pbar:
                pbar.write(f"extractTranslation Error: {e2} after JSON error {e} on String {translatedTextList}")
            return None


def calculateCost(inputTokens, outputTokens, model):
    """
    Calculate the cost of translation based on token usage and model pricing.

    For Claude models the cost is derived from the actual cache token breakdown
    recorded by translateAI, so cache discounts are reflected accurately:
      - Cache reads:  10 % of the base input rate
      - Cache writes: 125 % of the base input rate
      - Regular input: 100 % of the base input rate

    Call pattern (no module changes required):
      Per-file call: file_cost_ready flag is True → read thread-local per-file
                     accumulators (which span all translateAI calls for the file),
                     compute cost, reset accumulators, clear flag, return cost.
      TOTAL call:    file_cost_ready is False (already cleared) → return the
                     cross-thread _global_accurate_cost running sum.

    Falls back to naive token × rate calculation for non-Claude models.
    """
    _is_claude = model and any(x in model.lower() for x in ("claude", "sonnet", "haiku", "opus"))
    if _is_claude:
        if getattr(_thread_local, 'file_cost_ready', False):
            # Per-file call: compute from accumulators (may be 0 for disk-cached files),
            # reset everything, return the file cost.
            cr  = getattr(_thread_local, 'file_cache_read',  0)
            cw  = getattr(_thread_local, 'file_cache_write', 0)
            reg = getattr(_thread_local, 'file_regular',     0)
            out = getattr(_thread_local, 'file_output',      0)
            bcr  = getattr(_thread_local, 'file_batch_read',    0)
            bcw  = getattr(_thread_local, 'file_batch_write',   0)
            breg = getattr(_thread_local, 'file_batch_regular', 0)
            bout = getattr(_thread_local, 'file_batch_output',  0)
            pricing  = getPricingConfig(model)
            br  = pricing["inputAPICost"]  / 1_000_000
            orr = pricing["outputAPICost"] / 1_000_000
            cost = (cr * br * 0.10 + cw * br * 2.00 + reg * br + out * orr
                    # Batch API tokens: same rates, then the 50% batch discount.
                    + (bcr * br * 0.10 + bcw * br * 2.00 + breg * br + bout * orr) * 0.50)
            _thread_local.file_cache_read  = 0
            _thread_local.file_cache_write = 0
            _thread_local.file_regular     = 0
            _thread_local.file_output      = 0
            _thread_local.file_batch_read    = 0
            _thread_local.file_batch_write   = 0
            _thread_local.file_batch_regular = 0
            _thread_local.file_batch_output  = 0
            _thread_local.file_cost_ready  = False
            return cost
    # TOTAL call: cache-aware Claude and all async providers accumulate here.
    with _global_accurate_cost_lock:
        accurate = _global_accurate_cost
    if accurate > 0 and (_is_claude or get_batch_phase() == "consume"):
        return accurate

    # Non-Claude, estimate mode, or no accurate data: naive calculation.
    # For Claude models, use the accumulated static_system token count (the portion
    # that is always cache-written at the 1hr TTL rate = 2x input rate).
    # Remaining tokens are billed at the regular input rate.
    pricing = getPricingConfig(model)
    _is_claude_naive = model and any(x in model.lower() for x in ("claude", "sonnet", "haiku", "opus"))
    if _is_claude_naive:
        static_tok  = getattr(_thread_local, 'estimate_static_tokens', 0)
        regular_tok = getattr(_thread_local, 'estimate_regular_tokens', 0)
        batch_count = max(1, getattr(_thread_local, 'estimate_batch_count', 1))
        _thread_local.estimate_static_tokens  = 0
        _thread_local.estimate_regular_tokens = 0
        _thread_local.estimate_batch_count    = 0
        # If cache is disabled, every batch is a write (2x) — no reads ever.
        # Otherwise: each distinct batch size (= distinct output_config schema) gets exactly
        # one cache write on first use; all subsequent batches of that size are reads (0.10x).
        # Load from disk first so GUI subprocesses (one per file) share warm-cache state.
        global _estimate_written_sizes
        if DISABLE_CACHE:
            write_batches = batch_count
            read_batches  = 0
        else:
            _load_estimate_written_sizes()
            seen_sizes = getattr(_thread_local, 'estimate_seen_sizes', set())
            new_sizes = seen_sizes - _estimate_written_sizes
            write_batches = len(new_sizes)  # one write per newly-seen size
            read_batches  = batch_count - write_batches
            _estimate_written_sizes.update(new_sizes)
            _save_estimate_written_sizes()
            _thread_local.estimate_seen_sizes = set()
        write_cost   = (write_batches * static_tok / 1_000_000) * pricing["inputAPICost"] * 2.0
        read_cost    = (read_batches  * static_tok / 1_000_000) * pricing["inputAPICost"] * 0.10
        regular_cost = (regular_tok / 1_000_000) * pricing["inputAPICost"]
        inputCost    = write_cost + read_cost + regular_cost
    else:
        inputCost = (inputTokens / 1_000_000) * pricing["inputAPICost"]
    outputCost = (outputTokens / 1_000_000) * pricing["outputAPICost"]
    return inputCost + outputCost


def countTokens(system, user, history):
    """Count tokens for cost estimation"""
    inputTotalTokens = 0
    outputTotalTokens = 0
    enc = tiktoken.encoding_for_model("gpt-4")

    # Input
    if isinstance(history, list):
        for line in history:
            inputTotalTokens += len(enc.encode(line))
    else:
        inputTotalTokens += len(enc.encode(history))
    inputTotalTokens += len(enc.encode(system))
    inputTotalTokens += len(enc.encode(user))

    # Output
    outputTotalTokens += round(len(enc.encode(user)) * 2.5)

    return [inputTotalTokens, outputTotalTokens]


def last_translation_had_mismatch() -> bool:
    """Return whether the latest translateAI call on this thread fell back."""
    return bool(getattr(_thread_local, "last_translation_had_mismatch", False))


@retry(exceptions=Exception, tries=5, delay=5)
def translateAI(text, history, config, filename=None, pbar=None, lock=None, mismatchList=None):
    """
    Main translation entry point used by all modules.

    Returns [translatedText, [inputTokens, outputTokens]].
    """
    _thread_local.last_translation_had_mismatch = False
    if not text:
        return [text, [0, 0]]

    # Use TRANSLATION_RUN_LOG env var as log path if set.
    run_log = os.getenv("TRANSLATION_RUN_LOG")
    if run_log:
        # Make sure parent dir exists
        try:
            Path(run_log).parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        config.logFilePath = run_log

    # Ensure log directory exists for the configured path
    try:
        Path(config.logFilePath).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    # Token tracking: [input, output].
    totalTokens = [0, 0]

    # Init per-file accumulators on first call on this thread (never reset here —
    # they span all translateAI calls for a file; reset by calculateCost).
    if not hasattr(_thread_local, 'file_cache_read'):
        _thread_local.file_cache_read  = 0
        _thread_local.file_cache_write = 0
        _thread_local.file_regular     = 0
        _thread_local.file_output      = 0
    # Batch API usage is billed at 50% so it is accumulated separately.
    if not hasattr(_thread_local, 'file_batch_read'):
        _thread_local.file_batch_read    = 0
        _thread_local.file_batch_write   = 0
        _thread_local.file_batch_regular = 0
        _thread_local.file_batch_output  = 0
    # Snapshot accumulators so end-of-call delta only counts tokens from this call.
    _prev_cr  = _thread_local.file_cache_read
    _prev_cw  = _thread_local.file_cache_write
    _prev_reg = _thread_local.file_regular
    _prev_out = _thread_local.file_output
    _prev_bcr  = _thread_local.file_batch_read
    _prev_bcw  = _thread_local.file_batch_write
    _prev_breg = _thread_local.file_batch_regular
    _prev_bout = _thread_local.file_batch_output
    _thread_local.file_cost_ready = False  # will be set True at end of translateAI

    # Provider batch phase ('collect'/'consume'); None when off or unsupported.
    batch_phase = get_batch_phase()
    batch_provider = getBatchProvider(config.model)
    if batch_phase and (config.estimateMode or not batch_provider):
        batch_phase = None
    
    if isinstance(text, list):
        formatType = "json"
        tList = batchList(text, config.batchSize)
    else:
        formatType = "json"
        tList = [text]

    for index, tItem in enumerate(tList):
        # Check if text contains target language
        if not re.search(config.langRegex, str(tItem)):
            if pbar is not None:
                pbar.update(len(tItem) if isinstance(tItem, list) else 1)
            if isinstance(tItem, list):
                for j in range(len(tItem)):
                    tItem[j] = cleanTranslatedText(tItem[j], config.language)
                tList[index] = tItem
            else:
                tList[index] = cleanTranslatedText(tItem, config.language)
            history = tItem[-config.maxHistory:] if isinstance(tItem, list) else tItem
            continue

        # Ellipsis-only bypass: strings whose translatable content is purely '…' characters
        # (e.g. "「………」") should never be sent to the AI — just convert brackets and pass through.
        def _is_ellipsis_only(s):
            inner = str(s).strip().lstrip('「『').rstrip('」』').strip()
            return bool(inner) and all(c in '\u2026\u30FC' for c in inner)

        def _convert_ellipsis(s):
            return convert_corner_brackets(str(s), config.convertQuotes)

        if isinstance(tItem, list):
            if all(_is_ellipsis_only(s) for s in tItem):
                tList[index] = [_convert_ellipsis(s) for s in tItem]
                if pbar is not None:
                    pbar.update(len(tItem))
                continue
        else:
            if _is_ellipsis_only(tItem):
                tList[index] = _convert_ellipsis(tItem)
                if pbar is not None:
                    pbar.update(1)
                continue

        # Protect script codes before translation
        protected_items = []
        all_replacements = {}
        
        if isinstance(tItem, list):
            for j in range(len(tItem)):
                if not tItem[j] or not str(tItem[j]).strip():
                    protected_items.append("Placeholder Text")
                    all_replacements[j] = {}
                else:
                    collapsed = re.sub(r'(.)\1{9,}', lambda m: m.group(1) * 10, tItem[j])
                    protected_text, replacements = protect_script_codes(collapsed)
                    protected_items.append(protected_text)
                    all_replacements[j] = replacements
        else:
            if not tItem or not str(tItem).strip():
                protected_items = "Placeholder Text"
                all_replacements[0] = {}
            else:
                collapsed = re.sub(r'(.)\1{9,}', lambda m: m.group(1) * 10, tItem)
                protected_items, all_replacements[0] = protect_script_codes(collapsed)
        
        # Filter out corrupted/mojibake text (U+FFFD) from the batch before API call
        corrupted_map = {}  # original_index -> original_text
        if isinstance(tItem, list):
            for j in range(len(tItem)):
                if tItem[j] and "\ufffd" in str(tItem[j]):
                    corrupted_map[j] = tItem[j]
        elif tItem and "\ufffd" in str(tItem):
            # Single corrupted string - skip translation entirely
            tList[index] = tItem
            if pbar is not None:
                pbar.update(1)
            history = tItem
            continue

        # Skip non-Japanese lines (AI empties them); restore after translation.
        no_japanese_map = {}  # original_index -> already-cleaned text
        if isinstance(tItem, list):
            for j in range(len(tItem)):
                if j in corrupted_map:
                    continue
                item_str = str(tItem[j]).strip() if tItem[j] else ""
                if item_str and item_str != "Placeholder Text" and not re.search(config.langRegex, item_str):
                    cleaned = cleanTranslatedText(tItem[j], config.language)
                    cleaned = convert_corner_brackets(cleaned, config.convertQuotes).strip()
                    no_japanese_map[j] = cleaned

        # Combine skip sets and rebuild protected_items / all_replacements
        skip_indices = set(corrupted_map.keys()) | set(no_japanese_map.keys())
        if isinstance(tItem, list) and skip_indices:
            clean_indices = [j for j in range(len(tItem)) if j not in skip_indices]

            if not clean_indices:
                # Every item is either corrupted or untranslatable — reassemble and move on
                result = []
                for j in range(len(tItem)):
                    if j in corrupted_map:
                        result.append(corrupted_map[j])
                    elif j in no_japanese_map:
                        result.append(no_japanese_map[j])
                    else:
                        result.append(tItem[j])
                tList[index] = result
                if pbar is not None:
                    pbar.update(len(tItem))
                history = result[-config.maxHistory:]
                continue

            # Rebuild protected_items and all_replacements for translatable items only
            protected_items = [protected_items[j] for j in clean_indices]
            new_replacements = {}
            for new_idx, old_idx in enumerate(clean_indices):
                new_replacements[new_idx] = all_replacements.get(old_idx, {})
            all_replacements = new_replacements

        # Build filtered tItem for validation (excludes skipped items)
        if isinstance(tItem, list) and skip_indices:
            clean_tItem = [tItem[j] for j in range(len(tItem)) if j not in skip_indices]
        else:
            clean_tItem = tItem

        # Format for translation
        if isinstance(tItem, list):
            payload = {f"Line{i+1}": string for i, string in enumerate(protected_items)}
            payload = json.dumps(payload, indent=4, ensure_ascii=False)
            subbedT = payload
        else:
            subbedT = json.dumps({"Line1": protected_items}, indent=4, ensure_ascii=False)

        # Build the matched glossary context before cache/batch lookup. Its
        # fingerprint is part of the lookup key, so results produced under an
        # older relevant spelling cannot bypass the current glossary.
        static_system, glossary_text, sfx_text, user = createContextParts(
            config, subbedT, formatType, history
        )
        vocab_text = glossary_text + sfx_text

        # Batch collect queues list payloads only. Single strings (speaker and
        # variable names) translate live — modules memoize them and embed the
        # results into later payloads, so they must resolve identically in both
        # passes or the consume pass couldn't match the queued payload keys.
        # This is the names-first phase; names are a tiny share of the volume.
        queue_for_batch = batch_phase == "collect" and isinstance(tItem, list)

        # Check cache for this exact payload (the collect pass uses a
        # non-blocking peek so no pending markers are left behind for the
        # consume pass to wait on)
        if queue_for_batch:
            cached_result = peek_cached_translation(
                subbedT, config.language, vocab_text
            )
        else:
            cached_result = get_cached_translation(
                subbedT, config.language, vocab_text
            )
        if cached_result is not None:
            cached_values = cached_result if isinstance(cached_result, list) else [cached_result]
            source_values = clean_tItem if isinstance(clean_tItem, list) else [clean_tItem]
            controls_ok, _control_errors = validate_control_codes(
                source_values, cached_values, all_replacements
            )
            protected_source_values = (
                protected_items if isinstance(protected_items, list) else [protected_items]
            )
            cached_content_values = [
                _reprotect_cached_codes(value, all_replacements.get(line, {}))
                for line, value in enumerate(cached_values)
            ]
            content_ok, _invalid_indices, _content_reasons = validate_translation_content(
                protected_source_values, cached_content_values, config.langRegex
            )
            if len(source_values) != len(cached_values) or not controls_ok or not content_ok:
                # Ignore stale/corrupt cache entries. A successful live result
                # below overwrites the same key.
                cached_result = None

        if cached_result is not None:
            # Estimate mode: keep original tList[index]; cached length may differ.
            if not config.estimateMode:
                if isinstance(tItem, list):
                    # Cached value is Japanese-only; re-expand skipped items for this batch.
                    if (corrupted_map or no_japanese_map) and isinstance(cached_result, list):
                        expanded_cached = expand_clean_to_batch(
                            cached_result, tItem, corrupted_map, no_japanese_map
                        )
                        tList[index] = expanded_cached
                        history = expanded_cached[-config.maxHistory:]
                    else:
                        tList[index] = cached_result
                        history = cached_result[-config.maxHistory:] if isinstance(cached_result, list) else cached_result
                else:
                    tList[index] = cached_result
                    history = cached_result
            else:
                if isinstance(cached_result, list) and cached_result:
                    history = cached_result[-config.maxHistory:]
                elif cached_result:
                    history = cached_result

            if lock and pbar is not None:
                with lock:
                    pbar.update(len(tItem) if isinstance(tItem, list) else 1)

            # Consume pass: still record what was applied. Cache hits used to
            # skip the log entirely, which left the GUI Translation Log empty
            # after a resume even though translated/ was written.
            if batch_phase == "consume" and not config.estimateMode:
                try:
                    if isinstance(cached_result, list):
                        out_payload = {
                            f"Line{i+1}": string for i, string in enumerate(cached_result)
                        }
                        formatted_output = json.dumps(out_payload, indent=4, ensure_ascii=False)
                    else:
                        formatted_output = json.dumps(
                            {"Line1": cached_result}, indent=4, ensure_ascii=False
                        )
                    Path(config.logFilePath).parent.mkdir(parents=True, exist_ok=True)
                    with open(config.logFilePath, "a", encoding="utf-8") as logFile:
                        logFile.write("[CACHE] Applied cached translation (no new API call)\n")
                        logFile.write(f"Input:\n{subbedT}\n")
                        logFile.write(f"Output:\n{formatted_output}\n")
                        logFile.flush()
                except Exception:
                    pass

            continue

        # Batch collect pass: queue the request (built exactly like a live one)
        # instead of calling the API. The text stays untranslated; the consume
        # pass fills it in from the fetched batch results. History carries the
        # preceding source lines so the model still sees scene context.
        if queue_for_batch:
            numLines = len(clean_tItem) if isinstance(tItem, list) else 1
            if batch_provider == "anthropic":
                params = buildClaudeRequest(
                    static_system, user, history, formatType,
                    config.model, numLines, vocab_text=vocab_text,
                )
            else:
                params = buildOpenAIRequest(
                    static_system, user, history, 0.05, formatType,
                    config.model, numLines, vocab_text=vocab_text,
                    api_provider=batch_provider,
                )
            queue_batch_request(
                subbedT,
                config.language,
                params,
                cache_context=vocab_text,
                provider=batch_provider,
            )
            if lock and pbar is not None:
                with lock:
                    pbar.update(len(tItem))
            history = tItem[-config.maxHistory:]
            continue

        # Calculate estimate if in estimate mode
        if config.estimateMode:
            estimate = countTokens(static_system + vocab_text, user, history)
            totalTokens[0] += estimate[0]
            totalTokens[1] += estimate[1]

            # Track exact cache write size (static_system, constant across batches)
            # and accumulate non-cached (vocab + user + history) tokens per batch.
            _est_api = os.getenv("api", "").strip()
            _is_claude_est = (
                config.model
                and any(x in config.model.lower() for x in ("claude", "sonnet", "haiku", "opus"))
                and (not _est_api or "anthropic" in _est_api.lower())
            )
            if _is_claude_est:
                # Use Anthropic's count_tokens API once to get the exact cached token count.
                # Only called on the first batch; result reused for all subsequent batches.
                if not getattr(_thread_local, 'estimate_static_tokens', 0):
                    try:
                        _ant_count_client = anthropic.Anthropic(api_key=openai.api_key)
                        backtick = chr(96) * 3
                        _sys_block = [{"type": "text", "text": backtick + "\n" + static_system + "\n" + backtick, "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
                        _count_resp = _ant_count_client.beta.messages.count_tokens(
                            betas=["token-counting-2024-11-01"],
                            model=config.model,
                            system=_sys_block,
                            messages=[{"role": "user", "content": "x"}]
                        )
                        _thread_local.estimate_static_tokens = _count_resp.input_tokens
                    except Exception:
                        # Fallback to tiktoken if count_tokens fails
                        enc = tiktoken.encoding_for_model("gpt-4")
                        _thread_local.estimate_static_tokens = len(enc.encode(static_system))
                regular_tok = max(0, estimate[0] - getattr(_thread_local, 'estimate_static_tokens', 0))
                _thread_local.estimate_regular_tokens = getattr(_thread_local, 'estimate_regular_tokens', 0) + regular_tok
                _thread_local.estimate_batch_count = getattr(_thread_local, 'estimate_batch_count', 0) + 1
                # Track unique batch sizes seen this file (each maps to a distinct schema)
                _size = len(clean_tItem) if isinstance(clean_tItem, list) else 1
                _seen = getattr(_thread_local, 'estimate_seen_sizes', set())
                _seen.add(_size)
                _thread_local.estimate_seen_sizes = _seen
            
            # Cache the payload with original text as placeholder for future estimates
            if isinstance(tItem, list):
                cache_translation(
                    subbedT, tItem, config.language, cache_context=vocab_text
                )
            else:
                cache_translation(
                    subbedT, [tItem], config.language, cache_context=vocab_text
                )
            
            continue

        # --- Translation and Validation Retry Block ---
        # A fetched provider result may be validated once, but a consume pass
        # must never turn a missing/invalid discounted result into an implicit
        # full-price live retry. The user can start normal Translate explicitly.
        max_retries = 0 if batch_phase == "consume" else 2
        final_translations = None
        last_raw_translation = ""
        from_batch = False
        numLines = len(clean_tItem) if isinstance(tItem, list) else 1

        for attempt in range(max_retries + 1):
            is_valid = True

            # On retries, prepend the correction note to the USER message so the
            # cached static_system block is never modified (avoids cache busting).
            current_user = user
            if attempt > 0:
                retry_note = (
                    f"IMPORTANT: Your previous attempt was incorrect or incomplete. Please ensure:\n"
                    f"1. The entire output is translated to {config.language} with no untranslated characters\n"
                    f"2. The JSON structure is correct with NO EMPTY or near-empty translations\n"
                    f"   - Every line with Japanese text MUST be fully translated\n"
                    f"   - Do NOT leave translations empty (\"\") or as single punctuation marks (\":\")\n"
                    f"3. ALL placeholders (like __PROTECTED_0__, __PROTECTED_1__, etc.) are preserved EXACTLY as they appear in the input\n"
                    f"   - Do not modify, translate, or remove any __PROTECTED_N__ placeholders\n"
                    f"   - Keep them in the exact same position in your translation\n"
                    f"4. Do NOT repeat the same letter or symbol many times in a row (e.g. uuuuuuuu... or broken tails)\n"
                    f"   - Keep moans/effects natural; never output long runs of one character\n\n"
                )
                current_user = retry_note + user
                if pbar:
                    pbar.write(f"Retrying translation... (Attempt {attempt + 1}/{max_retries + 1})")

            # Translate - a consume pass must use the matching fetched result.
            from_batch = False
            if batch_phase == "consume" and attempt == 0:
                batch_result = require_batch_result(
                    subbedT, config.language, cache_context=vocab_text
                )
                response = _AnthropicCompat(
                    batch_result.get("text", ""),
                    batch_result.get("prompt_tokens", 0) or 0,
                    batch_result.get("completion_tokens", 0) or 0,
                    batch_result.get("cache_read_input_tokens", 0) or 0,
                    batch_result.get("cache_creation_input_tokens", 0) or 0,
                )
                from_batch = True
                _write_request_debug_log(
                    f"{batch_provider or 'provider'}-batch",
                    {"payload": subbedT}, response.usage,
                )
            if not from_batch:
                if batch_phase == "consume":
                    raise BatchResultUnavailableError(
                        "[BATCH] Consume attempted to use the live API. The run "
                        "was stopped before any full-price fallback request."
                    )
                try:
                    response = translateText(static_system, current_user, history, 0.05, formatType, config.model, numLines, vocab_text=vocab_text)
                except Exception as api_err:
                    err_msg = f"[API_ERROR] {api_err}"
                    # Print to stdout so the GUI captures it immediately
                    print(err_msg, flush=True)
                    if pbar:
                        pbar.write(err_msg)
                    # Also write to the translation log file for persistence
                    try:
                        Path(config.logFilePath).parent.mkdir(parents=True, exist_ok=True)
                        with open(config.logFilePath, "a", encoding="utf-8") as _lf:
                            _lf.write(f"{err_msg}\n")
                            _lf.flush()
                    except Exception:
                        pass
                    raise  # Let retry decorator handle it
            translatedText = response.choices[0].message.content
            last_raw_translation = translatedText

            # Update token count for this attempt
            totalTokens[0] += response.usage.prompt_tokens
            totalTokens[1] += response.usage.completion_tokens

            # --- Cache/batch cost tracking ---
            _is_claude_model = config.model and any(x in config.model.lower() for x in ("claude", "sonnet", "haiku", "opus"))
            if _is_claude_model or from_batch:
                usage = response.usage

                # Read cache fields from _AnthropicCompat._Usage; fall back to model_extra.
                def _get_usage_field(field):
                    v = getattr(usage, field, None)
                    if v is None:
                        v = (getattr(usage, "model_extra", None) or {}).get(field)
                    return int(v) if v else 0

                batch_cache_read  = _get_usage_field("cache_read_input_tokens")
                batch_cache_write = _get_usage_field("cache_creation_input_tokens")
                batch_prompt_total = getattr(usage, "prompt_tokens", 0) or 0
                batch_regular = max(0, batch_prompt_total - batch_cache_read - batch_cache_write)
                batch_output  = getattr(usage, "completion_tokens", 0) or 0

                # Accumulate into per-file thread-local counters. Batch API
                # usage is billed at 50% so it goes into its own counters.
                if from_batch:
                    _thread_local.file_batch_read    += batch_cache_read
                    _thread_local.file_batch_write   += batch_cache_write
                    _thread_local.file_batch_regular += batch_regular
                    _thread_local.file_batch_output  += batch_output
                elif _is_claude_model:
                    _thread_local.file_cache_read  += batch_cache_read
                    _thread_local.file_cache_write += batch_cache_write
                    _thread_local.file_regular     += batch_regular
                    _thread_local.file_output      += batch_output

            # --- Debug Token Logging ---
            if DEBUG:
                try:
                    _dbg_dir = Path("log")
                    _dbg_dir.mkdir(parents=True, exist_ok=True)
                    with open(_dbg_dir / "debug.log", "a", encoding="utf-8") as _dbf:
                        _dbf.write(f"\n--- Batch ({len(clean_tItem) if isinstance(tItem, list) else 1} lines) ---\n")
                        _dbf.write(f"Prompt: {response.usage.prompt_tokens} tokens | Output: {response.usage.completion_tokens} tokens\n")
                        if hasattr(response.usage, "cache_read_input_tokens"):
                            cr = getattr(response.usage, "cache_read_input_tokens", 0) or 0
                            cw = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
                            cache_status = "HIT" if cr > 0 else ("WRITE" if cw > 0 else "MISS")
                            _dbf.write(f"Cache: {cache_status} (read={cr}, write={cw})\n")
                        _dbf.flush()
                except Exception:
                    pass

            # Clean the translation first for consistency
            cleaned_text = cleanTranslatedText(translatedText, config.language)

            # Process and validate translation result
            if cleaned_text:
                if isinstance(tItem, list):
                    extracted = extractTranslation(cleaned_text, True, pbar)

                    # Check 1: Mismatch in length -> still a hard failure
                    if extracted is None or len(clean_tItem) != len(extracted):
                        is_valid = False
                        if pbar:
                            pbar.write(f"Length mismatch: expected {len(clean_tItem)}, got {len(extracted) if extracted else 0}")
                    else:
                        # Check 2: Validate placeholders are preserved
                        # Flatten all_replacements for batch validation
                        all_protected_text = protected_items  # The list we sent
                        placeholder_valid, missing, extra = validate_placeholders(all_protected_text, extracted, 
                                                                                  {k: v for replacements in all_replacements.values() for k, v in replacements.items()})
                        
                        if not placeholder_valid:
                            is_valid = False
                            if pbar:
                                if missing:
                                    pbar.write(f"Missing placeholders: {', '.join(missing)}")
                                if extra:
                                    pbar.write(f"Extra placeholders: {', '.join(extra)}")
                        else:
                            restored_for_validation = [
                                restore_script_codes(line, all_replacements.get(j, {}))
                                for j, line in enumerate(extracted)
                            ]
                            control_valid, control_reasons = validate_control_codes(
                                clean_tItem, restored_for_validation, all_replacements
                            )
                            if not control_valid:
                                is_valid = False
                                if pbar:
                                    pbar.write("Control-code mismatch detected:")
                                    for reason in control_reasons[:5]:
                                        pbar.write(f"  - {reason}")
                            else:
                                # Check 3: Validate that translations are not empty or nearly empty
                                content_valid, invalid_indices, content_reasons = validate_translation_content(
                                    clean_tItem, extracted, config.langRegex
                                )

                                if not content_valid:
                                    is_valid = False
                                    if pbar:
                                        pbar.write(f"Invalid translation content detected:")
                                        for reason in content_reasons[:5]:  # Show first 5 issues
                                            pbar.write(f"  - {reason}")
                                        if len(content_reasons) > 5:
                                            pbar.write(f"  ... and {len(content_reasons) - 5} more issues")
                                else:
                                    _, content_warnings = translation_content_warnings(
                                        clean_tItem, extracted, config.langRegex
                                    )
                                    if content_warnings and pbar:
                                        pbar.write("Translation content warning:")
                                        for warning in content_warnings[:5]:
                                            pbar.write(f"  - {warning}")
                                    # Set translations (line count matches, placeholders valid, and content is good)
                                    # Strip "Placeholder Text" from individual lines (AI placeholder for untranslatable input)
                                    # Also apply the 「→" / 」→" replacements here per-line (safe now that JSON is parsed)
                                    def _clean_extracted_line(line):
                                        if not isinstance(line, str):
                                            return line
                                        line = line.replace("Placeholder Text", "").strip()
                                        return convert_corner_brackets(line, config.convertQuotes)
                                    final_translations = [_clean_extracted_line(line) for line in extracted]
                else:
                    # Single string: extract from JSON schema response
                    extracted = extractTranslation(cleaned_text, False, pbar)
                    if extracted is None:
                        is_valid = False
                        if pbar:
                            pbar.write(f"Failed to extract translation from response: {cleaned_text[:100]}")
                    else:
                        # Validate placeholders against extracted value
                        placeholder_valid, missing, extra = validate_placeholders(protected_items, extracted, all_replacements[0])
                        
                        if not placeholder_valid:
                            is_valid = False
                            if pbar:
                                if missing:
                                    pbar.write(f"Missing placeholders: {', '.join(missing)}")
                                if extra:
                                    pbar.write(f"Extra placeholders: {', '.join(extra)}")
                        else:
                            restored_for_validation = restore_script_codes(
                                extracted, all_replacements[0]
                            )
                            control_valid, control_reasons = validate_control_codes(
                                tItem, restored_for_validation, all_replacements
                            )
                            if not control_valid:
                                is_valid = False
                                if pbar:
                                    pbar.write("Control-code mismatch detected:")
                                    for reason in control_reasons:
                                        pbar.write(f"  - {reason}")
                            else:
                                # Validate content for single string
                                final_cleaned = extracted.replace("Placeholder Text", "")
                                content_valid, _, content_reasons = validate_translation_content(
                                    tItem, final_cleaned, config.langRegex
                                )

                                if not content_valid:
                                    is_valid = False
                                    if pbar:
                                        pbar.write(f"Invalid translation content:")
                                        for reason in content_reasons:
                                            pbar.write(f"  - {reason}")
                                else:
                                    _, content_warnings = translation_content_warnings(
                                        tItem, final_cleaned, config.langRegex
                                    )
                                    if content_warnings and pbar:
                                        pbar.write("Translation content warning:")
                                        for warning in content_warnings:
                                            pbar.write(f"  - {warning}")
                                    # Accept output - all validations passed
                                    final_cleaned = convert_corner_brackets(
                                        final_cleaned, config.convertQuotes
                                    )
                                    final_translations = final_cleaned
            else:
                is_valid = False
                if pbar: pbar.write(f"AI Refused: {tItem}\n")

            # If translation is valid, break the retry loop
            if is_valid:
                break
        
        # --- End of Retry Block ---

        # After the loop, handle the final result
        if final_translations is not None: # Success case
            # Restore protected script codes
            if isinstance(tItem, list):
                for j in range(len(final_translations)):
                    if j in all_replacements:
                        final_translations[j] = restore_script_codes(final_translations[j], all_replacements[j])

                # Cache before expansion; key is Japanese-only, so value must match.
                if not config.estimateMode:
                    cache_translation(
                        subbedT,
                        list(final_translations),
                        config.language,
                        cache_context=vocab_text,
                    )

                # Re-insert skipped items at original positions
                if corrupted_map or no_japanese_map:
                    final_translations = expand_clean_to_batch(
                        final_translations, tItem, corrupted_map, no_japanese_map
                    )
            else:
                final_translations = restore_script_codes(final_translations, all_replacements[0])
            
            formatted_output = last_raw_translation
            try:
                parsed_json = json.loads(last_raw_translation)
                # Normalize array-based output to LineN format for log readability
                if isinstance(parsed_json, dict) and "translations" in parsed_json and isinstance(parsed_json["translations"], list):
                    parsed_json = {f"Line{i+1}": v for i, v in enumerate(parsed_json["translations"])}
                formatted_output = json.dumps(parsed_json, indent=4, ensure_ascii=False)
            except (json.JSONDecodeError, ValueError):
                pass
            
            # Only open and write to log file when we have something to log
            try:
                with open(config.logFilePath, "a", encoding="utf-8") as logFile:
                    if from_batch:
                        logFile.write("[BATCH] Applied provider batch result\n")
                    logFile.write(f"Input:\n{subbedT}\n")
                    logFile.write(f"Output:\n{formatted_output}\n")
                    logFile.flush()  # Ensure data is written to disk immediately
            except Exception:
                pass  # Don't fail if logging fails

            # Non-list payloads cache here; lists are cached above.
            if not config.estimateMode and not isinstance(tItem, list):
                cache_translation(
                    subbedT,
                    final_translations,
                    config.language,
                    cache_context=vocab_text,
                )

            if isinstance(tItem, list):
                tList[index] = final_translations
                history = final_translations[-config.maxHistory:]
            else:
                tList[index] = final_translations
                history = final_translations

            if lock and pbar is not None:
                with lock:
                    pbar.update(len(tItem) if isinstance(tItem, list) else 1)

        else: # Failure case after all retries
            _thread_local.last_translation_had_mismatch = True
            if pbar: pbar.write(f"Translation failed after {max_retries + 1} attempts. Check mismatch log.")

            # Emit a machine-readable marker on stdout so the GUI worker
            # thread can detect the mismatch reliably (stdout is captured
            # synchronously, unlike file-tail polling which can be racy).
            try:
                print(f"MISMATCH_EVENT:{filename}", flush=True)
            except Exception:
                pass

            formatted_mismatch_output = last_raw_translation
            try:
                parsed_json = json.loads(last_raw_translation)
                if isinstance(parsed_json, dict) and "translations" in parsed_json and isinstance(parsed_json["translations"], list):
                    parsed_json = {f"Line{i+1}": v for i, v in enumerate(parsed_json["translations"])}
                formatted_mismatch_output = json.dumps(parsed_json, indent=4, ensure_ascii=False)
            except (json.JSONDecodeError, ValueError):
                pass
            with open(config.mismatchLogPath, "a+", encoding="utf-8") as mismatchFile:
                mismatchFile.write(f"Failed after retries: {filename}\n")
                mismatchFile.write(f"Input:\n{subbedT}\n")
                mismatchFile.write(f"Final Output:\n{formatted_mismatch_output}\n")
                mismatchFile.flush()  # Ensure data is written to disk immediately

            # Also write to the main translation log so the GUI log viewer can display it
            try:
                with open(config.logFilePath, "a", encoding="utf-8") as logFile:
                    logFile.write(f"[MISMATCH] Failed after retries: {filename}\n")
                    logFile.write(f"[MISMATCH] Input:\n")
                    for mline in subbedT.splitlines():
                        logFile.write(f"[MISMATCH] {mline}\n")
                    logFile.write(f"[MISMATCH] Final Output:\n")
                    for mline in formatted_mismatch_output.splitlines():
                        logFile.write(f"[MISMATCH] {mline}\n")
                    logFile.flush()
            except Exception:
                pass  # Don't fail if logging fails

            if filename and mismatchList is not None and filename not in mismatchList:
                mismatchList.append(filename)
            
            tList[index] = tItem
            history = text[-config.maxHistory:] if isinstance(text, list) else text

    # Combine if multilist
    if tList and isinstance(tList[0], list):
        tList = [t for sublist in tList for t in sublist]
    
    # Save cache after processing (for both estimate and translation modes)
    save_cache()

    # Batch collect pass: merge this call's queued requests into the disk queue.
    if batch_phase == "collect":
        flush_batch_queue()

    # Accumulate Claude cache-aware calls and every provider's discounted batch.
    # file_* accumulators hold full per-file totals; calculateCost() reads them.
    _is_claude_final = config.model and any(x in config.model.lower() for x in ("claude", "sonnet", "haiku", "opus"))
    _has_batch_delta = (
        getattr(_thread_local, 'file_batch_regular', 0) > _prev_breg
        or getattr(_thread_local, 'file_batch_output', 0) > _prev_bout
    )
    if (_is_claude_final or _has_batch_delta) and not config.estimateMode:
        _pricing = getPricingConfig(config.model)
        _br = _pricing["inputAPICost"] / 1_000_000
        _or = _pricing["outputAPICost"] / 1_000_000
        # Delta = tokens added in this call only (not earlier calls for same file).
        _delta_cr  = getattr(_thread_local, 'file_cache_read',  0) - _prev_cr
        _delta_cw  = getattr(_thread_local, 'file_cache_write', 0) - _prev_cw
        _delta_reg = getattr(_thread_local, 'file_regular',     0) - _prev_reg
        _delta_out = getattr(_thread_local, 'file_output',      0) - _prev_out
        _delta_bcr  = getattr(_thread_local, 'file_batch_read',    0) - _prev_bcr
        _delta_bcw  = getattr(_thread_local, 'file_batch_write',   0) - _prev_bcw
        _delta_breg = getattr(_thread_local, 'file_batch_regular', 0) - _prev_breg
        _delta_bout = getattr(_thread_local, 'file_batch_output',  0) - _prev_bout
        _call_cost = (
            _delta_cr  * _br * 0.10 +
            _delta_cw  * _br * 2.00 +
            _delta_reg * _br +
            _delta_out * _or +
            # Batch API tokens: same rates, then the 50% batch discount.
            (_delta_bcr  * _br * 0.10 +
             _delta_bcw  * _br * 2.00 +
             _delta_breg * _br +
             _delta_bout * _or) * 0.50
        )
        global _global_accurate_cost
        with _global_accurate_cost_lock:
            _global_accurate_cost += _call_cost
        _thread_local.file_cost_ready = True  # signals calculateCost to use file accumulators

    # Return result
    if isinstance(text, list):
        return [tList, totalTokens]
    else:
        return [tList[0], totalTokens]
