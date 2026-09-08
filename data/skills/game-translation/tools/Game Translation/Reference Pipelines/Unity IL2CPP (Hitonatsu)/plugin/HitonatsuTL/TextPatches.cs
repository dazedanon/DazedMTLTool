using System.Collections.Generic;
using HarmonyLib;
using TMPro;
using UnityEngine.UI;

namespace HitonatsuTL
{
    /// <summary>
    /// Two coverage layers:
    ///
    ///   1) Setter prefixes — catch every runtime `tmp.text = "..."` from
    ///      game code (this is how CSV dialogue strings flow). We mutate
    ///      `value` in-place so the rest of the engine only ever sees the
    ///      translated string.
    ///
    ///   2) Awake / OnEnable postfixes — catch text that Unity wrote
    ///      *directly into the m_text backing field* during scene/prefab
    ///      deserialization. Those writes never go through the setter, so
    ///      static UI labels (Recollection, Bedroom, ~Faith Bonus~, etc.)
    ///      need a one-shot pass after the component comes alive.
    ///
    ///   Re-assigning `t.text` here goes through the setter prefix; if the
    ///   string is already English the lookup misses and the setter just
    ///   passes through.
    /// </summary>
    [HarmonyPatch]
    internal static class TextPatches
    {
        // -------- TMP_Text: setters (runtime writes) --------

        [HarmonyPrefix]
        [HarmonyPatch(typeof(TMP_Text), nameof(TMP_Text.text), MethodType.Setter)]
        private static void TMP_SetText_Prefix(ref string value) => TryTranslate(ref value);

        [HarmonyPrefix]
        [HarmonyPatch(typeof(TMP_Text), nameof(TMP_Text.SetText),
            new[] { typeof(string), typeof(bool) })]
        private static void TMP_SetText_Method_Prefix(ref string sourceText)
            => TryTranslate(ref sourceText);

        // -------- TMP_Text: lifecycle (deserialized writes) --------

        [HarmonyPostfix]
        [HarmonyPatch(typeof(TextMeshProUGUI), "Awake")]
        private static void TMP_UGUI_Awake_Postfix(TextMeshProUGUI __instance)
            => RefreshTMP(__instance);

        [HarmonyPostfix]
        [HarmonyPatch(typeof(TextMeshProUGUI), "OnEnable")]
        private static void TMP_UGUI_OnEnable_Postfix(TextMeshProUGUI __instance)
            => RefreshTMP(__instance);

        [HarmonyPostfix]
        [HarmonyPatch(typeof(TextMeshPro), "Awake")]
        private static void TMP_World_Awake_Postfix(TextMeshPro __instance)
            => RefreshTMP(__instance);

        [HarmonyPostfix]
        [HarmonyPatch(typeof(TextMeshPro), "OnEnable")]
        private static void TMP_World_OnEnable_Postfix(TextMeshPro __instance)
            => RefreshTMP(__instance);

        // -------- legacy UnityEngine.UI.Text --------

        [HarmonyPrefix]
        [HarmonyPatch(typeof(Text), nameof(Text.text), MethodType.Setter)]
        private static void UIText_SetText_Prefix(ref string value) => TryTranslate(ref value);

        [HarmonyPostfix]
        [HarmonyPatch(typeof(Text), "OnEnable")]
        private static void UIText_OnEnable_Postfix(Text __instance) => RefreshUIText(__instance);

        // -------- helpers --------

        // tracks which components we've already configured for auto-sizing.
        // Unity instance IDs are stable per-component within a run.
        private static readonly HashSet<int> _autoSizedTMP = new HashSet<int>();
        private static readonly HashSet<int> _autoSizedUI = new HashSet<int>();

