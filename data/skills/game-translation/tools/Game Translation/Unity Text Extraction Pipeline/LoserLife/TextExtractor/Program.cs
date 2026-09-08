using System.Collections.Concurrent;
using System.Diagnostics;
using System.Globalization;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.RegularExpressions;

internal sealed record TextRow(
    string Category,
    string SourceFile,
    int Line,
    string Field,
    string Context,
    string ObjectType,
    string ObjectId,
    string Text
);

internal static partial class Program
{
    private static readonly Regex JapaneseRegex = JapanesePattern();
    private static readonly Regex ScalarRegex = ScalarPattern();
    private static readonly Regex ListItemRegex = ListItemPattern();
    private static readonly Regex ObjectRegex = ObjectPattern();
    private static readonly Regex CSharpStringRegex = CSharpStringPattern();
    private static readonly Regex CSharpConstRegex = CSharpConstPattern();

    private static readonly HashSet<string> TextExtensions = new(StringComparer.OrdinalIgnoreCase)
    {
        ".anim",
        ".asset",
        ".cs",
        ".controller",
        ".json",
        ".overridecontroller",
        ".prefab",
        ".txt",
        ".unity",
        ".yaml",
        ".yml",
    };

    private static readonly string[] NoisePathParts =
    {
        "/font/",
        "/fonts/",
        "/textmesh pro/",
        "/textmeshpro/",
        "/tmp/",
    };

    private static readonly HashSet<string> NoiseFieldNames = new(StringComparer.OrdinalIgnoreCase)
    {
        "m_atlastextures",
        "m_characterlookupdictionary",
        "m_charactertable",
        "m_creationsettings",
        "m_fallbackfontassettable",
        "m_fontasset",
        "m_fontfeaturetable",
        "m_fontinfo",
        "m_glyphtable",
        "m_kerningtable",
        "m_material",
        "m_script",
        "charactersequence",
        "serializedversion",
    };

    private static readonly HashSet<string> TitleFields = new(StringComparer.OrdinalIgnoreCase)
    {
        "title",
        "name",
        "m_name",
        "fieldname",
        "label",
        "displayname",
    };

    private static readonly HashSet<string> PlayerTextFields = new(StringComparer.OrdinalIgnoreCase)
    {
        "m_text",
        "text",
        "value",
        "dialogtitle",
        "dialogtitlewhenlock",
        "fixedtext",
        "fixedtext_1",
        "fixedtext_2",
        "fixedtext_3",
        "fixedtext_4",
        "talk_1",
        "talk_2",
        "talk_3",
        "lookboobstalk_1",
        "lookboobstalk_2",
        "lookboobstalk_3",
        "lookvagtalk_1",
        "lookvagtalk_2",
        "lookvagtalk_3",
        "ejatalk_1",
        "ejatalk_2",
        "ejatalk_3",
        "shopname",
        "preshoptext",
        "aftershoptext",
        "cancelshoptext",
        "preshoppewtext",
        "aftershoppewtext",
        "cancelshoppewtext",
        "playershowshoptext",
        "playercancelshoptext",
        "playershowshoppewtext",
        "playercancelshoppewtext",
        "girlshoptext_1",
        "girlshoptext_2",
        "girlshoptext_3",
        "salecostumes",
        "itemname",
        "infoname",
        "mainname",
        "subname",
        "dungeonname",
        "tip",
        "tiptext",
        "itemtip",
        "iteminfotiptext",
        "dungeiontiptext",
        "message",
        "alert",
        "clearmessage",
        "notpermitmessage",
        "startalertmessage",
        "productname",
    };

