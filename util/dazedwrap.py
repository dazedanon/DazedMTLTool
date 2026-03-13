import re

def _get_visible_length(text: str) -> int:
    """
    Calculate the visible length of text, ignoring RPG Maker color codes.
    
    Args:
        text (str): The text to measure
        
    Returns:
        int: The length of the text excluding color codes
    """
    # Remove all color codes like \c[5] or \C[35], and also ignore \\! and \\.
    cleaned_text = re.sub(r'[\\]+[cC]\[\d+\]', '', text)
    # Remove \\! and \\.
    cleaned_text = re.sub(r'[\\]+.', '', cleaned_text)
    return len(cleaned_text)

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