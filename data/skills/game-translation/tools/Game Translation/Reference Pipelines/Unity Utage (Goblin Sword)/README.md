# Mistral Translation Runner: Unity/Utage

This folder is tailored for the extracted Unity IL2CPP / Utage visual novel data in this game folder.

It uses normal Mistral `/v1/chat/completions` requests. The Mistral Batch API is not used, because some free-tier keys do not have permission for batch jobs.

It uses:

- `prompt.md` for Unity/Utage-specific localization rules.
- `glossary.md` for names, UI terms, RPG terms, and speaker/title consistency.
- `translate_mistral.py` for scene-aware request building, retry/resume-safe JSONL output, validation, and merge files.
- `run_translation.cmd` / `run_translation.ps1` as Windows entry points.

## Default Input

The default input is the scene-grouped dialogue extract:

```text
tooling\utage_dialogue_scenes.json
```

Each Utage scene is sent as a normal chat-completion request when possible, so dialogue, narration, and choices stay together for LLM context.

For UI/menu/general Japanese text, use:

```text
tooling\non_dialogue_japanese.json
```

## Quick Start

Preview the live request payloads without using API credits:

```powershell
tooling\mistral_translate\run_translation.cmd -DryRun -MaxUnits 3
```

Run a small live test:

```powershell
$env:MISTRAL_API_KEY = "your_key_here"
tooling\mistral_translate\run_translation.cmd -MaxUnits 1
```

Run the full dialogue translation:

```powershell
tooling\mistral_translate\run_translation.cmd
```

Translate non-dialogue UI/general text:

```powershell
tooling\mistral_translate\run_remaining_japanese.cmd
```

Merge existing JSONL translations without calling the API:

```powershell
tooling\mistral_translate\run_translation.cmd -MergeOnly
```

## Outputs

Dry-run request preview:

```text
tooling\mistral_translate\out\utage_live_preview.jsonl
```

Resume-safe per-line translations:

```text
tooling\mistral_translate\out\utage_translations.jsonl
```

Merged scene JSON:

```text
tooling\mistral_translate\out\utage_dialogue_scenes.mistral.en.json
```

Failures and validation warnings:

```text
tooling\mistral_translate\out\utage_translations.failed.jsonl
```

## Useful Filters

Translate only choices:

```powershell
tooling\mistral_translate\run_translation.cmd -Kind choice
```

Translate only narration:

```powershell
tooling\mistral_translate\run_translation.cmd -Kind narration
```

Slow down requests for tighter free-tier limits:

```powershell
tooling\mistral_translate\run_translation.cmd -LiveSleepSeconds 3 -RequestsPerMinute 20
```

Use a different model:

```powershell
tooling\mistral_translate\run_translation.cmd -Model mistral-small-latest
```

## Notes

The runner does not patch Unity assets directly. It creates reviewable translation JSON first. Injection/repacking should stay separate so rich text tags, placeholders, punctuation, and line ids can be validated before touching game data.
