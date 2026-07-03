//! Reusable UI pieces: native file dialogs (thin `rfd` wrappers) and the small labelled
//! controls the sections lean on heavily (a checkbox-with-tooltip and a path-field-plus-Browse).
//!
//! An option flag like `--en-punct` becomes one `labeled_checkbox(...)` call, and a path argument
//! becomes one `path_field(...)` call, with the tooltip and Browse button handled here. Every
//! non-obvious control gets a plain-language tooltip.

// Shared widget/dialog toolkit. Some helpers are not wired into a section yet, so allow dead code
// here rather than annotating each one.
#![allow(dead_code)]

use std::path::PathBuf;

// ----------------------------------------------------------------------------
// File dialogs (rfd)
// ----------------------------------------------------------------------------

/// Pick an existing folder. `None` if the user cancels.
pub fn pick_folder() -> Option<PathBuf> {
    rfd::FileDialog::new().pick_folder()
}

/// Pick an existing folder, starting the dialog at `start` when it exists.
pub fn pick_folder_in(start: Option<&std::path::Path>) -> Option<PathBuf> {
    let mut dlg = rfd::FileDialog::new();
    if let Some(dir) = start.filter(|p| p.is_dir()) {
        dlg = dlg.set_directory(dir);
    }
    dlg.pick_folder()
}

/// Pick an existing file. `filters` is a list of `(label, &[extensions])`, e.g.
/// `&[("Wolf archive", &["wolf"]), ("Game data", &["dat"])]`. `None` if cancelled.
pub fn pick_file(filters: &[(&str, &[&str])]) -> Option<PathBuf> {
    let mut dlg = rfd::FileDialog::new();
    for (label, exts) in filters {
        dlg = dlg.add_filter(*label, exts);
    }
    dlg.pick_file()
}

/// Pick an existing file, starting the dialog in `start` when it is a directory. `filters` is a list
/// of `(label, &[extensions])`. `None` if cancelled.
pub fn pick_file_in(start: Option<&std::path::Path>, filters: &[(&str, &[&str])]) -> Option<PathBuf> {
    let mut dlg = rfd::FileDialog::new();
    if let Some(dir) = start.filter(|p| p.is_dir()) {
        dlg = dlg.set_directory(dir);
    }
    for (label, exts) in filters {
        dlg = dlg.add_filter(*label, exts);
    }
    dlg.pick_file()
}

/// Choose a destination path for a save, pre-filled with `default_name`. `None` if cancelled.
pub fn save_file(default_name: &str, filters: &[(&str, &[&str])]) -> Option<PathBuf> {
    let mut dlg = rfd::FileDialog::new().set_file_name(default_name);
    for (label, exts) in filters {
        dlg = dlg.add_filter(*label, exts);
    }
    dlg.save_file()
}

// ----------------------------------------------------------------------------
// Reusable controls
// ----------------------------------------------------------------------------

/// A checkbox with a label and a hover tooltip. Returns `true` if the value changed this frame.
/// Sections use this for optional flags (`--en-punct`, `--allow-code-drift`, encrypt toggles…).
pub fn labeled_checkbox(ui: &mut egui::Ui, value: &mut bool, label: &str, tooltip: &str) -> bool {
    ui.checkbox(value, label).on_hover_text(tooltip).changed()
}

// ----------------------------------------------------------------------------
// Aligned form rows (shared layout for every section)
// ----------------------------------------------------------------------------
//
// These helpers give one consistent layout: a fixed-width left LABEL column, an input that FILLS
// the remaining width (so every input in a section shares the same left AND right edge), and a
// fixed right-hand BUTTON area for Browse/× so those align too. The input fills available width
// rather than taking a fixed pixel width, which keeps rows uniform and responsive to window size.

/// The fixed width (px) of a form row's left label column. Wide enough for the longest labels used
/// across the sections ("Start-up message", "Default PC graphic", "Output folder", …) so every
/// input starts at the same x regardless of its label.
pub const LABEL_COL_W: f32 = 128.0;

/// The reserved width (px) of a path row's right-hand button area. Room for "Browse… ×" so the
/// Browse buttons (and the optional clear ×) line up in a fixed column across a section.
pub const BTN_COL_W: f32 = 128.0;

