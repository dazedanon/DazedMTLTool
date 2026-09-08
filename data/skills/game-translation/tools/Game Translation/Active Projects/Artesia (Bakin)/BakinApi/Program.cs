using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;

// Reflect over a Bakin common.dll and print the surface a translation tool needs.
// The API moves between engine builds - r64268 has no localization feature at all -
// so every field name BakinTL touches is verified here before it is compiled against.
static class Program
{
    [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
    static extern bool SetDllDirectory(string path);

    static int Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        string data = Path.GetFullPath(Environment.GetEnvironmentVariable("BAKIN_DATA"));
        SetDllDirectory(data);
        AppDomain.CurrentDomain.AssemblyResolve += (s, e) =>
        {
            string f = Path.Combine(data, new AssemblyName(e.Name).Name + ".dll");
            return File.Exists(f) ? Assembly.LoadFrom(f) : null;
        };
        var asm = Assembly.LoadFrom(Path.Combine(data, "common.dll"));
        Func<Type[]> allTypes = () => {
            // Some types reference assemblies that only exist under the player's
            // own probing path; a partial list is still a complete answer here.
            try { return asm.GetTypes(); }
            catch (ReflectionTypeLoadException ex) { return ex.Types.Where(x => x != null).ToArray(); }
        };

        if (args.Length > 0 && args[0] == "types")
        {
            string filter = args.Length > 1 ? args[1] : "";
            foreach (var t in allTypes().Where(t => t.FullName.IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0)
                                            .OrderBy(t => t.FullName))
                Console.WriteLine(t.FullName);
            return 0;
        }
        if (args.Length > 0 && args[0] == "static")
        {
            // Print the value of a static field, for the engine's own tables
            // (the control-code keyword list above all).
            var t2 = allTypes().FirstOrDefault(x => x.FullName == args[1] || x.Name == args[1]);
            var f2 = t2.GetField(args[2], BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
            System.Runtime.CompilerServices.RuntimeHelpers.RunClassConstructor(t2.TypeHandle);
            object v2 = f2.GetValue(null);
            var seq2 = v2 as System.Collections.IEnumerable;
            if (seq2 != null && !(v2 is string)) { int i = 0; foreach (var e in seq2) Console.WriteLine((i++) + "	" + e); }
            else Console.WriteLine(v2);
            return 0;
        }
        if (args.Length > 0 && args[0] == "engine")
        {
            // Same reflection, over bakinengine.dll rather than common.dll.
            var eng = Assembly.LoadFrom(Path.Combine(data, "bakinengine.dll"));
            Type[] et;
            try { et = eng.GetTypes(); }
            catch (ReflectionTypeLoadException ex) { et = ex.Types.Where(x => x != null).ToArray(); }
            string filt = args.Length > 1 ? args[1] : "";
            foreach (var t3 in et.Where(x => x.FullName.IndexOf(filt, StringComparison.OrdinalIgnoreCase) >= 0).OrderBy(x => x.FullName))
                Console.WriteLine(t3.FullName);
            return 0;
        }
        if (args.Length > 0 && args[0] == "sigs")
        {
            var cat = asm.GetType("Yukar.Common.Catalog");
            var fi = cat.GetField("romSignatureToTypeDic", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Static);
            if (fi == null) { Console.WriteLine("romSignatureToTypeDic not found"); 
                foreach (var f in cat.GetFields(BindingFlags.Public|BindingFlags.NonPublic|BindingFlags.Static))
                    Console.WriteLine("  static " + f.FieldType.Name + " " + f.Name);
                return 0; }
            System.Runtime.CompilerServices.RuntimeHelpers.RunClassConstructor(cat.TypeHandle);
            var dic = fi.GetValue(null) as System.Collections.IDictionary;
            if (dic == null)
            {
                // Lazily built: constructing a Catalog is what fills it.
                Activator.CreateInstance(cat, new object[] { false });
                dic = fi.GetValue(null) as System.Collections.IDictionary;
            }
            if (dic == null) { Console.WriteLine("still null"); return 1; }
            foreach (System.Collections.DictionaryEntry e in dic)
                Console.WriteLine(Convert.ToInt64(e.Key) + "	0x" + Convert.ToInt64(e.Key).ToString("x") + "	" + ((Type)e.Value).FullName);
            return 0;
        }
        if (args.Length > 0 && args[0] == "attrs")
        {
            foreach (var t in allTypes().Where(t => typeof(Attribute).IsAssignableFrom(t)).OrderBy(t => t.FullName))
                Console.WriteLine(t.FullName);
            return 0;
        }
        foreach (string name in args)
        {
            var t = asm.GetType(name) ?? allTypes().FirstOrDefault(x => x.Name == name);
            if (t == null) { Console.WriteLine("== " + name + ": NOT FOUND"); continue; }
            Console.WriteLine("== " + t.FullName + "  : " + (t.BaseType == null ? "-" : t.BaseType.FullName));
            foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static)
                               .OrderBy(f => f.Name))
                Console.WriteLine(string.Format("   {0,-8} {1,-46} {2} {3}",
                    f.IsStatic ? "static" : (f.IsPublic ? "field" : "priv"),
                    Short(f.FieldType), f.Name, Attrs(f)));
            foreach (var p in t.GetProperties(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static).OrderBy(p => p.Name))
                Console.WriteLine(string.Format("   {0,-8} {1,-46} {2} {3}", "prop", Short(p.PropertyType), p.Name, Attrs(p)));
            foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)
                               .Where(m => !m.IsSpecialName).OrderBy(m => m.Name))
                Console.WriteLine(string.Format("   {0,-8} {1,-46} {2}({3})", "method", Short(m.ReturnType), m.Name,
                    string.Join(", ", m.GetParameters().Select(x => Short(x.ParameterType) + " " + x.Name))));
            foreach (var n in t.GetNestedTypes(BindingFlags.Public | BindingFlags.NonPublic).OrderBy(x => x.Name))
                Console.WriteLine("   nested   " + n.Name);
            if (t.IsEnum)
                foreach (var v in Enum.GetNames(t)) Console.WriteLine("   enum     " + v + " = " + Convert.ToInt64(Enum.Parse(t, v)));
            Console.WriteLine();
        }
        return 0;
    }

    static string Attrs(MemberInfo m)
    {
        var a = m.GetCustomAttributes(false).Select(x => x.GetType().Name).ToArray();
        return a.Length == 0 ? "" : "[" + string.Join(",", a) + "]";
    }

    static string Short(Type t)
    {
        if (t == null) return "void";
        if (!t.IsGenericType) return t.Name;
        return t.Name.Split('`')[0] + "<" + string.Join(",", t.GetGenericArguments().Select(Short)) + ">";
    }
}