    public static int Main(string[] args)
    {
        Console.OutputEncoding = Encoding.UTF8;
        var options = Options.Parse(args);
        var root = Path.GetFullPath(options.Root ?? Directory.GetCurrentDirectory());
        var exportedProject = Path.GetFullPath(options.ExportedProject ?? FindNewestExportedProject(root));
        var outputDir = Path.GetFullPath(options.OutputDir ?? Path.Combine(root, "tooling", "outputs"));
        Directory.CreateDirectory(outputDir);

        var scanRoots = new[]
        {
            Path.Combine(exportedProject, "Assets"),
            Path.Combine(exportedProject, "ProjectSettings"),
        }.Where(Directory.Exists).ToArray();

        var files = scanRoots
            .SelectMany(scanRoot => Directory.EnumerateFiles(scanRoot, "*", SearchOption.AllDirectories))
            .Where(IsTextFile)
            .ToArray();

        var stopwatch = Stopwatch.StartNew();
        var rows = ScanFiles(exportedProject, files, options.MaxDegreeOfParallelism);
        stopwatch.Stop();

        var sortedRows = rows
            .OrderBy(row => row.SourceFile, StringComparer.OrdinalIgnoreCase)
            .ThenBy(row => row.Line)
            .ThenBy(row => row.Field, StringComparer.OrdinalIgnoreCase)
            .ThenBy(row => row.Text, StringComparer.Ordinal)
            .ToList();

        var csvPath = Path.Combine(outputDir, "japanese_text_all_occurrences.csv");
        var jsonPath = Path.Combine(outputDir, "japanese_text_all_occurrences.json");
        var txtPath = Path.Combine(outputDir, "japanese_text_dump.txt");
        var summaryPath = Path.Combine(outputDir, "japanese_text_summary.txt");

        WriteCsv(csvPath, sortedRows);
        WriteJson(jsonPath, sortedRows);
        WriteTextDump(txtPath, sortedRows, exportedProject, files.Length, stopwatch.Elapsed);
        WriteSummary(summaryPath, sortedRows, files.Length, stopwatch.Elapsed);

        Console.WriteLine($"Scanned files: {files.Length}");
        Console.WriteLine($"Occurrences: {sortedRows.Count}");
        Console.WriteLine($"Unique strings: {sortedRows.Select(row => row.Text).Distinct(StringComparer.Ordinal).Count()}");
        Console.WriteLine($"Elapsed: {stopwatch.Elapsed.TotalSeconds:n2}s");
        Console.WriteLine($"Wrote: {txtPath}");
        Console.WriteLine($"Wrote: {csvPath}");
        Console.WriteLine($"Wrote: {jsonPath}");
        Console.WriteLine($"Wrote: {summaryPath}");
        return 0;
    }

    private static List<TextRow> ScanFiles(string exportedProject, string[] files, int maxDegreeOfParallelism)
    {
        var bag = new ConcurrentBag<TextRow>();
        var parallelOptions = new ParallelOptions
        {
            MaxDegreeOfParallelism = maxDegreeOfParallelism <= 0 ? Environment.ProcessorCount : maxDegreeOfParallelism,
        };

        Parallel.ForEach(files, parallelOptions, file =>
        {
            foreach (var row in ScanFile(exportedProject, file))
            {
                bag.Add(row);
            }
        });

        return bag.ToList();
    }

    private static IEnumerable<TextRow> ScanFile(string exportedProject, string path)
    {
        var rows = new List<TextRow>();
        var relPath = NormalizeRelative(Path.GetRelativePath(exportedProject, path));
        var currentContext = "";
        var currentObjectType = "";
        var currentObjectId = "";
        var labelByIndent = new Dictionary<int, string>();
        var containerByIndent = new Dictionary<int, string>();
        BlockState? block = null;

        using var reader = new StreamReader(path, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false, throwOnInvalidBytes: false), detectEncodingFromByteOrderMarks: true);
        var lineNo = 0;
        while (reader.ReadLine() is { } line)
        {
            lineNo++;

            if (block is not null)
            {
                var indent = CountIndent(line);
                if (string.IsNullOrWhiteSpace(line) || indent > block.Indent)
                {
                    block.Parts.Add(line.Length > block.Indent + 1 ? line[(block.Indent + 1)..] : "");
                    continue;
                }

                AddRow(rows, relPath, path, block.Line, block.Field, string.Join('\n', block.Parts), currentContext, currentObjectType, currentObjectId, block.Label);
                block = null;
            }

            var objectMatch = ObjectRegex.Match(line);
            if (objectMatch.Success)
            {
                currentObjectType = objectMatch.Groups[1].Value;
                currentObjectId = objectMatch.Groups[2].Value;
                currentContext = "";
                labelByIndent.Clear();
                containerByIndent.Clear();
                continue;
            }

            var scalarMatch = ScalarRegex.Match(line);
            if (scalarMatch.Success)
            {
                var indent = CountIndent(scalarMatch.Groups[1].Value);
                var field = scalarMatch.Groups[2].Value;
                var rawValue = scalarMatch.Groups[3].Success ? scalarMatch.Groups[3].Value : "";
                var label = BestLabel(labelByIndent, indent);

                if (string.IsNullOrWhiteSpace(rawValue))
                {
                    containerByIndent[indent] = field;
                    continue;
                }

                var parsed = ParseScalar(rawValue);
                if (IsBlockMarker(parsed))
                {
                    block = new BlockState(field, lineNo, indent, label);
                    continue;
                }

                if (field.Equals("m_Name", StringComparison.OrdinalIgnoreCase))
                {
                    currentContext = parsed;
                }

                if (TitleFields.Contains(field) && parsed.Length > 0)
                {
                    labelByIndent[indent] = parsed;
                }

                AddRow(rows, relPath, path, lineNo, field, parsed, currentContext, currentObjectType, currentObjectId, label);
                continue;
            }

            var listMatch = ListItemRegex.Match(line);
            if (listMatch.Success)
            {
                var indent = CountIndent(listMatch.Groups[1].Value);
                var parsed = ParseScalar(listMatch.Groups[2].Value);
                var field = BestContainer(containerByIndent, indent);
                AddRow(rows, relPath, path, lineNo, field, parsed, currentContext, currentObjectType, currentObjectId, "");
                continue;
            }

            var ext = Path.GetExtension(path);
            if (ext.Equals(".cs", StringComparison.OrdinalIgnoreCase))
            {
                ScanCSharpLine(rows, relPath, path, lineNo, line);
                continue;
            }

            if ((ext.Equals(".txt", StringComparison.OrdinalIgnoreCase) || ext.Equals(".json", StringComparison.OrdinalIgnoreCase)) && HasJapanese(line))
            {
                AddRow(rows, relPath, path, lineNo, "line", line, currentContext, currentObjectType, currentObjectId, "");
            }
        }

