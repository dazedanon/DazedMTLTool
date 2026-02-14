"""
Shared translation utilities for DazedMTLTool
This module provides a centralized translation function that can be used across all modules
without relying on global variables.
"""

import os
import re
import json
import tiktoken
import openai
from openai import APIError, APIConnectionError, RateLimitError, APIStatusError
import hashlib
import threading
from dotenv import load_dotenv
from pathlib import Path
from retry import retry

# Set to True to print input/output token counts and content for each API call
DEBUG_LOGGING = False


# ===== Placeholder Protection System =====
# Patterns to protect from translation (sound effects, control codes, etc.)
PROTECTED_PATTERNS = [
    r'\\SE\[[^\]]+\]',      # \SE[sound_effect_name]
    r'\\ME\[[^\]]+\]',      # \ME[music_effect_name]
    r'\\BGM\[[^\]]+\]',     # \BGM[background_music_name]
    r'\\BGS\[[^\]]+\]',     # \BGS[background_sound_name]
    r'_pum\[[^\]]+\]',     # \BGS[background_sound_name]
    r'\\VS\[[^\]]+\]',     # \BGS[background_sound_name]
]

def protect_script_codes(text):
    """
    Replace script codes (like \\SE[タイプライター]) with unique placeholders before translation.
    Returns: (protected_text, replacements_dict)
    """
    if not text or not isinstance(text, str):
        return text, {}
    
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
    Validate that translated items are not empty or nearly empty.
    Returns: (is_valid, invalid_indices, reason)
    
    Rules:
    1. If original has content, translation must not be empty or just whitespace
    2. If original has Japanese text, translation must not be a single punctuation mark
    3. Translation should have meaningful content (more than 1-2 characters for substantial originals)
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
            
            # Check 2: Translation is just a single punctuation mark or very short
            # Allow control codes like \\C[27]\\V[45] but not just ":" or ""
            if len(trans_str) <= 2 and not re.search(r'\\[A-Z]\[', trans_str):
                # Exception: if original is also very short (like "回" -> "x"), that's ok
                if len(orig_str) > 3:
                    invalid_indices.append(i)
                    reasons.append(f"Line{i+1}: Translation too short ('{trans_str}') for '{orig_str[:50]}...'")
                    continue
            
            # Check 3: For longer originals (>10 chars), translation should be more than just 1-2 chars
            # unless it's a special case like numbers or codes
            if len(orig_str) > 10 and len(trans_str) <= 2:
                # Allow if it contains control codes or is just a replacement word
                if not re.search(r'\\[A-Z]\[', trans_str) and not trans_str.isalnum():
                    invalid_indices.append(i)
                    reasons.append(f"Line{i+1}: Translation suspiciously short ('{trans_str}') for '{orig_str[:50]}...'")
                    continue
    
    is_valid = len(invalid_indices) == 0
    return is_valid, invalid_indices, reasons

# (from .env if present), strip accidental whitespace, and set the base URL,
# organization, and API key. It also handles the Gemini compatibility layer.
load_dotenv()
api_provider = os.getenv("API_PROVIDER", "openai").lower()
env_api = os.getenv("api", "").strip()
if api_provider == "gemini":
    # Use Google Generative Language compatibility endpoint when running Gemini
    openai.base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    openai.organization = None
else:
    if env_api:
        openai.base_url = env_api
    # Support both 'organization' (gui/.env.example) and legacy 'org' names
    org = os.getenv("organization") or os.getenv("org")
    if org:
        openai.organization = org.strip()

# Always set API key from 'key' env var (trim whitespace)
openai.api_key = os.getenv("key", "").strip()

# Translation cache management
CACHE_FILE = Path("log/translation_cache.json")
CACHE_LOCK = threading.Lock()
_cache = None

def clear_cache():
    """Clear the translation cache (called at start of each run)"""
    global _cache
    with CACHE_LOCK:
        _cache = {}
        # Also clear the cache file on disk
        try:
            if CACHE_FILE.exists():
                CACHE_FILE.unlink()
        except Exception:
            pass

