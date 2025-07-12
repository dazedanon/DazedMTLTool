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