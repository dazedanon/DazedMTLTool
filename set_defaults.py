import re
from copy import deepcopy

# Canonical defaults used by the GUI and the `set_defaults` script.
# Stored as booleans for easier consumption by the GUI.
DEFAULTS = {
    'FIRSTLINESPEAKERS': False,
    'FACENAME101': False,
    'BRFLAG': False,
    'FIXTEXTWRAP': True,
    'IGNORETLTEXT': False,
    # Speakers / Dialogue / Scroll / Choices (Main Codes)
    'CODE101': True,
    'CODE401': True,
    'CODE405': True,
    'CODE102': True,
    # Optional
    'CODE408': False,
    # Variables
    'CODE122': False,
    # Other
    'CODE355655': False,
    'CODE357': False,
    'CODE657': False,
    'CODE356': False,
    'CODE320': False,
    'CODE324': False,
    'CODE111': False,
    'CODE108': False
}


def get_defaults():
    """Return a shallow copy of the DEFAULTS dictionary."""
    return deepcopy(DEFAULTS)


def set_defaults(file_path):
    """Write canonical default values into a module file.

    The module file contains assignments like `CODE401 = True`. This
    function replaces those assignment lines with the canonical defaults.
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()

    # Update the content with the default values (converted to Python literals)
    for key, value in DEFAULTS.items():
        value_str = 'True' if value else 'False'
        content = re.sub(rf'{re.escape(key)}\s*=\s*.*', f'{key} = {value_str}', content)

    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(content)


if __name__ == "__main__":
    set_defaults('modules/rpgmakermvmz.py')