/// Emit `label` into a fixed-width [`LABEL_COL_W`] left cell (left-aligned, vertically centred to
/// match the adjacent control), then run `content` for the rest of the row inside one
/// `ui.horizontal`. The label's `Response` carries `tooltip`. Returns whatever `content` returns.
///
/// The other form helpers (and the sections' bespoke rows) build on this, so every labelled row
/// across the app shares the same left column and baseline.
pub fn form_row<R>(
    ui: &mut egui::Ui,
    label: &str,
    tooltip: &str,
    content: impl FnOnce(&mut egui::Ui) -> R,
) -> R {
    ui.horizontal(|ui| {
        // Reserve an EXACT fixed-width cell for the label. `allocate_ui_with_layout` advances the
        // cursor by the label's width, not the desired width, so short labels leave each row's input
        // starting at a different x. `allocate_exact_size` reserves the full column unconditionally,
        // so every input begins at a constant x and is uniform width. The label is painted (clipped
        // to the cell) like `nav_button`.
        let h = ui.spacing().interact_size.y;
        let (rect, resp) = ui.allocate_exact_size(egui::vec2(LABEL_COL_W, h), egui::Sense::hover());
        let font = egui::TextStyle::Body.resolve(ui.style());
        let color = ui.visuals().widgets.noninteractive.fg_stroke.color;
        ui.painter().with_clip_rect(rect).text(
            egui::pos2(rect.left(), rect.center().y),
            egui::Align2::LEFT_CENTER,
            label,
            font,
            color,
        );
        if !tooltip.is_empty() {
            resp.on_hover_text(tooltip);
        }
        content(ui)
    })
    .inner
}

/// A labelled path row: a read-only [`TextEdit`] that FILLS the row up to a common right edge
/// (`available_width - BTN_COL_W`), followed by a "Browse…" button (and, when `clearable`, a ×) in
/// the reserved right-hand area. Because the input fills to a fixed offset from the right, every
/// path row in a section is identical width and every Browse lines up. When the button is pressed
/// `browse` produces a new path. A returned `Some` replaces `value`. Returns `true` when `value`
/// changed this frame. Shows a placeholder when empty.
pub fn path_row(
    ui: &mut egui::Ui,
    label: &str,
    value: &mut Option<PathBuf>,
    tooltip: &str,
    clearable: bool,
    browse: impl FnOnce() -> Option<PathBuf>,
) -> bool {
    let mut changed = false;
    form_row(ui, label, tooltip, |ui| {
        // The input fills everything except the reserved right-hand button area, so it ends at a
        // common x and the Browse button(s) line up across the section.
        let input_w = (ui.available_width() - BTN_COL_W).max(80.0);
        // Editable: the text is derived from `value` each frame and written straight back when the
        // user types, so a path can be typed directly (for example naming an output folder
        // "extracted") without the Browse dialog. Browse still fills it for those who prefer it.
        let mut text = value
            .as_ref()
            .map(|p| p.display().to_string())
            .unwrap_or_default();
        let resp = ui.add(
            egui::TextEdit::singleline(&mut text)
                .hint_text("type a path or use Browse…")
                .desired_width(input_w),
        );
        if resp.changed() {
            let t = text.trim();
            *value = if t.is_empty() { None } else { Some(PathBuf::from(t)) };
            changed = true;
        }
        if ui.button("Browse…").on_hover_text(tooltip).clicked() {
            if let Some(picked) = browse() {
                *value = Some(picked);
                changed = true;
            }
        }
        if clearable && value.is_some() && ui.button("×").on_hover_text("Clear").clicked() {
            *value = None;
            changed = true;
        }
    });
    changed
}

/// A labelled text-input row: a `&mut String` editor that FILLS the whole remaining row width (no
/// trailing button), so every text row in a section is uniform full width. `hint` is the
/// placeholder shown when empty. Returns the input's `Response` so callers can attach a tooltip or
/// inspect `.changed()`.
pub fn text_row(
    ui: &mut egui::Ui,
    label: &str,
    value: &mut String,
    label_tooltip: &str,
    hint: &str,
) -> egui::Response {
    form_row(ui, label, label_tooltip, |ui| {
        // `desired_width` (not `add_sized`) reliably makes the TextEdit fill the column. `add_sized`
        // lets TextEdit's intrinsic content sizing win, which left filled rows narrower than empty ones.
        let avail = ui.available_width().max(80.0);
        ui.add(egui::TextEdit::singleline(value).hint_text(hint).desired_width(avail))
    })
}

/// A read-only path field followed by a "Browse…" button. Thin wrapper over [`path_row`] (clearable)
/// that sections call as their entry point. The layout is the shared aligned one.
pub fn path_field(
    ui: &mut egui::Ui,
    label: &str,
    value: &mut Option<PathBuf>,
    tooltip: &str,
    browse: impl FnOnce() -> Option<PathBuf>,
) -> bool {
    path_row(ui, label, value, tooltip, true, browse)
}

/// A small, dimmed caption line, used for the "what this section will do" blurbs.
pub fn caption(ui: &mut egui::Ui, text: &str) {
    ui.label(egui::RichText::new(text).weak());
}

/// The standard "coming soon" body for a not-yet-built section: a heading, a one-line description
/// of what the section will do, and the phase it lands in. Keeps the full nav shape visible now.
pub fn coming_soon(ui: &mut egui::Ui, phase: u8, description: &str) {
    ui.add_space(8.0);
    ui.heading("Coming soon");
    ui.add_space(4.0);
    caption(ui, description);
    ui.add_space(8.0);
    ui.label(
        egui::RichText::new(format!("Planned for Phase {phase}."))
            .italics()
            .weak(),
    );
}
