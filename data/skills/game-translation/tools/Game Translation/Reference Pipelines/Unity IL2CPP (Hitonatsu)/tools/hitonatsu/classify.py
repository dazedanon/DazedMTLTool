"""Which JP-bearing field paths are player-facing, and which are keys.

Every JP field path found in the shipped data must appear in exactly one table
below. A path in neither is a FATAL extraction error, not a warning - that is
what makes this a gate rather than a report, and it is what will catch a field
the next game build introduces.

`DISPLAY` -> becomes a translation unit.
`INTERNAL` -> deliberately excluded, with the evidence for excluding it.
"""

DISPLAY = {
    "MonoBehaviour.m_text":
        "TMP_Text.m_text - the serialized label a TextMeshPro component draws.",
    "MonoBehaviour.m_Options.m_Options[].m_Text":
        "TMP_Dropdown.OptionData.m_Text - an option row in a dropdown list.",
    "MonoBehaviour.defaultDropdownLabel":
        "VoiceFaceOverrideController - caption for the un-overridden expression set.",
    "MonoBehaviour.mainDropdownLabel":
        "VoiceFaceOverrideController - caption of the main voice dropdown.",
    "MonoBehaviour.dropdown0104Label":
        "VoiceFaceOverrideController - caption of the afterglow voice dropdown.",
    "MonoBehaviour.overrideList[].dropdownName":
        "VoiceFaceOverrideController - the per-entry name listed in the expression dropdown.",
}

INTERNAL = {
    "MonoBehaviour.fsm.states[].name":
        "PlayMaker FSM state name. transitions[].toState must match it byte for byte; "
        "renaming either half silently breaks scene flow.",
    "MonoBehaviour.fsm.states[].transitions[].toState":
        "PlayMaker transition target - the other half of the same identity pair.",
    "MonoBehaviour.fsm.name":
        "PlayMaker FSM asset name, addressed by FsmString lookups.",
    "MonoBehaviour.fsm.startState":
        "PlayMaker entry state name - same identity constraint as toState.",
    "GameObject.m_Name":
        "Scene object / armature bone names (mostly the literal word ボーン). Resolved by "
        "GameObject.Find and by the skinned-mesh bone bindings.",
    "MonoBehaviour.expressions[].shapes[].shapeName":
        "Blendshape channel name, looked up on the mesh. The game's own error string "
        "'... というシェイプキーが見つかりません。名前が合っているか確認してください。' proves it is "
        "matched by name, so translating it breaks facial expressions.",
    "MonoBehaviour.overrideList[].overrideShapes[].shapeName":
        "Same blendshape channel lookup, on the override path.",
    "MonoBehaviour.mixerKeySettings[].keyword":
        "Substring matched against the Addressables address of a voice clip - see the log "
        "string '[VoiceOverride Mixer] アドレス名: '. A key, not a label.",
}

# Dialogue System database fields, same rule.
DB_DISPLAY = {
    "Dialogue Text": "The subtitle line shown for a dialogue entry.",
    "Menu Text": "The player-choice button label.",
}

DB_INTERNAL = {
    "Description": "Author's editor note on an entry. Never drawn at runtime.",
    "Title": "Conversation/actor identifier, addressed by name from PlayMaker and Lua.",
    "Name": "Actor identifier, used as the Lua key and by DialogueLua.",
    "Sequence": "Sequencer command string (Fade, Delay, AudioWait...). Executable, not text.",
    "Conditions": "Lua boolean expression.",
    "Script": "Lua statement executed when the entry runs.",
    "Initial Value": "Variable seed value.",
    "Pictures": "Asset path list.",
    "IsPlayer": "Boolean flag.",
    "Actor": "Actor id reference.",
    "Conversant": "Actor id reference.",
}


class UnclassifiedPath(Exception):
    """A JP-bearing field nobody has ruled on. Fail loudly rather than drop it."""


def classify(path: str, table_display: dict, table_internal: dict) -> str:
    if path in table_display:
        return "display"
    if path in table_internal:
        return "internal"
    raise UnclassifiedPath(
        f"{path!r} contains Japanese but is in neither DISPLAY nor INTERNAL.\n"
        f"Rule on it in tools/hitonatsu/classify.py before extracting: is it drawn "
        f"on screen, or is it matched by name at runtime?"
    )
