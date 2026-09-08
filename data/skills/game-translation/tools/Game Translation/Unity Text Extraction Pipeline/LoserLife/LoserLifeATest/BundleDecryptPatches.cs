using HarmonyLib;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using System;
using System.Linq;
using System.Reflection;
using UnityEngine;

namespace LoserLifeATest;

internal static class BundleDecryptPatches
{
    public static void Apply(Harmony harmony)
    {
        var constructor = FindSeekableAesStreamConstructor();
        if (constructor == null)
        {
            Plugin.Log.LogWarning("Skipping bundle decrypt hook: SeekableAesStream constructor not found");
            return;
        }

        var postfix = typeof(BundleDecryptPatches).GetMethod(
            nameof(SeekableAesStream_Ctor_Postfix),
            BindingFlags.Static | BindingFlags.NonPublic);
        harmony.Patch(constructor, postfix: new HarmonyMethod(postfix));
        Plugin.Log.LogInfo("Bundle decrypt hook installed on SeekableAesStream constructor");

        PatchSeekableAesRead(harmony);
        PatchAssetBundleMemoryLoads(harmony);
    }

    private static ConstructorInfo FindSeekableAesStreamConstructor()
    {
        foreach (var constructor in typeof(global::SeekableAesStream).GetConstructors(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic))
        {
            if (constructor.GetParameters().Length == 3)
            {
                return constructor;
            }
        }

        return null;
    }

    private static void SeekableAesStream_Ctor_Postfix(object[] __args)
    {
        try
        {
            BundleDecryptDumper.OnSeekableAesStreamConstructed(__args);
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"Bundle decrypt hook failed: {ex.Message}");
        }
    }

    private static void PatchSeekableAesRead(Harmony harmony)
    {
        var read = AccessTools.Method(
            typeof(global::SeekableAesStream),
            nameof(global::SeekableAesStream.Read),
            new[] { typeof(Il2CppStructArray<byte>), typeof(int), typeof(int) });

        if (read == null)
        {
            Plugin.Log.LogWarning("Skipping bundle read dump hook: SeekableAesStream.Read not found");
            return;
        }

        var prefix = typeof(BundleDecryptPatches).GetMethod(
            nameof(SeekableAesStream_Read_Prefix),
            BindingFlags.Static | BindingFlags.NonPublic);
        var postfix = typeof(BundleDecryptPatches).GetMethod(
            nameof(SeekableAesStream_Read_Postfix),
            BindingFlags.Static | BindingFlags.NonPublic);
        harmony.Patch(read, prefix: new HarmonyMethod(prefix), postfix: new HarmonyMethod(postfix));
        Plugin.Log.LogInfo("Bundle read dump hook installed on SeekableAesStream.Read");
    }

    private static void PatchAssetBundleMemoryLoads(Harmony harmony)
    {
        var prefix = typeof(BundleDecryptPatches).GetMethod(
            nameof(AssetBundleLoad_Prefix),
            BindingFlags.Static | BindingFlags.NonPublic);
        var harmonyPrefix = new HarmonyMethod(prefix);
        var patched = 0;

        foreach (var method in typeof(AssetBundle).GetMethods(BindingFlags.Static | BindingFlags.Public)
                     .Where(method => method.Name.StartsWith("LoadFromMemory", StringComparison.Ordinal) ||
                                      method.Name.StartsWith("LoadFromFile", StringComparison.Ordinal) ||
                                      method.Name.StartsWith("LoadFromStream", StringComparison.Ordinal)))
        {
            try
            {
                harmony.Patch(method, prefix: harmonyPrefix);
                patched++;
            }
            catch (Exception ex)
            {
                Plugin.Log.LogDebug($"Skipping AssetBundle load hook {method.Name}: {ex.Message}");
            }
        }

        Plugin.Log.LogInfo($"AssetBundle load probe hooks installed: {patched}");
    }

    private static void SeekableAesStream_Read_Prefix(global::SeekableAesStream __instance, out long __state)
    {
        __state = BundleDecryptDumper.GetStreamPosition(__instance);
    }

    private static void SeekableAesStream_Read_Postfix(global::SeekableAesStream __instance, object[] __args, int __result, long __state)
    {
        try
        {
            BundleDecryptDumper.OnSeekableAesStreamRead(__instance, __args, __result, __state);
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"Bundle read dump hook failed: {ex.Message}");
        }
    }

    private static void AssetBundleLoad_Prefix(MethodBase __originalMethod, object[] __args)
    {
        try
        {
            BundleDecryptDumper.OnAssetBundleLoadCalled(__originalMethod, __args);
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"AssetBundle load probe failed: {ex.Message}");
        }
    }
}
