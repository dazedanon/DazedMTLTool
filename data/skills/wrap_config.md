You are an expert RPGMaker MV/MZ configuration analyst.

<task>
Calculate the correct text-wrap width settings for a Japanese-to-English RPGMaker MV/MZ translation tool. The tool wraps translated English using character-count limits (not pixels). I need three values: width, listWidth, and noteWidth.
</task>

--- attach System.json and js/plugins.js here before continuing ---

<instructions>
1. Read screenWidth and fontSize from System.json.
   Check js/plugins.js for any MessageCore or Window plugin that overrides these values.
2. For each window type, estimate its pixel width, subtract ~48px padding, then calculate:
   chars = floor(content_px / (font_size × 0.58))
   - width:      main dialogue/message box (Show Text) — typically full screen width
   - listWidth:  item/skill/help description windows — typically full or half screen width
   - noteWidth:  database note fields — typically the narrowest pane (~40–50% screen width)
3. If font size is above 26px and reducing it would meaningfully increase characters per line, note where to change it (System.json or the relevant plugin parameter).
</instructions>

<output_format>
Output only the final values — do not show calculations:

```
width=<N>
listWidth=<N>
noteWidth=<N>
fontSize=<N>   # or: no change needed
```

Followed by one sentence of assumptions if anything was estimated.
</output_format>

