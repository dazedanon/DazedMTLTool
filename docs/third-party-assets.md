# Third-party asset inventory

This inventory records the source, revision, exact checksum, and redistribution
status of third-party or externally built assets shipped with DazedTL. A source
URL is not a license grant. Rows marked **release blocker** must be resolved
before producing another public release.

| Asset | Source revision | SHA-256 | Redistribution record |
| --- | --- | --- | --- |
| `data/sfx_reference/j_ono.json` | [J-Ono Data](https://github.com/ObakeConstructs/j-ono-data) | `f4a5357a4625b8d31861b5e895faec681cfc0e7bd187368362b5b0e487f24c77` | MIT; `data/sfx_reference/LICENSE.md` |
| `gameupdate/UberWolfCli.exe` | [Sinflower/UberWolf](https://github.com/Sinflower/UberWolf) | `fffbe66caf10699865010217aeabe3a3684ec9320ffe461268f1c9509fda8917` | MIT; `gameupdate/UberWolfCli.LICENSE.txt` |
| `util/ace/offline/RV2JSON.exe` | [RV2JSON 1.2.1, commit `35db081`](https://github.com/Sinflower/RV2JSON/commit/35db081809af3989e1c13d04d9be0dce0e074bf9), blob `0ea07c6` | `51353f380ed0a7e64e5ac7834ee52b55660bcc193148147cd1239d16bb9df0c4` | MIT; `util/ace/offline/RV2JSON.LICENSE.txt` |
| `util/ace/offline/RPGMakerDecrypter-cli.exe` | [v3.0.4, commit `465c88c`](https://github.com/uuksu/RPGMakerDecrypter/releases/tag/v3.0.4) | `34cd16998a57d5d844e941d739be5b721abeb2392b971bbf540247b254712cf9` | MIT; `util/ace/offline/RPGMakerDecrypter-cli.LICENSE.txt` |
| `util/wolfdawn/bin/linux/wolf` | [1.0.0, commit `a30a3e8`](https://gitgud.io/zero64801/wolfdawn/-/commit/a30a3e82f133cebe10847f82897e7ff953fc57a5) | `92300b8c86099e3488b5236358695d3cb2309da63c0ce9ebc5e92c9502d5b834` | **Release blocker: upstream declares no license**; `util/wolfdawn/bin/PROVENANCE.md` |
| `util/wolfdawn/bin/windows/wolf.exe` | [1.0.0, commit `a30a3e8`](https://gitgud.io/zero64801/wolfdawn/-/commit/a30a3e82f133cebe10847f82897e7ff953fc57a5) | `aecf735c7421f12a04237faf46eb834af1a8859a9eed9dda7495b7c65bc1ada7` | **Release blocker: upstream declares no license**; `util/wolfdawn/bin/PROVENANCE.md` |
| `util/forge/upstream/Forge_MV.js` | [commit `0ac4cfe`](https://gitgud.io/zero64801/forge-mvmz/-/commit/0ac4cfe97c902756f26540de2592279918a5b453) | `117ea4a9e0b032f6831f42bcfdb0aaddea0904f4f483b2c7dfbdcf00547eb581` | MIT; `util/forge/upstream/LICENSE.txt` |
| `util/forge/upstream/Forge_MZ.js` | [commit `0ac4cfe`](https://gitgud.io/zero64801/forge-mvmz/-/commit/0ac4cfe97c902756f26540de2592279918a5b453) | `f5d6b764dccf63149559579cfa037fb1843fe70e5adca31d4e4b82b430b5cd73` | MIT; `util/forge/upstream/LICENSE.txt` |
| `util/tl_inspector/TLInspector.js` | Sakura & Kao_SSS; no public source located | `284d68269c68ae0005c9a4274f6ec80436be7d3514ba2eeebc10b60dff8b9e0d` | **Release blocker: no source or license grant**; `util/tl_inspector/PROVENANCE.md` |

When refreshing an asset, update its checksum and revision information in the
same change. Keep license texts next to the affected bundle so source archives
and offline installations retain them.
