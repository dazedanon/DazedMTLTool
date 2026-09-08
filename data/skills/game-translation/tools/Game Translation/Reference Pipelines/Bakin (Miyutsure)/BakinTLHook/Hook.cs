using System;
using System.IO;

// Bakin extracts the whole project into a fresh temp folder on every launch and
// only then starts bakinplayer.exe, so by the time this runs the folder the
// engine will read is already complete and can simply be overlaid.
//
// Hooked through <appDomainManagerAssembly> in bakinplayer.exe.config, which
// runs before Main without modifying any of the game's own binaries. Reverting
// the patch is deleting three lines from that config.
public sealed class BakinTranslationHook : AppDomainManager
{
    public override void InitializeNewDomain(AppDomainSetup info)
    {
        base.InitializeNewDomain(info);
        try { Overlay(); }
        catch (Exception e) { Fail(e.ToString()); }
    }

    static void Overlay()
    {
        string launchDir = null, tempDir = null;
        foreach (string a in Environment.GetCommandLineArgs())
        {
            if (!a.StartsWith("/TMP=")) continue;
            string[] p = a.Substring(5).Split('|');
            if (p.Length < 3) return;
            launchDir = p[0].Trim('"');
            tempDir = p[2].Trim('"');
        }
        if (launchDir == null || tempDir == null || !Directory.Exists(tempDir)) return;

        string src = Path.Combine(launchDir, "translation");
        if (!Directory.Exists(src)) return;

        // Translated map names change the map file names, so the shipped map set
        // replaces the extracted one wholesale rather than merging into it.
        string srcMaps = Path.Combine(src, "map"), dstMaps = Path.Combine(tempDir, "map");
        if (Directory.Exists(srcMaps) && Directory.Exists(dstMaps))
            foreach (string f in Directory.GetFiles(dstMaps, "*.rbr", SearchOption.TopDirectoryOnly))
                File.Delete(f);

        foreach (string f in Directory.GetFiles(src, "*", SearchOption.AllDirectories))
        {
            string rel = f.Substring(src.Length).TrimStart(Path.DirectorySeparatorChar);
            string dst = Path.Combine(tempDir, rel);
            Directory.CreateDirectory(Path.GetDirectoryName(dst));
            File.Copy(f, dst, true);
        }
    }

    // The CLR swallows anything thrown from here and the game would start in
    // Japanese with no clue why, so leave a breadcrumb next to the game.
    static void Fail(string message)
    {
        try
        {
            File.WriteAllText(Path.Combine(Path.GetTempPath(), "bakin_translation_hook_error.txt"), message);
        }
        catch { }
    }
}
