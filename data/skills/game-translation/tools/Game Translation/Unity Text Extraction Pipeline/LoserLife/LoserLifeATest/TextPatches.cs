using HarmonyLib;
using System.Reflection;
using TMPro;
using UnityEngine.UI;

namespace LoserLifeATest;

internal static class TextPatches
{
    public static void Apply(Harmony harmony)
    {
        PatchPrefix(harmony, AccessTools.PropertySetter(typeof(TMP_Text), nameof(TMP_Text.text)), nameof(TMP_SetText_Prefix));
        PatchPrefix(harmony, AccessTools.Method(typeof(TMP_Text), nameof(TMP_Text.SetText), new[] { typeof(string), typeof(bool) }), nameof(TMP_SetText_Method_Prefix));

        PatchPostfix(harmony, AccessTools.DeclaredMethod(typeof(TextMeshProUGUI), "Awake"), nameof(TMP_UGUI_Awake_Postfix), optional: true);
        PatchPostfix(harmony, AccessTools.DeclaredMethod(typeof(TextMeshProUGUI), "OnEnable"), nameof(TMP_UGUI_OnEnable_Postfix), optional: true);
        PatchPostfix(harmony, AccessTools.DeclaredMethod(typeof(TextMeshPro), "Awake"), nameof(TMP_World_Awake_Postfix), optional: true);
        PatchPostfix(harmony, AccessTools.DeclaredMethod(typeof(TextMeshPro), "OnEnable"), nameof(TMP_World_OnEnable_Postfix), optional: true);

        PatchPrefix(harmony, AccessTools.PropertySetter(typeof(Text), nameof(Text.text)), nameof(UIText_SetText_Prefix));
        PatchPostfix(harmony, AccessTools.DeclaredMethod(typeof(Text), "OnEnable"), nameof(UIText_OnEnable_Postfix), optional: true);

        PatchPostfix(harmony, AccessTools.DeclaredMethod(typeof(global::UI_Skill), "UpdateInfo"), nameof(UI_Skill_UpdateInfo_Postfix), optional: true);
        PatchPostfix(harmony, AccessTools.DeclaredMethod(typeof(global::SkillSlotTemplate), "UpdateInfo"), nameof(SkillSlotTemplate_UpdateInfo_Postfix), optional: true);
    }

    private static void TMP_SetText_Prefix(ref string value)
    {
        TextRuntime.Replace(ref value);
    }

    private static void TMP_SetText_Method_Prefix(ref string sourceText)
    {
        TextRuntime.Replace(ref sourceText);
    }

    private static void TMP_UGUI_Awake_Postfix(TextMeshProUGUI __instance)
    {
        TextRuntime.ReplaceTMP(__instance);
    }

    private static void TMP_UGUI_OnEnable_Postfix(TextMeshProUGUI __instance)
    {
        TextRuntime.ReplaceTMP(__instance);
    }

    private static void TMP_World_Awake_Postfix(TextMeshPro __instance)
    {
        TextRuntime.ReplaceTMP(__instance);
    }

    private static void TMP_World_OnEnable_Postfix(TextMeshPro __instance)
    {
        TextRuntime.ReplaceTMP(__instance);
    }

    private static void UIText_SetText_Prefix(ref string value)
    {
        TextRuntime.Replace(ref value);
    }

    private static void UIText_OnEnable_Postfix(Text __instance)
    {
        TextRuntime.ReplaceUIText(__instance);
    }

    private static void UI_Skill_UpdateInfo_Postfix(global::UI_Skill __instance)
    {
        RuntimeTextHarvester.HarvestFromUiSkill(__instance);
    }

    private static void SkillSlotTemplate_UpdateInfo_Postfix(global::SkillSlotTemplate __instance)
    {
        RuntimeTextHarvester.HarvestFromSkillSlot(__instance);
    }

    private static void PatchPrefix(Harmony harmony, MethodBase original, string patchMethodName, bool optional = false)
    {
        Patch(harmony, original, patchMethodName, prefix: true, optional);
    }

    private static void PatchPostfix(Harmony harmony, MethodBase original, string patchMethodName, bool optional = false)
    {
        Patch(harmony, original, patchMethodName, prefix: false, optional);
    }

    private static void Patch(Harmony harmony, MethodBase original, string patchMethodName, bool prefix, bool optional)
    {
        if (original == null)
        {
            var message = $"Skipping {(optional ? "optional " : "")}patch {patchMethodName}: target method not found";
            if (optional)
            {
                Plugin.Log.LogDebug(message);
                return;
            }

            Plugin.Log.LogWarning(message);
            return;
        }

        var patch = typeof(TextPatches).GetMethod(patchMethodName, BindingFlags.Static | BindingFlags.NonPublic);
        if (patch == null)
        {
            Plugin.Log.LogWarning($"Skipping patch {patchMethodName}: patch method not found");
            return;
        }

        var harmonyMethod = new HarmonyMethod(patch);
        if (prefix)
        {
            harmony.Patch(original, prefix: harmonyMethod);
        }
        else
        {
            harmony.Patch(original, postfix: harmonyMethod);
        }
    }
}
