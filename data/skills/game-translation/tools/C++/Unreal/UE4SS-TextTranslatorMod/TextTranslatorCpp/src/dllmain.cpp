#include <algorithm>
#include <codecvt>
#include <cctype>
#include <cstdint>
#include <cstddef>
#include <filesystem>
#include <fstream>
#include <locale>
#include <optional>
#include <string>
#include <string_view>
#include <type_traits>
#include <atomic>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include <DynamicOutput/DynamicOutput.hpp>
#include <Mod/CppUserModBase.hpp>
#include <Unreal/CoreUObject/UObject/Class.hpp>
#include <Unreal/CoreUObject/UObject/FStrProperty.hpp>
#include <Unreal/CoreUObject/UObject/UnrealType.hpp>
#include <Unreal/Engine/UDataTable.hpp>
#include <Unreal/FOutputDevice.hpp>
#include <Unreal/FText.hpp>
#include <Unreal/FWeakObjectPtr.hpp>
#include <Unreal/Hooks/Hooks.hpp>
#include <Unreal/Property/FTextProperty.hpp>
#include <Unreal/UObject.hpp>
#include <Unreal/UObjectGlobals.hpp>
#include <Unreal/UnrealFlags.hpp>
#include <Unreal/UnrealInitializer.hpp>

using namespace RC;
using namespace RC::Unreal;

namespace
{
    constexpr auto ModTag = STR("[TextTranslatorCpp]");
    thread_local bool g_text_translation_active = false;
    thread_local int g_text_refresh_depth = 0;

    // ProcessEvent nests for every Blueprint VM call; our callbacks add stack
    // per nesting level, which can overflow on deep script recursion the game
    // itself survives. Beyond this depth we contribute nothing (and no stack).
    thread_local int g_hook_depth = 0;

    struct HookDepthGuard
    {
        HookDepthGuard()
        {
            ++g_hook_depth;
        }
        ~HookDepthGuard()
        {
            --g_hook_depth;
        }
    };

    constexpr int MaxHookDepth = 24;

    struct TranslationScope
    {
        bool Entered{};

        TranslationScope()
        {
            if (!g_text_translation_active)
            {
                g_text_translation_active = true;
                Entered = true;
            }
        }

        ~TranslationScope()
        {
            if (Entered)
            {
                g_text_translation_active = false;
            }
        }
    };

    struct TextParamInfo
    {
        std::vector<FProperty*> TextBearingProperties{};
    };

    struct SweepStats
    {
        size_t ObjectsVisited{};
        size_t TextPropertiesVisited{};
        size_t StringPropertiesVisited{};
        size_t Replacements{};
        size_t Refreshes{};
    };

    auto trim_copy(StringType value) -> StringType
    {
        auto is_space = [](CharType ch) {
            return ch == STR(' ') || ch == STR('\t') || ch == STR('\n') || ch == STR('\r') || ch == STR('\u3000');
        };

        while (!value.empty() && is_space(value.front()))
        {
            value.erase(value.begin());
        }
        while (!value.empty() && is_space(value.back()))
        {
            value.pop_back();
        }
        return value;
    }

    auto decode_csv_meta_text(StringType value) -> StringType
    {
        value = trim_copy(std::move(value));
        if (value.size() >= 2 && value.front() == STR('"') && value.back() == STR('"'))
        {
            value = value.substr(1, value.size() - 2);
        }

        StringType decoded;
        decoded.reserve(value.size());
        for (size_t i = 0; i < value.size(); ++i)
        {
            if (value[i] == STR('\\') && i + 1 < value.size())
            {
                const auto next = value[++i];
                if (next == STR('r'))
                {
                    decoded += STR('\r');
                }
                else if (next == STR('n'))
                {
                    decoded += STR('\n');
                }
                else if (next == STR('t'))
                {
                    decoded += STR('\t');
                }
                else
                {
                    decoded += next;
                }
                continue;
            }
            decoded += value[i];
        }
        return decoded;
    }

    auto strip_wrapping_pair(StringType value, CharType left, CharType right) -> StringType
    {
        value = trim_copy(std::move(value));
        if (value.size() >= 2 && value.front() == left && value.back() == right)
        {
            return trim_copy(value.substr(1, value.size() - 2));
        }
        return value;
    }

    auto strip_japanese_wrapping_quotes(StringType value) -> StringType
    {
        value = strip_wrapping_pair(std::move(value), STR('\u300c'), STR('\u300d'));
        value = strip_wrapping_pair(std::move(value), STR('\u300e'), STR('\u300f'));
        return value;
    }

    auto strip_ascii_wrapping_quotes(StringType value) -> StringType
    {
        return strip_wrapping_pair(std::move(value), STR('"'), STR('"'));
    }

    auto normalize(StringType value) -> StringType
    {
        value.erase(std::remove(value.begin(), value.end(), STR('\r')), value.end());
        return trim_copy(std::move(value));
    }

    auto starts_with(StringViewType value, StringViewType prefix) -> bool
    {
        return value.size() >= prefix.size() && value.substr(0, prefix.size()) == prefix;
    }

    auto contains_japanese(StringViewType value) -> bool
    {
        for (const auto ch : value)
        {
            if ((ch >= STR('\u3040') && ch <= STR('\u30ff')) || (ch >= STR('\u3400') && ch <= STR('\u9fff')))
            {
                return true;
            }
        }
        return false;
    }

    auto utf8_to_string_type(const std::string& value) -> StringType
    {
        std::wstring_convert<std::codecvt_utf8_utf16<wchar_t>> converter;
        auto wide = converter.from_bytes(value);
        if constexpr (std::is_same_v<CharType, wchar_t>)
        {
            return wide;
        }
        else
        {
            return StringType{wide.begin(), wide.end()};
        }
    }

    auto string_type_to_utf8(StringViewType value) -> std::string
    {
        std::wstring_convert<std::codecvt_utf8_utf16<wchar_t>> converter;
        if constexpr (std::is_same_v<CharType, wchar_t>)
        {
            return converter.to_bytes(value.data(), value.data() + value.size());
        }
        else
        {
            return std::string{value.begin(), value.end()};
        }
    }

    auto csv_escape(std::string value) -> std::string
    {
        bool needs_quotes = false;
        std::string escaped;
        escaped.reserve(value.size());
        for (const auto ch : value)
        {
            if (ch == '"')
            {
                escaped += "\"\"";
                needs_quotes = true;
            }
            else
            {
                if (ch == ',' || ch == '\r' || ch == '\n')
                {
                    needs_quotes = true;
                }
                escaped += ch;
            }
        }

        if (!needs_quotes)
        {
            return escaped;
        }
        return "\"" + escaped + "\"";
    }

    auto parse_csv_record(const std::string& text, size_t& pos) -> std::vector<std::string>
    {
        std::vector<std::string> fields;
        const auto n = text.size();

        while (pos <= n)
        {
            std::string field;
            if (pos < n && text[pos] == '"')
            {
                ++pos;
                while (pos < n)
                {
                    const char ch = text[pos++];
                    if (ch == '"')
                    {
                        if (pos < n && text[pos] == '"')
                        {
                            field.push_back('"');
                            ++pos;
                        }
                        else
                        {
                            break;
                        }
                    }
                    else
                    {
                        field.push_back(ch);
                    }
                }
            }
            else
            {
                while (pos < n && text[pos] != ',' && text[pos] != '\n' && text[pos] != '\r')
                {
                    field.push_back(text[pos++]);
                }
            }

            fields.emplace_back(std::move(field));

            if (pos >= n)
            {
                break;
            }
            if (text[pos] == ',')
            {
                ++pos;
                continue;
            }
            if (text[pos] == '\r')
            {
                ++pos;
                if (pos < n && text[pos] == '\n')
                {
                    ++pos;
                }
                break;
            }
            if (text[pos] == '\n')
            {
                ++pos;
                break;
            }
        }

        return fields;
    }

    auto read_file_bytes(const std::filesystem::path& path) -> std::string
    {
        std::ifstream file{path, std::ios::binary};
        if (!file)
        {
            return {};
        }
        return std::string{std::istreambuf_iterator<char>{file}, std::istreambuf_iterator<char>{}};
    }

    auto function_has_name(UFunction* function, StringViewType needle) -> bool
    {
        if (!function)
        {
            return false;
        }
        const auto full_name = function->GetFullName();
        return full_name.find(needle) != StringType::npos;
    }
}

class TextTranslatorCpp final : public CppUserModBase
{
  public:
    TextTranslatorCpp()
    {
        ModName = STR("TextTranslatorCpp");
        ModVersion = STR("0.1.0");
        ModDescription = STR("Generic runtime FText/FString translation for UE4SS games (drop-in, game-agnostic)");
        ModAuthors = STR("sw + Codex");
        if (m_debug_log)
        {
            Output::send<LogLevel::Verbose>(STR("{} booting\n"), ModTag);
        }
    }

    auto on_unreal_init() -> void override
    {
        load_translation_table();
        install_hooks();
    }

  private:
    struct RuntimeTextRecord
    {
        StringType Source{};
        StringType Translation{};
        StringType Kind{};
        StringType Context{};
        size_t Count{};
        bool Translated{};
    };

    struct PendingObjectScan
    {
        StringType ObjectFullName{};
        StringType ObjectPath{};
        int32_t NextTick{};
        int32_t Attempts{};
    };

    std::unordered_map<StringType, StringType> m_translations{};

    // FText::Format patterns from the table ("購入：{Cost} <img .../>",
    // charm descriptions with {Value} etc). Runtime strings are the patterns
    // with values substituted; we match literal segments, capture the values,
    // and substitute them into the translated pattern.
    struct FormatPattern
    {
        std::vector<StringType> Literals{};  // Tokens.size() + 1 entries
        std::vector<StringType> Tokens{};    // "{Value}" placeholder tokens
        StringType Translation{};
        size_t LiteralLength{};
    };
    std::vector<FormatPattern> m_format_patterns{};
    std::unordered_map<StringType, RuntimeTextRecord> m_runtime_texts{};
    std::unordered_map<StringType, float> m_text_fit_base_font_sizes{};
    // class/function pointer keys can be recycled by GC; each entry carries a
    // weak ptr whose serial number proves the key still refers to the same
    // object, otherwise the stale FProperty* list would be dereferenced
    struct ClassTextPropertyCacheEntry
    {
        FWeakObjectPtr ClassPtr{};
        std::vector<FProperty*> Properties{};
    };
    std::unordered_map<UClass*, ClassTextPropertyCacheEntry> m_object_text_property_cache{};
    std::unordered_map<UFunction*, bool> m_set_text_function_cache{};
    std::unordered_map<UFunction*, bool> m_lifecycle_function_cache{};
    std::unordered_map<UFunction*, bool> m_construct_function_cache{};
    struct FunctionTextParamCacheEntry
    {
        FWeakObjectPtr FunctionPtr{};
        TextParamInfo Info{};
    };
    std::unordered_map<UFunction*, FunctionTextParamCacheEntry> m_function_text_param_cache{};
    UClass* m_widget_class{};
    UClass* m_text_block_class{};
    UClass* m_rich_text_block_class{};
    UClass* m_text_render_component_class{};
    UClass* m_datatable_class{};
    int32_t m_requested_datatable_sweep_tick{-1};

    // live registry of TextBlock/RichTextBlock instances, checked every tick
    // by comparing the FText internal data pointer: native C++ SetText calls
    // never pass through any hookable path, and this corrects them within the
    // same frame for the cost of one pointer compare per widget
    struct LiveTextWidget
    {
        FWeakObjectPtr Object{};
        FTextProperty* TextProperty{};
        void* LastTextData{};
    };
    std::vector<LiveTextWidget> m_live_text_widgets{};
    // tick_live_text_widgets iterates by reference; refreshes it triggers can
    // re-enter register_live_text_widget via the SetText hook, and a push_back
    // would reallocate under the iterator (heap corruption — three crashes all
    // manifested at the next push_back's memcpy). Park additions while locked.
    std::vector<LiveTextWidget> m_deferred_registry_additions{};
    bool m_live_registry_locked{false};

    // combo boxes (incl. the game's native RichTextComboBoxString) get their
    // option arrays repopulated from C++; retranslate them every tick (they
    // are few and lookups on already-English strings are cheap)
    std::unordered_map<UClass*, bool> m_combo_class_cache{};
    std::atomic<bool> m_datatable_constructed_async{false};
    size_t m_apply_count{};
    size_t m_property_apply_count{};
    size_t m_string_property_apply_count{};
    size_t m_text_fit_count{};
    size_t m_targeted_scan_count{};
    int32_t m_tick_count{};
    int32_t m_next_runtime_text_flush_tick{180};
    bool m_hooks_installed{};
    bool m_bootstrap_scan_seeded{};
    bool m_debug_collect_runtime_text{false};
    bool m_debug_log{};

    // runtime kill switches for bisecting bad interactions (ttcpp_only / ttcpp_all)
    bool m_enable_param_translation{true};
    bool m_enable_object_sweeps{true};
    bool m_enable_registry{true};
    bool m_enable_datatable_sweep{true};
    bool m_enable_template_sweep{true};

