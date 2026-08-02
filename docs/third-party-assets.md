# Third-party asset inventory

This inventory records the source and exact checksum of third-party or
externally built assets shipped with DazedTL. A documented source is not a
substitute for an adjacent license file; rows marked **missing** require a
license/provenance follow-up before the next release.

| Asset | Source / credit | SHA-256 | License record |
| --- | --- | --- | --- |
| `data/sfx_reference/j_ono.json` | [J-Ono Data](https://github.com/ObakeConstructs/j-ono-data) | `f4a5357a4625b8d31861b5e895faec681cfc0e7bd187368362b5b0e487f24c77` | MIT; `data/sfx_reference/LICENSE.md` |
| `gameupdate/UberWolfCli.exe` | [Sinflower/UberWolf](https://github.com/Sinflower/UberWolf) | `fffbe66caf10699865010217aeabe3a3684ec9320ffe461268f1c9509fda8917` | MIT; `gameupdate/UberWolfCli.LICENSE.txt` |
| `util/ace/offline/RV2JSON.exe` | [Sinflower/RV2JSON](https://github.com/Sinflower/RV2JSON) | `51353f380ed0a7e64e5ac7834ee52b55660bcc193148147cd1239d16bb9df0c4` | **Missing adjacent license record** |
| `util/ace/offline/RPGMakerDecrypter-cli.exe` | [uuksu/RPGMakerDecrypter](https://github.com/uuksu/RPGMakerDecrypter) | `34cd16998a57d5d844e941d739be5b721abeb2392b971bbf540247b254712cf9` | **Missing adjacent license record** |
| `util/wolfdawn/bin/linux/wolf` | [zero64801/wolfdawn](https://gitgud.io/zero64801/wolfdawn) | `92300b8c86099e3488b5236358695d3cb2309da63c0ce9ebc5e92c9502d5b834` | **Missing adjacent license/build revision record** |
| `util/wolfdawn/bin/windows/wolf.exe` | [zero64801/wolfdawn](https://gitgud.io/zero64801/wolfdawn) | `aecf735c7421f12a04237faf46eb834af1a8859a9eed9dda7495b7c65bc1ada7` | **Missing adjacent license/build revision record** |
| `util/forge/upstream/Forge_MV.js` | [zero64801/forge-mvmz](https://gitgud.io/zero64801/forge-mvmz) | `117ea4a9e0b032f6831f42bcfdb0aaddea0904f4f483b2c7dfbdcf00547eb581` | **Missing adjacent license/revision record** |
| `util/forge/upstream/Forge_MZ.js` | [zero64801/forge-mvmz](https://gitgud.io/zero64801/forge-mvmz) | `f5d6b764dccf63149559579cfa037fb1843fe70e5adca31d4e4b82b430b5cd73` | **Missing adjacent license/revision record** |
| `util/tl_inspector/TLInspector.js` | Sakura & Kao_SSS | `284d68269c68ae0005c9a4274f6ec80436be7d3514ba2eeebc10b60dff8b9e0d` | **Missing source and adjacent license record** |
| `fonts/TsunagiGothic.ttf` | Tsunagi Gothic | `847de1a1c7baf5c7edbda3b26fd18e5dbdfbe470d3eaa77f354e16b3c6d3e895` | **Missing source, version, and adjacent license record** |

When refreshing an asset, update its checksum and revision information in the
same change. Keep license texts next to the affected bundle so source archives
and offline installations retain them.
