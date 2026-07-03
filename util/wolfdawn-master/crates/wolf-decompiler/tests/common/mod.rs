//! Shared helpers for the integration tests.
//!
//! Several tests need real Wolf game data (saves, an unpacked Data dir) that cannot be bundled
//! because it is copyrighted. Point `WOLFDAWN_TEST_DATA` at a fixtures root laid out as described in
//! the README and those tests run. With the var unset, or a given file missing, the lookup returns
//! `None` and the test skips itself.

/// Resolve a fixture by its clean relative path under `WOLFDAWN_TEST_DATA`. Returns `None` when the
/// var is unset or the file/dir does not exist, so callers can skip gracefully.
#[allow(dead_code)]
pub fn test_data(rel: &str) -> Option<std::path::PathBuf> {
    let base = std::env::var_os("WOLFDAWN_TEST_DATA")?;
    let p = std::path::Path::new(&base).join(rel);
    p.exists().then_some(p)
}