def load_cache():
    """Load the translation cache from disk"""
    global _cache
    if _cache is not None:
        return _cache
    
    with CACHE_LOCK:
        if _cache is not None:  # Double-check after acquiring lock
            return _cache
        
        # Try to load existing cache from disk
        _cache = {}
        try:
            if CACHE_FILE.exists():
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    _cache = json.load(f)
        except Exception:
            # If cache file is corrupted or unreadable, start fresh
            _cache = {}
        
        return _cache

def save_cache():
    """Save the translation cache to disk"""
    global _cache
    if _cache is None:
        return
    
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Use atomic write
        tmp_file = CACHE_FILE.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False, indent=2)
        tmp_file.replace(CACHE_FILE)
    except Exception:
        pass

def get_cache_key(payload, language):
    """Generate a cache key for a payload (can be single string or JSON batch)"""
    # Use hash to keep keys short but unique
    payload_str = str(payload) if payload is not None else ""
    combined = f"{payload_str}|{language}"
    return hashlib.md5(combined.encode("utf-8")).hexdigest()

def get_cached_translation(payload, language):
    """Get cached translation if it exists"""
    cache = load_cache()
    key = get_cache_key(payload, language)
    return cache.get(key)

def cache_translation(payload, translation, language):
    """Cache a translation payload and its response"""
    global _cache
    cache = load_cache()
    key = get_cache_key(payload, language)
    
    with CACHE_LOCK:
        cache[key] = translation
        # Save every 10 new entries to avoid excessive disk writes
        if len(cache) % 10 == 0:
            save_cache()


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
                 mismatchLogPath="log/mismatchHistory.txt"):
        
        # Load from environment if not provided
        self.model = model or os.getenv("model")
        self.language = (language or os.getenv("language", "english")).capitalize()
        
        # Load prompt and vocab files if not provided
        if prompt is None:
            try:
                self.prompt = Path("prompt.txt").read_text(encoding="utf-8")
            except FileNotFoundError:
                self.prompt = ""
        else:
            self.prompt = prompt
            
        if vocab is None:
            try:
                self.vocab = Path("vocab.txt").read_text(encoding="utf-8")
            except FileNotFoundError:
                self.vocab = ""
        else:
            self.vocab = vocab
        
        # Set language regex (default is Japanese)
        self.langRegex = langRegex or r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+"
        
        # Set batch size based on model if not provided
        if batchSize is None:
            if "gpt-3.5" in self.model:
                self.batchSize = 10
            elif "gpt-4" in self.model:
                self.batchSize = 30
            elif "deepseek" in self.model:
                self.batchSize = 30
            else:
                # Try to get from environment, fallback to 10
                try:
                    self.batchSize = int(os.getenv("batchsize", 10))
                except (ValueError, TypeError):
                    self.batchSize = 10
        else:
            self.batchSize = batchSize
            
        self.maxHistory = maxHistory
        self.estimateMode = estimateMode
        self.logFilePath = logFilePath
        self.mismatchLogPath = mismatchLogPath