    bool m_runtime_text_dirty{};
    size_t m_runtime_miss_log_count{};
    std::vector<PendingObjectScan> m_pending_object_scans{};
    std::vector<PendingObjectScan> m_deferred_scan_requests{};
    bool m_pending_scan_queue_locked{false};
    std::filesystem::path m_runtime_debug_dir{"ue4ss/Mods/TextTranslatorCpp"};
    // per-INSTANCE, not per-name: level transitions reload DataTables as new
    // objects with the same name, and those must be swept again
    std::vector<FWeakObjectPtr> m_translated_datatable_objects{};

    auto load_translation_table() -> void
    {
        m_translations.clear();

        const std::vector<std::filesystem::path> candidates{
                "Mods/TextTranslatorCpp/translation.csv",
                "Mods/TextTranslator/translation.csv",
                "ue4ss/Mods/TextTranslatorCpp/translation.csv",
                "ue4ss/Mods/TextTranslator/translation.csv",
        };

        std::filesystem::path selected;
        std::string bytes;
        for (const auto& candidate : candidates)
        {
            bytes = read_file_bytes(candidate);
            if (!bytes.empty())
            {
                selected = candidate;
                m_runtime_debug_dir = selected.parent_path();
                break;
            }
        }

        if (bytes.empty())
        {
            Output::send<LogLevel::Error>(STR("{} could not load translation.csv\n"), ModTag);
            return;
        }

        if (bytes.size() >= 3 && static_cast<unsigned char>(bytes[0]) == 0xEF && static_cast<unsigned char>(bytes[1]) == 0xBB &&
            static_cast<unsigned char>(bytes[2]) == 0xBF)
        {
            bytes.erase(0, 3);
        }

        size_t pos = 0;
        const auto header = parse_csv_record(bytes, pos);
        size_t source_index = std::string::npos;
        size_t translation_index = std::string::npos;
        size_t group_id_index = std::string::npos;
        size_t segment_index_index = std::string::npos;
        size_t segment_count_index = std::string::npos;
        size_t segment_prefix_index = std::string::npos;
        size_t segment_separator_index = std::string::npos;
        for (size_t i = 0; i < header.size(); ++i)
        {
            auto name = header[i];
            std::transform(name.begin(), name.end(), name.begin(), [](unsigned char ch) {
                return static_cast<char>(std::tolower(ch));
            });
            if (name == "source")
            {
                source_index = i;
            }
            else if (name == "translation")
            {
                translation_index = i;
            }
            else if (name == "group_id")
            {
                group_id_index = i;
            }
            else if (name == "segment_index")
            {
                segment_index_index = i;
            }
            else if (name == "segment_count")
            {
                segment_count_index = i;
            }
            else if (name == "segment_prefix")
            {
                segment_prefix_index = i;
            }
            else if (name == "segment_separator")
            {
                segment_separator_index = i;
            }
        }

        if (source_index == std::string::npos || translation_index == std::string::npos)
        {
            Output::send<LogLevel::Error>(STR("{} translation.csv missing source/translation columns\n"), ModTag);
            return;
        }

        struct GroupSegment
        {
            size_t Index{};
            size_t Count{};
            StringType Source{};
            StringType Translation{};
            StringType Prefix{};
            StringType Separator{};
        };

        auto parse_size = [](const std::string& value) -> size_t {
            try
            {
                return static_cast<size_t>(std::stoull(value));
            }
            catch (...)
            {
                return 0;
            }
        };

        size_t duplicate_count = 0;
        std::unordered_map<StringType, std::vector<GroupSegment>> grouped_segments;

        auto store_translation = [this, &duplicate_count](StringType source, StringType translation) {
            source = normalize(std::move(source));
            if (source.empty() || translation.empty())
            {
                return;
            }

            if (m_translations.contains(source) && m_translations[source] != translation)
            {
                ++duplicate_count;
            }
            m_translations[source] = translation;

            const auto unquoted_source = normalize(strip_japanese_wrapping_quotes(source));
            if (!unquoted_source.empty() && unquoted_source != source)
            {
                auto unquoted_translation = strip_ascii_wrapping_quotes(translation);
                if (m_translations.contains(unquoted_source) && m_translations[unquoted_source] != unquoted_translation)
                {
                    ++duplicate_count;
                }
                m_translations[unquoted_source] = std::move(unquoted_translation);
            }

            // also register the tag-stripped variant so styled/plain swaps of
            // the same label (tab active states etc.) keep matching
            if (const auto wrapped = parse_tag_wrapped(source))
            {
                auto inner_translation = translation;
                if (const auto wrapped_translation = parse_tag_wrapped(translation))
                {
                    inner_translation = wrapped_translation->Inner;
                }
                else if (translation.find(STR('<')) != StringType::npos)
                {
                    // translation has markup that is not a clean single wrapper;
                    // mapping a plain key to it would leak tags into plain text
                    inner_translation.clear();
                }
                const auto inner_source = normalize(wrapped->Inner);
                if (!inner_source.empty() && !inner_translation.empty() && !m_translations.contains(inner_source))
                {
                    m_translations[inner_source] = std::move(inner_translation);
                }
            }
        };

        while (pos < bytes.size())
        {
            auto row = parse_csv_record(bytes, pos);
            if (row.empty() || source_index >= row.size() || translation_index >= row.size())
            {
                continue;
            }

            auto source = utf8_to_string_type(row[source_index]);
            auto translation = utf8_to_string_type(row[translation_index]);
            store_translation(source, translation);

            const bool has_group_columns = group_id_index < row.size() && segment_index_index < row.size() && segment_count_index < row.size() &&
                                           segment_prefix_index < row.size() && segment_separator_index < row.size();
            if (!has_group_columns)
            {
                continue;
            }

            const auto segment_count = parse_size(row[segment_count_index]);
            const auto segment_index = parse_size(row[segment_index_index]);
            auto group_id = normalize(utf8_to_string_type(row[group_id_index]));
            auto prefix = decode_csv_meta_text(utf8_to_string_type(row[segment_prefix_index]));
            auto separator = decode_csv_meta_text(utf8_to_string_type(row[segment_separator_index]));
            if (group_id.empty() || segment_count <= 1 || segment_index >= segment_count)
            {
                // single-segment rows can still carry hidden prefix/suffix text
                // that is part of the real in-game string (e.g. "___" pauses).
                // Whitespace-only affixes normalize away and would just clobber
                // the clean entry with a padded translation, so require the
                // composed key to actually differ.
                if (!prefix.empty() || !separator.empty())
                {
                    auto composed_source = prefix + source + separator;
                    if (normalize(composed_source) != normalize(source))
                    {
                        store_translation(std::move(composed_source), prefix + translation + separator);
                    }
                }
                continue;
            }

            grouped_segments[group_id].push_back(GroupSegment{
                    segment_index,
                    segment_count,
                    std::move(source),
                    std::move(translation),
                    std::move(prefix),
                    std::move(separator),
            });
        }

        for (auto& [_, segments] : grouped_segments)
        {
            if (segments.empty())
            {
                continue;
            }
            std::sort(segments.begin(), segments.end(), [](const GroupSegment& lhs, const GroupSegment& rhs) {
                return lhs.Index < rhs.Index;
            });

            auto build_group = [&segments, &store_translation](std::optional<StringType> forced_separator) {
                StringType source;
                StringType translation;
                for (size_t i = 0; i < segments.size(); ++i)
                {
                    source += segments[i].Prefix;
                    source += segments[i].Source;
                    translation += segments[i].Prefix;
                    translation += segments[i].Translation;
                    if (i + 1 < segments.size())
                    {
                        const auto& separator = forced_separator ? *forced_separator : segments[i].Separator;
                        source += separator;
                        translation += separator;
                    }
                }
                store_translation(std::move(source), std::move(translation));
            };

            build_group(std::nullopt);
            build_group(StringType{STR("\n")});
            build_group(StringType{});
        }

        if (m_debug_log)
        {
            Output::send<LogLevel::Verbose>(STR("{} loaded {} unique translation sources ({} duplicate source keys) from {}\n"),
                                            ModTag,
                                            m_translations.size(),
                                            duplicate_count,
                                            selected.wstring());
        }

        load_extra_translation_table(selected.parent_path());
        build_format_patterns();
        if (m_debug_log)
        {
            Output::send<LogLevel::Verbose>(STR("{} compiled {} format patterns\n"), ModTag, m_format_patterns.size());
        }
    }

    // translation_extra.csv: hand-maintained source/translation pairs for
    // strings that exist only at runtime (engine/C++ UI such as the settings
    // dropdown options) and therefore never appear in the extracted assets.
    auto load_extra_translation_table(const std::filesystem::path& base_dir) -> void
    {
        auto bytes = read_file_bytes(base_dir / "translation_extra.csv");
        if (bytes.empty())
        {
            return;
        }
        if (bytes.size() >= 3 && static_cast<unsigned char>(bytes[0]) == 0xEF && static_cast<unsigned char>(bytes[1]) == 0xBB &&
            static_cast<unsigned char>(bytes[2]) == 0xBF)
        {
            bytes.erase(0, 3);
        }

        size_t pos = 0;
        const auto header = parse_csv_record(bytes, pos);
        size_t source_index = std::string::npos;
        size_t translation_index = std::string::npos;
        for (size_t i = 0; i < header.size(); ++i)
        {
            auto name = header[i];
            std::transform(name.begin(), name.end(), name.begin(), [](unsigned char ch) {
                return static_cast<char>(std::tolower(ch));
            });
            if (name == "source")
            {
                source_index = i;
            }
            else if (name == "translation")
            {
                translation_index = i;
            }
        }
        if (source_index == std::string::npos || translation_index == std::string::npos)
        {
            Output::send<LogLevel::Error>(STR("{} translation_extra.csv missing source/translation columns\n"), ModTag);
            return;
        }

        size_t loaded = 0;
        while (pos < bytes.size())
        {
            auto row = parse_csv_record(bytes, pos);
            if (row.empty() || source_index >= row.size() || translation_index >= row.size())
            {
                continue;
            }
            auto source = normalize(utf8_to_string_type(row[source_index]));
            auto translation = utf8_to_string_type(row[translation_index]);
            if (source.empty() || translation.empty())
            {
                continue;
            }
            m_translations[std::move(source)] = std::move(translation);
            ++loaded;
        }
        Output::send<LogLevel::Verbose>(STR("{} loaded {} extra translation(s) from translation_extra.csv\n"), ModTag, loaded);
    }

    struct TagWrapped
    {
        StringType Tag{};
        StringType Inner{};
    };

    // "<Pink>描画</>" -> {"<Pink>", "描画"}; only single full wrappers qualify
    static auto parse_tag_wrapped(StringViewType value) -> std::optional<TagWrapped>
    {
        if (value.size() < 5 || value.front() != STR('<') || value[1] == STR('/'))
        {
            return std::nullopt;
        }
        const auto close = value.find(STR('>'));
        if (close == StringViewType::npos || close + 4 > value.size())
        {
            return std::nullopt;
        }
        if (value.substr(value.size() - 3) != StringViewType{STR("</>")})
        {
            return std::nullopt;
        }
        auto inner = value.substr(close + 1, value.size() - 3 - (close + 1));
        if (inner.empty() || inner.find(STR('<')) != StringViewType::npos)
        {
            return std::nullopt;
        }
        return TagWrapped{StringType{value.substr(0, close + 1)}, StringType{inner}};
    }

    auto lookup(StringType source) const -> const StringType*
    {
        if (source.empty())
        {
            return nullptr;
        }

        if (const auto direct = m_translations.find(source); direct != m_translations.end())
        {
            return &direct->second;
        }

        auto cleaned = normalize(std::move(source));
        if (const auto normalized = m_translations.find(cleaned); normalized != m_translations.end())
        {
            return &normalized->second;
        }

        const auto unquoted = normalize(strip_japanese_wrapping_quotes(cleaned));
        if (!unquoted.empty() && unquoted != cleaned)
        {
            if (const auto stripped = m_translations.find(unquoted); stripped != m_translations.end())
            {
                return &stripped->second;
            }
        }

        return nullptr;
    }

    // markup-insensitive text: runtime-composed strings carry <img .../>
    // variants that do not byte-match the asset patterns (self-closing vs
    // paired close), so patterns match on markup-stripped text and the
    // translation template supplies its own markup
    static auto strip_markup(StringViewType value) -> StringType
    {
        StringType out;
        out.reserve(value.size());
        size_t i = 0;
        while (i < value.size())
        {
            if (value[i] == STR('<'))
            {
                const auto close = value.find(STR('>'), i);
                if (close == StringViewType::npos)
                {
                    out += value.substr(i);
                    break;
                }
                i = close + 1;
                continue;
            }
            out += value[i];
            ++i;
        }
        return out;
    }

