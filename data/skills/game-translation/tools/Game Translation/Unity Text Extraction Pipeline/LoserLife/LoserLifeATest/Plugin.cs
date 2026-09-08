using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using HarmonyLib;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace LoserLifeATest;

[BepInPlugin(Guid, Name, Version)]
public sealed class Plugin : BasePlugin
{
    public const string Guid = "com.sw.loserlife.atest";
    public const string Name = "LoserLifeATest";
    public const string Version = "1.0.0";

    internal static new ManualLogSource Log;
    internal static ConfigEntry<string> Replacement;
    internal static ConfigEntry<bool> ReplaceEmptyText;
    internal static ConfigEntry<bool> RequireExtractedMatch;
    internal static ConfigEntry<bool> AllowCompositeExtractedMatch;
    internal static ConfigEntry<bool> PreserveDynamicValues;
    internal static ConfigEntry<bool> LogUnmatchedJapanese;
    internal static ConfigEntry<bool> HarvestRuntimeTexts;
    internal static ConfigEntry<bool> WriteRuntimeHarvestLog;
    internal static ConfigEntry<float> RuntimeHarvestIntervalSeconds;
    internal static ConfigEntry<bool> CaptureBundleKeys;
    internal static ConfigEntry<bool> DumpDecryptedBundles;
    internal static ConfigEntry<bool> DumpSeekableAesReads;
    internal static ConfigEntry<bool> DumpFullSeekableAesStreams;
    internal static ConfigEntry<bool> DumpAssetBundleMemoryLoads;
    internal static ConfigEntry<bool> OverwriteBundleDumps;
    internal static ConfigEntry<string> BundleDumpDirectory;
    internal static ConfigEntry<bool> EnableSweeper;
    internal static ConfigEntry<bool> ContinuousSweeper;
    internal static ConfigEntry<bool> SweepOnSceneChange;
    internal static ConfigEntry<float> SweepIntervalSeconds;
    internal static ConfigEntry<bool> Verbose;

    private Harmony _harmony;

    public override void Load()
    {
        Log = base.Log;
        Replacement = Config.Bind("General", "Replacement", "A", "Text assigned to every visible UI/text component.");
        ReplaceEmptyText = Config.Bind("General", "ReplaceEmptyText", false, "Also replace empty strings. Usually too noisy.");
        EnableSweeper = Config.Bind("Performance", "EnableSweeper", true, "Run occasional safety-net sweeps for text that bypasses setters.");
        ContinuousSweeper = Config.Bind("Performance", "ContinuousSweeper", false, "Sweep on a timer forever. More complete but can cause hitches if the interval is too low.");
        SweepOnSceneChange = Config.Bind("Performance", "SweepOnSceneChange", true, "Run one sweep when the active Unity scene changes.");
        SweepIntervalSeconds = Config.Bind("Performance", "SweepIntervalSeconds", 15.0f, "How often occasional sweeps run when ContinuousSweeper is true.");
        RequireExtractedMatch = Config.Bind("Coverage", "RequireExtractedMatch", true, "Only replace strings that are present in the extracted text list.");
        AllowCompositeExtractedMatch = Config.Bind("Coverage", "AllowCompositeExtractedMatch", true, "Treat runtime strings as covered if all Japanese fragments are in the extracted text list.");
        PreserveDynamicValues = Config.Bind("Coverage", "PreserveDynamicValues", true, "For non-exact composed runtime strings, replace known extracted fragments with the marker while keeping inserted values like amounts/counts visible.");
        LogUnmatchedJapanese = Config.Bind("Coverage", "LogUnmatchedJapanese", true, "Log visible Japanese strings that are not in the extracted text list.");
        HarvestRuntimeTexts = Config.Bind("Coverage", "HarvestRuntimeTexts", true, "Learn Japanese strings from live game objects, such as encrypted skill data that is not present in the static dump.");
        WriteRuntimeHarvestLog = Config.Bind("Coverage", "WriteRuntimeHarvestLog", true, "Write newly learned runtime strings to runtime_harvested_texts.tsv beside the plugin.");
        RuntimeHarvestIntervalSeconds = Config.Bind("Coverage", "RuntimeHarvestIntervalSeconds", 5.0f, "How often to scan targeted runtime objects for missing strings.");
        CaptureBundleKeys = Config.Bind("BundleDump", "CaptureBundleKeys", true, "Hook SeekableAesStream and log bundle password/salt values.");
        DumpDecryptedBundles = Config.Bind("BundleDump", "DumpDecryptedBundles", true, "Use captured password/salt to dump decrypted copies of encrypted StreamingAssets bundles.");
        DumpSeekableAesReads = Config.Bind("BundleDump", "DumpSeekableAesReads", true, "Fallback: append decrypted bytes returned by SeekableAesStream.Read when constructor key capture misses.");
        DumpFullSeekableAesStreams = Config.Bind("BundleDump", "DumpFullSeekableAesStreams", true, "Fallback: on first read, seek and copy the entire decrypted SeekableAesStream to a complete bundle file.");
        DumpAssetBundleMemoryLoads = Config.Bind("BundleDump", "DumpAssetBundleMemoryLoads", true, "Fallback: dump byte arrays passed to AssetBundle.LoadFromMemory/LoadFromMemoryAsync.");
        OverwriteBundleDumps = Config.Bind("BundleDump", "OverwriteBundleDumps", false, "Overwrite existing decrypted bundle dumps.");
        BundleDumpDirectory = Config.Bind("BundleDump", "BundleDumpDirectory", "decrypted_bundles", "Directory beside the plugin where decrypted bundle dumps are written.");
        Verbose = Config.Bind("Debug", "Verbose", false, "Log replacement counts during sweeps.");

        Log.LogInfo($"{Name} v{Version} loading");
        ExtractedTextStore.Load();
        RuntimeTextHarvester.Initialize();
        Log.LogInfo($"{ExtractedTextStore.Count} extracted strings loaded for coverage test");

        _harmony = new Harmony(Guid);
        TextPatches.Apply(_harmony);
        BundleDecryptPatches.Apply(_harmony);

        ClassInjector.RegisterTypeInIl2Cpp<TextSweepBehaviour>();
        var sweeper = new GameObject("LoserLifeATest_TextSweep");
        Object.DontDestroyOnLoad(sweeper);
        sweeper.hideFlags = HideFlags.HideAndDontSave;
        sweeper.AddComponent<TextSweepBehaviour>();

        Log.LogInfo($"{Name} ready; replacing text with '{TextRuntime.CurrentReplacement}'");
    }

    public override bool Unload()
    {
        _harmony?.UnpatchSelf();
        return base.Unload();
    }
}