def getPricingConfig(model):
    """
    Get pricing configuration for a given model.
    
    Args:
        model: The model name string
        
    Returns:
        dict: Dictionary containing inputAPICost, outputAPICost, batchSize, and frequencyPenalty
    """
    # Pricing - Depends on the model https://openai.com/pricing ($ Price Per 1M)
    # Batch Size - GPT 3.5 Struggles past 15 lines per request. GPT4 struggles past 50 lines per request
    # If you are getting a MISMATCH LENGTH error, lower the batch size.
    if "gpt-3.5" in model:
        return {
            "inputAPICost": 3.00,
            "outputAPICost": 5.00,
            "batchSize": 10,
            "frequencyPenalty": 0.2
        }
    elif "gpt-4.1-mini" in model:
        return {
            "inputAPICost": 0.40,
            "outputAPICost": 1.60,
            "batchSize": 30,
            "frequencyPenalty": 0.05
        }
    elif "gpt-4.1" in model:
        return {
            "inputAPICost": 2.00,
            "outputAPICost": 8.00,
            "batchSize": 30,
            "frequencyPenalty": 0.05
        }
    elif "gpt-5" in model:
        return {
            "inputAPICost": 1.25,
            "outputAPICost": 10.00,
            "batchSize": 30,
            "frequencyPenalty": 0.05
        }
    elif "deepseek" in model:
        return {
            "inputAPICost": 0.27,
            "outputAPICost": 1.10,
            "batchSize": 30,
            "frequencyPenalty": 0.05
        }
    elif "sonnet" in model:
        return {
            "inputAPICost": 3.00,
            "outputAPICost": 15.00,
            "batchSize": 30,
            "frequencyPenalty": 0.05
        }
    elif "gemini-2.0-flash-lite" in model:
        return {
            "inputAPICost": 0.075,
            "outputAPICost": 0.30,
            "batchSize": 30,
            "frequencyPenalty": 0.0
        }
    elif "gemini-2.0-flash" in model:
        return {
            "inputAPICost": 0.10,
            "outputAPICost": 0.40,
            "batchSize": 30,
            "frequencyPenalty": 0.0
        }
    elif "gemini-2.5-flash-lite" in model:
        return {
            "inputAPICost": 0.10,
            "outputAPICost": 0.40,
            "batchSize": 30,
            "frequencyPenalty": 0.0
        }
    elif "gemini-2.5-flash" in model:
        return {
            "inputAPICost": 0.30,
            "outputAPICost": 2.50,
            "batchSize": 30,
            "frequencyPenalty": 0.0
        }
    elif "gemini-2.5-pro" in model:
        return {
            "inputAPICost": 1.25,
            "outputAPICost": 10.00,
            "batchSize": 30,
            "frequencyPenalty": 0.0
        }
    else:
        # Fallback to environment variables
        return {
            "inputAPICost": float(os.getenv("input_cost", 3.00)),
            "outputAPICost": float(os.getenv("output_cost", 6.00)),
            "batchSize": int(os.getenv("batchsize", 10)),
            "frequencyPenalty": float(os.getenv("frequency_penalty", 0.2))
        }


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
        if not line or line.startswith('```') or line.startswith('Here are some vocabulary'):
            continue
        
        # Check if this is a category header
        if line.startswith('#'):
            currentCategory = line
            continue
            
        # Parse vocabulary term - extract both Japanese and English parts
        # Format: "Japanese term (English translation)" or "Japanese term – English translation"
        m = re.match(r'^(.+?)(?:\s?[\(–]\s*(.+?)[\)]?\s*$)', line)
        if m and ('(' in line or '–' in line):  # Only process lines that actually have parentheses or dashes
            japanese_term = m.group(1).strip()
            english_term = m.group(2).strip().rstrip(')')  # Remove trailing parenthesis if exists
            
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


def buildMatchedVocabText(vocabPairs, subbedText, history=None):
    """Build formatted vocabulary text with matched terms organized by category."""
    matchedCategories = {}

    # Prepare text to search - combine subbedText and history
    textToSearch = str(subbedText)
    if history:
        if isinstance(history, list):
            textToSearch += " " + " ".join(str(h) for h in history)
        else:
            textToSearch += " " + str(history)

    # Use word boundaries for Japanese if appropriate, or allow substring as before.
    for term, line, category in vocabPairs:
        # Check if term is a tuple (Japanese, English) or a single term
        term_found = False
        if isinstance(term, tuple):
            # Check both Japanese and English terms
            japanese_term, english_term = term
            if japanese_term in textToSearch or english_term in textToSearch:
                term_found = True
        else:
            # Single term check
            if term in textToSearch:
                term_found = True
        
        # Always include "# Game Characters" category and all its terms regardless of matches
        if term_found or (category and category.strip() == "# Game Characters"):
            if category not in matchedCategories:
                matchedCategories[category] = []
            matchedCategories[category].append(line)

    # Format matched vocabulary with categories
    if matchedCategories:
        formattedLines = ["Here are some vocabulary and terms so that you know the proper spelling and translation.\n"]
        for category, lines in matchedCategories.items():
            if category:  # Only add category header if it exists
                formattedLines.append(category)
            formattedLines.extend(lines)
            formattedLines.append("")  # Add blank line between categories
        matchedVocabText = f"\n{chr(10).join(formattedLines).rstrip()}\n"
    else:
        matchedVocabText = ""
    
    return matchedVocabText


