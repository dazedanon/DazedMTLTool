import re

def set_defaults(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        content = file.read()

    # Define the default values with comments
    defaults = {
        'FIRSTLINESPEAKERS': 'False  # If 1st line of 401 is a speaker, set to True (False)',
        'FACENAME101': 'False  # Find Speakers in 101 Codes based on Face Name (False)',
        'NAMES': 'False  # Output a list of all the character names found (False)',
        'BRFLAG': 'False  # If the game uses <br> instead (False)',
        'FIXTEXTWRAP': 'True  # Overwrites textwrap (True)',
        'IGNORETLTEXT': 'False  # Ignores all translated text. (False)'
    }

    # Update the content with the default values
    for key, value in defaults.items():
        content = re.sub(f'{key} = .*', f'{key} = {value}', content)

    with open(file_path, 'w', encoding='utf-8') as file:
        file.write(content)

if __name__ == "__main__":
    set_defaults('modules/rpgmakermvmz.py')
