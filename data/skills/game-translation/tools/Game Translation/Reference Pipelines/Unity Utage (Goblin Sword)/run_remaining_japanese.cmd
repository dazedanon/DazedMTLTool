@echo off
powershell -ExecutionPolicy Bypass -File "%~dp0run_translation.ps1" -InputJson "%~dp0..\non_dialogue_japanese.json" -InputType non-dialogue -OutputJsonl "%~dp0out\non_dialogue_translations.jsonl" -FailedJsonl "%~dp0out\non_dialogue_translations.failed.jsonl" -MergedJson "%~dp0out\non_dialogue_japanese.mistral.en.json" -DryrunJsonl "%~dp0out\non_dialogue_live_preview.jsonl" %*
