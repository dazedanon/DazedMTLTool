//! `wolf-decompiler` turns the byte-faithful command programs from `wolf-formats`
//! into readable, editable WolfScript.
//!
//! Provides the decompile (render) direction. The byte-exact `RawCommand` stays the
//! round-trip authority. The parse/recompile direction is built on top of it.

#![forbid(unsafe_code)]

pub mod compile;
pub mod db_edit;
pub mod document;
pub mod json;
pub mod merge;
pub mod names;
pub mod save;
pub mod save_pro;
pub mod spec;
pub mod strings;
pub mod symbols;
pub mod text;
pub mod txt_events;
pub mod wolfscript;

pub use compile::{compile_commands, compile_commands_enc};
pub use db_edit::apply_database_edit;
pub use document::{
    compile_common_events_edit, compile_map_edit, decompile_common_events_edit,
    decompile_common_events_edit_annotated, decompile_map_edit, decompile_map_edit_annotated,
};
pub use json::database_to_json;
pub use merge::{apply_memory, build_memory, dropped_sources, MergeStats};
pub use names::{check_name_conflicts, extract_db_name_cells, extract_names, inject_names, Conflict};
pub use save::{
    inspect_save, read_title, read_title_at, update_save, SaveFormat, SaveInfo, SaveUpdateStats,
};
pub use save_pro::{decrypt_pro, encrypt_pro, is_pro_save};
pub use strings::{
    apply_game_dat, audit_common_events_to_json, audit_db_to_json, audit_map_to_json,
    db_strings_to_json, dump_game_dat, extract_common_events, extract_db_strings, extract_game_dat,
    extract_map, inject_common_events, inject_db_strings, inject_game_dat, inject_map,
    normalize_en_punct, scenes_to_json, InjectOptions, InjectStats,
};

pub use symbols::SymbolTable;
pub use txt_events::{extract_txt_dir, extract_txt_events, inject_txt_events, split_txt_dir};
pub use wolfscript::{
    decompile_commands, decompile_commands_annotated, decompile_commands_enc,
    decompile_common_events, decompile_map, operand, Renderer,
};