        /// <summary>
        /// Make a TMP component shrink-to-fit so EN translations don't blow
        /// out of buttons sized for ~5 JP chars. Called once per component;
        /// subsequent calls are no-ops.
        ///
        /// Strategy: keep the component's authored font size as the upper
        /// bound (so JP text that already fit doesn't grow), let it shrink
        /// to a small min, and prefer wrapping over ellipsis so multi-word
        /// EN strings ("Missionary Upgrade") can break onto two lines if
        /// the box has any vertical room.
        /// </summary>
        private static void EnableAutoSizeTMP(TMP_Text t)
        {
            if (t == null) return;
            int id;
            try { id = t.GetInstanceID(); } catch { return; }
            if (!_autoSizedTMP.Add(id)) return;
            if (Plugin.CfgAutoSize?.Value != true) return;
            try
            {
                float originalSize = t.fontSize;
                if (originalSize <= 0) originalSize = 24f;
                t.enableAutoSizing = true;
                t.fontSizeMin = 6f;
                t.fontSizeMax = originalSize;
                // Deliberately NOT setting overflowMode to Ellipsis. The
                // template does, which is right for a button and wrong for a
                // subtitle - a clipped dialogue line loses words silently,
                // and shrinking already buys back the width English needs.
            }
            catch (System.Exception e)
            {
                Plugin.Log.LogWarning($"EnableAutoSizeTMP failed: {e.Message}");
            }
        }

        private static void EnableAutoSizeUI(Text t)
        {
            if (t == null) return;
            int id;
            try { id = t.GetInstanceID(); } catch { return; }
            if (!_autoSizedUI.Add(id)) return;
            if (Plugin.CfgAutoSize?.Value != true) return;
            try
            {
                int originalSize = t.fontSize;
                if (originalSize <= 0) originalSize = 24;
                t.resizeTextForBestFit = true;
                t.resizeTextMinSize = 6;
                t.resizeTextMaxSize = originalSize;
                t.SetVerticesDirty();
            }
            catch (System.Exception e)
            {
                Plugin.Log.LogWarning($"EnableAutoSizeUI failed: {e.Message}");
            }
        }

        private static void RefreshTMP(TMP_Text t)
        {
            if (t == null) return;
            try
            {
                EnableAutoSizeTMP(t);

                var current = t.text;
                if (string.IsNullOrEmpty(current)) return;
                if (TranslationStore.TryGet(current, out var translated) && translated != current)
                {
                    if (Plugin.CfgVerbose?.Value == true)
                        Plugin.Log.LogInfo($"TL[init]: {Truncate(current)} -> {Truncate(translated)}");
                    t.text = translated;        // setter prefix sees English, no-op match -> pass through
                }
                else
                {
                    TranslationStore.ReportIfUntranslated(current, "tmp-init");
                }
            }
            catch (System.Exception e)
            {
                Plugin.Log.LogWarning($"RefreshTMP failed: {e.Message}");
            }
        }

        private static void RefreshUIText(Text t)
        {
            if (t == null) return;
            try
            {
                EnableAutoSizeUI(t);

                var current = t.text;
                if (string.IsNullOrEmpty(current)) return;
                if (TranslationStore.TryGet(current, out var translated) && translated != current)
                {
                    if (Plugin.CfgVerbose?.Value == true)
                        Plugin.Log.LogInfo($"TL[init]: {Truncate(current)} -> {Truncate(translated)}");
                    t.text = translated;
                }
            }
            catch (System.Exception e)
            {
                Plugin.Log.LogWarning($"RefreshUIText failed: {e.Message}");
            }
        }

        private static void TryTranslate(ref string value)
        {
            if (string.IsNullOrEmpty(value)) return;
            if (TranslationStore.TryGet(value, out var translated))
            {
                if (Plugin.CfgVerbose?.Value == true)
                    Plugin.Log.LogInfo($"TL: {Truncate(value)} -> {Truncate(translated)}");
                value = translated;
            }
            else
            {
                TranslationStore.ReportIfUntranslated(value, "setter");
            }
        }

        private static string Truncate(string s)
        {
            if (s == null) return "<null>";
            return s.Length <= 60 ? s : s.Substring(0, 57) + "...";
        }
    }
}

