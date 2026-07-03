//! The command reference. Argument schemas for every Wolf command id and move-route
//! sub-command, loaded from `data/commands.json`. Drives bespoke rendering so no command
//! falls back to an unlabeled dump.

use std::collections::HashMap;
use std::sync::OnceLock;

use serde::Deserialize;

static REFERENCE_JSON: &str = include_str!("../data/commands.json");

#[derive(Debug, Deserialize)]
struct Reference {
    commands: Vec<CommandSpec>,
    #[serde(default)]
    route_commands: Vec<RouteSpec>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct CommandSpec {
    pub cid: u32,
    pub name: String,
    #[serde(default)]
    pub int_args: Vec<IntField>,
    #[serde(default)]
    pub string_args: Vec<StrField>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct IntField {
    pub label: String,
    #[serde(default)]
    pub kind: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct StrField {
    #[allow(dead_code)]
    pub label: String,
    #[serde(default)]
    pub role: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct RouteSpec {
    pub id: u32,
    pub name: String,
    #[serde(default)]
    pub args: String,
}

struct Tables {
    commands: HashMap<u32, CommandSpec>,
    routes: HashMap<u32, RouteSpec>,
}

fn tables() -> &'static Tables {
    static TABLES: OnceLock<Tables> = OnceLock::new();
    TABLES.get_or_init(|| {
        // The data file may carry a UTF-8 BOM (Windows PowerShell export); strip it.
        let json = REFERENCE_JSON.trim_start_matches('\u{feff}');
        let reference: Reference =
            serde_json::from_str(json).expect("embedded data/commands.json failed to parse");
        let commands = reference.commands.into_iter().map(|c| (c.cid, c)).collect();
        let routes = reference
            .route_commands
            .into_iter()
            .map(|r| (r.id, r))
            .collect();
        Tables { commands, routes }
    })
}

/// Argument schema for a command id, if catalogued.
pub fn command(cid: u32) -> Option<&'static CommandSpec> {
    tables().commands.get(&cid)
}

/// Display name for a command id (falls back to `Cmd<cid>`).
pub fn command_name(cid: u32) -> String {
    command(cid)
        .map(|c| c.name.clone())
        .unwrap_or_else(|| format!("Cmd{cid}"))
}

/// Reverse lookup: command id for a display name (for the recompiler).
pub fn cid_for_name(name: &str) -> Option<u32> {
    tables()
        .commands
        .values()
        .find(|c| c.name == name)
        .map(|c| c.cid)
}

/// Name of a move-route sub-command id (falls back to `route<id>`).
pub fn route_name(id: u32) -> String {
    tables()
        .routes
        .get(&id)
        .map(|r| r.name.clone())
        .unwrap_or_else(|| format!("route{id}"))
}

/// Reverse lookup: move-route sub-command id for a display name (for the recompiler).
/// Accepts the `route<id>` fallback form too.
pub fn route_id_for_name(name: &str) -> Option<u32> {
    if let Some(rest) = name.strip_prefix("route") {
        if let Ok(id) = rest.parse::<u32>() {
            return Some(id);
        }
    }
    tables()
        .routes
        .values()
        .find(|r| r.name == name)
        .map(|r| r.id)
}
