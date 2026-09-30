"""Lightweight conversion between portable image jobs and desktop controls."""
from copy import deepcopy


def rgba(value, alpha=255):
    if value is None:
        return None
    if isinstance(value, list):
        return value
    return [int(value[i:i + 2], 16) for i in (1, 3, 5)] + [alpha]


def desktop_block(value):
    value = deepcopy(value)
    style = value.get('style') or {'background': 'auto'}
    for key, default in [('fill', '#20242c'), ('text_color', '#ffffff'), ('outline_color', '#000000')]:
        raw = style.get(key)
        style[key] = '#' + ''.join(f'{v:02x}' for v in raw[:3]) if isinstance(raw, list) else raw or default
        style[key + '_alpha'] = raw[3] if isinstance(raw, list) and len(raw) > 3 else 255
    for key, default in {'cap_height': 20, 'align': 'center', 'bold': False, 'italic': False}.items():
        style.setdefault(key, default)
    value['style'] = style
    return value


def portable_block(value):
    value = deepcopy(value)
    style = value.get('style') or {}
    if style.get('background', 'auto') == 'auto':
        value.pop('style', None)
    else:
        for key in ['fill', 'text_color', 'outline_color']:
            style[key] = rgba(style.get(key), style.pop(key + '_alpha', 255))
        if not style.get('outline_width'):
            style['outline_color'] = None
        value['style'] = style
    return value
