using System;
using HarmonyLib;
using PixelCrushers;
using PixelCrushers.DialogueSystem;
using UnityEngine;

namespace NTRSoccerEnglish
{
    /// <summary>
    /// Forces the Pixel Crushers Dialogue System to its base/Default language,
    /// which is this game's official English:
    ///
    ///  - DialogueSystemController.SetLanguage(string) — called by
    ///    InitializeLocalization() with the scene-serialized "ja" on every
    ///    scene load, and by any game code that switches language.
    ///  - UILocalizationManager.currentLanguage setter — used by SetLanguage
    ///    and the language-changed pipeline; UpdateUIs() persists the value
    ///    to PlayerPrefs("Language").
    ///  - Localization.language static setter — the low-level switch every
    ///    localized field lookup keys off (isDefaultLanguage => base fields).
    ///  - TextTable.currentLanguageID static setter — raw language ID used by
    ///    TextTable.GetFieldText and settable by the SetCurrentTextTableLanguage
    ///    PlayMaker action (unused by this game's scenes, patched anyway;
    ///    ID 0 = Default = English).
    ///
    /// With language == "" :
    ///  - Field.LookupLocalizedValue returns the base "Dialogue Text" /
    ///    "Menu Text" / actor "Name" fields (official English).
    ///  - TextTable.GetFieldTextForLanguage falls back to the Default column,
    ///    and for the handful of fields whose Default is blank it returns the
    ///    field name itself — which is also English ("Info", "Contacts", ...).
    /// </summary>
    internal static class LanguagePatches
    {
        public static int Apply(Harmony harmony)
        {
            int n = 0;
            n += TryPatchPrefix(harmony,
                AccessTools.Method(typeof(DialogueSystemController), "SetLanguage",
                    new[] { typeof(string) }),
                nameof(ForceLanguageArg0),
                "DialogueSystemController.SetLanguage");
            n += TryPatchPrefix(harmony,
                AccessTools.PropertySetter(typeof(UILocalizationManager), "currentLanguage"),
                nameof(ForceLanguageValue),
                "UILocalizationManager.set_currentLanguage");
            n += TryPatchPrefix(harmony,
                AccessTools.PropertySetter(typeof(Localization), "language"),
                nameof(ForceLanguageValue),
                "Localization.set_language");
            n += TryPatchPrefix(harmony,
                AccessTools.PropertySetter(typeof(TextTable), "currentLanguageID"),
                nameof(ForceLanguageId),
                "TextTable.set_currentLanguageID");

            // Clear any previously saved language choice so nothing re-applies "ja"
            // before our prefixes see it.
            try
            {
                if (PlayerPrefs.HasKey("Language") &&
                    !string.IsNullOrEmpty(PlayerPrefs.GetString("Language")))
                {
                    Plugin.Log.LogInfo(
                        $"clearing saved PlayerPrefs Language '{PlayerPrefs.GetString("Language")}'");
                    PlayerPrefs.SetString("Language", string.Empty);
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"PlayerPrefs language reset failed: {e.Message}");
            }
            return n;
        }

        private static int TryPatchPrefix(Harmony harmony, System.Reflection.MethodBase target,
            string prefixName, string label)
        {
            if (target == null)
            {
                Plugin.Log.LogWarning($"patch target not found: {label}");
                return 0;
            }
            try
            {
                harmony.Patch(target,
                    prefix: new HarmonyMethod(typeof(LanguagePatches), prefixName));
                return 1;
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"failed to patch {label}: {e.Message}");
                return 0;
            }
        }

        private static void ForceLanguageArg0(ref string language)
        {
            if (!string.IsNullOrEmpty(language))
            {
                language = string.Empty;
            }
        }

        private static void ForceLanguageValue(ref string value)
        {
            if (!string.IsNullOrEmpty(value))
            {
                value = string.Empty;
            }
        }

        private static void ForceLanguageId(ref int value)
        {
            if (value != 0)
            {
                value = 0;   // 0 = Default column = official English
            }
        }
    }
}
