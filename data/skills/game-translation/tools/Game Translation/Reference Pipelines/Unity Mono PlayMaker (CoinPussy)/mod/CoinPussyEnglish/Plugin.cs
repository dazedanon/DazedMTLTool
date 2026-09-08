using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using HarmonyLib;

namespace CoinPussyEnglish
{
    /// <summary>
    /// English patch for コイン☆プッシー / "Coin Pussy" (くじら1%, Unity 2022.3 Mono,
    /// BepInEx 5.4.23.5).
    ///
    /// The game has no localization system and no player-facing strings in
    /// Assembly-CSharp — all logic is PlayMaker FSMs. Text comes from two places,
    /// so the patch has two independent layers:
    ///
    /// Layer 1 (CsvPatches) — the whole scripted script (H-scene subtitles, the
    ///   broadcast narrator, story dialogue, battle barks, viewer comments; 5,018
    ///   units) lives in five TextAsset CSVs inside resources.assets, parsed
    ///   through PlayMaker's `CsvReader.LoadFromString`. One prefix there swaps
    ///   the entire CSV for a translated copy, matched by SHA-1 of the original,
    ///   so every row is translated at source with no ambiguity.
    ///
    /// Layer 2 (TextPatches + TranslationStore) — the 662 strings baked into
    ///   scenes and prefabs (UI labels, popups, tutorial panels, stage titles) are
    ///   caught by a JP->EN dictionary on the UI.Text / TMP_Text setters plus
    ///   Awake/OnEnable passes. This runs after every FSM comparison, so the
    ///   handful of strings that are both display labels and StringSwitch keys
    ///   (支配人, バニー, 終了) are safe to translate here.
    ///
    /// Either layer can be disabled independently in the config.
    /// </summary>
    [BepInPlugin(GUID, NAME, VERSION)]
    public class Plugin : BaseUnityPlugin
    {
        public const string GUID = "com.sw.coinpussy.english";
        public const string NAME = "CoinPussyEnglish";
        public const string VERSION = "1.0.0";

        internal static ManualLogSource Log;
        internal static ConfigEntry<bool> CfgCsvSwap;
        internal static ConfigEntry<bool> CfgTextHook;
        internal static ConfigEntry<bool> CfgAutoSize;
        internal static ConfigEntry<bool> CfgVerbose;
        internal static ConfigEntry<bool> CfgLogUntranslated;
        internal static ConfigEntry<bool> CfgFallbackContains;
        internal static ConfigEntry<bool> CfgDumpCsv;

        private Harmony _harmony;

        private void Awake()
        {
            Log = Logger;

            CfgCsvSwap = Config.Bind("General", "EnableCsvSwap", true,
                "Swap the game's five script CSVs (dialogue, narration, barks, viewer " +
                "comments) for translated copies as PlayMaker parses them. This is the " +
                "bulk of the translation.");
            CfgTextHook = Config.Bind("General", "EnableTextHook", true,
                "Hook UI.Text / TextMeshPro setters and translate scene- and prefab-baked " +
                "strings (UI labels, popups, tutorial panels) via the bundled dictionary.");
            CfgAutoSize = Config.Bind("General", "EnableAutoSize", false,
                "Shrink-to-fit text components so long English overflows less. Off by " +
                "default: the translation is written to keep the source's line count, and " +
                "auto-sizing makes the fixed subtitle boxes look inconsistent.");
            CfgVerbose = Config.Bind("Debug", "VerboseLogging", false,
                "Log every translation swap performed by the text hook.");
            CfgLogUntranslated = Config.Bind("Debug", "LogUntranslated", true,
                "Write Japanese that reaches a text component without a dictionary hit to " +
                "BepInEx/plugins/CoinPussyEnglish/untranslated.txt. Check it after playing.");
            CfgDumpCsv = Config.Bind("Debug", "DumpLoadedCsv", false,
                "Dump every CSV the game parses to BepInEx/plugins/CoinPussyEnglish/dump/. " +
                "Use this to catch a script CSV the extraction pipeline missed.");
            CfgFallbackContains = Config.Bind("Advanced", "FallbackContainsReplace", false,
                "Last-resort substring replace for composed strings. Off by default — it " +
                "can splice a partial match into an otherwise-Japanese line.");

            _harmony = new Harmony(GUID);
            int hooks = 0;

            if (CfgCsvSwap.Value)
            {
                CsvStore.LoadAll();
                hooks += CsvPatches.Apply(_harmony);
            }
            if (CfgTextHook.Value)
            {
                TranslationStore.LoadAll();
                hooks += TextPatches.Apply(_harmony);
            }

            Log.LogInfo($"{NAME} {VERSION}: {hooks} hooks applied, " +
                        $"{CsvStore.Count} translated CSVs, " +
                        $"{TranslationStore.Count} dictionary entries.");
        }

        /// <summary>Applies legacy UI.Text swaps queued during OnEnable — see
        /// TextPatches.DrainPending for why they cannot be applied inline.</summary>
        private void Update()
        {
            if (CfgTextHook?.Value == true) TextPatches.DrainPending();
        }
    }
}
