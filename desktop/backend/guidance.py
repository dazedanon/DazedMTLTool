"""Portable game guidance shared by guided projects and Len handoffs."""
from pathlib import Path
from .project import digest
from .workflow_actions import regular

DOCUMENTS = {"glossary": (".dazedtl/glossary.txt", "glossary.txt"),
             "quirks": (".dazedtl/skills/quirks.md", "translation_quirks.txt"),
             "game": (".dazedtl/skills/game.md", "skills/translation.md")}

def documents(root):
    root = Path(root)
    result = {}
    candidates_by_name = dict(DOCUMENTS)
    for parent in (root / ".dazedtl/skills", root / "skills"):
        from util.project_preparation import _game_path
        _game_path(root, parent)
        for path in parent.glob("*.md"):
            if path.stem not in {"game", "quirks", "translation"} and valid_document_name("custom:" + path.stem):
                candidates_by_name["custom:" + path.stem] = (f".dazedtl/skills/{path.name}", f"skills/{path.name}")
    for name, candidates in candidates_by_name.items():
        found = [regular(root, root / candidate) for candidate in candidates if (root / candidate).exists() or (root / candidate).is_symlink()]
        if len(found) > 1:
            raise ValueError(f"Both portable and legacy {name} files exist. Reconcile them before editing.")
        path = found[0] if found else root / candidates[0]
        if path.exists() and path.stat().st_size > 1_000_000:
            raise ValueError("Guidance files must be below 1 MB.")
        text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        if name == "glossary":
            from util.vocab import _split_base
            text = _split_base(text)[0].rstrip("\n")
        result[name] = {"text": text, "revision": digest(text.encode()), "path": str(path)}
    return result

def document_save(root, name, revision, text):
    root = Path(root)
    current = documents(root)
    if not valid_document_name(name) or not isinstance(text, str) or len(text.encode()) > 1_000_000:
        raise ValueError("Choose a guidance document below 1 MB.")
    if name not in current:
        current[name] = {"revision": digest(b""), "text": ""}
        if revision == "":
            revision = current[name]["revision"]
    if current[name]["revision"] != revision:
        raise ValueError("This guidance changed on disk. Reload before saving.")
    if name == "glossary":
        from util.vocab import write_game_vocab
        write_game_vocab(text, game_root=root)
    else:
        from util.skills import game_skill_path_for_game, quirks_path_for_game, custom_skill_path_for_game
        path = custom_skill_path_for_game(root, name.removeprefix("custom:")) if name.startswith("custom:") else (game_skill_path_for_game if name == "game" else quirks_path_for_game)(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".desktop-tmp")
        regular(root, temporary).write_text(text, encoding="utf-8")
        temporary.replace(path)
    return documents(root)


def valid_document_name(name):
    if name in DOCUMENTS:
        return True
    if not isinstance(name, str) or not name.startswith("custom:"):
        return False
    from util.skills import sanitize_custom_skill_stem
    try:
        stem = name.removeprefix("custom:")
        return bool(stem) and sanitize_custom_skill_stem(stem) == stem
    except ValueError:
        return False
