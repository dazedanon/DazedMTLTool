# Test-suite policy

Before adding or expanding tests:

- State the concrete regression, user-visible behavior, safety invariant, or external contract being protected.
- Search existing tests and extend the closest case when possible.
- Do not add coverage for a declarative registry/configuration entry when existing tests already exercise its processing path and schema consistency.
- Use the cheapest level that detects the regression: pure function, component, workflow, then full application.
- Do not add tests solely for coverage, implementation details, production-source substrings, exact prose, pixel geometry, widget ancestry, or constant values.
- Full `QWidget`, workflow, or application construction belongs in the extended suite. Add its test ID prefix to `EXTENDED_TEST_PREFIXES` only when necessary and explain why in the handoff.
- Keep tests hermetic: no network, ignored workspace data, `.env`, user configuration, existing logs, or pre-existing `files/` and `translated/` content.
- Prefer small generated or committed fixtures inside a disposable directory.
- Treat test-count headroom as capacity for distinct regressions, not permission
  to split related input/output cases that should remain parameterized.
- Do not increase suite, per-test, module, or test-count targets or budgets without explicit user approval.
- When changing tests, report the protected regression, overlapping coverage considered, suite tier, commands run, and before/after timing when the change materially affects runtime.

## Suite intent

- `core`: default development suite; deterministic behavior and lightweight component coverage.
- `integration`: Git/subprocess workflows, persisted multi-step jobs, and provider orchestration with external calls faked.
- `extended`: full Qt widgets, workflow composition, and application navigation.
- `imagetl`: semi-manual image rendering/editor behavior; requires the on-demand OpenCV extras.
- `full`: core plus integration plus extended; required for test-runner and suite-partition changes.

## Code Review Rules

### Low-signal tests

Flag a new or expanded test when it primarily freezes copy, layout, implementation structure, or a third-party/library behavior rather than a product regression.

Safe path: assert the resulting state or side effect at a cheaper boundary, or document why the presentation detail is a deliberate stable contract.

### Runtime and isolation

Flag changes that raise a budget, bypass the suite runner, add uncontrolled waits, access local workspaces, or put a full GUI test in the core suite.

Safe path: use fake clocks/workers, temporary directories, miniature fixtures, pure presenters/controllers, and a small extended smoke test.
