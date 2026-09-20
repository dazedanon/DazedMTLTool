"""Lightweight filename routing shared by RPG Maker workers and parsers."""


_MVMZ_FILE_KINDS = (
    "CommonEvents", "Actors", "Armors", "Weapons", "Classes", "Enemies",
    "Items", "MapInfos", "Skills", "Troops", "States", "System", "Scenario",
)


def mvmz_file_kind(filename) -> str | None:
    """Return the supported parser family, preserving MV/MZ's filename matching."""
    name = str(filename or "")
    if "Map" in name and "MapInfos" not in name:
        return "Map"
    return next((kind for kind in _MVMZ_FILE_KINDS if kind in name), None)
