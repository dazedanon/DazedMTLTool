using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using HarmonyLib;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace HitonatsuTL
{
    /// <summary>
    /// English translation layer for ひと夏の思い出 (Hachimitsu Sand).
    /// Unity 6000.3.6f1 / IL2CPP, BepInEx 6 + Il2CppInterop.
    ///
    /// Nothing in the game files is modified. Every string is swapped as it
    /// reaches a text component, so the patch is a drop-in folder and reverts
    /// by deleting it.
    /// </summary>
    [BepInPlugin(GUID, NAME, VERSION)]
    public class Plugin : BasePlugin
    {
        public const string GUID = "com.sw.hitonatsu.tl";
        public const string NAME = "HitonatsuTL";
        public const string VERSION = "1.0.0";

        internal static new ManualLogSource Log;
        internal static ConfigEntry<bool> CfgVerbose;
        internal static ConfigEntry<bool> CfgFallbackContains;
        internal static ConfigEntry<bool> CfgHarvest;
        internal static ConfigEntry<bool> CfgAutoSize;
        internal static ConfigEntry<bool> CfgSweep;
        internal static ConfigEntry<float> CfgSweepInterval;

        private Harmony _harmony;

        public override void Load()
        {
            Log = base.Log;

            CfgVerbose = Config.Bind(
                "General", "Verbose", false,
                "Log every translated string. Spammy - debugging only.");
            CfgFallbackContains = Config.Bind(
                "General", "FallbackContains", false,
                "If a string is not an exact match, look for a translated key contained "
                + "within it. Slow, and can produce half-translated output. Off by default.");
            CfgHarvest = Config.Bind(
                "QA", "Harvest", false,
                "Write every Japanese string that reaches a text component with no "
                + "dictionary hit to untranslated.txt next to this dll. Turn this on, play "
                + "through once, and anything listed is text the static extraction missed. "
                + "MUST be off in a release build.");
            CfgAutoSize = Config.Bind(
                "Layout", "AutoSize", true,
                "Let TextMeshPro shrink a label that no longer fits its box. English runs "
                + "about 2.1x the Japanese here, and the settings rows are fixed width.");
            CfgSweep = Config.Bind(
                "Coverage", "Sweep", true,
                "Periodically re-check every live TextMeshPro component. Catches text "
                + "that never passes through the property setter or the Awake/OnEnable "
                + "hooks.");
            CfgSweepInterval = Config.Bind(
                "Coverage", "SweepIntervalSeconds", 5f,
                "Seconds between sweeps. Minimum 2.");

            Log.LogInfo($"{NAME} v{VERSION} loading");

            TranslationStore.LoadAll();
            ImagePatches.LoadAll();

            _harmony = new Harmony(GUID);
            _harmony.PatchAll(typeof(TextPatches));
            GamePatches.Apply(_harmony);
            ImagePatches.Apply(_harmony);

            // The sweeper is a custom MonoBehaviour, so IL2CPP has to be told
            // the type exists before anything can AddComponent it.
            ClassInjector.RegisterTypeInIl2Cpp<TextSweep>();
            var host = new GameObject("HitonatsuTL");
            UnityEngine.Object.DontDestroyOnLoad(host);
            host.hideFlags = HideFlags.HideAndDontSave;
            host.AddComponent<TextSweep>();

            Log.LogInfo($"{NAME} ready: {TranslationStore.Count} translations, "
                        + $"{ImagePatches.Count} image replacements active");
            if (CfgHarvest.Value)
                Log.LogWarning("Harvest is ON - this is a QA build, not a release build.");
        }

        public override bool Unload()
        {
            _harmony?.UnpatchSelf();
            return base.Unload();
        }
    }
}
