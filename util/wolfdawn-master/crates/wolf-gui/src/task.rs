//! Background jobs. The shared pattern every long-running section uses.
//!
//! Long operations (unpack, extract, inject, save-update...) must never run on the UI thread
//! or the window freezes. The pattern here:
//!
//! 1. A section calls [`JobManager::run`] with a label and a closure that does the work. The
//!    closure receives a [`Reporter`] it pushes progress + log messages through.
//! 2. The closure runs on a fresh `std::thread`. Each [`Reporter::progress`] / `Reporter::log`
//!    call sends a [`JobMsg`] down an `mpsc` channel. The final `Result` is sent as
//!    [`JobMsg::Done`].
//! 3. Every frame, [`JobManager::poll`] drains the channel: progress updates the bar, log
//!    messages append to the [`Log`], and `Done` clears the active job. While a job is live the
//!    app keeps calling `ctx.request_repaint()` so the UI animates even with no user input.
//!
//! Sections copy this shape verbatim: build the inputs on the UI thread (cheap), then hand the
//! heavy work to `run(...)` so the result and progress flow back through the channel.

// `Reporter::warn`/`error` round out the reporting API for the heavier jobs that later sections
// add. The Phase 0 demo job only needs `info`/`progress`, so allow the unused-yet variants here.
#![allow(dead_code)]

use std::sync::mpsc::{Receiver, Sender};

use crate::log::{Level, Log};

/// A message from a running job back to the UI thread.
pub enum JobMsg {
    /// Fractional progress in `0.0..=1.0` plus a short status line.
    Progress(f32, String),
    /// A line to append to the log at the given level.
    Log(Level, String),
    /// The job finished. `Ok` carries a human summary. `Err` carries the failure message.
    Done(Result<String, String>),
}

/// Handed to a job closure so it can report progress and log lines back to the UI. Cloneable so a
/// job can pass it into sub-steps. Sends are best-effort: if the UI side has hung up (app closing)
/// the calls become no-ops rather than panicking.
#[derive(Clone)]
pub struct Reporter {
    tx: Sender<JobMsg>,
}

impl Reporter {
    /// Report fractional progress (`0.0..=1.0`) and a status line shown next to the bar.
    pub fn progress(&self, fraction: f32, status: impl Into<String>) {
        let _ = self.tx.send(JobMsg::Progress(fraction.clamp(0.0, 1.0), status.into()));
    }

    /// Append an info line to the log.
    pub fn info(&self, msg: impl Into<String>) {
        let _ = self.tx.send(JobMsg::Log(Level::Info, msg.into()));
    }

    /// Append a warning line to the log.
    pub fn warn(&self, msg: impl Into<String>) {
        let _ = self.tx.send(JobMsg::Log(Level::Warn, msg.into()));
    }

    /// Append an error line to the log.
    pub fn error(&self, msg: impl Into<String>) {
        let _ = self.tx.send(JobMsg::Log(Level::Error, msg.into()));
    }
}

/// The single in-flight background job (if any) plus its latest progress, owned by the app.
///
/// At most one job runs at a time. The section UIs disable their action buttons via
/// [`JobManager::is_running`] while one is live, so the worker never contends with itself.
#[derive(Default)]
pub struct JobManager {
    /// Receiver for the active job's messages. `None` when idle.
    rx: Option<Receiver<JobMsg>>,
    /// Label of the active job (shown by the progress bar).
    label: String,
    /// Latest fractional progress in `0.0..=1.0`.
    progress: f32,
    /// Latest status line from the job.
    status: String,
}

impl JobManager {
    pub fn new() -> Self {
        Self::default()
    }

    /// True while a background job is in flight.
    pub fn is_running(&self) -> bool {
        self.rx.is_some()
    }

    pub fn label(&self) -> &str {
        &self.label
    }

    pub fn progress(&self) -> f32 {
        self.progress
    }

    pub fn status(&self) -> &str {
        &self.status
    }

    /// Spawn `work` on a worker thread, routing its progress/log/result back to this manager.
    ///
    /// `work` returns `Ok(summary)` on success or `Err(message)` on failure. Both are surfaced in
    /// the log when the job completes. If a job is already running the call is ignored (the caller
    /// should gate its button on [`is_running`](Self::is_running)).
    pub fn run<F>(&mut self, label: impl Into<String>, log: &mut Log, work: F)
    where
        F: FnOnce(&Reporter) -> Result<String, String> + Send + 'static,
    {
        if self.is_running() {
            log.warn("a job is already running; please wait for it to finish");
            return;
        }
        let label = label.into();
        let (tx, rx) = std::sync::mpsc::channel();
        self.rx = Some(rx);
        self.label = label.clone();
        self.progress = 0.0;
        self.status = "starting…".to_string();
        log.info(format!("▶ {label}"));

        // The worker owns its Reporter (and thus the Sender). When the thread ends the Sender drops
        // and the channel closes, which is how `poll` detects completion even if `Done` is missed.
        std::thread::spawn(move || {
            let reporter = Reporter { tx };
            let result = work(&reporter);
            let _ = reporter.tx.send(JobMsg::Done(result));
        });
    }

    /// Drain all pending messages from the active job into the log + progress fields. Returns
    /// `true` while a job is still running (the caller then requests a repaint so the bar animates).
    pub fn poll(&mut self, log: &mut Log) -> bool {
        let Some(rx) = &self.rx else {
            return false;
        };
        // Drain everything available this frame so the bar/log stay current under a chatty job.
        let mut finished = false;
        loop {
            match rx.try_recv() {
                Ok(JobMsg::Progress(frac, status)) => {
                    self.progress = frac;
                    self.status = status;
                }
                Ok(JobMsg::Log(level, msg)) => log.push(level, msg),
                Ok(JobMsg::Done(result)) => {
                    match result {
                        Ok(summary) => log.info(format!("done — {} — {summary}", self.label)),
                        Err(err) => log.error(format!("failed — {} — {err}", self.label)),
                    }
                    finished = true;
                }
                Err(std::sync::mpsc::TryRecvError::Empty) => break,
                Err(std::sync::mpsc::TryRecvError::Disconnected) => {
                    // Worker thread ended without an explicit Done (panic / early drop). Treat the
                    // channel close as completion so the UI never gets stuck "running" forever.
                    finished = true;
                    break;
                }
            }
        }
        if finished {
            self.rx = None;
            self.progress = 0.0;
            self.status.clear();
            self.label.clear();
            return false;
        }
        true
    }
}
