"""Shared, Qt-independent RPG Maker workflow phase profiles."""

# Phase profiles applied to rpgmakermvmz.py before each translation run
# ---------------------------------------------------------------------------

# Core database files — translated first (names/descriptions)
DB_FILES = {
    "Actors.json", "Armors.json", "Classes.json", "Enemies.json",
    "Items.json",  "MapInfos.json", "Skills.json",  "States.json",
    "System.json", "Weapons.json",
}

# Event files — translated in phases 1 / 1b / 2
EVENT_FILES_EXACT = {"CommonEvents.json", "Troops.json"}
# Any Map????.json is also an event file (matched by prefix below)

PHASE0_CONFIG = {
    # All event codes OFF — DB files use top-level name/description fields
    "CODE101": False, "CODE401": False, "CODE405": False,
    "CODE102": False, "CODE408": False,
    "CODE111": False, "CODE122": False, "CODE357": False,
    "CODE355655": False, "CODE657": False, "CODE356": False,
    "CODE320": False, "CODE324": False, "CODE325": False,
    "CODE108": False,
}

PHASE1_CONFIG = {
    # Safe dialogue / choices
    "CODE101": True,
    "CODE401": True,
    "CODE405": True,
    "CODE102": True,
    # Comment continuations are project-dependent: plugins sometimes display
    # them, but most games use them only as internal editor notes.
    "CODE408": False,
    # Risky codes OFF
    "CODE122": False,
    "CODE355655": False,
    "CODE357": False,
    "CODE657": False,
    "CODE356": False,
    "CODE320": False,
    "CODE324": False,
    "CODE325": False,
    "CODE111": False,
    "CODE108": False,
}

PHASE1B_CONFIG = {
    # Dialogue OFF (handled by Phase 1)
    "CODE101": False,
    "CODE401": False,
    "CODE405": False,
    "CODE102": False,
    "CODE408": False,
    # Only 111 ON — build the var-translation cache from string comparisons
    "CODE111": True,
    "CODE122": False,
    "CODE357": False,
    "CODE355655": False,
    "CODE657": False,
    "CODE356": False,
    "CODE320": False,
    "CODE324": False,
    "CODE325": False,
    "CODE108": False,
}

PHASE2_CONFIG = {
    # Dialogue OFF (already handled by Phase 1)
    "CODE101": False,
    "CODE401": False,
    "CODE405": False,
    "CODE102": False,
    "CODE408": False,
    # Risky codes ON (111 OFF — cache already built by Phase 1b)
    "CODE122": True,
    "CODE357": True,
    "CODE111": False,
    "CODE356": False,   # plugin cmd — user can enable manually if needed
    "CODE108": False,   # comment — rarely needed
}
