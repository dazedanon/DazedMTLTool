using Il2CppInterop.Runtime.InteropTypes.Arrays;
using Il2CppInterop.Runtime.InteropTypes;
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text;
using UnityEngine;

namespace LoserLifeATest;

internal static class BundleDecryptDumper
{
    private static readonly Encoding Utf8NoBom = new UTF8Encoding(false);
    private static readonly object DumpLock = new();
    private static readonly HashSet<string> LoggedKeys = new(StringComparer.Ordinal);
    private static readonly HashSet<string> DumpedKeys = new(StringComparer.Ordinal);
    private static readonly Dictionary<string, string> ReadDumpPaths = new(StringComparer.Ordinal);
    private static readonly Dictionary<string, StreamDumpInfo> StreamInfos = new(StringComparer.Ordinal);
    private static readonly HashSet<string> InitializedReadDumps = new(StringComparer.Ordinal);
    private static readonly HashSet<string> LoggedReadDumps = new(StringComparer.Ordinal);
    private static readonly HashSet<string> FullDumpedStreams = new(StringComparer.Ordinal);
    private static int _memoryDumpIndex;

    [ThreadStatic]
    private static bool _insideDump;

    public static void OnSeekableAesStreamConstructed(object[] args)
    {
        if (_insideDump || Plugin.CaptureBundleKeys?.Value != true || args == null || args.Length < 3)
        {
            return;
        }

        var baseStream = args[0];
        var password = args[1]?.ToString() ?? string.Empty;
        var salt = ToByteArray(args[2]);
        var sourcePaths = ResolveSourcePaths(baseStream);
        var sourceText = sourcePaths.Count == 0 ? "<unknown>" : string.Join(", ", sourcePaths.Select(Path.GetFileName));
        var key = BuildKey(sourceText, password, salt);

        if (LoggedKeys.Add(key))
        {
            Plugin.Log.LogInfo($"Captured bundle decrypt key: source={sourceText}, password={password}, salt={ToHex(salt)}");
            AppendKeyLog(sourceText, password, salt);
        }

        if (Plugin.DumpDecryptedBundles?.Value != true)
        {
            return;
        }

        if (sourcePaths.Count == 0)
        {
            Plugin.Log.LogWarning("Captured bundle key, but could not identify the source StreamingAssets file to dump.");
            return;
        }

        foreach (var sourcePath in sourcePaths)
        {
            DumpBundle(sourcePath, password, salt);
        }
    }

