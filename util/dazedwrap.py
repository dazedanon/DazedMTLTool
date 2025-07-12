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
    
    words = text.split()
    lines = []
    current_line = []
    current_length = 0
    
    for word in words:
        # Calculate visible length ignoring color codes
        word_length = _get_visible_length(word)
        
        # Check if adding this word would exceed the width
        if current_length + word_length + len(current_line) <= width:
            current_line.append(word)
            current_length += word_length
        else:
            if current_line:  # Only add line if we have words
                lines.append(" ".join(current_line))
            current_line = [word]
            current_length = word_length
    
    # Add the last line if it has any words
    if current_line:
        lines.append(" ".join(current_line))
    
    return "\n".join(lines)