    auto build_format_patterns() -> void
    {
        m_format_patterns.clear();
        for (const auto& [key, value] : m_translations)
        {
            if (key.find(STR('{')) == StringType::npos || key.find(STR('}')) == StringType::npos)
            {
                continue;
            }
            FormatPattern pattern{};
            pattern.Translation = value;
            size_t pos = 0;
            bool valid = true;
            while (pos < key.size())
            {
                const auto open = key.find(STR('{'), pos);
                if (open == StringType::npos)
                {
                    pattern.Literals.push_back(key.substr(pos));
                    pos = key.size();
                    break;
                }
                const auto close = key.find(STR('}'), open);
                if (close == StringType::npos)
                {
                    valid = false;
                    break;
                }
                pattern.Literals.push_back(key.substr(pos, open - pos));
                pattern.Tokens.push_back(key.substr(open, close - open + 1));
                pos = close + 1;
            }
            if (pos >= key.size() && pattern.Literals.size() == pattern.Tokens.size())
            {
                pattern.Literals.push_back(StringType{});
            }
            if (!valid || pattern.Tokens.empty() || pattern.Literals.size() != pattern.Tokens.size() + 1)
            {
                continue;
            }
            for (auto& literal : pattern.Literals)
            {
                literal = strip_markup(literal);
                pattern.LiteralLength += literal.size();
            }
            if (pattern.LiteralLength < 4)
            {
                continue;
            }
            m_format_patterns.push_back(std::move(pattern));
        }
        // longest literal coverage wins ties during matching
        std::sort(m_format_patterns.begin(), m_format_patterns.end(), [](const FormatPattern& lhs, const FormatPattern& rhs) {
            return lhs.LiteralLength > rhs.LiteralLength;
        });
    }

    static auto is_value_char(CharType ch) -> bool
    {
        return (ch >= STR('0') && ch <= STR('9')) || ch == STR('.') || ch == STR(',') || ch == STR('%') ||
               ch == STR('+') || ch == STR('-') || ch == STR('x') || ch == static_cast<CharType>(0x00D7) || ch == STR(' ');
    }

    // matches against the RAW string but compares literal characters while
    // skipping <markup> spans, so captures and trailing slices keep their
    // original markup (the translation template provides the literal text)
    auto match_format_pattern(const StringType& line) const -> std::optional<StringType>
    {
        const auto skip_markup = [&line](size_t at) -> size_t {
            while (at < line.size() && line[at] == STR('<'))
            {
                const auto close = line.find(STR('>'), at);
                if (close == StringType::npos)
                {
                    break;
                }
                at = close + 1;
            }
            return at;
        };
        // try to match a (markup-free) literal at raw position `at`; returns
        // the raw position after the literal, or npos
        const auto match_literal_at = [&](size_t at, const StringType& literal) -> size_t {
            for (const auto literal_char : literal)
            {
                at = skip_markup(at);
                if (at >= line.size() || line[at] != literal_char)
                {
                    return StringType::npos;
                }
                ++at;
            }
            return at;
        };

        for (const auto& pattern : m_format_patterns)
        {
            size_t pos = match_literal_at(0, pattern.Literals.front());
            if (pos == StringType::npos)
            {
                continue;
            }
            std::vector<StringType> captures;
            captures.reserve(pattern.Tokens.size());
            bool matched = true;
            for (size_t t = 0; t < pattern.Tokens.size() && matched; ++t)
            {
                const auto& next_literal = pattern.Literals[t + 1];
                if (next_literal.empty())
                {
                    if (t + 1 != pattern.Tokens.size())
                    {
                        matched = false; // adjacent placeholders are ambiguous
                        break;
                    }
                    // open-ended capture: take one value token (an optional
                    // leading sign + digits/%/separators), skipping the markup
                    // that wraps the value itself (e.g. "<Yellow>4</>"). A
                    // later +/- once digits are seen, or a markup tag that
                    // introduces non-value text, starts the appended trailing
                    // remainder (e.g. "<Green>+Gambler Trait...</>").
                    pos = skip_markup(pos);
                    const size_t value_begin = pos;
                    size_t value_end = pos;
                    bool seen_digit = false;
                    while (value_end < line.size())
                    {
                        if (line[value_end] == STR('<'))
                        {
                            // peek the text right after this markup: a value
                            // char continues the number (the value's own
                            // </><tag> wrappers); anything else is trailing
                            const size_t after_markup = skip_markup(value_end);
                            if (after_markup < line.size() && is_value_char(line[after_markup]) &&
                                !((line[after_markup] == STR('+') || line[after_markup] == STR('-')) && seen_digit))
                            {
                                value_end = after_markup;
                                continue;
                            }
                            break;
                        }
                        const auto vc = line[value_end];
                        if ((vc == STR('+') || vc == STR('-')) && seen_digit)
                        {
                            break;
                        }
                        if (!is_value_char(vc))
                        {
                            break;
                        }
                        if (vc >= STR('0') && vc <= STR('9'))
                        {
                            seen_digit = true;
                        }
                        ++value_end;
                    }
                    while (value_end > value_begin && line[value_end - 1] == STR(' '))
                    {
                        --value_end;
                    }
                    if (value_end == value_begin)
                    {
                        matched = false;
                        break;
                    }
                    // captured value is markup-stripped (template re-adds style)
                    captures.push_back(strip_markup(line.substr(value_begin, value_end - value_begin)));
                    pos = value_end;
                    break;
                }
                // scan forward for the next literal, capturing the value
                size_t scan = pos;
                size_t after = StringType::npos;
                while (scan <= line.size())
                {
                    after = match_literal_at(scan, next_literal);
                    if (after != StringType::npos)
                    {
                        break;
                    }
                    if (scan >= line.size())
                    {
                        break;
                    }
                    scan = (line[scan] == STR('<')) ? skip_markup(scan) : scan + 1;
                    if (after == StringType::npos && scan == pos)
                    {
                        ++scan;
                    }
                }
                if (after == StringType::npos)
                {
                    matched = false;
                    break;
                }
                // strip the markup wrapping the captured value (e.g. the
                // "<Yellow>35%</>" around a probability)
                captures.push_back(strip_markup(line.substr(pos, scan - pos)));
                pos = after;
            }
            if (!matched || captures.size() != pattern.Tokens.size())
            {
                continue;
            }
            bool captures_ok = true;
            for (const auto& capture : captures)
            {
                if (capture.size() > 24)
                {
                    captures_ok = false;
                    break;
                }
            }
            if (!captures_ok)
            {
                continue;
            }
            // trailing remainder appended by the game (uses counters, already
            // translated trait lines): translate if Japanese, keep otherwise
            StringType trailing;
            if (pos != line.size())
            {
                size_t rest_start = pos;
                // drop the value's own orphan close tag ("</>") that precedes
                // the appended remainder; the template already closed the value
                while (rest_start + 3 <= line.size() && line.compare(rest_start, 3, STR("</>")) == 0)
                {
                    rest_start += 3;
                }
                const StringType rest{line.substr(rest_start)};
                if (std::any_of(rest.begin(), rest.end(), [](CharType ch) { return is_jp_run_char(ch); }))
                {
                    const auto rest_translated = translate_jp_tokens(rest);
                    if (!rest_translated)
                    {
                        continue;
                    }
                    trailing = *rest_translated;
                }
                else
                {
                    trailing = rest;
                }
            }

            auto result = pattern.Translation;
            for (size_t t = 0; t < pattern.Tokens.size(); ++t)
            {
                const auto& token = pattern.Tokens[t];
                for (size_t at = result.find(token); at != StringType::npos; at = result.find(token, at + captures[t].size()))
                {
                    result.replace(at, token.size(), captures[t]);
                }
            }
            return result + trailing;
        }
        return std::nullopt;
    }

    static auto is_jp_run_char(CharType ch) -> bool
    {
        return (ch >= 0x3000 && ch <= 0x30FF) || (ch >= 0x3400 && ch <= 0x4DBF) || (ch >= 0x4E00 && ch <= 0x9FFF) ||
               (ch >= 0xF900 && ch <= 0xFAFF) || (ch >= 0xFF01 && ch <= 0xFF65);
    }

    static auto ascii_punct_for(CharType ch) -> const CharType*
    {
        switch (ch)
        {
        case 0x3000: return STR(" ");   //
        case 0xFF1A: return STR(": ");  // ：
        case 0xFF1B: return STR("; ");  // ；
        case 0x3002: return STR(". ");  // 。
        case 0x3001: return STR(", ");  // 、
        case 0xFF08: return STR(" ("); // （
        case 0xFF09: return STR(")");   // ）
        case 0xFF01: return STR("!");   // ！
        case 0xFF1F: return STR("?");   // ？
        case 0x300C: return STR("\""); // 「
        case 0x300D: return STR("\""); // 」
        case 0xFF3B: return STR("[");   // ［
        case 0xFF3D: return STR("] ");  // ］
        case 0xFF0B: return STR("+");   // ＋
        default: return nullptr;
        }
    }

    // Token fallback for runtime-composed strings ("死の期限 #1 残り3R",
    // "購入：3 <img .../>", "...破棄（残り9）"): translate each contiguous
    // Japanese run via the table, peel translatable punctuation, keep markup
    // and ASCII (numbers) as-is. Only used when full-string lookups failed.
    auto translate_jp_tokens(StringViewType value) const -> std::optional<StringType>
    {
        StringType out;
        out.reserve(value.size() + 16);
        bool changed = false;
        size_t i = 0;
        while (i < value.size())
        {
            if (value[i] == STR('<'))
            {
                const auto close = value.find(STR('>'), i);
                if (close == StringViewType::npos)
                {
                    out += value.substr(i);
                    break;
                }
                out += value.substr(i, close - i + 1);
                i = close + 1;
                continue;
            }
            if (!is_jp_run_char(value[i]))
            {
                out += value[i];
                ++i;
                continue;
            }
            size_t j = i;
            while (j < value.size() && is_jp_run_char(value[j]))
            {
                ++j;
            }
            const StringType original_run{value.substr(i, j - i)};
            i = j;
            if (const auto* direct = lookup(original_run))
            {
                out += *direct;
                changed = true;
                continue;
            }
            StringType run = original_run;
            StringType head;
            StringType tail;
            while (!run.empty() && ascii_punct_for(run.back()))
            {
                tail.insert(0, ascii_punct_for(run.back()));
                run.pop_back();
            }
            while (!run.empty() && ascii_punct_for(run.front()))
            {
                head += ascii_punct_for(run.front());
                run.erase(run.begin());
            }
            if (run.empty())
            {
                // run was pure punctuation, fully mapped to ASCII
                out += head + tail;
                changed = true;
                continue;
            }
            if (const auto* core = lookup(run))
            {
                out += head + *core + tail;
                changed = true;
            }
            else
            {
                // split on internal mapped punctuation (［アナル］刺激中 style
                // compositions) and require every piece to resolve
                StringType rebuilt = head;
                StringType piece;
                bool pieces_ok = true;
                auto flush_piece = [&]() {
                    if (piece.empty())
                    {
                        return;
                    }
                    if (const auto* piece_translation = lookup(piece))
                    {
                        rebuilt += *piece_translation;
                    }
                    else
                    {
                        pieces_ok = false;
                    }
                    piece.clear();
                };
                for (const auto run_char : run)
                {
                    if (const auto* mapped = ascii_punct_for(run_char))
                    {
                        flush_piece();
                        rebuilt += mapped;
                    }
                    else
                    {
                        piece += run_char;
                    }
                    if (!pieces_ok)
                    {
                        break;
                    }
                }
                flush_piece();
                if (!pieces_ok || rebuilt == head + run)
                {
                    // all-or-nothing: a partially translated mix would overwrite
                    // the original and prevent a later full/pattern match
                    return std::nullopt;
                }
                out += rebuilt + tail;
                changed = true;
            }
        }
        if (!changed)
        {
            return std::nullopt;
        }
        return out;
    }