    public static long GetStreamPosition(object stream)
    {
        if (stream == null)
        {
            return -1;
        }

        try
        {
            var property = stream.GetType().GetProperty("Position", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (property?.GetValue(stream) is object value)
            {
                return Convert.ToInt64(value);
            }
        }
        catch
        {
        }

        return -1;
    }

    public static void OnSeekableAesStreamRead(global::SeekableAesStream instance, object[] args, int bytesRead, long startPosition)
    {
        if (_insideDump ||
            Plugin.DumpDecryptedBundles?.Value != true ||
            Plugin.DumpSeekableAesReads?.Value != true ||
            instance == null ||
            args == null ||
            args.Length < 3 ||
            bytesRead <= 0)
        {
            return;
        }

        var buffer = args[0] as Il2CppStructArray<byte>;
        if (buffer == null)
        {
            return;
        }

        var offset = Convert.ToInt32(args[1]);
        var key = GetObjectKey(instance);
        if (startPosition < 0)
        {
            var currentPosition = GetStreamPosition(instance);
            if (currentPosition >= bytesRead)
            {
                startPosition = currentPosition - bytesRead;
            }
        }

        if (startPosition < 0)
        {
            Plugin.Log?.LogWarning("Skipping decrypted stream read dump: stream position unavailable.");
            return;
        }

        var path = GetReadDumpPath(key);
        TryDumpFullStream(instance, key, startPosition, bytesRead);

        try
        {
            var managed = new byte[bytesRead];
            for (var i = 0; i < bytesRead; i++)
            {
                managed[i] = buffer[offset + i];
            }

            lock (DumpLock)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                InitializeReadDump(key, path);
                using var output = File.Open(path, FileMode.OpenOrCreate, FileAccess.Write, FileShare.Read);
                output.Seek(startPosition, SeekOrigin.Begin);
                output.Write(managed, 0, managed.Length);

                if (LoggedReadDumps.Add(key))
                {
                    Plugin.Log.LogInfo($"Started positioned decrypted stream dump: {path}");
                }
            }
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"Failed to write positioned decrypted stream dump: {ex.Message}");
        }
    }

    public static void OnAssetBundleLoadCalled(MethodBase originalMethod, object[] args)
    {
        if (Plugin.DumpDecryptedBundles?.Value != true || originalMethod == null || args == null)
        {
            return;
        }

        LogAssetBundleLoadProbe(originalMethod, args);
        RegisterAssetBundleStream(originalMethod, args);

        if (Plugin.DumpAssetBundleMemoryLoads?.Value != true ||
            !originalMethod.Name.StartsWith("LoadFromMemory", StringComparison.Ordinal) ||
            args.Length == 0)
        {
            return;
        }

        var bytes = ToByteArray(args[0]);
        if (bytes.Length == 0)
        {
            return;
        }

        DumpMemoryLoadBytes(originalMethod.Name, bytes);
    }

    private static List<string> ResolveSourcePaths(object baseStream)
    {
        var paths = new List<string>();
        var directPath = TryGetStreamPath(baseStream);
        if (!string.IsNullOrEmpty(directPath) && File.Exists(directPath))
        {
            paths.Add(directPath);
            return paths;
        }

        var length = TryGetStreamLength(baseStream);
        if (length == null)
        {
            return paths;
        }

        try
        {
            var streamingAssetsPath = Application.streamingAssetsPath;
            if (string.IsNullOrEmpty(streamingAssetsPath) || !Directory.Exists(streamingAssetsPath))
            {
                return paths;
            }

            foreach (var path in Directory.GetFiles(streamingAssetsPath, "e*"))
            {
                var info = new FileInfo(path);
                if (info.Length == length.Value)
                {
                    paths.Add(path);
                }
            }
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"Could not resolve StreamingAssets source by length: {ex.Message}");
        }

        return paths;
    }

    private static void DumpBundle(string sourcePath, string password, byte[] salt)
    {
        var sourceName = Path.GetFileName(sourcePath);
        var dumpKey = BuildKey(sourcePath, password, salt);
        if (!DumpedKeys.Add(dumpKey))
        {
            return;
        }

        try
        {
            var outputDir = GetDumpDirectory();
            Directory.CreateDirectory(outputDir);

            var outputPath = Path.Combine(outputDir, sourceName + ".decrypted.bundle");
            if (File.Exists(outputPath) && Plugin.OverwriteBundleDumps?.Value != true)
            {
                Plugin.Log.LogInfo($"Decrypted bundle already exists, skipping: {outputPath}");
                return;
            }

            var tempPath = outputPath + ".tmp";
            if (File.Exists(tempPath))
            {
                File.Delete(tempPath);
            }

            Plugin.Log.LogInfo($"Dumping decrypted bundle: {sourceName}");
            Il2CppSystem.IO.Stream input = null;
            global::SeekableAesStream decrypted = null;
            _insideDump = true;
            try
            {
                input = Il2CppSystem.IO.File.OpenRead(sourcePath);
                decrypted = new global::SeekableAesStream(input, password, ToIl2CppBytes(salt));
                using var output = File.Create(tempPath);
                CopyIl2CppStream(decrypted, output);
            }
            finally
            {
                _insideDump = false;
                TryClose(decrypted);
                TryClose(input);
            }

            File.Move(tempPath, outputPath, true);
            Plugin.Log.LogInfo($"Dumped decrypted bundle: {outputPath} ({new FileInfo(outputPath).Length} bytes, header={ReadHeader(outputPath)})");
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"Failed to dump decrypted bundle {sourceName}: {ex}");
        }
    }

    private static void DumpMemoryLoadBytes(string methodName, byte[] bytes)
    {
        try
        {
            var outputDir = GetDumpDirectory();
            Directory.CreateDirectory(outputDir);

            var index = System.Threading.Interlocked.Increment(ref _memoryDumpIndex);
            var outputPath = Path.Combine(outputDir, $"assetbundle_memory_{index:000}_{methodName}.bin");
            File.WriteAllBytes(outputPath, bytes);
            Plugin.Log.LogInfo($"Dumped AssetBundle memory load bytes: {outputPath} ({bytes.Length} bytes, header={HeaderFromBytes(bytes)})");
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"Failed to dump AssetBundle memory load bytes: {ex.Message}");
        }
    }

    private static void TryDumpFullStream(global::SeekableAesStream instance, string key, long startPosition, int bytesRead)
    {
        if (Plugin.DumpFullSeekableAesStreams?.Value != true || !FullDumpedStreams.Add(key))
        {
            return;
        }

        if (!StreamInfos.TryGetValue(key, out var info))
        {
            info = new StreamDumpInfo($"stream_{key}", Path.Combine(GetDumpDirectory(), $"stream_{key}.decrypted.full.bundle"), TryGetStreamLength(instance));
        }

        var outputPath = Path.Combine(GetDumpDirectory(), $"{info.SourceName}.decrypted.full.bundle");
        var tempPath = outputPath + ".tmp";

        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(outputPath));
            if (File.Exists(outputPath) && Plugin.OverwriteBundleDumps?.Value != true)
            {
                Plugin.Log.LogInfo($"Full decrypted stream dump already exists, skipping: {outputPath}");
                return;
            }

            var restorePosition = GetStreamPosition(instance);
            if (restorePosition < 0 && startPosition >= 0)
            {
                restorePosition = startPosition + bytesRead;
            }

            Plugin.Log.LogInfo($"Dumping full decrypted stream: {info.SourceName}");
            _insideDump = true;
            try
            {
                SeekIl2CppStream(instance, 0);
                using var output = File.Create(tempPath);
                CopyIl2CppStream(instance, output);
                if (restorePosition >= 0)
                {
                    SeekIl2CppStream(instance, restorePosition);
                }
            }
            finally
            {
                _insideDump = false;
            }

            File.Move(tempPath, outputPath, true);
            Plugin.Log.LogInfo($"Dumped full decrypted stream: {outputPath} ({new FileInfo(outputPath).Length} bytes, header={ReadHeader(outputPath)})");
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"Failed to dump full decrypted stream {info.SourceName}: {ex.Message}");
            try
            {
                if (File.Exists(tempPath))
                {
                    File.Delete(tempPath);
                }
            }
            catch
            {
            }
        }
    }

    private static void LogAssetBundleLoadProbe(MethodBase method, object[] args)
    {
        try
        {
            var detail = args.Length == 0 ? string.Empty : DescribeArg(args[0]);
            Plugin.Log.LogInfo($"AssetBundle.{method.Name} called {detail}");
        }
        catch
        {
        }
    }

    private static void RegisterAssetBundleStream(MethodBase method, object[] args)
    {
        if (!method.Name.StartsWith("LoadFromStream", StringComparison.Ordinal) || args.Length == 0 || args[0] == null)
        {
            return;
        }

        var key = GetObjectKey(args[0]);
        if (StreamInfos.ContainsKey(key))
        {
            return;
        }

        var length = TryGetStreamLength(args[0]);
        var sourceName = ResolveSourceNameByLength(length) ?? $"stream_{key}";
        var outputPath = Path.Combine(GetDumpDirectory(), $"{sourceName}.decrypted.position.bundle");
        StreamInfos[key] = new StreamDumpInfo(sourceName, outputPath, length);
        Plugin.Log.LogInfo($"Registered positioned bundle dump stream: {sourceName} length={length?.ToString() ?? "<unknown>"}");
    }

    private static string GetDumpDirectory()
    {
        var pluginDir = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        if (string.IsNullOrEmpty(pluginDir))
        {
            pluginDir = Path.Combine(Application.dataPath, "..", "BepInEx", "plugins", "LoserLifeATest");
        }
        var configured = Plugin.BundleDumpDirectory?.Value;
        if (string.IsNullOrWhiteSpace(configured))
        {
            configured = "decrypted_bundles";
        }

        return Path.IsPathRooted(configured)
            ? configured
            : Path.Combine(pluginDir, configured);
    }

    private static string GetReadDumpPath(string key)
    {
        if (ReadDumpPaths.TryGetValue(key, out var path))
        {
            return path;
        }

        var outputDir = GetDumpDirectory();
        path = StreamInfos.TryGetValue(key, out var info)
            ? info.OutputPath
            : Path.Combine(outputDir, $"seekable_pos_{key}.bundle");

        ReadDumpPaths[key] = path;
        return path;
    }

    private static void InitializeReadDump(string key, string path)
    {
        if (!InitializedReadDumps.Add(key))
        {
            return;
        }

        if (File.Exists(path))
        {
            try
            {
                File.Delete(path);
            }
            catch
            {
            }
        }

        if (StreamInfos.TryGetValue(key, out var info) && info.Length is > 0)
        {
            using var output = File.Open(path, FileMode.CreateNew, FileAccess.Write, FileShare.Read);
            output.SetLength(info.Length.Value);
        }
    }

    private static string ResolveSourceNameByLength(long? length)
    {
        if (length == null)
        {
            return null;
        }

        try
        {
            var streamingAssetsPath = Application.streamingAssetsPath;
            if (string.IsNullOrEmpty(streamingAssetsPath) || !Directory.Exists(streamingAssetsPath))
            {
                return null;
            }

            foreach (var path in Directory.GetFiles(streamingAssetsPath, "e*"))
            {
                if (new FileInfo(path).Length == length.Value)
                {
                    return Path.GetFileName(path);
                }
            }
        }
        catch
        {
        }

        return null;
    }

    private static string TryGetStreamPath(object stream)
    {
        if (stream == null)
        {
            return null;
        }

        if (stream is FileStream fileStream)
        {
            return fileStream.Name;
        }

        try
        {
            var type = stream.GetType();
            var nameProperty = type.GetProperty("Name", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (nameProperty?.GetValue(stream) is string name && File.Exists(name))
            {
                return name;
            }

            var pathProperty = type.GetProperty("Path", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (pathProperty?.GetValue(stream) is string path && File.Exists(path))
            {
                return path;
            }
        }
        catch
        {
        }

        return null;
    }

    private static long? TryGetStreamLength(object stream)
    {
        if (stream == null)
        {
            return null;
        }

        if (stream is Stream managedStream)
        {
            try
            {
                return managedStream.Length;
            }
            catch
            {
            }
        }

        try
        {
            var lengthProperty = stream.GetType().GetProperty("Length", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            var value = lengthProperty?.GetValue(stream);
            return value == null ? null : Convert.ToInt64(value);
        }
        catch
        {
            return null;
        }
    }

    private static byte[] ToByteArray(object value)
    {
        switch (value)
        {
            case null:
                return Array.Empty<byte>();
            case byte[] bytes:
                return bytes;
            case Il2CppStructArray<byte> il2CppBytes:
            {
                var bytes = new byte[il2CppBytes.Length];
                for (var i = 0; i < bytes.Length; i++)
                {
                    bytes[i] = il2CppBytes[i];
                }

                return bytes;
            }
            case IEnumerable enumerable:
            {
                var bytes = new List<byte>();
                foreach (var item in enumerable)
                {
                    if (item is byte b)
                    {
                        bytes.Add(b);
                    }
                }

                return bytes.ToArray();
            }
            default:
                return Array.Empty<byte>();
        }
    }

    private static string GetObjectKey(object value)
    {
        try
        {
            if (value is Il2CppObjectBase il2Cpp && il2Cpp.Pointer != IntPtr.Zero)
            {
                return il2Cpp.Pointer.ToString("x");
            }
        }
        catch
        {
        }

        return RuntimeHelpers.GetHashCode(value).ToString("x");
    }

    private static Il2CppStructArray<byte> ToIl2CppBytes(byte[] bytes)
    {
        bytes ??= Array.Empty<byte>();
        var array = new Il2CppStructArray<byte>(bytes.Length);
        for (var i = 0; i < bytes.Length; i++)
        {
            array[i] = bytes[i];
        }

        return array;
    }

    private static void CopyIl2CppStream(global::SeekableAesStream input, Stream output)
    {
        var il2CppBuffer = new Il2CppStructArray<byte>(1024 * 1024);
        var managedBuffer = new byte[il2CppBuffer.Length];

        while (true)
        {
            var read = input.Read(il2CppBuffer, 0, il2CppBuffer.Length);
            if (read <= 0)
            {
                break;
            }

            for (var i = 0; i < read; i++)
            {
                managedBuffer[i] = il2CppBuffer[i];
            }

            output.Write(managedBuffer, 0, read);
        }
    }

    private static long SeekIl2CppStream(global::SeekableAesStream input, long offset)
    {
        return input.Seek(offset, Il2CppSystem.IO.SeekOrigin.Begin);
    }

    private static void TryClose(object stream)
    {
        if (stream == null)
        {
            return;
        }

        try
        {
            stream.GetType().GetMethod("Close", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null)?.Invoke(stream, null);
        }
        catch
        {
        }

        try
        {
            stream.GetType().GetMethod("Dispose", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic, null, Type.EmptyTypes, null)?.Invoke(stream, null);
        }
        catch
        {
        }
    }

    private static void AppendKeyLog(string source, string password, byte[] salt)
    {
        try
        {
            var outputDir = GetDumpDirectory();
            Directory.CreateDirectory(outputDir);
            var logPath = Path.Combine(outputDir, "bundle_keys.tsv");
            var line = string.Concat(
                DateTimeOffset.Now.ToString("O"),
                "\t",
                Escape(source),
                "\t",
                Escape(password),
                "\t",
                ToHex(salt),
                "\t",
                Convert.ToBase64String(salt),
                Environment.NewLine);
            File.AppendAllText(logPath, line, Utf8NoBom);
        }
        catch (Exception ex)
        {
            Plugin.Log?.LogWarning($"Could not append bundle key log: {ex.Message}");
        }
    }

    private static string BuildKey(string source, string password, byte[] salt)
    {
        return string.Concat(source, "\u001f", password, "\u001f", ToHex(salt));
    }

    private static string ToHex(byte[] bytes)
    {
        if (bytes == null || bytes.Length == 0)
        {
            return string.Empty;
        }

        var builder = new StringBuilder(bytes.Length * 2);
        foreach (var b in bytes)
        {
            builder.Append(b.ToString("x2"));
        }

        return builder.ToString();
    }

    private static string ReadHeader(string path)
    {
        try
        {
            var bytes = new byte[6];
            using var stream = File.OpenRead(path);
            var read = stream.Read(bytes, 0, bytes.Length);
            return Encoding.ASCII.GetString(bytes, 0, read).Replace("\0", "\\0");
        }
        catch
        {
            return "<unreadable>";
        }
    }

    private static string HeaderFromBytes(byte[] bytes)
    {
        if (bytes == null || bytes.Length == 0)
        {
            return string.Empty;
        }

        var read = Math.Min(6, bytes.Length);
        return Encoding.ASCII.GetString(bytes, 0, read).Replace("\0", "\\0");
    }

    private static string DescribeArg(object arg)
    {
        switch (arg)
        {
            case null:
                return "arg0=<null>";
            case string text:
                return $"arg0=\"{text}\"";
            case Il2CppStructArray<byte> bytes:
                return $"arg0=byte[{bytes.Length}] header={HeaderFromIl2CppBytes(bytes)}";
            default:
                var length = TryGetStreamLength(arg);
                return length == null
                    ? $"arg0Type={arg.GetType().FullName}"
                    : $"arg0Type={arg.GetType().FullName} length={length.Value}";
        }
    }

    private static string HeaderFromIl2CppBytes(Il2CppStructArray<byte> bytes)
    {
        if (bytes == null || bytes.Length == 0)
        {
            return string.Empty;
        }

        var read = Math.Min(6, bytes.Length);
        var managed = new byte[read];
        for (var i = 0; i < read; i++)
        {
            managed[i] = bytes[i];
        }

        return HeaderFromBytes(managed);
    }

    private static string Escape(string value)
    {
        return (value ?? string.Empty)
            .Replace("\\", "\\\\")
            .Replace("\r", "\\r")
            .Replace("\n", "\\n")
            .Replace("\t", "\\t");
    }

    private sealed record StreamDumpInfo(string SourceName, string OutputPath, long? Length);
}
