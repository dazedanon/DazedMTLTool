@echo off
setlocal

cd /d "%~dp0\.."

echo.
echo Mistral speaker/context labeling
echo Output: .translation_tooling\work\mistral_text_labels.tsv
echo.
set /p MISTRAL_API_KEY=Paste Mistral API key and press Enter: 

if "%MISTRAL_API_KEY%"=="" (
  echo No API key entered.
  pause
  exit /b 1
)

python .translation_tooling\scripts\mistral_label_context.py ^
  --input .translation_tooling\work\all_text_context.tsv ^
  --output .translation_tooling\work\mistral_text_labels.tsv ^
  --raw-log .translation_tooling\work\mistral_text_labels.raw.jsonl ^
  --batch-size 20 ^
  --context-before 6 ^
  --context-after 6 ^
  --rpm 25 ^
  --concurrency 2

echo.
echo Done. Review .translation_tooling\work\mistral_text_labels.tsv
pause
