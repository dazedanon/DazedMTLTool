import re

# Wolf / RPG Maker inline codes that do not occupy visible box width.
_WOLF_INLINE_VISIBLE_STRIP = re.compile(
    r"[\\]+(?:"
    r"r\[[^\]]*\]|"
    r"c(?:self)?\[[^\]]*\]|"
    r"f\[[^\]]*\]|"
    r"[A-Za-z]+\[[^\]]*\]|"
    r"\^|"
    r"[ @<>\-]|"
    r"[A-Za-z]"
    r")"
)
_WOLF_CODE_PLACEHOLDER = re.compile(r"__WOLF_CODE_\d+__")


def _get_visible_length(text: str) -> int:
    """
    Calculate the visible length of text, ignoring inline control codes.

    Handles Wolf ``\\f[N]``, ``\\c[N]``, ruby ``\\r[...]``, and legacy RPG Maker
    color codes so wrap-width checks match in-game bulletin / message boxes.
    """
    if not text:
        return 0
    cleaned = _WOLF_INLINE_VISIBLE_STRIP.sub("", text)
    cleaned = _WOLF_CODE_PLACEHOLDER.sub("", cleaned)
    cleaned = re.sub(r"[\\]+[cC]\[\d+\]", "", cleaned)
    cleaned = re.sub(r"[\\]+[fF](?:\[\d+\])?", "", cleaned)
    cleaned = re.sub(r"[\\]+.", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return len(cleaned)


def visible_word_wrap_end_index(text: str, width: int) -> int:
    """Return index into *text* after the last word that fits *width* visible chars.

    Uses the same word-wrapping rules as :func:`wrapText`. Wolf ``\\c[]`` /
    ``\\f[]`` codes do not count toward *width*.
    """
    if not text or width <= 0:
        return len(text)
    if _get_visible_length(text) <= width:
        return len(text)
    words = text.split()
    if not words:
        return len(text)
    current_len = 0
    kept = 0
    pos = 0
    fit_end = 0
    for word in words:
        wl = _get_visible_length(word)
        gap = 1 if kept > 0 else 0
        if current_len + gap + wl <= width:
            idx = text.find(word, pos)
            if idx < 0:
                break
            pos = idx + len(word)
            fit_end = pos
            kept += 1
            current_len += gap + wl
        else:
            break
    if kept == 0 and words:
        idx = text.find(words[0], 0)
        fit_end = (idx + len(words[0])) if idx >= 0 else len(text)
    return fit_end


def max_line_visible_length(text: str) -> int:
    """Longest visible line length in *text* (handles ``\\r`` / ``\\n``)."""
    if not isinstance(text, str) or not text:
        return 0
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n") if normalized else [""]
    if not lines:
        return _get_visible_length(normalized)
    return max(_get_visible_length(line) for line in lines)

def wrapText(text: str, width: int) -> str:
    """
    Wrap text to the specified width, preserving RPG Maker color codes.
    
    Args:
        text (str): The text to wrap
        width (int): The maximum number of characters per line
    
    Returns:
        str: The wrapped text with lines separated by \n
    """
    if not text:
        return ""

    # Split on double newlines (\n\n or \\n\\n)
    import re
    segments = re.split(r'(?:\n\n|\\n\\n)', text)
    wrapped_segments = []
    for segment in segments:
        words = segment.split()
        lines = []
        current_line = []
        current_length = 0
        for word in words:
            word_length = _get_visible_length(word)
            if current_length + word_length + len(current_line) <= width:
                current_line.append(word)
                current_length += word_length
            else:
                if current_line:
                    lines.append(" ".join(current_line))
                current_line = [word]
                current_length = word_length
        if current_line:
            lines.append(" ".join(current_line))
        wrapped_segments.append("\n".join(lines))
    # Rejoin with double newlines to preserve hard breaks
    return "\n\n".join(wrapped_segments)


def wrapSGDesc(text: str, width: int) -> str:
    """Structured word-wrap for SG plugin description blocks.

    Unlike wrapText, this function understands the layout of SG info-box
    content:
      ◆ / ・ / • / ● lines are always kept on their own line as section
      headers; the body text immediately following is word-wrapped to
      *width*.  Paragraph breaks (\\n\\n) are preserved between sections.
    """
    HEADER_CHARS = ("◆", "・", "•", "●")

    paragraphs = text.split("\n\n")
    wrapped_paragraphs = []
    for para in paragraphs:
        lines = para.split("\n")
        out_parts = []
        body_buf: list[str] = []

        def flush_body():
            if not body_buf:
                return
            words = " ".join(body_buf).split()
            cur_line: list[str] = []
            cur_len = 0
            for word in words:
                wl = _get_visible_length(word)
                if cur_len + wl + len(cur_line) <= width:
                    cur_line.append(word)
                    cur_len += wl
                else:
                    if cur_line:
                        out_parts.append(" ".join(cur_line))
                    cur_line = [word]
                    cur_len = wl
            if cur_line:
                out_parts.append(" ".join(cur_line))
            body_buf.clear()

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(HEADER_CHARS):
                flush_body()
                # Word-wrap the header line itself — the bullet stays on the
                # first wrapped line; continuation lines are plain body lines.
                words = stripped.split()
                cur_line: list[str] = []
                cur_len = 0
                for word in words:
                    wl = _get_visible_length(word)
                    if cur_len + wl + len(cur_line) <= width:
                        cur_line.append(word)
                        cur_len += wl
                    else:
                        if cur_line:
                            out_parts.append(" ".join(cur_line))
                        cur_line = [word]
                        cur_len = wl
                if cur_line:
                    out_parts.append(" ".join(cur_line))
            else:
                body_buf.append(stripped)
        flush_body()
        wrapped_paragraphs.append("\n".join(out_parts))

    return "\n\n".join(wrapped_paragraphs)