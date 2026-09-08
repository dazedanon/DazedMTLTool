using BepInEx;
using BepInEx.Logging;
using HarmonyLib;
using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace VBV
{
    [BepInPlugin("com.yourname.vbv", "VBV", "1.0.0")]
    public class Plugin : BaseUnityPlugin
    {
        internal static ManualLogSource Log;
        private Harmony _harmony;

        private void Awake()
        {
            Log = Logger;
            Log.LogInfo("VBV loading");

            DontDestroyOnLoad(gameObject);
            gameObject.hideFlags = HideFlags.HideAndDontSave;

            _harmony = new Harmony("com.yourname.vbv");
            _harmony.PatchAll(typeof(TextPatches));

            Log.LogInfo("VBV ready");
        }

        private void OnDestroy()
        {
            _harmony?.UnpatchSelf();
        }
    }

    [HarmonyPatch]
    internal class TextPatches
    {
        private static readonly HashSet<object> processed = new HashSet<object>();
        private static readonly HashSet<object> currentlyProcessing = new HashSet<object>();

        [HarmonyPostfix]
        [HarmonyPatch(typeof(TextMeshProUGUI), "GenerateTextMesh")]
        private static void TMPUGUI_GenerateTextMesh_Postfix(TextMeshProUGUI __instance)
            => ApplyToTMP(__instance);

        [HarmonyPostfix]
        [HarmonyPatch(typeof(TextMeshPro), "GenerateTextMesh")]
        private static void TMP_GenerateTextMesh_Postfix(TextMeshPro __instance)
            => ApplyToTMP(__instance);

        [HarmonyPostfix]
        [HarmonyPatch(typeof(Text), "OnEnable")]
        private static void Text_OnEnable_Postfix(Text __instance)
            => ApplyToLegacy(__instance);

        private static void ApplyToTMP(TMP_Text t)
        {
            if (t == null) return;
            if (currentlyProcessing.Contains(t)) return;
            if (processed.Contains(t)) return;

            try
            {
                currentlyProcessing.Add(t);

                var originalSize = t.fontSize;
                t.enableAutoSizing = true;
                t.fontSizeMin = 6;
                t.fontSizeMax = originalSize > 0 ? originalSize : 24;
                t.overflowMode = TextOverflowModes.Ellipsis;
                #pragma warning disable CS0618
                t.enableWordWrapping = false;
                #pragma warning restore CS0618

                processed.Add(t);
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"TMP apply failed: {e.Message}");
            }
            finally
            {
                currentlyProcessing.Remove(t);
                try { t.ForceMeshUpdate(false, false); } catch { }
            }
        }

        private static void ApplyToLegacy(Text t)
        {
            if (t == null) return;
            if (currentlyProcessing.Contains(t)) return;
            if (processed.Contains(t)) return;

            try
            {
                currentlyProcessing.Add(t);

                var originalSize = t.fontSize;
                t.resizeTextForBestFit = true;
                t.resizeTextMinSize = 6;
                t.resizeTextMaxSize = originalSize > 0 ? originalSize : 24;
                t.horizontalOverflow = HorizontalWrapMode.Overflow;
                t.verticalOverflow = VerticalWrapMode.Overflow;
                t.SetVerticesDirty();

                processed.Add(t);
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"Legacy apply failed: {e.Message}");
            }
            finally
            {
                currentlyProcessing.Remove(t);
            }
        }
    }
}