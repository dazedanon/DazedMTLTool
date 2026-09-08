using System;
using System.Reflection;
using HarmonyLib;
using TMPro;

namespace HitonatsuTL
{
    /// <summary>
    /// Patches for text a generic setter hook cannot reach.
    ///
    /// Currently that is just TMP_Dropdown. The voice dropdown's 105 options
    /// live in no asset file: VoiceFaceOverrideController ships an empty
    /// replaceSetList and builds the list from Addressables, assigning each
    /// ReplaceSet.setName the address itself (RVA 0x792780), which
    /// SetupDropdownOptions (RVA 0x7963E0) feeds straight into OptionData.
    ///
    /// (GetBaseSituationName at RVA 0x795200 looks like the label builder
    /// because it slices an address at 喘ぎ / 絶頂 / 余韻. It is not - its only
    /// caller is a String.Compare sort comparator.)
    ///
    /// The addresses are enumerated from catalog.bin by tools/extract.py, so
    /// these arrive through the normal dictionary; this hook is what applies
    /// them, since a dropdown option never passes through a text setter.
    ///
    /// FacialLipSync is deliberately NOT patched. See the note in PIPELINE.md:
    /// its ctor defaults (targetSpeakerName = "美羽", textUIName =
    /// "SubtitleText", speakerNameUIName = "SpeakerNameText") look like they
    /// create two problems for an English patch, but BOTH scene instances
    /// serialize all three fields EMPTY, and Unity's serialized values win over
    /// ctor defaults. GameObject.Find("") returns null, so targetText and
    /// speakerNameText are never assigned, the character-count timing is never
    /// computed, and the speaker comparison is never reached. Lip sync here runs
    /// off audio amplitude (GetOutputData) and is indifferent to text length.
    ///
    /// Registration is explicit rather than PatchAll so a target a future build
    /// renames costs us that one feature, with a line in the log, instead of
    /// taking the whole translation layer down with it.
    /// </summary>
    internal static class GamePatches
    {
        public static void Apply(Harmony harmony)
        {
            Patch(harmony,
                  AccessTools.DeclaredMethod(typeof(TMP_Dropdown),
                                             nameof(TMP_Dropdown.RefreshShownValue)),
                  nameof(Dropdown_Postfix), "TMP_Dropdown.RefreshShownValue");

            Patch(harmony, AccessTools.DeclaredMethod(typeof(TMP_Dropdown), "Awake"),
                  nameof(Dropdown_Postfix), "TMP_Dropdown.Awake");
        }

        private static void Patch(Harmony harmony, MethodBase target,
                                  string postfix, string label)
        {
            if (target == null)
            {
                Plugin.Log.LogWarning($"patch target not found, skipping: {label}");
                return;
            }
            try
            {
                harmony.Patch(target,
                              postfix: new HarmonyMethod(typeof(GamePatches), postfix));
                Plugin.Log.LogInfo($"patched {label}");
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"failed to patch {label}: {e.Message}");
            }
        }

        private static void Dropdown_Postfix(TMP_Dropdown __instance)
        {
            var d = __instance;
            if (d == null) return;
            try
            {
                var options = d.options;
                if (options != null)
                {
                    for (int i = 0; i < options.Count; i++)
                    {
                        var opt = options[i];
                        if (opt == null) continue;
                        var text = opt.text;
                        if (string.IsNullOrEmpty(text)) continue;
                        // Idempotent: an option already in English misses the
                        // dictionary and is left alone, so re-running is free.
                        if (TranslationStore.TryGet(text, out var en) && en != text)
                        {
                            opt.text = en;
                            if (Plugin.CfgVerbose?.Value == true)
                                Plugin.Log.LogInfo($"TL[dropdown]: {text} -> {en}");
                        }
                        else
                        {
                            TranslationStore.ReportIfUntranslated(text, "dropdown");
                        }
                    }
                }

                // The caption is a separate component and does not re-read the
                // option list once we have edited an entry in place.
                var caption = d.captionText;
                if (caption != null && !string.IsNullOrEmpty(caption.text)
                    && TranslationStore.TryGet(caption.text, out var cen))
                {
                    caption.text = cen;
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"Dropdown_Postfix failed: {e.Message}");
            }
        }
    }
}
