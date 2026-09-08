using System;
using System.IO;
using System.Reflection;
using System.Text;
using SharpKmyIO;

// Read assets out of a Bakin data.rbpack through the engine's own resource
// layer, so the native index format never has to be reversed.
//
//   BakinRes probe   <data.rbpack> <relPath> [diskFile]
//   BakinRes extract <data.rbpack> <paths.txt> <outDir>
static class Program
{
    [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
    static extern bool SetDllDirectory(string path);

    static int Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        string data = Environment.GetEnvironmentVariable("BAKIN_DATA");
        if (string.IsNullOrEmpty(data) || !Directory.Exists(data))
        {
            Console.Error.WriteLine("set BAKIN_DATA to the game's data folder");
            return 2;
        }
        data = Path.GetFullPath(data);
        SetDllDirectory(data);
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) =>
        {
            string f = Path.Combine(data, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(f) ? Assembly.LoadFrom(f) : null;
        };
        if (args.Length < 2) { Console.Error.WriteLine("probe|extract ..."); return 2; }
        switch (args[0])
        {
            case "probe": return Probe(args[1], args[2], args.Length > 3 ? args[3] : null);
            case "extract": return Extract(args[1], args[2], args[3]);
            case "sizes": return Sizes(args[1], args[2], args[3]);
            default: return 2;
        }
    }

    static bool Init(string pack)
    {
        // The player sets this from the rbpack header before initialising the
        // resource layer; the native descramble is keyed on it, so without it
        // every lookup misses. Header layout: "BKNPAK" then a big-endian uint16.
        byte[] head = new byte[8];
        using (var fs = File.OpenRead(pack)) fs.Read(head, 0, 8);
        int version = (head[6] << 8) | head[7];
        SharpKmyBase.StdResourceServer.SetDataVersion(version);
        Console.WriteLine("data version: " + version);
        bool ok = FSEx.initializeResourceFileInfo(Path.GetFullPath(pack));
        Console.WriteLine("initializeResourceFileInfo: " + ok);
        return ok;
    }

    // Does a file on disk at the same relative path beat the packed copy?
    // That is the whole question for injecting translated art.
    static int Probe(string pack, string rel, string diskFile)
    {
        if (!Init(pack)) return 1;
        Console.WriteLine("exists(" + rel + "): " + FSEx.existsResourceFile(rel));
        byte[] before = FSEx.readResourceFileAllBytes(rel);
        Console.WriteLine("packed bytes: " + (before == null ? -1 : before.Length));
        if (diskFile == null) return 0;

        string cwd = Directory.GetCurrentDirectory();
        string dst = Path.Combine(cwd, rel);
        Directory.CreateDirectory(Path.GetDirectoryName(dst));
        File.Copy(diskFile, dst, true);
        Console.WriteLine("placed " + new FileInfo(dst).Length + " bytes at " + dst);
        byte[] after = FSEx.readResourceFileAllBytes(rel);
        Console.WriteLine("after placing a loose copy: " + (after == null ? -1 : after.Length));
        Console.WriteLine(before != null && after != null && before.Length == after.Length
            ? "PACK WINS - a loose file is ignored"
            : "DISK WINS - a loose file overrides the pack");
        return 0;
    }

    // path<TAB>size for every harvested path the pack actually serves. The true
    // sizes are the lever for decoding the index records without reversing the
    // native reader.
    static int Sizes(string pack, string listPath, string outPath)
    {
        if (!Init(pack)) return 1;
        int ok = 0, miss = 0;
        using (var w = new StreamWriter(outPath, false, new UTF8Encoding(false)))
        {
            foreach (string raw in File.ReadAllLines(listPath, Encoding.UTF8))
            {
                string rel = raw.Trim();
                if (rel.Length == 0) continue;
                if (!FSEx.existsResourceFile(rel)) { miss++; continue; }
                byte[] b = FSEx.readResourceFileAllBytes(rel);
                w.WriteLine(rel + "\t" + (b == null ? 0 : b.Length));
                ok++;
            }
        }
        Console.WriteLine("sized " + ok + ", missing " + miss);
        return 0;
    }

    static int Extract(string pack, string listPath, string outDir)
    {
        if (!Init(pack)) return 1;
        int ok = 0, miss = 0;
        long bytes = 0;
        foreach (string raw in File.ReadAllLines(listPath, Encoding.UTF8))
        {
            string rel = raw.Trim();
            if (rel.Length == 0) continue;
            if (!FSEx.existsResourceFile(rel)) { miss++; continue; }
            byte[] b = FSEx.readResourceFileAllBytes(rel);
            if (b == null || b.Length == 0) { miss++; continue; }
            string dst = Path.Combine(outDir, rel.Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(dst));
            File.WriteAllBytes(dst, b);
            ok++;
            bytes += b.Length;
            if (ok % 500 == 0) Console.WriteLine("  " + ok + " files, " + (bytes >> 20) + " MB");
        }
        Console.WriteLine("extracted " + ok + " (" + (bytes >> 20) + " MB), missing " + miss);
        return 0;
    }
}
