//! A bounded, colour-coded activity log shown in the bottom panel.
//!
//! It is a simple ring buffer of `(level, message)`: helpers `info`/`warn`/`error` append a line,
//! the oldest lines are dropped past a cap so a long session never grows unbounded, and
//! [`Log::show`] renders it bottom-anchored with auto-scroll. Background jobs feed it through the
//! [`Reporter`](crate::task::Reporter). The UI thread feeds it directly.

// `len`/`is_empty` are part of the log's public surface (and exercised by tests) but not called by
// the Phase 0 bin itself. Allow them rather than gating on `cfg(test)`.
#![allow(dead_code)]

use egui::Color32;

/// Severity of a log line, controlling its colour.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Level {
    Info,
    Warn,
    Error,
}

impl Level {
    fn color(self) -> Color32 {
        match self {
            Level::Info => Color32::from_rgb(0xC8, 0xC8, 0xC8),
            Level::Warn => Color32::from_rgb(0xE0, 0xB0, 0x40),
            Level::Error => Color32::from_rgb(0xE0, 0x60, 0x60),
        }
    }
}

/// A scrolling activity log with a fixed line cap.
pub struct Log {
    lines: Vec<(Level, String)>,
    cap: usize,
}

impl Default for Log {
    fn default() -> Self {
        Self {
            lines: Vec::new(),
            cap: 500,
        }
    }
}

impl Log {
    pub fn new() -> Self {
        Self::default()
    }

    /// Append a line at `level`, dropping the oldest if the cap is exceeded.
    pub fn push(&mut self, level: Level, msg: impl Into<String>) {
        self.lines.push((level, msg.into()));
        if self.lines.len() > self.cap {
            let overflow = self.lines.len() - self.cap;
            self.lines.drain(0..overflow);
        }
    }

    pub fn info(&mut self, msg: impl Into<String>) {
        self.push(Level::Info, msg);
    }

    pub fn warn(&mut self, msg: impl Into<String>) {
        self.push(Level::Warn, msg);
    }

    pub fn error(&mut self, msg: impl Into<String>) {
        self.push(Level::Error, msg);
    }

    /// Number of buffered lines (used by tests).
    pub fn len(&self) -> usize {
        self.lines.len()
    }

    pub fn is_empty(&self) -> bool {
        self.lines.is_empty()
    }

    /// Render the log into the current panel, scrolled to the newest line.
    pub fn show(&self, ui: &mut egui::Ui) {
        egui::ScrollArea::vertical()
            .auto_shrink([false, false])
            .stick_to_bottom(true)
            .show(ui, |ui| {
                ui.spacing_mut().item_spacing.y = 1.0;
                for (level, msg) in &self.lines {
                    ui.colored_label(level.color(), egui::RichText::new(msg).monospace());
                }
            });
    }
}
