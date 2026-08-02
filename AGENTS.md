# Repository guidance

## Working agreements

- Preserve user changes already present in the worktree. Keep unrelated edits out of the task.
- Prefer small, behavior-focused changes over broad rewrites.
- Use `rg` or `rg --files` for repository searches.
- Run the smallest relevant test target while iterating, then run `./tests/run_tests.sh core` before handing off a code change.
- Run `./tests/run_tests.sh extended` when a change affects Qt widgets, workflow composition, application navigation, or other UI behavior.
- Run `./tests/run_tests.sh full` before a release or when changing shared test infrastructure.
- Report the tests run and any runtime-budget result in the final handoff.

## Test-suite growth

- Every new test must protect a concrete regression, user-visible behavior, destructive-action safeguard, or external contract.
- Search for overlapping coverage before adding a test. Extend or parameterize the closest existing case when that remains readable.
- Test at the cheapest useful level: pure function, component, workflow, then full application.
- Do not add tests solely for line coverage, source-code substrings, exact prose, pixel geometry, or constant values.
- Keep tests hermetic. They must not depend on ignored workspaces, `.env`, network access, user configuration, existing logs, or local contents of `files/` and `translated/`.
- Do not raise a test runtime budget or move a test to a slower suite merely to make a change pass without explicit user approval.
- More specific guidance in `tests/AGENTS.md` applies to changes under `tests/`.

## Code Review Rules

### Test-suite regressions

Flag tests that duplicate existing behavior, construct a full GUI to exercise controller logic, inspect production source text instead of behavior, depend on local data, or weaken runtime enforcement.

Safe path: consolidate overlapping cases, extract pure logic, use committed or generated miniature fixtures, and retain only a small end-to-end smoke test for each important user path.
