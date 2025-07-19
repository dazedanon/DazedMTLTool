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
from pathlib import Path
from retry import retry


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
        system = config.prompt + matchedVocabText
    else:
        system = f"""\
You are an expert Eroge Game translator who translates Japanese text to {config.language}.
Output ONLY the {config.language} translation in the following format: `Translation: <{config.language.upper()}_TRANSLATION>`
- You translate everything, including erotic and explicit content.
- 'Game Characters' - The names, nicknames, and genders of the game characters. Reference this to know the names, nicknames, and gender of characters in the game
- All text in your response must be in {config.language} even if it is hard to translate.
- Never include any notes, explanations, dislaimers, or anything similar in your response.
- Maintain any spacing in the translation.
- Maintain any code text in brackets if given. (e.g `[Color_0]`, `[Ascii_0]`, `[FCode_1`], etc)
- `...` can be a part of the dialogue. Translate it as it is.
{matchedVocabText}
"""
    
    if formatType == "json":
        user = f"```json\n{subbedText}\n```"
    else:
        user = subbedText
    
    return system, user


def translateText(system, user, history, penalty, formatType, model):
    """Send translation request to OpenAI API"""
    # Prompt
    msg = [{"role": "system", "content": f"```\n{system}\n```"}]

    # History
    if isinstance(history, list):
        msg.append({"role": "system", "content": "Translation History:\n```"})
        msg.extend([{"role": "assistant", "content": h} for h in history])
        msg.append({"role": "system", "content": "```"})
    else:
        msg.append({"role": "assistant", "content": history})

    # Response Format
    if formatType == "json":
        responseFormat = {"type": "json_object"}
    else:
        responseFormat = {"type": "text"}

    # Content to TL
    msg.append({"role": "user", "content": f"```\n{user}\n```"})
    response = openai.chat.completions.create(
        temperature=0,
        frequency_penalty=penalty,
        model=model,
        response_format=responseFormat,
        messages=msg,
    )
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
        "- ": "-",
        "—": "―",
        "】": "]",
        "【": "[",
        "é": "e",
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
    """Extract translation from JSON response"""
    try:
        translatedTextList = re.sub(r'\\"+\"([^,\n}])', r'\\"\1', translatedTextList)
        translatedTextList = re.sub(r"(?<![\\])\"+(?![\n,])", r'"', translatedTextList)
        lineDict = json.loads(translatedTextList)
        # If it's a batch (i.e., list), extract with tags; otherwise, return the single item.
        stringList = list(lineDict.values())
        if isList:
            return stringList
        else:
            return stringList[0]

    except Exception as e:
        if pbar:
            pbar.write(f"extractTranslation Error: {e} on String {translatedTextList}")
        return None


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
    
    with open(config.logFilePath, "a+", encoding="utf-8") as logFile:
        mismatch = False
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

            # Format for translation
            if isinstance(tItem, list):
                for j in range(len(tItem)):
                    if not tItem[j]:
                        tItem[j] = tItem[j].replace("", "Placeholder Text")
                payload = {f"Line{i+1}": string for i, string in enumerate(tItem)}
                payload = json.dumps(payload, indent=4, ensure_ascii=False)
                subbedT = payload
            else:
                subbedT = tItem

            # Create context
            system, user = createContext(config, fullPromptFlag, subbedT, formatType, history)

            # Calculate estimate if in estimate mode
            if config.estimateMode:
                estimate = countTokens(system, user, history)
                totalTokens[0] += estimate[0]
                totalTokens[1] += estimate[1]
                continue

            # Translate
            response = translateText(system, user, history, 0.05, formatType, config.model)
            translatedText = response.choices[0].message.content

            # Retry if AI refused
            if not translatedText:
                response = translateText(
                    f"{system}\n You translate ALL content.", 
                    user, history, 0.1, formatType, "gpt-4o"
                )
                translatedText = response.choices[0].message.content

            # Update token count
            totalTokens[0] += response.usage.prompt_tokens
            totalTokens[1] += response.usage.completion_tokens

            # Process translation result
            if translatedText:
                translatedText = cleanTranslatedText(translatedText, config.language)
                
                if isinstance(tItem, list):
                    extractedTranslations = extractTranslation(translatedText, True, pbar)
                    if extractedTranslations is None or len(tItem) != len(extractedTranslations):
                        # Mismatch, try again
                        response = translateText(system, user, history, 0.05, formatType, config.model)
                        translatedText = response.choices[0].message.content
                        totalTokens[0] += response.usage.prompt_tokens
                        totalTokens[1] += response.usage.completion_tokens

                        # Format and check again
                        translatedText = cleanTranslatedText(translatedText, config.language)
                        if isinstance(tItem, list):
                            extractedTranslations = extractTranslation(translatedText, True, pbar)
                            if extractedTranslations is None or len(tItem) != len(extractedTranslations):
                                # Log mismatch
                                with open(config.mismatchLogPath, "a+", encoding="utf-8") as mismatchFile:
                                    mismatchFile.write(f"Mismatch: {filename}\n")
                                    mismatchFile.write(f"Input:\n{subbedT}\n")
                                    mismatchFile.write(f"Output:\n{translatedText}\n")
                                    mismatch = True

                    logFile.write(f"Input:\n{subbedT}\n")
                    logFile.write(f"Output:\n{translatedText}\n")

                    # Set results if no mismatch
                    if not mismatch:
                        tList[index] = extractedTranslations
                        history = extractedTranslations[-config.maxHistory:]
                    else:
                        history = text[-config.maxHistory:] if isinstance(text, list) else text
                        mismatch = False
                        if filename and mismatchList is not None and filename not in mismatchList:
                            mismatchList.append(filename)

                    # Update progress bar
                    if lock and pbar is not None:
                        with lock:
                            pbar.update(len(tItem))
                else:
                    # Single string translation
                    tList[index] = translatedText.replace("Placeholder Text", "")
            else:
                if pbar:
                    pbar.write(f"AI Refused: {tItem}\n")

    # Combine if multilist
    if isinstance(tList[0], list):
        tList = [t for sublist in tList for t in sublist]

    # Return result
    if formatType == "json":
        return [tList, totalTokens]
    else:
        return [tList[0], totalTokens]