    // dynamic line: longest table-key prefix (charm descriptions with appended
    // "（残り9）" style counters) + token pass on the remainder
    auto resolve_dynamic_line(const StringType& line) const -> std::optional<StringType>
    {
        // a peeled/recursed remainder may itself be a whole table entry
        // (e.g. "テスラディルド (アナル)" after the leading icon is removed)
        if (const auto* whole = lookup(line))
        {
            return *whole;
        }

        // gate on the VISIBLE text (markup stripped): an <img id="..."/> icon
        // is long but adds no visible length, so a short label must not be
        // judged a long dialogue sentence by its markup
        const StringType visible = strip_markup(line);
        const bool has_digit = std::any_of(visible.begin(), visible.end(), [](CharType ch) { return ch >= STR('0') && ch <= STR('9'); });
        const bool has_bracket = visible.find_first_of(STR("[]")) != StringType::npos ||
                                 visible.find(static_cast<CharType>(0xFF3B)) != StringType::npos ||
                                 visible.find(static_cast<CharType>(0xFF3D)) != StringType::npos;
        if (!has_digit && !has_bracket && visible.size() > 16)
        {
            // gate to runtime-composed shapes (numbers, bracketed tags, short
            // labels); long plain sentences are dialogue and stay untouched
            return std::nullopt;
        }

        if (auto pattern_result = match_format_pattern(line))
        {
            return pattern_result;
        }

        // titles like "<img .../>NAME [trait]" hide a known prefix behind a
        // leading icon; peel the markup, resolve the rest, re-attach
        size_t markup_end = 0;
        while (markup_end < line.size() && line[markup_end] == STR('<'))
        {
            const auto close = line.find(STR('>'), markup_end);
            if (close == StringType::npos)
            {
                markup_end = 0;
                break;
            }
            markup_end = close + 1;
        }
        if (markup_end > 0 && markup_end < line.size())
        {
            const StringType peeled{line.substr(0, markup_end)};
            const StringType rest{line.substr(markup_end)};
            if (auto rest_result = resolve_dynamic_line(rest))
            {
                return peeled + *rest_result;
            }
        }

        const StringType* best_value = nullptr;
        size_t best_length = 0;
        for (const auto& [key, value] : m_translations)
        {
            if (key.size() >= 8 && key.size() > best_length && line.size() > key.size() &&
                line.compare(0, key.size(), key) == 0)
            {
                best_value = &value;
                best_length = key.size();
            }
        }
        if (best_value)
        {
            const StringType remainder{line.substr(best_length)};
            if (const auto rest = translate_jp_tokens(remainder))
            {
                return *best_value + *rest;
            }
            return *best_value + remainder;
        }
        return translate_jp_tokens(line);
    }

    auto resolve_translation(const StringType& source) const -> std::optional<StringType>
    {
        if (const auto* direct = lookup(source))
        {
            return *direct;
        }

        // incoming "<SomeTag>known text</>" with only the inner text in the
        // table: translate the inner and keep the wrapper
        if (const auto wrapped = parse_tag_wrapped(normalize(source)))
        {
            if (const auto* inner = lookup(wrapped->Inner))
            {
                return wrapped->Tag + *inner + STR("</>");
            }
        }

        if (!contains_japanese(source))
        {
            return std::nullopt;
        }

        StringType output;
        StringType line;
        bool changed = false;

        auto flush_line = [&]() {
            if (line.empty())
            {
                return;
            }

            if (const auto* translated_line = lookup(line))
            {
                output += *translated_line;
                changed = true;
            }
            else if (const auto dynamic_line = resolve_dynamic_line(line))
            {
                output += *dynamic_line;
                changed = true;
            }
            else
            {
                output += line;
            }
            line.clear();
        };

        for (size_t i = 0; i < source.size(); ++i)
        {
            const auto ch = source[i];
            if (ch == STR('\r') || ch == STR('\n'))
            {
                flush_line();
                output += ch;
                if (ch == STR('\r') && i + 1 < source.size() && source[i + 1] == STR('\n'))
                {
                    output += source[++i];
                }
            }
            else
            {
                line += ch;
            }
        }
        flush_line();

        if (!changed)
        {
            return std::nullopt;
        }
        return output;
    }

    auto property_may_contain_text(FProperty* property, int32_t depth = 0) const -> bool
    {
        if (!property || depth > 6)
        {
            return false;
        }

        if (CastField<FTextProperty>(property) || CastField<FStrProperty>(property))
        {
            return true;
        }

        if (auto* array_property = CastField<FArrayProperty>(property))
        {
            return property_may_contain_text(array_property->GetInner(), depth + 1);
        }

        if (auto* struct_property = CastField<FStructProperty>(property))
        {
            auto* script_struct = struct_property->GetStruct().Get();
            if (!script_struct)
            {
                return false;
            }

            for (auto* nested_property : script_struct->ForEachPropertyInChain())
            {
                if (property_may_contain_text(nested_property, depth + 1))
                {
                    return true;
                }
            }
        }

        return false;
    }

    // FText-only variant for OBJECT property sweeps: FString properties on
    // live objects are game data, not display text (mode names, option values,
    // ids) — translating them breaks native logic such as the display-mode
    // setting. Display text on widgets is FText (TextBlock/RichTextBlock).
    auto property_may_contain_display_text(FProperty* property, int32_t depth = 0) const -> bool
    {
        if (!property || depth > 6)
        {
            return false;
        }
        if (CastField<FTextProperty>(property))
        {
            return true;
        }
        if (CastField<FStrProperty>(property))
        {
            return false;
        }
        if (auto* array_property = CastField<FArrayProperty>(property))
        {
            return property_may_contain_display_text(array_property->GetInner(), depth + 1);
        }
        if (auto* struct_property = CastField<FStructProperty>(property))
        {
            auto* script_struct = struct_property->GetStruct().Get();
            if (!script_struct)
            {
                return false;
            }
            for (auto* nested_property : script_struct->ForEachPropertyInChain())
            {
                if (property_may_contain_display_text(nested_property, depth + 1))
                {
                    return true;
                }
            }
        }
        return false;
    }

    auto get_text_bearing_object_properties(UClass* klass) -> const std::vector<FProperty*>&
    {
        static const std::vector<FProperty*> no_properties{};
        if (!klass)
        {
            return no_properties;
        }
        if (klass->HasAnyFlags(static_cast<EObjectFlags>(RF_NeedInitialization | RF_NeedLoad | RF_NeedPostLoad)))
        {
            // the class object exists but its property chain is not linked
            // yet (async load); iterating it yields garbage FProperty
            // pointers whose GetName() reads unmapped memory. Do not cache:
            // retry once the class has finished loading.
            return no_properties;
        }

        auto it = m_object_text_property_cache.find(klass);
        if (it != m_object_text_property_cache.end() && it->second.ClassPtr.Get() == static_cast<UObject*>(klass))
        {
            return it->second.Properties;
        }

        auto& entry = m_object_text_property_cache[klass];
        entry.ClassPtr = FWeakObjectPtr{static_cast<UObject*>(klass)};
        entry.Properties.clear();
        for (auto* property : klass->ForEachPropertyInChain())
        {
            if (property_may_contain_display_text(property))
            {
                entry.Properties.emplace_back(property);
            }
        }
        return entry.Properties;
    }

    auto get_text_param_info(UFunction* function) -> const TextParamInfo&
    {
        static const TextParamInfo empty{};
        if (!function)
        {
            return empty;
        }

        // cached: this runs on every ProcessEvent in the game. The weak ptr
        // serial check guards against a GC'd UFunction being reallocated at
        // the same address with a different signature.
        auto it = m_function_text_param_cache.find(function);
        if (it != m_function_text_param_cache.end() && it->second.FunctionPtr.Get() == static_cast<UObject*>(function))
        {
            return it->second.Info;
        }

        auto& entry = m_function_text_param_cache[function];
        entry.FunctionPtr = FWeakObjectPtr{static_cast<UObject*>(function)};
        entry.Info.TextBearingProperties.clear();
        for (auto* property : function->ForEachProperty())
        {
            if (!property || !property->HasAnyPropertyFlags(CPF_Parm | CPF_ReturnParm))
            {
                continue;
            }
            // FText params only. FString params are logic values (e.g. the
            // combo OnSelectionChanged payload the display-mode setting
            // compares against Japanese literals); translating them breaks
            // native code, and FString-fed UI still ends up in an FText
            // property that the registry/sweeps translate.
            if (CastField<FTextProperty>(property))
            {
                entry.Info.TextBearingProperties.emplace_back(property);
            }
        }
        return entry.Info;
    }

    auto is_target_set_text_function(UFunction* function) -> bool
    {
        if (!function)
        {
            return false;
        }

        if (const auto cached = m_set_text_function_cache.find(function); cached != m_set_text_function_cache.end())
        {
            return cached->second;
        }

        bool is_target = false;
        if (function->GetName() == STR("SetText"))
        {
            is_target = function_has_name(function, STR("/Script/UMG.TextBlock:SetText")) ||
                        function_has_name(function, STR("/Script/UMG.RichTextBlock:SetText")) ||
                        function_has_name(function, STR("/Script/UMG.MultiLineEditableText:SetText")) ||
                        function_has_name(function, STR("/Script/UMG.EditableText:SetText")) ||
                        function_has_name(function, STR("/Script/UMG.EditableTextBox:SetText"));
        }

        m_set_text_function_cache.emplace(function, is_target);
        return is_target;
    }


    auto is_widget_lifecycle_function(UFunction* function) -> bool
    {
        if (!function)
        {
            return false;
        }

        if (const auto cached = m_lifecycle_function_cache.find(function); cached != m_lifecycle_function_cache.end())
        {
            return cached->second;
        }

        const auto name = function->GetName();
        const bool is_target = name == STR("SynchronizeProperties") || name == STR("PreConstruct") || name == STR("Construct") ||
                               name == STR("OnInitialized");
        m_lifecycle_function_cache.emplace(function, is_target);
        return is_target;
    }

    auto is_one_time_construct_function(UFunction* function) -> bool
    {
        if (!function)
        {
            return false;
        }
        if (const auto cached = m_construct_function_cache.find(function); cached != m_construct_function_cache.end())
        {
            return cached->second;
        }
        const auto name = function->GetName();
        // deliberately excludes SynchronizeProperties: it can fire every frame
        const bool is_target = name == STR("PreConstruct") || name == STR("Construct") || name == STR("OnInitialized");
        m_construct_function_cache.emplace(function, is_target);
        return is_target;
    }

    auto build_property_context(StringViewType context, FProperty* property) const -> StringType
    {
        if (!m_debug_collect_runtime_text && !m_debug_log)
        {
            return {};
        }

        StringType result{context};
        if (!result.empty())
        {
            result += STR(" :: ");
        }
        result += STR("<property>");
        return result;
    }

    auto record_observed_text(StringViewType kind, StringType source, StringViewType context, const StringType* translation) -> void
    {
        if (!m_debug_collect_runtime_text)
        {
            return;
        }

        source = normalize(std::move(source));
        if (source.empty() || !contains_japanese(source))
        {
            return;
        }

        StringType key = source;
        key += STR("\x1f");
        key += kind;
        key += STR("\x1f");
        key += context;

        auto [it, inserted] = m_runtime_texts.try_emplace(
                key,
                RuntimeTextRecord{source, translation ? *translation : StringType{}, StringType{kind}, StringType{context}, 0, translation != nullptr});

        auto& record = it->second;
        ++record.Count;
        if (translation && !translation->empty())
        {
            record.Translated = true;
            record.Translation = *translation;
        }
        m_runtime_text_dirty = true;

        if (m_debug_log && inserted && !translation && m_runtime_miss_log_count < 40)
        {
            ++m_runtime_miss_log_count;
            Output::send<LogLevel::Verbose>(STR("{} untranslated runtime text [{}] '{}' at {}\n"), ModTag, kind, source, context);
        }
    }

    auto write_runtime_texts(bool announce) -> void
    {
        const auto all_path = m_runtime_debug_dir / "runtime_text.csv";
        const auto missing_path = m_runtime_debug_dir / "missing_text.csv";

        try
        {
            std::filesystem::create_directories(all_path.parent_path());
        }
        catch (const std::exception& e)
        {
            Output::send<LogLevel::Warning>(STR("{} could not create runtime debug directory: {}\n"), ModTag, utf8_to_string_type(e.what()));
            return;
        }

        std::vector<const RuntimeTextRecord*> records;
        records.reserve(m_runtime_texts.size());
        for (const auto& [_, record] : m_runtime_texts)
        {
            records.emplace_back(&record);
        }
        std::sort(records.begin(), records.end(), [](const RuntimeTextRecord* lhs, const RuntimeTextRecord* rhs) {
            if (lhs->Translated != rhs->Translated)
            {
                return !lhs->Translated;
            }
            if (lhs->Source != rhs->Source)
            {
                return lhs->Source < rhs->Source;
            }
            return lhs->Context < rhs->Context;
        });

        auto write_header = [](std::ofstream& file) {
            file << "\xEF\xBB\xBFsource,translation,status,kind,context,count\n";
        };
        auto write_record = [](std::ofstream& file, const RuntimeTextRecord& record) {
            file << csv_escape(string_type_to_utf8(record.Source)) << ','
                 << csv_escape(string_type_to_utf8(record.Translation)) << ','
                 << (record.Translated ? "translated" : "missing") << ','
                 << csv_escape(string_type_to_utf8(record.Kind)) << ','
                 << csv_escape(string_type_to_utf8(record.Context)) << ','
                 << record.Count << '\n';
        };

        std::ofstream all_file{all_path, std::ios::binary};
        std::ofstream missing_file{missing_path, std::ios::binary};
        if (!all_file || !missing_file)
        {
            Output::send<LogLevel::Warning>(STR("{} could not open runtime debug CSV files for writing\n"), ModTag);
            return;
        }

        write_header(all_file);
        write_header(missing_file);
        size_t missing_count = 0;
        for (const auto* record : records)
        {
            write_record(all_file, *record);
            if (!record->Translated)
            {
                write_record(missing_file, *record);
                ++missing_count;
            }
        }

        m_runtime_text_dirty = false;
        if (announce)
        {
            Output::send<LogLevel::Verbose>(
                    STR("{} wrote runtime text debug: {} records ({} missing) to {} and {}\n"),
                    ModTag,
                    records.size(),
                    missing_count,
                    all_path.wstring(),
                    missing_path.wstring());
        }
    }

