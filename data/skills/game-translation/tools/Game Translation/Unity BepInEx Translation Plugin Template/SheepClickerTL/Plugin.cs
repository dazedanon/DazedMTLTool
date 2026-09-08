using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using HarmonyLib;

namespace SheepClickerTL
{
    [BepInPlugin(GUID, NAME, VERSION)]
    public class Plugin : BasePlugin
    {
        public const string GUID = "com.sw.sheepclicker.tl";
        public const string NAME = "SheepClickerTL";
        public const string VERSION = "1.0.0";

        internal static new ManualLogSource Log;
        internal static ConfigEntry<bool> CfgVerbose;
        internal static ConfigEntry<bool> CfgFallbackContains;

        private Harmony _harmony;

        public override void Load()
        {
            Log = base.Log;

            CfgVerbose = Config.Bind(
                "General", "Verbose", false,
                "Log every translated string. Spammy — use only for debugging.");
            CfgFallbackContains = Config.Bind(
                "General", "FallbackContains", false,
                "If a string isn't an exact match, try to find any translated key contained within it (slow, off by default).");

            Log.LogInfo($"{NAME} v{VERSION} loading");

            TranslationStore.LoadAll();

            _harmony = new Harmony(GUID);
            _harmony.PatchAll(typeof(TextPatches));
            _harmony.PatchAll(typeof(BubblePatches));

            Log.LogInfo($"{NAME} ready: {TranslationStore.Count} translations active");
        }

        public override bool Unload()
        {
            _harmony?.UnpatchSelf();
            return base.Unload();
        }
    }
}
