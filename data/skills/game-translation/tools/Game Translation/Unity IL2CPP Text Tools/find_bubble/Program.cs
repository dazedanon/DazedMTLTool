// Reflect Assembly-CSharp.dll for any type with "Bubble" / "Message" /
// "Talk" / "Dialog" / "Typewriter" in its name and dump its method/field
// signatures so we can pick a hook target.
using System;
using System.IO;
using System.Linq;
using Mono.Cecil;

class FindBubble
{
    static void Main(string[] args)
    {
        var path = args.Length > 0 ? args[0]
            : @"C:\Users\sw\Desktop\SheepClicker\BepInEx\interop\Assembly-CSharp.dll";
        var resolver = new DefaultAssemblyResolver();
        resolver.AddSearchDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        var rp = new ReaderParameters { ReadSymbols = false, AssemblyResolver = resolver };
        using var asm = AssemblyDefinition.ReadAssembly(path, rp);

        var keywords = new[] {
            "Bubble", "Message", "Talk", "Dialog", "Typewriter", "Story", "Speech",
            "Floating", "Follower", "Sheep", "Npc", "Mob", "Reaction", "Popup", "Tip"
        };
        foreach (var t in asm.MainModule.GetTypes()
                     .Where(x => keywords.Any(k => x.Name.IndexOf(k, StringComparison.OrdinalIgnoreCase) >= 0))
                     .OrderBy(x => x.FullName))
        {
            Console.WriteLine($"\n== {t.FullName} ==");
            foreach (var f in t.Fields.Take(40))
                Console.WriteLine($"  field: {f.FieldType.Name} {f.Name}");
            foreach (var m in t.Methods.Where(m => !m.IsConstructor && !m.IsSpecialName).Take(40))
            {
                var ps = string.Join(", ",
                    m.Parameters.Select(p => $"{p.ParameterType.Name} {p.Name}"));
                Console.WriteLine($"  method: {m.ReturnType.Name} {m.Name}({ps})");
            }
        }
    }
}
