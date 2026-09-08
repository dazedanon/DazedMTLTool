from pathlib import Path
base=Path(__file__).resolve().parents[1]
out=base/'text_translation'
out.mkdir(exist_ok=True)
for name in ['runtime_host.js','launch_runtime.ps1','runtime_request.py']:
    text=(base/'image_translation'/name).read_text(encoding='utf-8')
    text=text.replace('translation_tooling/image_translation','translation_tooling/text_translation')
    text=text.replace('translation_tooling\\image_translation','translation_tooling\\text_translation')
    (out/name).write_text(text,encoding='utf-8')
print('Isolated text QA host prepared.')
