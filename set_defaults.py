import re

def set_defaults(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()

    # Define the default values with comments
    defaults = {
        'FIRSTLINESPEAKERS': 'False',
        'FACENAME101': 'False',
        'NAMES': 'False',
        'BRFLAG': 'False',
        'FIXTEXTWRAP': 'True',
        'IGNORETLTEXT': 'False',
        # Speakers / Dialogue / Scroll / Choices (Main Codes)
        'CODE101': 'True',
        'CODE401': 'True',
        'CODE405': 'True',
        'CODE102': 'True',
        # Optional
        'CODE408': 'False',
        # Variables
        'CODE122': 'False',
        # Other
        'CODE355655': 'False',
        'CODE357': 'False',
        'CODE657': 'False',
        'CODE356': 'False',
        'CODE320': 'False',
        'CODE324': 'False',
        'CODE111': 'False',
        'CODE108': 'False'
    }

    # Update the content with the default values
    for key, value in defaults.items():
        content = re.sub(f'{key} = .*', f'{key} = {value}', content)

    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(content)

if __name__ == "__main__":
    set_defaults('modules/rpgmakermvmz.py')