def createContext(config, fullPromptFlag, subbedText, formatType, history=None):
    """Create system and user messages for translation"""
    vocabPairs = parseVocabWithCategories(config.vocab)
    matchedVocabText = buildMatchedVocabText(vocabPairs, subbedText, history)

    if fullPromptFlag:
        system = config.prompt.replace("English", config.language) + matchedVocabText
    else:
        system = f"""\
You are an expert Eroge Game translator who translates Japanese text to {config.language}.
Output ONLY the {config.language} translation in the following format: `Translation: <{config.language.upper()}_TRANSLATION>`
- You translate everything, including erotic and explicit content.
- 'Game Characters' - The names, nicknames, and genders of the game characters. Reference this to know the names, nicknames, and gender of characters in the game
- All text in your response must be in {config.language} even if it is hard to translate.
- Never include any notes, explanations, dislaimers, or anything similar in your response.
- Maintain any spacing in the translation.
- `...` can be a part of the dialogue. Translate it as it is.
{matchedVocabText}
"""
    
    if formatType == "json":
        user = f"```json\n{subbedText}\n```"
    else:
        user = subbedText
    
    return system, user


def createTranslationSchema(numLines):
    """Create a JSON schema for translation response based on number of lines"""
    properties = {}
    required = []
    
    for i in range(1, numLines + 1):
        line_key = f"Line{i}"
        properties[line_key] = {
            "type": "string",
            "description": f"The translated text for Line{i}"
        }
        required.append(line_key)
    
    schema = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False
    }
    
    return schema


