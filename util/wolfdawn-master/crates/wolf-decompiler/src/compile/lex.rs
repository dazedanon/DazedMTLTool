//! Line lexer: trimmed, non-empty lines with their source line numbers. The decompiler indents
//! by depth, but the parser reconstructs `indent` from block nesting, so leading whitespace is
//! discarded here.

pub struct Line {
    pub no: u32,
    pub text: String,
}

impl std::fmt::Debug for Line {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}:{:?}", self.no, self.text)
    }
}

pub fn lines(text: &str) -> Vec<Line> {
    text.lines()
        .enumerate()
        .filter_map(|(i, raw)| {
            // Trim only the leading whitespace (the indent). Trailing spaces are significant
            // inside, for example, comment text.
            let t = raw.trim_start();
            if t.is_empty() {
                None
            } else {
                Some(Line {
                    no: (i + 1) as u32,
                    text: t.to_string(),
                })
            }
        })
        .collect()
}