    auto flush_runtime_texts_if_due() -> void
    {
        if (!m_debug_collect_runtime_text || !m_runtime_text_dirty || m_tick_count < m_next_runtime_text_flush_tick)
        {
            return;
        }

        write_runtime_texts(false);
        m_next_runtime_text_flush_tick = m_tick_count + 180;
    }

    auto translate_text_in_container(void* container, FTextProperty* property, StringViewType context = STR("")) -> bool
    {
        if (!container || !property)
        {
            return false;
        }

        auto* value = reinterpret_cast<FText*>(property->ContainerPtrToValuePtr<void>(container));
        return translate_text_value(value, context);
    }

    auto translate_text_value(FText* value, StringViewType context = STR("")) -> bool
    {
        if (!value)
        {
            return false;
        }

        const auto source = value->ToString();
        const auto translation = resolve_translation(source);
        record_observed_text(STR("FText"), source, context, translation ? &*translation : nullptr);
        if (!translation || *translation == source)
        {
            // identity entries must not count as replacements: a "replaced"
            // text triggers a refresh ProcessEvent, whose hooks would replace
            // it again, recursing forever
            return false;
        }

        *value = FText(translation->c_str());
        return true;
    }

    auto translate_string_in_container(void* container, FStrProperty* property, StringViewType context = STR("")) -> bool
    {
        if (!container || !property)
        {
            return false;
        }

        auto* value = reinterpret_cast<FString*>(property->ContainerPtrToValuePtr<void>(container));
        return translate_string_value(value, context);
    }

    auto translate_string_value(FString* value, StringViewType context = STR("")) -> bool
    {
        if (!value)
        {
            return false;
        }

        const StringType source{**value};
        const auto translation = resolve_translation(source);
        record_observed_text(STR("FString"), source, context, translation ? &*translation : nullptr);
        if (!translation || *translation == source)
        {
            return false;
        }

        *value = FString(translation->c_str());
        return true;
    }

    auto translate_property_value(void* container, FProperty* property, int32_t depth = 0, SweepStats* stats = nullptr, StringViewType context = STR(""))
            -> size_t
    {
        if (!container || !property || depth > 6)
        {
            return 0;
        }

        size_t replacements = 0;
        const auto property_context = build_property_context(context, property);
        const auto array_dim = std::max<int32_t>(1, property->GetArrayDim());
        for (int32_t array_index = 0; array_index < array_dim; ++array_index)
        {
            if (auto* text_property = CastField<FTextProperty>(property))
            {
                if (stats)
                {
                    ++stats->TextPropertiesVisited;
                }
                auto* value = reinterpret_cast<FText*>(text_property->ContainerPtrToValuePtr<void>(container, array_index));
                if (translate_text_value(value, property_context))
                {
                    ++replacements;
                }
            }
            else if (auto* string_property = CastField<FStrProperty>(property))
            {
                if (stats)
                {
                    ++stats->StringPropertiesVisited;
                }
                auto* value = reinterpret_cast<FString*>(string_property->ContainerPtrToValuePtr<void>(container, array_index));
                if (translate_string_value(value, property_context))
                {
                    ++replacements;
                    ++m_string_property_apply_count;
                }
            }
            else if (auto* array_property = CastField<FArrayProperty>(property))
            {
                auto* inner_property = array_property->GetInner();
                if (!property_may_contain_text(inner_property, depth + 1))
                {
                    continue;
                }

                auto* array_value = array_property->ContainerPtrToValuePtr<void>(container, array_index);
                if (!array_value)
                {
                    continue;
                }

                FScriptArrayHelper helper{array_property, array_value};
                const auto count = helper.Num();
                for (int32_t element_index = 0; element_index < count; ++element_index)
                {
                    auto* element = helper.GetRawPtr(element_index);
                    if (!element)
                    {
                        continue;
                    }
                    replacements += translate_property_value(element, inner_property, depth + 1, stats, property_context);
                }
            }
            else if (auto* struct_property = CastField<FStructProperty>(property))
            {
                auto* script_struct = struct_property->GetStruct().Get();
                if (!script_struct)
                {
                    continue;
                }

                auto* struct_value = struct_property->ContainerPtrToValuePtr<void>(container, array_index);
                if (!struct_value)
                {
                    continue;
                }

                for (auto* nested_property : script_struct->ForEachPropertyInChain())
                {
                    if (!property_may_contain_text(nested_property, depth + 1))
                    {
                        continue;
                    }
                    replacements += translate_property_value(struct_value, nested_property, depth + 1, stats, property_context);
                }
            }
        }

        return replacements;
    }

    auto translate_function_text_params(UFunction* function, void* params, bool include_return_values) -> size_t
    {
        if (!params || !function)
        {
            return 0;
        }
        if (g_text_translation_active || !IsInGameThreadRaw())
        {
            return 0;
        }

        TranslationScope scope;
        if (!scope.Entered)
        {
            return 0;
        }

        const auto& info = get_text_param_info(function);
        if (info.TextBearingProperties.empty())
        {
            return 0;
        }

        // building the full name is expensive; it is only consumed by the
        // debug/runtime-text recording paths
        StringType function_context;
        if (m_debug_log || m_debug_collect_runtime_text)
        {
            function_context = function->GetFullName();
        }
        size_t replacements = 0;
        for (auto* property : info.TextBearingProperties)
        {
            if (!include_return_values && property->HasAnyPropertyFlags(CPF_ReturnParm))
            {
                continue;
            }
            replacements += translate_property_value(params, property, 0, nullptr, function_context);
        }

        if (replacements > 0)
        {
            m_apply_count += replacements;
            if (m_debug_log && m_apply_count <= 60)
            {
                Output::send<LogLevel::Verbose>(
                        STR("{} ProcessEvent text param applied {} replacement(s) on {}\n"),
                        ModTag,
                        replacements,
                        function->GetFullName());
            }
        }

        return replacements;
    }

    auto translate_function_text_params_for_context(UObject* context, UFunction* function, void* params, bool include_return_values) -> size_t
    {
        struct ActiveEventContextScope
        {
            std::optional<StringType>& Target;
            std::optional<StringType> Previous;

            ActiveEventContextScope(std::optional<StringType>& target, UObject* context)
                : Target(target), Previous(std::move(target))
            {
                if (context)
                {
                    Target = context->GetFullName();
                }
                else
                {
                    Target.reset();
                }
            }

            ~ActiveEventContextScope()
            {
                Target = std::move(Previous);
            }
        };

        if (!m_enable_param_translation || !params || !function || g_text_translation_active || !IsInGameThreadRaw())
        {
            return 0;
        }
        if (get_text_param_info(function).TextBearingProperties.empty())
        {
            // hot path: almost every ProcessEvent lands here; the context
            // scope below builds GetFullName(), so skip it entirely
            return 0;
        }
        return translate_function_text_params(function, params, include_return_values);
    }

    auto translate_text_property(UObject* object, FTextProperty* property) -> bool
    {
        return translate_text_in_container(object, property, object ? object->GetFullName() : StringType{});
    }

    auto translate_string_property(UObject* object, FStrProperty* property) -> bool
    {
        return translate_string_in_container(object, property, object ? object->GetFullName() : StringType{});
    }

    auto is_umg_widget(UObject* object) const -> bool
    {
        return object && m_widget_class && object->IsA(m_widget_class);
    }

    auto is_text_block_widget(UObject* object) const -> bool
    {
        if (!object)
        {
            return false;
        }
        if (m_text_block_class && object->IsA(m_text_block_class))
        {
            return true;
        }
        if (m_rich_text_block_class && object->IsA(m_rich_text_block_class))
        {
            return true;
        }
        return starts_with(object->GetFullName(), STR("TextBlock "));
    }

    auto is_text_render_component(UObject* object) const -> bool
    {
        return object && m_text_render_component_class && object->IsA(m_text_render_component_class);
    }

    auto should_scan_object_properties(UObject* object) const -> bool
    {
        if (!object || object->HasAnyFlags(RF_ClassDefaultObject))
        {
            return false;
        }
        return is_umg_widget(object) || is_text_render_component(object);
    }

    auto get_text_property_value(UObject* object, StringViewType property_name) const -> FText*
    {
        if (!object)
        {
            return nullptr;
        }

        auto* klass = object->GetClassPrivate();
        if (!klass)
        {
            return nullptr;
        }

        for (auto* property : klass->ForEachPropertyInChain())
        {
            auto* text_property = CastField<FTextProperty>(property);
            if (!text_property || text_property->GetName() != property_name)
            {
                continue;
            }
            return reinterpret_cast<FText*>(text_property->ContainerPtrToValuePtr<void>(object));
        }

        return nullptr;
    }

    auto get_struct_property_value(UObject* object, StringViewType property_name) const -> void*
    {
        if (!object)
        {
            return nullptr;
        }

        auto* klass = object->GetClassPrivate();
        if (!klass)
        {
            return nullptr;
        }

        for (auto* property : klass->ForEachPropertyInChain())
        {
            auto* struct_property = CastField<FStructProperty>(property);
            if (!struct_property || struct_property->GetName() != property_name)
            {
                continue;
            }
            return struct_property->ContainerPtrToValuePtr<void>(object);
        }

        return nullptr;
    }

    auto should_fit_text_block(UObject* object, StringViewType text) const -> bool
    {
        if (!is_text_block_widget(object) || text.empty() || contains_japanese(text))
        {
            return false;
        }
        if (text.find(STR('\n')) != StringViewType::npos || text.find(STR('\r')) != StringViewType::npos)
        {
            return false;
        }

        // per-game exemption list: widgets that wrap long lines themselves,
        // where shrinking would make the text unreadably small
        static constexpr StringViewType no_fit_widgets[] = {STR("WBP_DialogueUI")};
        const auto full_name = object->GetFullName();
        bool exempt = false;
        for (const auto needle : no_fit_widgets)
        {
            if (full_name.find(needle) != StringType::npos)
            {
                exempt = true;
                break;
            }
        }
        if (exempt)
        {
            return false;
        }

        size_t visible_count = 0;
        size_t word_count = 0;
        size_t max_word_count = 0;
        for (const auto ch : text)
        {
            if (ch == STR('"') || ch == STR('\'') || ch == STR('\u201c') || ch == STR('\u201d'))
            {
                continue;
            }
            if (ch == STR(' ') || ch == STR('\t') || ch == STR('/') || ch == STR('-'))
            {
                max_word_count = std::max(max_word_count, word_count);
                word_count = 0;
                continue;
            }
            ++visible_count;
            ++word_count;
        }
        max_word_count = std::max(max_word_count, word_count);

        return visible_count > 10 || max_word_count > 9;
    }

    auto text_fit_ratio(StringViewType text) const -> float
    {
        size_t visible_count = 0;
        size_t word_count = 0;
        size_t max_word_count = 0;
        for (const auto ch : text)
        {
            if (ch == STR('"') || ch == STR('\'') || ch == STR('\u201c') || ch == STR('\u201d'))
            {
                continue;
            }
            if (ch == STR(' ') || ch == STR('\t') || ch == STR('/') || ch == STR('-'))
            {
                max_word_count = std::max(max_word_count, word_count);
                word_count = 0;
                continue;
            }
            ++visible_count;
            ++word_count;
        }
        max_word_count = std::max(max_word_count, word_count);

        float ratio = 1.0f;
        if (visible_count > 28)
        {
            ratio = 0.72f;
        }
        else if (visible_count > 22)
        {
            ratio = 0.78f;
        }
        else if (visible_count > 17)
        {
            ratio = 0.84f;
        }
        else if (visible_count > 13)
        {
            ratio = 0.90f;
        }
        else if (visible_count > 10)
        {
            ratio = 0.95f;
        }

        if (max_word_count > 14)
        {
            ratio = std::min(ratio, static_cast<float>(14.0 / static_cast<double>(max_word_count)));
        }
        return std::clamp(ratio, 0.68f, 1.0f);
    }