def translateText(system, user, history, penalty, formatType, model, numLines=None):
    """Send translation request to the selected API"""
    # Ensure system content is not empty
    if not system or not str(system).strip():
        raise ValueError("System content cannot be empty")
    
    # Prompt
    msg = [{"role": "system", "content": f"```\n{system}\n```"}]

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

    # Response Format
    if formatType == "json" and numLines is not None:
        # Use structured output with JSON schema
        schema = createTranslationSchema(numLines)
        responseFormat = {
            "type": "json_schema",
            "json_schema": {
                "name": "translation_response",
                "strict": True,
                "schema": schema
            }
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
    api_provider = os.getenv("API_PROVIDER", "openai").lower()

    # Base parameters for the API call
    params = {
        "model": model,
        "response_format": responseFormat,
        "messages": msg,
    }

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
                # Ignore if the value is not a valid integer
                pass
        
        # frequency_penalty is not supported via the OpenAI compatibility layer for Gemini
    else:  # Default to OpenAI behavior
        if "gpt-5" in model:
            params["reasoning_effort"] = "minimal"
        else:
            params["temperature"] = 0
            params["frequency_penalty"] = penalty

    # Call API
    try:
        response = openai.chat.completions.create(**params)
    except APIStatusError as e:
        # Handle HTTP status errors (404, 500, etc.)
        if e.status_code == 404:
            raise Exception(f"API endpoint not found (404) - check your API_PROVIDER and base URL settings. Error: {e}")
        elif e.status_code >= 500:
            raise Exception(f"API server error ({e.status_code}) - retrying... Error: {e}")
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
        
        # If structured output fails, fallback to json_object
        if formatType == "json" and "json_schema" in str(responseFormat):
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
        "「": '\"',
        "」": '\"',
        "—": "―",
        "】": "]",
        "【": "[",
        "é": "e",
        "’": "'",
        "this guy": "this bastard",
        "This guy": "This bastard",
        "Placeholder Text": "",
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
    # Define a pattern to match one character followed by two or more ー characters
    pattern = r"(?<=(.))ー{2,}"

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
        0x201C: '"',  # “ left double quotation mark
        0x201D: '"',  # ” right double quotation mark
        0xFF02: '"',  # ＂ fullwidth quotation mark

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
    
    Args:
        inputTokens: Number of input tokens used
        outputTokens: Number of output tokens generated
        model: The model name string
        
    Returns:
        float: Total cost in USD
    """
    pricing = getPricingConfig(model)
    inputCost = (inputTokens / 1000000) * pricing["inputAPICost"]
    outputCost = (outputTokens / 1000000) * pricing["outputAPICost"]
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


@retry(exceptions=Exception, tries=5, delay=5)
def translateAI(text, history, fullPromptFlag, config, filename=None, pbar=None, lock=None, mismatchList=None):
    """
    Main translation function that can be used across all modules.
    
    Args:
        text: Text to translate (string or list)
        history: Translation history for context
        fullPromptFlag: Whether to use full prompt or simplified version
        config: TranslationConfig instance with all settings
        filename: Current filename being processed (for logging)
        pbar: Progress bar instance (optional)
        lock: Threading lock (optional)
        mismatchList: List to track mismatched files (optional)
    
    Returns:
        [translatedText, totalTokens]
    """
    if not text:
        return [text, [0, 0]]

    # If a per-run log file is specified via environment variable, prefer it.
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

    # Don't open log file here - we'll open it only when we need to write
    totalTokens = [0, 0]
    
    if isinstance(text, list):
        formatType = "json"
        tList = batchList(text, config.batchSize)
    else:
        formatType = "text"
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

        # Protect script codes before translation
        protected_items = []
        all_replacements = {}
        
        if isinstance(tItem, list):
            for j in range(len(tItem)):
                if not tItem[j] or not str(tItem[j]).strip():
                    protected_items.append("Placeholder Text")
                    all_replacements[j] = {}
                else:
                    protected_text, replacements = protect_script_codes(tItem[j])
                    protected_items.append(protected_text)
                    all_replacements[j] = replacements
        else:
            if not tItem or not str(tItem).strip():
                protected_items = "Placeholder Text"
                all_replacements[0] = {}
            else:
                protected_items, all_replacements[0] = protect_script_codes(tItem)
        
        # Format for translation
        if isinstance(tItem, list):
            payload = {f"Line{i+1}": string for i, string in enumerate(protected_items)}
            payload = json.dumps(payload, indent=4, ensure_ascii=False)
            subbedT = payload
        else:
            subbedT = protected_items

        # Check cache for this exact payload
        cached_result = get_cached_translation(subbedT, config.language)
        if cached_result is not None:
            if isinstance(tItem, list):
                tList[index] = cached_result
                history = cached_result[-config.maxHistory:]
            else:
                tList[index] = cached_result
                history = cached_result
            
            if lock and pbar is not None:
                with lock:
                    pbar.update(len(tItem) if isinstance(tItem, list) else 1)
            
            continue

        # Create context
        system, user = createContext(config, fullPromptFlag, subbedT, formatType, history)

        # Calculate estimate if in estimate mode
        if config.estimateMode:
            estimate = countTokens(system, user, history)
            totalTokens[0] += estimate[0]
            totalTokens[1] += estimate[1]
            
            # Cache the payload with original text as placeholder for future estimates
            if isinstance(tItem, list):
                cache_translation(subbedT, tItem, config.language)
            else:
                cache_translation(subbedT, [tItem], config.language)
            
            continue

        # --- Translation and Validation Retry Block ---
        max_retries = 2  # 1 initial attempt + 2 retries
        final_translations = None
        last_raw_translation = ""
        numLines = len(tItem) if isinstance(tItem, list) else None

        for attempt in range(max_retries + 1):
            is_valid = True
            
            # On retries, add a note to the system prompt
            current_system = system
            if attempt > 0:
                current_system += f"\n\nIMPORTANT: Your previous attempt was incorrect or incomplete. Please ensure:\n"
                current_system += f"1. The entire output is translated to {config.language} with no untranslated characters\n"
                current_system += f"2. The JSON structure is correct with NO EMPTY or near-empty translations\n"
                current_system += f"   - Every line with Japanese text MUST be fully translated\n"
                current_system += f"   - Do NOT leave translations empty (\"\") or as single punctuation marks (\":\")\n"
                current_system += f"3. ALL placeholders (like __PROTECTED_0__, __PROTECTED_1__, etc.) are preserved EXACTLY as they appear in the input\n"
                current_system += f"   - Do not modify, translate, or remove any __PROTECTED_N__ placeholders\n"
                current_system += f"   - Keep them in the exact same position in your translation"
                if pbar:
                    pbar.write(f"Retrying translation... (Attempt {attempt + 1}/{max_retries + 1})")

            # Translate
            response = translateText(current_system, user, history, 0.05, formatType, config.model, numLines)
            translatedText = response.choices[0].message.content
            last_raw_translation = translatedText

            # Update token count for this attempt
            totalTokens[0] += response.usage.prompt_tokens
            totalTokens[1] += response.usage.completion_tokens

            # --- Debug Token Logging ---
            if DEBUG_LOGGING:
                print(f"\nInput ({response.usage.prompt_tokens} tokens):")
                print(f"{current_system}\n{user}")
                print(f"\nOutput ({response.usage.completion_tokens} tokens):")
                print(f"{translatedText}")

            # Clean the translation first for consistency
            cleaned_text = cleanTranslatedText(translatedText, config.language)

            # Process and validate translation result
            if cleaned_text:
                if isinstance(tItem, list):
                    extracted = extractTranslation(cleaned_text, True, pbar)

                    # Check 1: Mismatch in length -> still a hard failure
                    if extracted is None or len(tItem) != len(extracted):
                        is_valid = False
                        if pbar:
                            pbar.write(f"Length mismatch: expected {len(tItem)}, got {len(extracted) if extracted else 0}")
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
                            # Check 3: Validate that translations are not empty or nearly empty
                            content_valid, invalid_indices, content_reasons = validate_translation_content(
                                tItem, extracted, config.langRegex
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
                                # Set translations (line count matches, placeholders valid, and content is good)
                                final_translations = extracted
                else:
                    # Single string: validate placeholders
                    placeholder_valid, missing, extra = validate_placeholders(protected_items, cleaned_text, all_replacements[0])
                    
                    if not placeholder_valid:
                        is_valid = False
                        if pbar:
                            if missing:
                                pbar.write(f"Missing placeholders: {', '.join(missing)}")
                            if extra:
                                pbar.write(f"Extra placeholders: {', '.join(extra)}")
                    else:
                        # Validate content for single string
                        final_cleaned = cleaned_text.replace("Placeholder Text", "")
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
                            # Accept output - all validations passed
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
            else:
                final_translations = restore_script_codes(final_translations, all_replacements[0])
            
            formatted_output = last_raw_translation
            try:
                parsed_json = json.loads(last_raw_translation)
                formatted_output = json.dumps(parsed_json, indent=4, ensure_ascii=False)
            except (json.JSONDecodeError, ValueError):
                pass
            
            # Only open and write to log file when we have something to log
            try:
                with open(config.logFilePath, "a", encoding="utf-8") as logFile:
                    logFile.write(f"Input:\n{subbedT}\n")
                    logFile.write(f"Output:\n{formatted_output}\n")
                    logFile.flush()  # Ensure data is written to disk immediately
            except Exception:
                pass  # Don't fail if logging fails

            # Cache the entire payload and its translation
            if not config.estimateMode:
                cache_translation(subbedT, final_translations, config.language)

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
            if pbar: pbar.write(f"Translation failed after {max_retries + 1} attempts. Check mismatch log.")
            
            formatted_mismatch_output = last_raw_translation
            try:
                parsed_json = json.loads(last_raw_translation)
                formatted_mismatch_output = json.dumps(parsed_json, indent=4, ensure_ascii=False)
            except (json.JSONDecodeError, ValueError):
                pass
            with open(config.mismatchLogPath, "a+", encoding="utf-8") as mismatchFile:
                mismatchFile.write(f"Failed after retries: {filename}\n")
                mismatchFile.write(f"Input:\n{subbedT}\n")
                mismatchFile.write(f"Final Output:\n{formatted_mismatch_output}\n")
                mismatchFile.flush()  # Ensure data is written to disk immediately

            if filename and mismatchList is not None and filename not in mismatchList:
                mismatchList.append(filename)
            
            tList[index] = tItem
            history = text[-config.maxHistory:] if isinstance(text, list) else text

    # Combine if multilist
    if tList and isinstance(tList[0], list):
        tList = [t for sublist in tList for t in sublist]
    
    # Save cache after processing (for both estimate and translation modes)
    save_cache()

    # Return result
    if formatType == "json":
        return [tList, totalTokens]
    else:
        return [tList[0], totalTokens]