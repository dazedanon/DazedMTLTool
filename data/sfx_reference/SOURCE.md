# J-Ono SFX reference provenance

The bundled `j_ono.json` file is a definitions-only derivative of the JSON
collection from [ObakeConstructs/j-ono-data](https://github.com/ObakeConstructs/j-ono-data).
It contains kana variants, romaji, English semantic equivalents, meanings, and
SFX classifications. Manga example metadata and all images are excluded.

- Upstream revision: `673f9f51651122e89948f5ef25794c78efe29f50`
- Upstream path: `json/j-ono-data.json`
- Upstream SHA-256: `d8f10a6399c39c64a92a0427975b00e3210e9c2d779711818493d3b02db95b84`
- License: MIT; see `LICENSE.md` in this directory.

Maintainers can regenerate the snapshot with:

```bash
python scripts/update_sfx_reference.py
```

The translator reads only this local snapshot. It does not contact J-Ono or
any other dictionary service while translating.