    auto fit_text_block(UObject* object) -> bool
    {
        auto* text_value = get_text_property_value(object, STR("Text"));
        if (!text_value)
        {
            return false;
        }

        const auto text = text_value->ToString();
        if (!should_fit_text_block(object, text))
        {
            return false;
        }

        auto* font_memory = get_struct_property_value(object, STR("Font"));
        if (!font_memory)
        {
            return false;
        }

        constexpr size_t FontSizeOffset = 0x48;
        auto* font_size = reinterpret_cast<float*>(reinterpret_cast<std::byte*>(font_memory) + FontSizeOffset);
        if (!font_size || *font_size <= 4.0f || *font_size > 120.0f)
        {
            return false;
        }

        const auto object_name = object->GetFullName();
        auto [base_it, inserted] = m_text_fit_base_font_sizes.try_emplace(object_name, *font_size);
        if (!inserted && *font_size > base_it->second)
        {
            base_it->second = *font_size;
        }

        const auto base_size = base_it->second;
        const auto ratio = text_fit_ratio(text);
        const auto minimum_size = std::min(base_size, 11.0f);
        const auto target_size = std::max(minimum_size, static_cast<float>(static_cast<int32_t>((base_size * ratio) + 0.5f)));
        if (target_size >= *font_size - 0.1f && target_size <= *font_size + 0.1f)
        {
            return false;
        }

        *font_size = target_size;
        if (auto* set_font = object->GetFunctionByNameInChain(STR("SetFont")))
        {
            object->ProcessEvent(set_font, font_memory);
        }

        ++m_text_fit_count;
        if (m_debug_log && m_text_fit_count <= 40)
        {
            Output::send<LogLevel::Verbose>(
                    STR("{} text fit applied size {} -> {} on {}: \"{}\"\n"), ModTag, base_size, target_size, object_name, text);
        }
        return true;
    }

    auto refresh_changed_text_object(UObject* object) -> bool
    {
        // refresh fires ProcessEvent (SetText/SynchronizeProperties), whose
        // hooks can refresh again; cap the mutual recursion depth
        if (!object || g_text_refresh_depth >= 2)
        {
            return false;
        }
        ++g_text_refresh_depth;
        struct RefreshDepthGuard
        {
            ~RefreshDepthGuard()
            {
                --g_text_refresh_depth;
            }
        } refresh_depth_guard;

        bool refreshed = false;
        auto* set_text = object->GetFunctionByNameInChain(STR("SetText"));
        if (!set_text)
        {
            set_text = object->GetFunctionByNameInChain(STR("K2_SetText"));
        }
        if (set_text)
        {
            auto* klass = object->GetClassPrivate();
            if (klass)
            {
                FText* fallback_value = nullptr;
                for (auto* property : klass->ForEachPropertyInChain())
                {
                    auto* text_property = CastField<FTextProperty>(property);
                    if (!text_property)
                    {
                        continue;
                    }

                    auto* value = reinterpret_cast<FText*>(text_property->ContainerPtrToValuePtr<void>(object));
                    if (!value)
                    {
                        continue;
                    }

                    if (text_property->GetName() == STR("Text"))
                    {
                        object->ProcessEvent(set_text, value);
                        fit_text_block(object);
                        return true;
                    }
                    if (!fallback_value)
                    {
                        fallback_value = value;
                    }
                }

                if (fallback_value)
                {
                    object->ProcessEvent(set_text, fallback_value);
                    fit_text_block(object);
                    return true;
                }
            }
        }

        if (synchronize_widget(object))
        {
            return true;
        }
        return refreshed;
    }

    auto translate_object_text_properties(UObject* object) -> size_t
    {
        if (!m_enable_object_sweeps || !should_scan_object_properties(object))
        {
            return 0;
        }
        if (g_text_translation_active || !IsInGameThreadRaw())
        {
            return 0;
        }

        TranslationScope scope;
        if (!scope.Entered)
        {
            return 0;
        }

        auto* klass = object->GetClassPrivate();
        if (!klass)
        {
            return 0;
        }

        size_t replacements = 0;
        const auto object_context = object->GetFullName();
        for (auto* property : get_text_bearing_object_properties(klass))
        {
            replacements += translate_property_value(object, property, 0, nullptr, object_context);
        }

        m_property_apply_count += replacements;
        if (m_debug_log && replacements > 0 && m_property_apply_count <= 30)
        {
            Output::send<LogLevel::Verbose>(STR("{} object property hook applied {} replacement(s) on {}\n"), ModTag, replacements, object->GetFullName());
        }

        return replacements;
    }

    auto is_combo_box_widget(UObject* object) -> bool
    {
        if (!object)
        {
            return false;
        }
        auto* klass = object->GetClassPrivate();
        if (!klass)
        {
            return false;
        }
        if (const auto cached = m_combo_class_cache.find(klass); cached != m_combo_class_cache.end())
        {
            return cached->second;
        }
        bool is_combo = false;
        for (auto* current = static_cast<UStruct*>(klass); current; current = current->GetSuperStruct())
        {
            if (current->GetName().find(STR("ComboBox")) != StringType::npos)
            {
                is_combo = true;
                break;
            }
        }
        m_combo_class_cache.emplace(klass, is_combo);
        return is_combo;
    }

    // SEH shield: four crashes came through reflection walks in registration
    // hitting garbage properties of mid-load classes despite flag guards. A
    // skipped registration is recoverable (SetText hook / sweep retry later);
    // a crash is not. No destructible locals allowed in this function.
    auto register_live_text_widget_guarded(UObject* object) -> void
    {
        __try
        {
            register_live_text_widget(object);
        }
        __except (1 /* EXCEPTION_EXECUTE_HANDLER */)
        {
        }
    }

    auto register_live_text_widget(UObject* object) -> void
    {
        if (!object || object->HasAnyFlags(static_cast<EObjectFlags>(
                               RF_ClassDefaultObject | RF_ArchetypeObject | RF_NeedInitialization | RF_NeedLoad | RF_NeedPostLoad)))
        {
            return;
        }
        // class-only check here: this runs in the construct callback where the
        // object may not be fully initialized, so no GetFullName fallback.
        // TextRenderComponents (world-space text, e.g. cutscene skip prompts)
        // carry the same FText 'Text' property and are watched identically.
        const bool is_text_class = (m_text_block_class && object->IsA(m_text_block_class)) ||
                                   (m_rich_text_block_class && object->IsA(m_rich_text_block_class)) ||
                                   (m_text_render_component_class && object->IsA(m_text_render_component_class));
        if (!is_text_class)
        {
            return;
        }
        auto* klass = object->GetClassPrivate();
        if (!klass)
        {
            return;
        }
        FTextProperty* text_property = nullptr;
        static const FName text_name{STR("Text")};
        for (auto* property : get_text_bearing_object_properties(klass))
        {
            // FName comparison only: integers, no name-pool dereference (a
            // garbage property's GetName() string build is what crashed)
            if (auto* as_text = CastField<FTextProperty>(property); as_text && property->GetFName() == text_name)
            {
                text_property = as_text;
                break;
            }
        }
        if (!text_property)
        {
            return;
        }
        for (const auto& entry : m_live_text_widgets)
        {
            if (entry.Object.Get() == object)
            {
                return;
            }
        }
        if (m_live_registry_locked)
        {
            for (const auto& entry : m_deferred_registry_additions)
            {
                if (entry.Object.Get() == object)
                {
                    return;
                }
            }
            m_deferred_registry_additions.push_back(LiveTextWidget{FWeakObjectPtr{object}, text_property, nullptr});
            return;
        }
        // LastTextData deliberately null so the first tick examines it once
        m_live_text_widgets.push_back(LiveTextWidget{FWeakObjectPtr{object}, text_property, nullptr});
    }

    auto tick_live_text_widgets() -> void
    {
        if (!m_enable_registry || m_live_text_widgets.empty() || m_translations.empty() || g_text_translation_active ||
            !IsInGameThreadRaw())
        {
            return;
        }

        {
            struct RegistryLockGuard
            {
                bool& Locked;
                explicit RegistryLockGuard(bool& locked) : Locked(locked)
                {
                    Locked = true;
                }
                ~RegistryLockGuard()
                {
                    Locked = false;
                }
            } registry_lock_guard{m_live_registry_locked};

            for (auto& entry : m_live_text_widgets)
            {
                auto* object = entry.Object.Get();
                if (!object || !entry.TextProperty)
                {
                    continue;
                }
                auto* value = entry.TextProperty->ContainerPtrToValuePtr<FText>(object);
                if (!value)
                {
                    continue;
                }
                void* current_data = *reinterpret_cast<void* const*>(value);
                if (current_data == entry.LastTextData)
                {
                    // pointer unchanged, but native code can re-set the same
                    // FText buffer in place (cutscene prompt replays); if the
                    // visible text is still Japanese, translate it anyway
                    if (!contains_japanese(value->ToString()))
                    {
                        continue;
                    }
                }
                // text changed (or still untranslated): translate if it needs it
                process_text_object(object);
                value = entry.TextProperty->ContainerPtrToValuePtr<FText>(object);
                entry.LastTextData = value ? *reinterpret_cast<void* const*>(value) : nullptr;
            }
        }

        if (!m_deferred_registry_additions.empty())
        {
            for (auto& addition : m_deferred_registry_additions)
            {
                bool already_known = false;
                for (const auto& entry : m_live_text_widgets)
                {
                    if (entry.Object.Get() == addition.Object.Get())
                    {
                        already_known = true;
                        break;
                    }
                }
                if (!already_known)
                {
                    m_live_text_widgets.push_back(std::move(addition));
                }
            }
            m_deferred_registry_additions.clear();
        }

        if (m_tick_count % 600 == 0)
        {
            std::erase_if(m_live_text_widgets, [](const LiveTextWidget& entry) {
                return entry.Object.Get() == nullptr;
            });
        }
    }

    auto process_text_object(UObject* object) -> bool
    {
        if (!should_scan_object_properties(object))
        {
            return false;
        }

        if (translate_object_text_properties(object) > 0)
        {
            refresh_changed_text_object(object);
            return true;
        }
        return false;
    }

    auto process_targeted_object_scan(UObject* object) -> size_t
    {
        if (!object || g_text_translation_active || !IsInGameThreadRaw())
        {
            return 0;
        }

        size_t replacements = 0;
        if (process_text_object(object))
        {
            ++replacements;
        }

        auto* klass = object->GetClassPrivate();
        if (!klass)
        {
            return replacements;
        }

        std::vector<UObject*> visited_children{};
        visited_children.reserve(32);
        for (auto* property : klass->ForEachPropertyInChain())
        {
            auto* object_property = CastField<FObjectPropertyBase>(property);
            if (!object_property)
            {
                continue;
            }

            auto* value = object_property->ContainerPtrToValuePtr<void>(object);
            auto* child = object_property->GetObjectPropertyValue(value);
            if (!child || child == object || !should_scan_object_properties(child))
            {
                continue;
            }
            if (std::find(visited_children.begin(), visited_children.end(), child) != visited_children.end())
            {
                continue;
            }

            visited_children.emplace_back(child);
            if (process_text_object(child))
            {
                ++replacements;
            }
            if (visited_children.size() >= 48)
            {
                break;
            }
        }

        return replacements;
    }

    auto get_object_lookup_path(StringType full_name) const -> StringType
    {
        if (full_name.empty())
        {
            return {};
        }

        const auto class_separator = full_name.find(STR(' '));
        if (class_separator != StringType::npos && class_separator + 1 < full_name.size())
        {
            full_name.erase(0, class_separator + 1);
        }
        return full_name;
    }

    auto safe_static_find_object(const StringType& object_name) const -> UObject*
    {
        if (object_name.empty() || object_name.find(STR('/')) == StringType::npos)
        {
            return nullptr;
        }

        try
        {
            return UObjectGlobals::StaticFindObject<UObject*>(nullptr, nullptr, object_name.c_str());
        }
        catch (const std::exception& e)
        {
            if (m_debug_log)
            {
                Output::send<LogLevel::Error>(
                        STR("{} object lookup failed for '{}': {}\n"), ModTag, object_name, utf8_to_string_type(e.what()));
            }
        }
        catch (...)
        {
            if (m_debug_log)
            {
                Output::send<LogLevel::Error>(STR("{} object lookup failed for '{}'\n"), ModTag, object_name);
            }
        }

        return nullptr;
    }

    auto resolve_queued_object(const PendingObjectScan& pending) const -> UObject*
    {
        if (!pending.ObjectPath.empty())
        {
            if (auto* object = safe_static_find_object(pending.ObjectPath))
            {
                return object;
            }
        }

        if (!pending.ObjectFullName.empty())
        {
            return safe_static_find_object(pending.ObjectFullName);
        }

        return nullptr;
    }

    auto request_targeted_scan(UObject* object, int32_t minimum_delay_frames = 1, int32_t attempts = 6) -> void
    {
        if (!object || g_text_translation_active)
        {
            return;
        }

        const auto object_full_name = object->GetFullName();
        const auto object_path = get_object_lookup_path(object_full_name);
        if (object_full_name.empty() && object_path.empty())
        {
            return;
        }

        const auto next_tick = m_tick_count + std::max<int32_t>(minimum_delay_frames, 1);
        attempts = std::clamp<int32_t>(attempts, 1, 8);
        for (auto& pending : m_pending_object_scans)
        {
            if (pending.ObjectFullName == object_full_name)
            {
                pending.NextTick = std::min(pending.NextTick, next_tick);
                pending.Attempts = std::max(pending.Attempts, attempts);
                return;
            }
        }

        if (m_pending_scan_queue_locked)
        {
            // run_pending_object_scans is iterating m_pending_object_scans and
            // holds references into it; a push_back/erase here (reached
            // re-entrantly via ProcessEvent hooks during a scan refresh) would
            // invalidate them. Park new requests and merge after the loop.
            for (auto& deferred : m_deferred_scan_requests)
            {
                if (deferred.ObjectFullName == object_full_name)
                {
                    deferred.NextTick = std::min(deferred.NextTick, next_tick);
                    deferred.Attempts = std::max(deferred.Attempts, attempts);
                    return;
                }
            }
            m_deferred_scan_requests.push_back(PendingObjectScan{object_full_name, object_path, next_tick, attempts});
            return;
        }

        if (m_pending_object_scans.size() >= 4096)
        {
            m_pending_object_scans.erase(m_pending_object_scans.begin());
        }
        m_pending_object_scans.push_back(PendingObjectScan{object_full_name, object_path, next_tick, attempts});
    }

