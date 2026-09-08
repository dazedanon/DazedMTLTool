"""
YSTB repacker — apply translated dialogue back into a .ybn script.

Reads:
  - the original .ybn (to preserve all instructions, args, line numbers
    and any non-dialogue strings).
  - a translation JSON (same shape as ystb_extract.py output) where the
    'text' field of each line is updated with translated text. Set
    'speaker' too (keep original Japanese name unless renamed).

Writes a new .ybn with dialogue lines replaced. All other str-section
data is preserved by appending replacement strings at the END of the
str section and rewriting only the affected arg's offset/size.
"""
import os, sys, struct, json, re

KEY = bytes.fromhex('605e414a')
DIALOGUE_OPCODE = 0x6A

# Word-wrap config. Two modes:
#   PROPORTIONAL_WRAP=False — char-count wrap (good with monospace fonts
#     like Consolas where every ASCII char is the same pixel width).
#   PROPORTIONAL_WRAP=True  — pixel-width wrap measured with Pillow against
#     the actual TTF font. Required when the engine renders proportional
#     fonts (Verdana, Segoe UI...) — the engine's per-char advance must
#     also be proportional, which patch_locale.py's PROPORTIONAL_WIDTH
#     hook handles. Both must be set together.
PROPORTIONAL_WRAP = False
WORDWRAP_LINE_WIDTH = 60          # word budget; one cell before native wrap
WORDWRAP_PAD_WIDTH = 60           # padding target just before native wrap
WORDWRAP_FIRST_LINE_PAD_WIDTH = 61
WORDWRAP_NARRATION_PAD_WIDTH = 61 # narration starts farther left than dialogue
WORDWRAP_USE_NEWLINES = False     # raw LF is unreliable in YU-RIS dialogue strings
WORDWRAP_LINE_PX    = 595         # engine's dialog box pixel width (a few px under to be safe)
WORDWRAP_FONT_NAME  = 'segoeuib.ttf'  # Bold Segoe UI — engine renders bold (FW_BOLD=700)
WORDWRAP_FONT_SIZE  = 18          # bold Segoe UI 18 ≈ engine default

if PROPORTIONAL_WRAP:
    from PIL import ImageFont
    _font = ImageFont.truetype(WORDWRAP_FONT_NAME, WORDWRAP_FONT_SIZE)
    _SPACE_PX = _font.getlength(' ')

def _vw(s):
    """Visual width for the patched English path.

    The locale/font patch draws the cp932 quote brackets as the ASCII quote
    glyph, so they count as one visible cell. Counting them as double-width
    leaves the padding one space short and lets the next word split.
    """
    return len(s)