        if (block is not null)
        {
            AddRow(rows, relPath, path, block.Line, block.Field, string.Join('\n', block.Parts), currentContext, currentObjectType, currentObjectId, block.Label);
        }

        return rows;
    }

    private static void ScanCSharpLine(List<TextRow> rows, string relPath, string path, int lineNo, string line)
    {
        if (!HasJapanese(line))
        {
            return;
        }

        var constMatch = CSharpConstRegex.Match(line);
        var field = constMatch.Success ? constMatch.Groups[1].Value : "csharp_string";
        foreach (Match match in CSharpStringRegex.Matches(line))
        {
            var literal = match.Groups[1].Value;
            var parsed = UnescapeDoubleQuoted(literal);
            AddRow(rows, relPath, path, lineNo, field, parsed, Path.GetFileName(relPath), "cs", "", "");
        }
    }

    private static void AddRow(
        List<TextRow> rows,
        string relPath,
        string absolutePath,
        int line,
        string field,
        string value,
        string context,
        string objectType,
        string objectId,
        string label)
    {
        var text = CleanText(value);
        if (ShouldSkip(relPath, absolutePath, field, text))
        {
            return;
        }

        var displayField = field.Equals("value", StringComparison.OrdinalIgnoreCase) && !string.IsNullOrWhiteSpace(label)
            ? $"value[{label}]"
            : field;

        rows.Add(new TextRow(
            CategoryFor(relPath, field, label, context),
            relPath,
            line,
            displayField,
            CleanText(context),
            objectType,
            objectId,
            text));
    }

    private static bool ShouldSkip(string relPath, string absolutePath, string field, string text)
    {
        if (string.IsNullOrWhiteSpace(text) || !HasJapanese(text))
        {
            return true;
        }

        var lowerRel = "/" + relPath.Replace('\\', '/').ToLowerInvariant();
        if (lowerRel.Contains("linebreaking", StringComparison.OrdinalIgnoreCase))
        {
            return true;
        }

        if (NoisePathParts.Any(part => lowerRel.Contains(part, StringComparison.Ordinal)))
        {
            return true;
        }

        if (NoiseFieldNames.Contains(field))
        {
            return true;
        }

        if (LooksLikeCharacterTable(text))
        {
            return true;
        }

        return false;
    }

    private static string CategoryFor(string relPath, string field, string label, string context)
    {
        var relLower = relPath.ToLowerInvariant();
        var fieldLower = field.ToLowerInvariant();
        var labelLower = label.ToLowerInvariant();
        var contextLower = context.ToLowerInvariant();

        if (relLower.Contains("dialogue database.asset", StringComparison.Ordinal) ||
            labelLower is "dialogue text" or "menu text" or "sequence" or "conditions" or "user script")
        {
            return "dialogue_database";
        }

        if (relLower.Contains("01_scenes/tutorial.unity", StringComparison.Ordinal))
        {
            return "tutorial_ui";
        }

        if (fieldLower is "talk_1" or "talk_2" or "talk_3" or
            "lookboobstalk_1" or "lookboobstalk_2" or "lookboobstalk_3" or
            "lookvagtalk_1" or "lookvagtalk_2" or "lookvagtalk_3" or
            "ejatalk_1" or "ejatalk_2" or "ejatalk_3")
        {
            return "npc_ambient_dialogue";
        }

        if (fieldLower.Contains("shop", StringComparison.Ordinal) || contextLower.Contains("shop", StringComparison.Ordinal))
        {
            return "shop_text";
        }

        if (fieldLower == "m_text")
        {
            return "ui_text";
        }

        if (fieldLower == "csharp_string" || relLower.EndsWith(".cs", StringComparison.Ordinal))
        {
            return "source_literal";
        }

        if (fieldLower.Contains("tip", StringComparison.Ordinal) ||
            fieldLower.Contains("message", StringComparison.Ordinal) ||
            fieldLower.Contains("alert", StringComparison.Ordinal))
        {
            return "ui_message";
        }

        if (fieldLower.Contains("item", StringComparison.Ordinal) ||
            fieldLower.Contains("dungeon", StringComparison.Ordinal) ||
            fieldLower.Contains("costume", StringComparison.Ordinal) ||
            fieldLower.Contains("name", StringComparison.Ordinal))
        {
            return "game_data_name";
        }

        if (fieldLower == "m_name")
        {
            return "asset_name";
        }

        if (PlayerTextFields.Contains(fieldLower))
        {
            return "player_text";
        }

        return "japanese_text";
    }

    private static bool LooksLikeCharacterTable(string text)
    {
        var compact = new string(text.Where(ch => !char.IsWhiteSpace(ch)).ToArray());
        if (compact.Length < 320)
        {
            return false;
        }

        var uniqueRatio = compact.Distinct().Count() / (double)Math.Max(compact.Length, 1);
        var hasSentenceMarks = compact.Any(ch => ch is '。' or '．' or '、' or '！' or '？');
        return uniqueRatio > 0.38 && !hasSentenceMarks;
    }

    private static string CleanText(string text)
    {
        return text
            .Replace("\r\n", "\n", StringComparison.Ordinal)
            .Replace('\r', '\n')
            .Replace("\u200b", "", StringComparison.Ordinal)
            .Trim();
    }

    private static string ParseScalar(string rawValue)
    {
        var raw = rawValue.Trim();
        if (raw.Length == 0)
        {
            return "";
        }

        if (IsBlockMarker(raw))
        {
            return raw;
        }

        if (raw[0] == '"' && raw.Length >= 2)
        {
            var end = raw.EndsWith('"') ? raw.Length - 1 : raw.Length;
            return UnescapeDoubleQuoted(raw[1..end]);
        }

        if (raw[0] == '\'' && raw.Length >= 2)
        {
            var end = raw.EndsWith('\'') ? raw.Length - 1 : raw.Length;
            return raw[1..end].Replace("''", "'", StringComparison.Ordinal);
        }

        var commentIndex = raw.IndexOf(" #", StringComparison.Ordinal);
        if (commentIndex >= 0)
        {
            raw = raw[..commentIndex].TrimEnd();
        }

        return raw;
    }

    private static string UnescapeDoubleQuoted(string value)
    {
        var builder = new StringBuilder(value.Length);
        for (var i = 0; i < value.Length; i++)
        {
            var ch = value[i];
            if (ch != '\\' || i + 1 >= value.Length)
            {
                builder.Append(ch);
                continue;
            }

            var next = value[++i];
            switch (next)
            {
                case 'n':
                    builder.Append('\n');
                    break;
                case 'r':
                    builder.Append('\r');
                    break;
                case 't':
                    builder.Append('\t');
                    break;
                case '"':
                    builder.Append('"');
                    break;
                case '\\':
                    builder.Append('\\');
                    break;
                case 'u' when i + 4 < value.Length && TryReadHex(value.AsSpan(i + 1, 4), out var code):
                    builder.Append((char)code);
                    i += 4;
                    break;
                default:
                    builder.Append(next);
                    break;
            }
        }

        return builder.ToString();
    }

    private static bool TryReadHex(ReadOnlySpan<char> span, out int value)
    {
        value = 0;
        foreach (var ch in span)
        {
            value <<= 4;
            if (ch is >= '0' and <= '9')
            {
                value += ch - '0';
            }
            else if (ch is >= 'a' and <= 'f')
            {
                value += ch - 'a' + 10;
            }
            else if (ch is >= 'A' and <= 'F')
            {
                value += ch - 'A' + 10;
            }
            else
            {
                return false;
            }
        }

        return true;
    }

    private static bool IsBlockMarker(string value)
    {
        return value is "|" or "|-" or "|+" or ">" or ">-" or ">+";
    }

    private static string BestLabel(Dictionary<int, string> labelByIndent, int indent)
    {
        foreach (var candidate in new[] { indent, indent - 2, indent - 4, indent - 6 })
        {
            if (labelByIndent.TryGetValue(candidate, out var label))
            {
                return label;
            }
        }

        var key = labelByIndent.Keys.Where(k => k <= indent).DefaultIfEmpty(-1).Max();
        return key >= 0 ? labelByIndent[key] : "";
    }

    private static string BestContainer(Dictionary<int, string> containerByIndent, int indent)
    {
        var key = containerByIndent.Keys.Where(k => k < indent).DefaultIfEmpty(-1).Max();
        return key >= 0 ? containerByIndent[key] : "list_item";
    }

    private static int CountIndent(string value)
    {
        var count = 0;
        foreach (var ch in value)
        {
            if (ch == ' ')
            {
                count++;
            }
            else if (ch == '\t')
            {
                count += 4;
            }
            else
            {
                break;
            }
        }

        return count;
    }

    private static bool HasJapanese(string text)
    {
        return JapaneseRegex.IsMatch(text);
    }

    private static bool IsTextFile(string path)
    {
        if (Path.GetExtension(path).Equals(".meta", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        return TextExtensions.Contains(Path.GetExtension(path));
    }

    private static string NormalizeRelative(string path)
    {
        return path.Replace('\\', '/');
    }

    private static string FindNewestExportedProject(string root)
    {
        var exports = Directory
            .EnumerateDirectories(root, "AssetRipper_export_*", SearchOption.TopDirectoryOnly)
            .Select(dir => Path.Combine(dir, "ExportedProject"))
            .Where(Directory.Exists)
            .OrderBy(path => path, StringComparer.OrdinalIgnoreCase)
            .ToArray();

        if (exports.Length == 0)
        {
            throw new DirectoryNotFoundException("No AssetRipper_export_*/ExportedProject folder found.");
        }

        return exports[^1];
    }

    private static void WriteCsv(string path, IReadOnlyList<TextRow> rows)
    {
        using var writer = new StreamWriter(path, false, new UTF8Encoding(encoderShouldEmitUTF8Identifier: true));
        writer.WriteLine("category,source_file,line,field,context,object_type,object_id,text");
        foreach (var row in rows)
        {
            writer.WriteLine(string.Join(',', new[]
            {
                Csv(row.Category),
                Csv(row.SourceFile),
                row.Line.ToString(CultureInfo.InvariantCulture),
                Csv(row.Field),
                Csv(row.Context),
                Csv(row.ObjectType),
                Csv(row.ObjectId),
                Csv(row.Text),
            }));
        }
    }

    private static string Csv(string value)
    {
        if (value.IndexOfAny(['"', ',', '\n', '\r']) < 0)
        {
            return value;
        }

        return "\"" + value.Replace("\"", "\"\"", StringComparison.Ordinal) + "\"";
    }

    private static void WriteJson(string path, IReadOnlyList<TextRow> rows)
    {
        var options = new JsonSerializerOptions
        {
            Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
            WriteIndented = true,
        };
        using var writer = new StreamWriter(path, false, new UTF8Encoding(encoderShouldEmitUTF8Identifier: true));
        JsonSerializer.Serialize(writer.BaseStream, rows, options);
        writer.WriteLine();
    }

    private static void WriteTextDump(string path, IReadOnlyList<TextRow> rows, string exportedProject, int scannedFiles, TimeSpan elapsed)
    {
        var categoryCounts = rows.GroupBy(row => row.Category).OrderByDescending(group => group.Count()).ToList();
        var fileCounts = rows.GroupBy(row => row.SourceFile).ToDictionary(group => group.Key, group => group.Count());
        var uniqueByCategory = rows
            .GroupBy(row => row.Category)
            .ToDictionary(
                group => group.Key,
                group => group.GroupBy(row => row.Text, StringComparer.Ordinal)
                    .OrderBy(textGroup => textGroup.Key, StringComparer.Ordinal)
                    .ToList());

        using var writer = new StreamWriter(path, false, new UTF8Encoding(encoderShouldEmitUTF8Identifier: true));
        writer.WriteLine("Loser Life Japanese Text Dump");
        writer.WriteLine($"Generated: {DateTime.Now:yyyy-MM-dd HH:mm:ss}");
        writer.WriteLine($"Extractor: C#/.NET parallel scanner");
        writer.WriteLine($"AssetRipper project: {exportedProject}");
        writer.WriteLine();
        writer.WriteLine("Summary");
        writer.WriteLine($"- Scanned files: {scannedFiles}");
        writer.WriteLine($"- Occurrences: {rows.Count}");
        writer.WriteLine($"- Unique strings: {rows.Select(row => row.Text).Distinct(StringComparer.Ordinal).Count()}");
        writer.WriteLine($"- Source files: {fileCounts.Count}");
        writer.WriteLine($"- Elapsed: {elapsed.TotalSeconds:n2}s");
        writer.WriteLine("- Categories:");
        foreach (var group in categoryCounts)
        {
            writer.WriteLine($"  - {group.Key}: {group.Count()}");
        }

        writer.WriteLine();
        writer.WriteLine("Coverage Checks");
        var coverage = new Dictionary<string, bool>
        {
            ["Dialogue Database.asset"] = rows.Any(row => row.SourceFile.Contains("Dialogue Database.asset", StringComparison.OrdinalIgnoreCase)),
            ["Tutorial scene UI"] = rows.Any(row => row.SourceFile.Contains("01_Scenes/Tutorial.unity", StringComparison.OrdinalIgnoreCase)),
            ["Tutorial dialogue database entries"] = rows.Any(row => row.SourceFile.Contains("Dialogue Database.asset", StringComparison.OrdinalIgnoreCase) && (row.Text.Contains("チュートリアル", StringComparison.Ordinal) || row.Context.Contains("Tutorial", StringComparison.OrdinalIgnoreCase))),
            ["DefaultVillagerTalk fields"] = rows.Any(row => row.Category == "npc_ambient_dialogue"),
            ["Shop/Costume shop fields"] = rows.Any(row => row.Category == "shop_text"),
            ["Project productName"] = rows.Any(row => row.Field.Equals("productName", StringComparison.OrdinalIgnoreCase)),
        };

        foreach (var item in coverage)
        {
            writer.WriteLine($"- {item.Key}: {(item.Value ? "yes" : "no")}");
        }

        foreach (var category in uniqueByCategory.Keys.OrderBy(key => key, StringComparer.OrdinalIgnoreCase))
        {
            var groups = uniqueByCategory[category];
            writer.WriteLine();
            writer.WriteLine($"## {category} ({groups.Count} unique)");
            var index = 1;
            foreach (var group in groups)
            {
                var occurrences = group.ToList();
                writer.WriteLine();
                writer.WriteLine($"[{index:0000}]");
                var textLines = group.Key.Split('\n');
                for (var i = 0; i < textLines.Length; i++)
                {
                    writer.WriteLine($"{(i == 0 ? "text: " : "      ")}{textLines[i]}");
                }

                writer.WriteLine($"occurrences: {occurrences.Count}");
                writer.WriteLine("sources:");
                foreach (var row in occurrences.Take(10))
                {
                    var context = string.IsNullOrWhiteSpace(row.Context) ? "" : $" [{row.Context}]";
                    writer.WriteLine($"- {row.SourceFile}:{row.Line} {row.Field}{context}");
                }

                if (occurrences.Count > 10)
                {
                    writer.WriteLine($"- ... {occurrences.Count - 10} more occurrence(s)");
                }

                index++;
            }
        }
    }

    private static void WriteSummary(string path, IReadOnlyList<TextRow> rows, int scannedFiles, TimeSpan elapsed)
    {
        using var writer = new StreamWriter(path, false, new UTF8Encoding(encoderShouldEmitUTF8Identifier: true));
        writer.WriteLine("Japanese text extraction summary");
        writer.WriteLine();
        writer.WriteLine($"Extractor: C#/.NET parallel scanner");
        writer.WriteLine($"Scanned files: {scannedFiles}");
        writer.WriteLine($"Occurrences: {rows.Count}");
        writer.WriteLine($"Unique strings: {rows.Select(row => row.Text).Distinct(StringComparer.Ordinal).Count()}");
        writer.WriteLine($"Source files: {rows.Select(row => row.SourceFile).Distinct(StringComparer.OrdinalIgnoreCase).Count()}");
        writer.WriteLine($"Elapsed: {elapsed.TotalSeconds:n2}s");
        writer.WriteLine();
        writer.WriteLine("Categories");
        foreach (var group in rows.GroupBy(row => row.Category).OrderByDescending(group => group.Count()))
        {
            writer.WriteLine($"- {group.Key}: {group.Count()}");
        }

        writer.WriteLine();
        writer.WriteLine("Top source files");
        foreach (var group in rows.GroupBy(row => row.SourceFile).OrderByDescending(group => group.Count()).Take(30))
        {
            writer.WriteLine($"- {group.Key}: {group.Count()}");
        }
    }

    private sealed record BlockState(string Field, int Line, int Indent, string Label)
    {
        public List<string> Parts { get; } = [];
    }

    private sealed record Options(string? Root, string? ExportedProject, string? OutputDir, int MaxDegreeOfParallelism)
    {
        public static Options Parse(string[] args)
        {
            string? root = null;
            string? exportedProject = null;
            string? outputDir = null;
            var maxDegree = Environment.ProcessorCount;

            for (var i = 0; i < args.Length; i++)
            {
                var arg = args[i];
                string NextValue()
                {
                    if (i + 1 >= args.Length)
                    {
                        throw new ArgumentException($"Missing value for {arg}");
                    }

                    return args[++i];
                }

                switch (arg)
                {
                    case "--root":
                        root = NextValue();
                        break;
                    case "--exported-project":
                        exportedProject = NextValue();
                        break;
                    case "--output-dir":
                        outputDir = NextValue();
                        break;
                    case "--max-degree":
                        maxDegree = int.Parse(NextValue(), CultureInfo.InvariantCulture);
                        break;
                    case "--help":
                    case "-h":
                        PrintHelp();
                        Environment.Exit(0);
                        break;
                    default:
                        throw new ArgumentException($"Unknown argument: {arg}");
                }
            }

            return new Options(root, exportedProject, outputDir, maxDegree);
        }

        private static void PrintHelp()
        {
            Console.WriteLine("Usage: dotnet run --project tooling/TextExtractor -- [options]");
            Console.WriteLine("Options:");
            Console.WriteLine("  --root PATH              Game root. Defaults to current directory.");
            Console.WriteLine("  --exported-project PATH  AssetRipper ExportedProject path.");
            Console.WriteLine("  --output-dir PATH        Output directory. Defaults to tooling/outputs.");
            Console.WriteLine("  --max-degree N           Parallel worker count. Defaults to CPU count.");
        }
    }

    [GeneratedRegex("[\\u3040-\\u30ff\\u3400-\\u9fff]", RegexOptions.Compiled)]
    private static partial Regex JapanesePattern();

    [GeneratedRegex("^(\\s*)(?:-\\s+)?([A-Za-z_][\\w$<>.\\-]*):(?:\\s*(.*))?$", RegexOptions.Compiled)]
    private static partial Regex ScalarPattern();

    [GeneratedRegex("^(\\s*)-\\s+(.*)$", RegexOptions.Compiled)]
    private static partial Regex ListItemPattern();

    [GeneratedRegex("^--- !u!(\\d+) &(-?\\d+)", RegexOptions.Compiled)]
    private static partial Regex ObjectPattern();

    [GeneratedRegex("\"((?:\\\\.|[^\"\\\\])*)\"", RegexOptions.Compiled)]
    private static partial Regex CSharpStringPattern();

    [GeneratedRegex("\\b(?:public|private|protected|internal)?\\s*(?:const|static\\s+readonly)\\s+string\\s+([A-Za-z_][A-Za-z0-9_]*)", RegexOptions.Compiled)]
    private static partial Regex CSharpConstPattern();
}