    auto seed_existing_widgets_for_targeted_scan() -> void
    {
        if (m_bootstrap_scan_seeded || m_tick_count < 30 || g_text_translation_active || !IsInGameThreadRaw())
        {
            return;
        }

        m_bootstrap_scan_seeded = true;
        size_t queued = 0;
        UObjectGlobals::ForEachUObject([this, &queued](UObject* object, int32, int32) {
            if (should_scan_object_properties(object))
            {
                const auto delay = 1 + static_cast<int32_t>(queued / 12);
                request_targeted_scan(object, delay, 1);
                ++queued;
            }
            return LoopAction::Continue;
        });

        if (m_debug_log)
        {
            Output::send<LogLevel::Verbose>(STR("{} queued {} existing text widgets for targeted bootstrap scan\n"), ModTag, queued);
        }
    }

    auto run_pending_object_scans() -> void
    {
        if (m_pending_object_scans.empty() || g_text_translation_active || !IsInGameThreadRaw())
        {
            return;
        }

        size_t processed = 0;
        size_t refreshed = 0;
        struct QueueLockGuard
        {
            bool& Locked;
            explicit QueueLockGuard(bool& locked) : Locked(locked)
            {
                Locked = true;
            }
            ~QueueLockGuard()
            {
                Locked = false;
            }
        } queue_lock_guard{m_pending_scan_queue_locked};
        for (size_t index = 0; index < m_pending_object_scans.size() && processed < 12;)
        {
            auto& pending = m_pending_object_scans[index];
            if (pending.NextTick > m_tick_count)
            {
                ++index;
                continue;
            }

            if (auto* object = resolve_queued_object(pending))
            {
                try
                {
                    refreshed += process_targeted_object_scan(object);
                }
                catch (const std::exception& e)
                {
                    Output::send<LogLevel::Error>(
                            STR("{} targeted scan error for {}: {}\n"), ModTag, pending.ObjectFullName, utf8_to_string_type(e.what()));
                    pending.Attempts = 1;
                }
                catch (...)
                {
                    Output::send<LogLevel::Error>(STR("{} targeted scan unknown error for {}\n"), ModTag, pending.ObjectFullName);
                    pending.Attempts = 1;
                }
            }
            else
            {
                pending.Attempts = 1;
            }
            ++processed;
            --pending.Attempts;
            if (pending.Attempts <= 0)
            {
                m_pending_object_scans.erase(m_pending_object_scans.begin() + static_cast<std::ptrdiff_t>(index));
            }
            else
            {
                pending.NextTick = m_tick_count + 12;
                ++index;
            }
        }

        if (!m_deferred_scan_requests.empty())
        {
            for (auto& request : m_deferred_scan_requests)
            {
                bool merged = false;
                for (auto& pending : m_pending_object_scans)
                {
                    if (pending.ObjectFullName == request.ObjectFullName)
                    {
                        pending.NextTick = std::min(pending.NextTick, request.NextTick);
                        pending.Attempts = std::max(pending.Attempts, request.Attempts);
                        merged = true;
                        break;
                    }
                }
                if (!merged)
                {
                    if (m_pending_object_scans.size() >= 4096)
                    {
                        m_pending_object_scans.erase(m_pending_object_scans.begin());
                    }
                    m_pending_object_scans.push_back(std::move(request));
                }
            }
            m_deferred_scan_requests.clear();
        }

        if (m_debug_log && refreshed > 0)
        {
            ++m_targeted_scan_count;
            Output::send<LogLevel::Verbose>(
                    STR("{} targeted scan #{} processed={} refreshes={} pending={}\n"),
                    ModTag,
                    m_targeted_scan_count,
                    processed,
                    refreshed,
                    m_pending_object_scans.size());
        }
    }

    auto synchronize_widget(UObject* object) -> bool
    {
        if (!object)
        {
            return false;
        }

        auto* function = object->GetFunctionByNameInChain(STR("SynchronizeProperties"));
        if (!function)
        {
            return false;
        }

        object->ProcessEvent(function, nullptr);
        return true;
    }

    // Translate FText/FString fields inside UDataTable rows in memory. Dialogue
    // and typewriter-card text is read straight out of DT_* row structs by the
    // typewriter widgets, so translating the rows once at load means the
    // animation types English from the first frame instead of swapping after.
    auto sweep_datatable_rows() -> size_t
    {
        if (!m_enable_datatable_sweep || g_text_translation_active || !IsInGameThreadRaw() || m_translations.empty())
        {
            return 0;
        }

        TranslationScope scope;
        if (!scope.Entered)
        {
            return 0;
        }

        std::vector<UObject*> tables;
        UObjectGlobals::FindAllOf(STR("DataTable"), tables);

        size_t total_replacements = 0;
        for (auto* object : tables)
        {
            if (!object)
            {
                continue;
            }
            bool already_translated = false;
            for (const auto& seen : m_translated_datatable_objects)
            {
                if (seen.Get() == object)
                {
                    already_translated = true;
                    break;
                }
            }
            if (already_translated)
            {
                continue;
            }

            if (object->HasAnyFlags(static_cast<EObjectFlags>(RF_NeedInitialization | RF_NeedLoad | RF_NeedPostLoad)))
            {
                // still loading; the loader may be populating the RowMap
                continue;
            }

            auto* table = static_cast<UDataTable*>(object);
            auto* row_struct = table->GetRowStruct().Get();
            const auto& row_map = table->GetRowMap();
            if (!row_struct || row_map.Num() == 0)
            {
                // not serialized yet; retry on a later sweep
                continue;
            }
            const auto full_name = object->GetFullName();

            size_t replacements = 0;
            for (auto& pair : row_map)
            {
                auto* row_data = pair.Value;
                if (!row_data)
                {
                    continue;
                }
                for (auto* property : row_struct->ForEachPropertyInChain())
                {
                    replacements += translate_property_value(row_data, property, 0, nullptr, full_name);
                }
            }

            m_translated_datatable_objects.push_back(FWeakObjectPtr{object});
            total_replacements += replacements;
            if (m_debug_log && replacements > 0)
            {
                Output::send<LogLevel::Verbose>(
                        STR("{} datatable sweep translated {} field(s) in {}\n"), ModTag, replacements, full_name);
            }
        }
        return total_replacements;
    }

    // Translate widget TEMPLATES (CDOs / archetypes inside WidgetTrees).
    // Recreated menus instance their tree via StaticDuplicateObject, which
    // bypasses both ProcessEvent hooks and the construct callback — the first
    // painted frame shows whatever the template holds. Translating the
    // template once means every future instance is born English: no JP flash.
    auto sweep_widget_templates() -> size_t
    {
        if (!m_enable_template_sweep || g_text_translation_active || !IsInGameThreadRaw() || m_translations.empty())
        {
            return 0;
        }

        TranslationScope scope;
        if (!scope.Entered)
        {
            return 0;
        }

        size_t replacements = 0;
        UObjectGlobals::ForEachUObject([this, &replacements](UObject* object, int32, int32) {
            if (!object || !object->HasAnyFlags(static_cast<EObjectFlags>(RF_ClassDefaultObject | RF_ArchetypeObject)))
            {
                return LoopAction::Continue;
            }
            if (!(is_umg_widget(object) || is_text_render_component(object)))
            {
                return LoopAction::Continue;
            }
            auto* klass = object->GetClassPrivate();
            if (!klass)
            {
                return LoopAction::Continue;
            }
            for (auto* property : get_text_bearing_object_properties(klass))
            {
                // no refresh needed: templates are never rendered directly
                replacements += translate_property_value(object, property, 0, nullptr, STR("WidgetTemplate"));
            }
            return LoopAction::Continue;
        });

        if (m_debug_log && replacements > 0)
        {
            Output::send<LogLevel::Verbose>(STR("{} widget template sweep translated {} field(s)\n"), ModTag, replacements);
        }
        return replacements;
    }

    auto sweep_loaded_text_properties() -> SweepStats
    {
        SweepStats stats{};
        if (!m_enable_object_sweeps || g_text_translation_active || !IsInGameThreadRaw())
        {
            return stats;
        }

        TranslationScope scope;
        if (!scope.Entered)
        {
            return stats;
        }

        UObjectGlobals::ForEachUObject([this, &stats](UObject* object, int32, int32) {
            if (!should_scan_object_properties(object))
            {
                return LoopAction::Continue;
            }

            register_live_text_widget_guarded(object);
            ++stats.ObjectsVisited;

            bool changed_object = false;
            auto* klass = object->GetClassPrivate();
            if (!klass)
            {
                return LoopAction::Continue;
            }

            const auto object_context = object->GetFullName();
            for (auto* property : get_text_bearing_object_properties(klass))
            {
                const auto replacements = translate_property_value(object, property, 0, &stats, object_context);
                if (replacements > 0)
                {
                    changed_object = true;
                    stats.Replacements += replacements;
                }
            }

            if (changed_object && refresh_changed_text_object(object))
            {
                ++stats.Refreshes;
            }

            return LoopAction::Continue;
        });

        return stats;
    }