def _normalize_wrap_input(text):
    """Collapse accidental spacing before the script-side word wrap.

    The patched EN renderer is happiest with plain ASCII. A few translated
    lines still contain Japanese punctuation (notably the CP932 ellipsis),
    which renders as garbage in ANSI mode, so fold those before wrapping.
    """
    def ellipsis_to_dots(match):
        # Japanese VN ellipses are commonly written as "……" for "...".
        n = len(match.group(0))
        return '.' * max(3, (n * 3 + 1) // 2)

    text = re.sub(r'…+', ellipsis_to_dots, text)
    text = text.translate(str.maketrans({
        '―': '-',
        '！': '!',
        '？': '?',
        '）': ')',
    }))
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\t', ' ')
    return '\n'.join(re.sub(r' {2,}', ' ', segment).strip()
                     for segment in text.split('\n'))

def _word_wrap_chars(text, line_width=WORDWRAP_LINE_WIDTH,
                     pad_width=WORDWRAP_PAD_WIDTH,
                     first_pad_width=None):
    """Greedy word-wrap at word boundaries using padding spaces.

    YU-RIS does not treat raw LF as a reliable text return in this compiled
    dialogue path. Instead, keep words a couple cells short of the edge and
    pad each non-final segment to the engine's own monospace wrap column so
    its native character wrap fires on blank space before the next word.
    """
    if not text:
        return text
    text = _normalize_wrap_input(text)
    if _vw(text) <= line_width:
        return text
    words = text.split(' ')
    lines = []
    current = []
    current_len = 0
    for word in words:
        sep = 1 if current else 0
        wlen = _vw(word)
        if word and wlen >= line_width:
            if current:
                lines.append(' '.join(current))
                current = []; current_len = 0
            lines.append(word)
            continue
        if current_len + sep + wlen <= line_width:
            current.append(word); current_len += sep + wlen
        else:
            lines.append(' '.join(current))
            current = [word]; current_len = wlen
    if current:
        lines.append(' '.join(current))
    out = []
    for i, line in enumerate(lines):
        if i == len(lines) - 1:
            out.append(line)
        else:
            target_width = first_pad_width if i == 0 and first_pad_width is not None else pad_width
            pad = target_width - _vw(line)
            out.append(line + ' ' * max(1, pad))
    return ''.join(out)

def _word_wrap_newlines(text, line_width=WORDWRAP_LINE_WIDTH):
    """Greedy word-wrap at word boundaries using real line breaks.

    Padding spaces are visible with the current English font path, and the
    EXE's native wrap only notices the line is too wide after a word has
    already started. Explicit breaks keep both systems out of the way.
    """
    def split_long_word(word):
        if _vw(word) <= line_width:
            return [word]
        m = re.search(r'([.!?~…]+[」"\']*)$', word)
        suffix = m.group(1) if m else ''
        core = word[:-len(suffix)] if suffix and len(suffix) < line_width else word
        if not core:
            core, suffix = word, ''
        parts = []
        while _vw(core) > line_width:
            parts.append(core[:line_width])
            core = core[line_width:]
        if suffix and _vw(core + suffix) > line_width:
            room = max(1, line_width - _vw(suffix))
            if core[:room]:
                parts.append(core[:room])
            core = core[room:]
        if core or suffix:
            parts.append(core + suffix)
        return parts

    text = _normalize_wrap_input(text)

    def wrap_segment(segment):
        if not segment or _vw(segment) <= line_width:
            return segment
        words = segment.split(' ')
        lines = []
        current = []
        current_len = 0
        for word in words:
            sep = 1 if current else 0
            wlen = _vw(word)
            if wlen > line_width:
                if current:
                    lines.append(' '.join(current))
                    current = []
                    current_len = 0
                parts = split_long_word(word)
                lines.extend(parts[:-1])
                current = [parts[-1]]
                current_len = _vw(parts[-1])
                continue
            if current and current_len + sep + wlen > line_width:
                lines.append(' '.join(current))
                current = [word]
                current_len = wlen
            else:
                current.append(word)
                current_len += sep + wlen
        if current:
            lines.append(' '.join(current))
        return '\n'.join(lines)

    return '\n'.join(wrap_segment(segment) for segment in text.split('\n'))

def _word_wrap_pixels(text, line_px=WORDWRAP_LINE_PX):
    """Greedy word-wrap measured in pixels with Pillow against the active
    proportional font, padding each non-final line with trailing spaces
    so the line ends near the wrap pixel boundary."""
    if not text:
        return text
    if _font.getlength(text) <= line_px:
        return text
    words = text.split(' ')
    lines = []
    current = []
    current_px = 0.0
    for word in words:
        word_px = _font.getlength(word)
        sep_px = _SPACE_PX if current else 0
        if current and current_px + sep_px + word_px > line_px:
            lines.append(' '.join(current))
            current = [word]; current_px = word_px
        else:
            current.append(word); current_px += sep_px + word_px
    if current:
        lines.append(' '.join(current))
    # Pad each non-final line with trailing spaces so the line's pixel
    # width is just under line_px — that way the engine's pixel wrap
    # falls on a space rather than mid-word. Always emit at least 1 space
    # so adjacent lines don't visually merge into one word.
    out = []
    for i, line in enumerate(lines):
        if i < len(lines) - 1:
            cur_px = _font.getlength(line)
            pad_count = max(1, int((line_px - cur_px) / _SPACE_PX))
            out.append(line + ' ' * pad_count)
        else:
            out.append(line)
    return ''.join(out)

def word_wrap(text, pad_width=WORDWRAP_PAD_WIDTH, first_pad_width=None):
    if not text:
        return text
    if WORDWRAP_USE_NEWLINES:
        return _word_wrap_newlines(text)
    if PROPORTIONAL_WRAP:
        return _word_wrap_pixels(text)
    return _word_wrap_chars(text, WORDWRAP_LINE_WIDTH, pad_width, first_pad_width)

def xor_apply(data):
    return bytes(b ^ KEY[i & 3] for i, b in enumerate(data))

def repack(orig_ybn_path, translation_json_path, out_ybn_path):
    with open(orig_ybn_path, 'rb') as f:
        blob = f.read()
    if blob[:4] != b'YSTB':
        raise ValueError('not a YSTB file')
    ver, ic, code_sz, arg_sz, str_sz, line_sz, reserved = struct.unpack('<7I', blob[4:32])
    code_off = 32
    arg_off = code_off + code_sz
    str_off = arg_off + arg_sz
    line_off = str_off + str_sz

    code = xor_apply(blob[code_off:arg_off])
    args = bytearray(xor_apply(blob[arg_off:str_off]))
    strs = bytearray(xor_apply(blob[str_off:line_off]))
    lines = blob[line_off:line_off + line_sz]  # passthrough (still encrypted)

    with open(translation_json_path, 'r', encoding='utf-8') as f:
        trans = json.load(f)
    by_index = {entry['index']: entry for entry in trans['lines']}

    # Pull the *original* Japanese speaker key from `raw` (which we leave
    # alone). The engine matches 【...】 against the speaker registration
    # table; if we substituted English in the key, the plate stays empty
    # and the bracketed string gets rendered into the dialogue body.
    import re
    JP_SPEAKER = re.compile(r'^【([^】]*)】')
    arg_pos = 0
    for i in range(ic):
        op = code[i*4]
        argc = code[i*4+1]
        if op == DIALOGUE_OPCODE and i in by_index:
            entry = by_index[i]
            text = entry.get('text', '')
            kind = entry.get('kind', 'narration')
            raw = entry.get('raw', '')
            m = JP_SPEAKER.match(raw)
            jp_key = m.group(1) if m else ''
            if kind == 'spoken':
                # Wrap with the 「…」 brackets included — the engine renders
                # them as single-width chars in EN mode, so leaving them out
                # of the wrap budget causes line-1 padding to bleed onto
                # line 2 as leading whitespace.
                wrapped = word_wrap(f'「{text}」', WORDWRAP_PAD_WIDTH, WORDWRAP_FIRST_LINE_PAD_WIDTH)
                rebuilt = f'【{jp_key}】{wrapped}'
            elif kind == 'tagged':
                # Tagged lines are thoughts/asides like 【Name】（...） in the
                # original. The engine still needs the 「...」 dialogue wrapper
                # to split 【Name】 into the nameplate instead of rendering the
                # Japanese key inside the text body.
                wrapped = word_wrap(f'「{text}」', WORDWRAP_PAD_WIDTH, WORDWRAP_FIRST_LINE_PAD_WIDTH)
                rebuilt = f'【{jp_key}】{wrapped}'
            else:
                wrapped = word_wrap(text, WORDWRAP_NARRATION_PAD_WIDTH, WORDWRAP_NARRATION_PAD_WIDTH)
                rebuilt = wrapped
            new_bytes = rebuilt.encode('cp932')
            for a in range(argc):
                ap = arg_pos + a*12
                atype, asize, aoff = struct.unpack('<3I', args[ap:ap+12])
                if atype == 0x00000000:
                    new_off = len(strs)
                    strs.extend(new_bytes)
                    args[ap:ap+12] = struct.pack('<3I', atype, len(new_bytes), new_off)
                    break
        arg_pos += argc * 12

    new_str_sz = len(strs)
    new_arg_sz = len(args)
    enc_args = xor_apply(bytes(args))
    enc_strs = xor_apply(bytes(strs))
    enc_code = blob[code_off:arg_off]  # unchanged

    header = struct.pack('<4s7I', b'YSTB', ver, ic, code_sz, new_arg_sz, new_str_sz, line_sz, reserved)
    out_blob = header + enc_code + enc_args + enc_strs + lines
    with open(out_ybn_path, 'wb') as f:
        f.write(out_blob)
    print(f'wrote {out_ybn_path}: code={code_sz} arg={new_arg_sz} str={new_str_sz} line={line_sz}')

if __name__ == '__main__':
    if len(sys.argv) != 4:
        print('usage: ystb_repack.py <orig.ybn> <translation.json> <out.ybn>')
        sys.exit(1)
    repack(sys.argv[1], sys.argv[2], sys.argv[3])
