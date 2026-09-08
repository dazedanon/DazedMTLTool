using HarmonyLib;

namespace SheepClickerTL
{
    /// <summary>
    /// Hook the entry points that drive typing-style text reveal so the EN
    /// translation is in place BEFORE the coroutine starts emitting partial
    /// substrings. Without these, the TMP setter only sees Substring(0, n)
    /// frames that don't match any dictionary key, and translation only
    /// kicks in once typing finishes.
    ///
    /// Targets:
    ///   BubbleMessage.ShowMessage  — bubble UI, used for skill-charge,
    ///                                skill-action, idle banter, event bubbles
    ///   BubbleMessage.ShowInstant  — same UI, no-typing variant
    ///   StoryManager.TypeText      — story dialogue typewriter coroutine
    /// </summary>
    [HarmonyPatch]
    internal static class BubblePatches
    {
        [HarmonyPrefix]
        [HarmonyPatch(typeof(BubbleMessage), nameof(BubbleMessage.ShowMessage))]
        private static void BubbleMessage_ShowMessage_Prefix(ref string message)
            => Translate(ref message);

        [HarmonyPrefix]
        [HarmonyPatch(typeof(BubbleMessage), nameof(BubbleMessage.ShowInstant))]
        private static void BubbleMessage_ShowInstant_Prefix(ref string message)
            => Translate(ref message);

        // backup: catch direct coroutine construction that bypasses ShowMessage
        [HarmonyPrefix]
        [HarmonyPatch(typeof(BubbleMessage), "DisplayRoutine")]
        private static void BubbleMessage_DisplayRoutine_Prefix(ref string message)
            => Translate(ref message);

        [HarmonyPrefix]
        [HarmonyPatch(typeof(StoryManager), "TypeText")]
        private static void StoryManager_TypeText_Prefix(ref string fullText)
            => Translate(ref fullText);

        // in-game follower / NPC typing animation (click-to-interact)
        [HarmonyPrefix]
        [HarmonyPatch(typeof(Follower), "TypeTextWithSE")]
        private static void Follower_TypeTextWithSE_Prefix(ref string text)
            => Translate(ref text);

        // floating "+N yen" / "+N follower" popups above the click target
        [HarmonyPrefix]
        [HarmonyPatch(typeof(FloatingText), nameof(FloatingText.Show))]
        private static void FloatingText_Show_Prefix(ref string message)
            => Translate(ref message);

        private static void Translate(ref string s)
        {
            if (string.IsNullOrEmpty(s)) return;
            if (TranslationStore.TryGet(s, out var translated))
                s = translated;
        }
    }
}