    auto install_hooks() -> void
    {
        if (m_hooks_installed)
        {
            return;
        }
        m_hooks_installed = true;
        m_widget_class = UObjectGlobals::StaticFindObject<UClass*>(nullptr, nullptr, STR("/Script/UMG.Widget"));
        m_text_block_class = UObjectGlobals::StaticFindObject<UClass*>(nullptr, nullptr, STR("/Script/UMG.TextBlock"));
        m_rich_text_block_class = UObjectGlobals::StaticFindObject<UClass*>(nullptr, nullptr, STR("/Script/UMG.RichTextBlock"));
        m_text_render_component_class = UObjectGlobals::StaticFindObject<UClass*>(nullptr, nullptr, STR("/Script/Engine.TextRenderComponent"));
        m_datatable_class = UObjectGlobals::StaticFindObject<UClass*>(nullptr, nullptr, STR("/Script/Engine.DataTable"));
        if (!m_widget_class)
        {
            Output::send<LogLevel::Warning>(STR("{} could not resolve /Script/UMG.Widget; property lifecycle sweeps disabled\n"), ModTag);
        }
        if (!m_text_render_component_class)
        {
            Output::send<LogLevel::Warning>(STR("{} could not resolve /Script/Engine.TextRenderComponent; world text sweeps disabled\n"), ModTag);
        }

        Hook::RegisterProcessEventPreCallback(
                [this](auto&, UObject* context, UFunction* function, void* params) {
                    try
                    {
                        if (g_hook_depth >= MaxHookDepth || !IsInGameThreadRaw())
                        {
                            return;
                        }
                        HookDepthGuard hook_depth_guard;
                        const auto param_replacements = translate_function_text_params_for_context(context, function, params, false);
                        if (param_replacements > 0 && should_scan_object_properties(context) && !is_text_block_widget(context))
                        {
                            request_targeted_scan(context, 1, 2);
                        }
                        if (is_widget_lifecycle_function(function) && should_scan_object_properties(context))
                        {
                            if (is_one_time_construct_function(function))
                            {
                                // synchronous only: the widget must be English on
                                // its first painted frame. No deferred follow-up:
                                // queue entries resolve by full-path FindObject
                                // (expensive), and per-hover widget rebuilds
                                // flooded the queue into seconds of FPS drain.
                                process_targeted_object_scan(context);
                            }
                            else if (translate_object_text_properties(context) > 0)
                            {
                                // SynchronizeProperties can fire per frame: keep
                                // it to the cheap own-property pass
                                refresh_changed_text_object(context);
                            }
                        }
                    }
                    catch (const std::exception& e)
                    {
                        Output::send<LogLevel::Error>(STR("{} ProcessEvent callback error: {}\n"), ModTag, utf8_to_string_type(e.what()));
                    }
                    catch (...)
                    {
                        Output::send<LogLevel::Error>(STR("{} ProcessEvent callback unknown error\n"), ModTag);
                    }
                },
                {false, false, STR("TextTranslatorCpp"), STR("TextParamPre")});

        Hook::RegisterProcessEventPostCallback(
                [this](auto&, UObject* context, UFunction* function, void* params) {
                    try
                    {
                        if (g_hook_depth >= MaxHookDepth || !IsInGameThreadRaw())
                        {
                            return;
                        }
                        HookDepthGuard hook_depth_guard;
                        const auto replacements = translate_function_text_params_for_context(context, function, params, true);
                        if (replacements > 0 && should_scan_object_properties(context) && !is_text_block_widget(context))
                        {
                            // text widgets are watched by the registry; queueing
                            // them per translated param floods the scan queue on
                            // fast tooltip hovering
                            request_targeted_scan(context, 1, 2);
                        }
                        if (is_target_set_text_function(function))
                        {
                            // safe registration point: the widget is alive and
                            // actively receiving text. No deferred rescan here:
                            // translation already happened synchronously and the
                            // registry watches this widget from now on — queueing
                            // per SetText flooded the name-resolved scan queue
                            // during fast tooltip hovering (sustained FPS drop
                            // while it drained at 12 lookups/tick).
                            register_live_text_widget_guarded(context);
                            process_text_object(context);
                            fit_text_block(context);
                        }
                    }
                    catch (const std::exception& e)
                    {
                        Output::send<LogLevel::Error>(STR("{} ProcessEvent post callback error: {}\n"), ModTag, utf8_to_string_type(e.what()));
                    }
                    catch (...)
                    {
                        Output::send<LogLevel::Error>(STR("{} ProcessEvent post callback unknown error\n"), ModTag);
                    }
                },
                {false, false, STR("TextTranslatorCpp"), STR("TextParamPost")});

        Hook::RegisterStaticConstructObjectPostCallback(
                [this](auto& callback, const FStaticConstructObjectParameters&) {
                    try
                    {
                        if (!IsInGameThreadRaw())
                        {
                            // level streaming constructs DataTables on the async
                            // loading thread; note it (exact-class pointer
                            // compare only — safe off-thread) so the game-thread
                            // tick schedules a row sweep
                            auto* async_object = callback.GetCurrentResolvedReturnValue();
                            if (async_object)
                            {
                                auto* async_class = async_object->GetClassPrivate();
                                // text objects streamed with levels (cutscene
                                // skip prompts etc.) never reach the game-thread
                                // registration path; note them so the tick
                                // schedules a sweep that registers them
                                if (async_class == m_datatable_class || async_class == m_text_block_class ||
                                    async_class == m_rich_text_block_class || async_class == m_text_render_component_class)
                                {
                                    m_datatable_constructed_async.store(true);
                                }
                            }
                            return;
                        }
                        if (g_hook_depth >= MaxHookDepth)
                        {
                            return;
                        }
                        HookDepthGuard hook_depth_guard;
                        auto* constructed_object = callback.GetCurrentResolvedReturnValue();
                        if (constructed_object && m_datatable_class && constructed_object->IsA(m_datatable_class) &&
                            !constructed_object->HasAnyFlags(RF_ClassDefaultObject))
                        {
                            // rows are populated during serialization, after
                            // construction; sweep shortly afterwards
                            m_requested_datatable_sweep_tick = m_tick_count + 15;
                        }
                        if (constructed_object)
                        {
                            // safe now: the registry vector defers additions
                            // while it is being iterated (the actual cause of
                            // the heap-corruption crashes seen at push_back)
                            register_live_text_widget_guarded(constructed_object);
                        }
                        if (should_scan_object_properties(constructed_object))
                        {
                            // synchronous own-property pass only; the Construct
                            // lifecycle hook does the subtree, the registry
                            // watches text widgets, the sweep self-heals
                            if (translate_object_text_properties(constructed_object) > 0)
                            {
                                refresh_changed_text_object(constructed_object);
                            }
                        }
                    }
                    catch (const std::exception& e)
                    {
                        Output::send<LogLevel::Error>(STR("{} StaticConstructObject callback error: {}\n"), ModTag, utf8_to_string_type(e.what()));
                    }
                    catch (...)
                    {
                        Output::send<LogLevel::Error>(STR("{} StaticConstructObject callback unknown error\n"), ModTag);
                    }
                },
                {false, true, STR("TextTranslatorCpp"), STR("WidgetConstruct")});

        Hook::RegisterEngineTickPostCallback(
                [this](auto&, UEngine*, float, bool) {
                    try
                    {
                        ++m_tick_count;
                        tick_live_text_widgets();
                        if (m_datatable_constructed_async.exchange(false))
                        {
                            // a DataTable was constructed on the async loading
                            // thread (level streaming); sweep it soon
                            m_requested_datatable_sweep_tick = m_tick_count + 15;
                        }
                        flush_runtime_texts_if_due();
                        seed_existing_widgets_for_targeted_scan();
                        run_pending_object_scans();
                        // both passes walk GUObjectArray, so keep them on a
                        // staggered ~1s cadence; the first minute sweeps tables
                        // more eagerly to catch startup streaming
                        // sweeps are fully event-driven: they run only when
                        // something actually loaded (DataTable construct notify,
                        // level streaming) plus two startup passes. No periodic
                        // global walks — those were the every-few-seconds
                        // stutter; the hooks + registry handle steady state.
                        const bool datatable_sweep_requested =
                                m_requested_datatable_sweep_tick >= 0 && m_tick_count >= m_requested_datatable_sweep_tick;
                        if (datatable_sweep_requested || m_tick_count == 60 || m_tick_count == 600)
                        {
                            if (datatable_sweep_requested)
                            {
                                m_requested_datatable_sweep_tick = -1;
                            }
                            sweep_datatable_rows();
                            sweep_widget_templates();
                            // also (re)register async-loaded text objects and
                            // translate whatever streamed in with the level
                            sweep_loaded_text_properties();
                        }
                        if (m_tick_count % 3600 == 1800)
                        {
                            // GC safety + reload staleness: pointer-keyed caches
                            // could outlive a GC'd class; the table set keyed by
                            // name would skip a reloaded table forever. All are
                            // rebuilt lazily, and re-sweeps are idempotent.
                            m_function_text_param_cache.clear();
                            m_object_text_property_cache.clear();
                            m_combo_class_cache.clear();
                            m_construct_function_cache.clear();
                            m_set_text_function_cache.clear();
                            m_lifecycle_function_cache.clear();
                            std::erase_if(m_translated_datatable_objects, [](const FWeakObjectPtr& entry) {
                                return entry.Get() == nullptr;
                            });
                        }
                    }
                    catch (const std::exception& e)
                    {
                        Output::send<LogLevel::Error>(STR("{} EngineTick queue error: {}\n"), ModTag, utf8_to_string_type(e.what()));
                    }
                    catch (...)
                    {
                        Output::send<LogLevel::Error>(STR("{} EngineTick queue unknown error\n"), ModTag);
                    }
                },
                {false, false, STR("TextTranslatorCpp"), STR("TargetedQueue")});

        Hook::RegisterProcessConsoleExecGlobalPreCallback(
                [this](auto& callback, UObject*, const TCHAR* command, FOutputDevice&, UObject*) {
                    const StringType cmd = command ? StringType{command} : StringType{};
                    if (starts_with(cmd, STR("ttcpp_reload")))
                    {
                        load_translation_table();
                        m_translated_datatable_objects.clear();
                        sweep_datatable_rows();
                        sweep_widget_templates();
                        callback.TrySetReturnValue(true);
                        callback.PreventOriginalFunctionCall();
                    }
                    else if (starts_with(cmd, STR("ttcpp_sweep")))
                    {
                        const auto stats = sweep_loaded_text_properties();
                        Output::send<LogLevel::Verbose>(
                                STR("{} sweep: objects={} text_props={} string_props={} replacements={} refreshes={}\n"),
                                ModTag,
                                stats.ObjectsVisited,
                                stats.TextPropertiesVisited,
                                stats.StringPropertiesVisited,
                                stats.Replacements,
                                stats.Refreshes);
                        callback.TrySetReturnValue(true);
                        callback.PreventOriginalFunctionCall();
                    }
                    else if (starts_with(cmd, STR("ttcpp_dump_texts")) || starts_with(cmd, STR("ttcpp_dump_misses")))
                    {
                        write_runtime_texts(true);
                        callback.TrySetReturnValue(true);
                        callback.PreventOriginalFunctionCall();
                    }
                    else if (starts_with(cmd, STR("ttcpp_clear_texts")))
                    {
                        m_runtime_texts.clear();
                        m_runtime_text_dirty = true;
                        write_runtime_texts(true);
                        callback.TrySetReturnValue(true);
                        callback.PreventOriginalFunctionCall();
                    }
                    else if (starts_with(cmd, STR("ttcpp_flag")))
                    {
                        // ttcpp_flag <params|sweeps|registry|datatables|templates> <0|1>
                        const auto args = cmd.substr(10);
                        auto set_flag = [&](StringViewType name, bool& flag) {
                            const auto at = args.find(name);
                            if (at == StringType::npos)
                            {
                                return;
                            }
                            const auto value_pos = args.find_first_of(STR("01"), at + name.size());
                            if (value_pos != StringType::npos)
                            {
                                flag = args[value_pos] == STR('1');
                            }
                        };
                        set_flag(STR("params"), m_enable_param_translation);
                        set_flag(STR("sweeps"), m_enable_object_sweeps);
                        set_flag(STR("registry"), m_enable_registry);
                        set_flag(STR("datatables"), m_enable_datatable_sweep);
                        set_flag(STR("templates"), m_enable_template_sweep);
                        Output::send<LogLevel::Verbose>(
                                STR("{} flags: params={} sweeps={} registry={} datatables={} templates={}\n"),
                                ModTag,
                                m_enable_param_translation,
                                m_enable_object_sweeps,
                                m_enable_registry,
                                m_enable_datatable_sweep,
                                m_enable_template_sweep);
                        callback.TrySetReturnValue(true);
                        callback.PreventOriginalFunctionCall();
                    }
                    else if (starts_with(cmd, STR("ttcpp_combos")))
                    {
                        std::vector<UObject*> all;
                        UObjectGlobals::FindAllOf(STR("RichTextComboBoxString"), all);
                        std::vector<UObject*> base;
                        UObjectGlobals::FindAllOf(STR("ComboBoxString"), base);
                        all.insert(all.end(), base.begin(), base.end());
                        for (auto* combo : all)
                        {
                            if (!combo || combo->HasAnyFlags(RF_ClassDefaultObject))
                            {
                                continue;
                            }
                            Output::send<LogLevel::Verbose>(STR("{} combo {}\n"), ModTag, combo->GetFullName());
                            auto* klass = combo->GetClassPrivate();
                            if (!klass)
                            {
                                continue;
                            }
                            for (auto* property : klass->ForEachPropertyInChain())
                            {
                                if (auto* str_property = CastField<FStrProperty>(property))
                                {
                                    auto* value = str_property->ContainerPtrToValuePtr<FString>(combo);
                                    Output::send<LogLevel::Verbose>(
                                            STR("{}   {} = \"{}\"\n"), ModTag, property->GetName(), value ? StringType{**value} : StringType{});
                                }
                                else if (auto* array_property = CastField<FArrayProperty>(property))
                                {
                                    if (!CastField<FStrProperty>(array_property->GetInner()))
                                    {
                                        continue;
                                    }
                                    auto* array_value = array_property->ContainerPtrToValuePtr<void>(combo);
                                    FScriptArrayHelper helper{array_property, array_value};
                                    for (int32_t index = 0; index < helper.Num(); ++index)
                                    {
                                        auto* element = reinterpret_cast<FString*>(helper.GetRawPtr(index));
                                        Output::send<LogLevel::Verbose>(
                                                STR("{}   {}[{}] = \"{}\"\n"), ModTag, property->GetName(), index, element ? StringType{**element} : StringType{});
                                    }
                                }
                            }
                        }
                        callback.TrySetReturnValue(true);
                        callback.PreventOriginalFunctionCall();
                    }
                    else if (starts_with(cmd, STR("ttcpp_debug_on")))
                    {
                        m_debug_collect_runtime_text = true;
                        m_debug_log = true;
                        Output::send<LogLevel::Verbose>(STR("{} runtime text debug enabled\n"), ModTag);
                        callback.TrySetReturnValue(true);
                        callback.PreventOriginalFunctionCall();
                    }
                    else if (starts_with(cmd, STR("ttcpp_debug_off")))
                    {
                        m_debug_collect_runtime_text = false;
                        m_debug_log = false;
                        Output::send<LogLevel::Verbose>(STR("{} runtime text debug disabled\n"), ModTag);
                        callback.TrySetReturnValue(true);
                        callback.PreventOriginalFunctionCall();
                    }
                },
                {false, false, STR("TextTranslatorCpp"), STR("ConsoleCommands")});

        if (m_debug_log)
        {
            Output::send<LogLevel::Verbose>(
                    STR("{} hooks installed. Commands: ttcpp_reload, ttcpp_sweep, ttcpp_dump_texts, ttcpp_clear_texts, ttcpp_debug_on/off\n"),
                    ModTag);
        }
    }
};

#define TEXT_HOOK_MOD_API __declspec(dllexport)
extern "C"
{
    TEXT_HOOK_MOD_API CppUserModBase* start_mod()
    {
        return new TextTranslatorCpp();
    }

    TEXT_HOOK_MOD_API void uninstall_mod(CppUserModBase* mod)
    {
        delete mod;
    }
}
