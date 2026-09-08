using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using HarmonyLib;

namespace NTRSoccerEnglish
{
    /// <summary>
    /// Full English patch for NTR Soccer (Hizure, Unity 2022.3 Mono).
    ///
    /// The game ships a complete official English localization inside its
    /// Pixel Crushers Dialogue Database (base "Dialogue Text" fields) and UI
    /// TextTable ("Default" language), but every scene hard-locks the
    /// Dialogue System to language "ja".
    ///
    /// Layer 1 (LanguagePatches): force the Dialogue System language to the
    ///   base/Default language ("") so dialogue, actor names, response menus
    ///   and the UI text table all resolve to the official English.
    /// Layer 2 (TextPatches + TranslationStore): a TMP/UI.Text dictionary
    ///   hook loaded with all 2,595 JP->EN pairs (official EN + Mistral for
    ///   the gaps) that catches any Japanese string that still reaches a
    ///   text component, and logs whatever it cannot translate.
    /// </summary>
    [BepInPlugin(GUID, NAME, VERSION)]
    public class Plugin : BaseUnityPlugin
    {
        public const string GUID = "com.sw.ntrsoccer.english";
        public const string NAME = "NTRSoccerEnglish";
        public const string VERSION = "1.0.0";

        internal static ManualLogSource Log;
        internal static ConfigEntry<bool> CfgForceEnglish;
        internal static ConfigEntry<bool> CfgTextHook;
        internal static ConfigEntry<bool> CfgAutoSize;
        internal static ConfigEntry<bool> CfgVerbose;
        internal static ConfigEntry<bool> CfgLogUntranslated;
        internal static ConfigEntry<bool> CfgFallbackContains;

        private Harmony _harmony;

        private void Awake()
        {
            Log = Logger;

            CfgForceEnglish = Config.Bind("General", "ForceEnglishLanguage", true,
                "Force the Pixel Crushers Dialogue System language to the base language, " +
                "which is the game's official English. This alone translates dialogue, " +
                "names, menus and UI.");
            CfgTextHook = Config.Bind("General", "EnableTextHook", true,
                "Also hook TextMeshPro / UI.Text setters and translate any Japanese " +
                "string via the bundled dictionary (safety net).");
            CfgAutoSize = Config.Bind("General", "EnableAutoSize", false,
                "Shrink-to-fit text components so long English strings don't overflow " +
                "boxes authored for Japanese. Off by default because the game ships " +
                "official multi-language UI that already fits.");
            CfgVerbose = Config.Bind("Debug", "VerboseLogging", false,
                "Log every translation swap performed by the text hook.");
            CfgLogUntranslated = Config.Bind("Debug", "LogUntranslated", true,
                "Write Japanese strings that reach a text component without a dictionary " +
                "hit to BepInEx/plugins/NTRSoccerEnglish/untranslated.txt.");
            CfgFallbackContains = Config.Bind("Advanced", "FallbackContainsReplace", false,
                "Last-resort substring replace for composed strings. Usually unnecessary.");

            if (CfgTextHook.Value)
            {
                TranslationStore.LoadAll();
            }

            _harmony = new Harmony(GUID);
            int patched = 0;
            if (CfgForceEnglish.Value)
            {
                patched += LanguagePatches.Apply(_harmony);
            }
            if (CfgTextHook.Value)
            {
                patched += TextPatches.Apply(_harmony);
            }
            Log.LogInfo($"{NAME} {VERSION}: {patched} hooks applied, " +
                        $"{TranslationStore.Count} dictionary entries loaded.");
        }
    }
}
