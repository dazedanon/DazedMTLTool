"""The voice-dropdown options, which exist in no asset file.

`VoiceFaceOverrideController` in `Release.unity` ships `replaceSetList: []` and
`addressableLabel: OverrideVoice`, so the voice list is built at runtime from
Addressables. In the state machine `<InitializeReplaceDataAsync>d__36.MoveNext`
(RVA 0x792780) each `ReplaceSet.setName` (+0x10) is assigned the address itself:

    rax[0x10] = loc2;                                  // setName = address
    var v26 = loc2.Substring(removePrefix.Length);     // ...or minus the prefix
    rax[0x10] = v26;

`removePrefix` is empty in the scene, so the first branch holds and `setName` IS
the address. `SetupDropdownOptions` (RVA 0x7963E0) then feeds `setName` straight
into `OptionData..ctor` -> `TMP_Dropdown.AddOptions`, substituting the literal
`未設定のセット` only when it is empty.

The addresses live in `StreamingAssets/aa/catalog.bin` as length-prefixed
UTF-16LE, which is why a UTF-8 scan of that file returns nothing at all.

These are translated **by construction rather than by the model**: 105 options
built from four vocabulary words in a fixed shape. Generating them guarantees
`声1_喘ぎ01` and `声3_喘ぎ07` can never disagree about what 喘ぎ means, which is
exactly the parallel-construction drift a 105-unit model pass would risk.
"""
from __future__ import annotations

import re

# 声N_<category><NN>, where category is one of the four below.
# 喘ぎ_小 must precede 喘ぎ in the alternation or the longer form never matches.
ADDRESS_RE = re.compile(r"^声([1-4])_(喘ぎ_小|喘ぎ|絶頂|余韻)([0-9]{2})$")

# The same shape, unanchored, for pulling addresses out of a longer run. A run
# from catalog.bin usually carries trailing bytes from the next record, so the
# anchored form only ever matches when the address happens to end the run.
ADDRESS_SCAN_RE = re.compile(r"声[1-4]_(?:喘ぎ_小|喘ぎ|絶頂|余韻)[0-9]{2}")

CATEGORY_EN = {
    "喘ぎ": "Moan",
    "喘ぎ_小": "Moan (soft)",
    "絶頂": "Climax",
    "余韻": "Afterglow",
}


def translate(address: str) -> str | None:
    """`声1_喘ぎ01` -> `Voice 1 - Moan 01`. None if the shape does not match."""
    m = ADDRESS_RE.match(address)
    if not m:
        return None
    voice, category, index = m.groups()
    return f"Voice {voice} - {CATEGORY_EN[category]} {index}"


def addresses(runs: list[str]) -> list[str]:
    """Pick the OverrideVoice family out of every readable run in the catalog.

    Anchored on the whole shape, not on a substring: a run that merely contains
    声1 could be a wrong-parity artifact, and those decode to plausible-looking
    CJK.
    """
    found = set()
    for s in runs:
        found.update(ADDRESS_SCAN_RE.findall(s))
    return sorted(found)
