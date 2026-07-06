# UI Style Test Baseline

This document defines the current evidence boundary for making large FreeCAD
UI/style changes. It distinguishes tests that are green from UI surfaces that
are only inventoried, partially tested, or not testable yet.

The current baseline artifacts are expected under `/tmp/freecad-test-results`.
Run the full baseline collection with:

```sh
tools/run_ui_test_baseline.sh
```

That script records each step's command, exit status, and log under
`/tmp/freecad-test-results`, then writes
`/tmp/freecad-test-results/baseline-summary.json`. It keeps going after a
failing or timed-out step because those failures are part of the coverage
boundary. After all artifacts are collected, it returns the combined final
`ui-style-run-status`, `ui-style-requirement-audit`, and
`json-artifact-integrity-final` status, so CI cannot pass when the full-run
status, checklist-level audit, or final JSON integrity check is red.
It does not create missing approval manifests by default; set
`FREECAD_BASELINE_APPROVE_MISSING=1` only when intentionally bootstrapping or
refreshing approved CTest/visual baselines.
For visual baselines, that bootstrap path treats legacy manifests as needing
reapproval when they lack reviewer/note/timestamp/source metadata, portable
baseline images, scene-context fingerprints, scene-context identities, or the
strict visual policy thresholds required by the gate. A stale format-2 manifest
therefore cannot silently block regeneration just because it exists.

The final full-run status is written to
`/tmp/freecad-test-results/ui-style-run-status.json`. The run-status checker
parses `tools/run_ui_test_baseline.sh` and requires status files for every
`run_step` in the full battery. Approve-only bootstrap steps are optional when
they did not run, but if they do run their status is checked. Missing or nonzero
required step status files fail the final run status. Each step must also have
a command file and a per-step run id matching the current `run.id`, so stale
status files from an earlier baseline run cannot satisfy the gate.

Regenerate only the machine-readable summary from existing logs with:

```sh
tools/collect_ui_test_baseline.py \
  --results-dir /tmp/freecad-test-results \
  --build-dir build/release \
  --output /tmp/freecad-test-results/baseline-summary.json
```

Evaluate the summary against the style-readiness gates with:

```sh
tools/evaluate_ui_style_gate.py \
  --summary /tmp/freecad-test-results/baseline-summary.json \
  --repo-root . \
  --results-dir /tmp/freecad-test-results \
  --coverage-config tools/ui_style_coverage.default.json \
  --output /tmp/freecad-test-results/ui-style-gate.json
```

The evaluator is intentionally stricter than the collector. The collector
records evidence; the evaluator decides whether that evidence is sufficient.
Any crash, hidden nonzero process exit, timeout, unclassified traceback, or
missing required artifact keeps the overall gate at `fail`.

## Current Baseline

Captured build:

- FreeCAD 26.3.0 dev, revision `20260623 (Git shallow)`
- Commit `0d88b4ad4e221f05028ac623d15f49f2f2daf626`
- GUI and tests built in `build/release`
- IFC/BIM Python dependency supplied by repo-local `.venv`

### CTest

Command:

```sh
ctest --test-dir build/release --output-on-failure -j8
```

Observed result:

- `1684` tests in CTest inventory
- `1677` tests run
- `0` failed
- `100%` pass rate for tests that ran
- `7` disabled and `3` skipped
- Only `5` Qt-labeled tests, so this is primarily core/unit coverage

CTest is a good regression gate for core behavior. It is not a sufficient gate
for broad UI usability or style changes.

FreeCAD venv/IFC startup smoke:

```sh
tools/freecad_startup_smoke.py tools/freecadcmd_venv.sh \
  --output /tmp/freecad-test-results/freecad-startup-smoke.json
```

Observed startup smoke:

- Result: `ok`
- FreeCAD wrapper return code: `0`
- Venv path visible to FreeCAD Python: `true`
- IfcOpenShell version: `0.8.5`

This proves the test run is using the repo-local venv path and that IFC support
is importable through the FreeCADCmd wrapper. The smoke uses a temporary Python
script rather than a long `-c` expression because FreeCADCmd accepts script
execution reliably and can terminate unexpectedly on complex `-c` payloads.

Disabled/skipped inventory approval:

```sh
tools/ctest_inventory_regression.py approve \
  --summary /tmp/freecad-test-results/baseline-summary.json \
  --manifest /tmp/freecad-test-results/ctest-not-run-approved.json
```

Disabled/skipped inventory check:

```sh
tools/ctest_inventory_regression.py check \
  --summary /tmp/freecad-test-results/baseline-summary.json \
  --manifest /tmp/freecad-test-results/ctest-not-run-approved.json \
  > /tmp/freecad-test-results/ctest-not-run-check.json
```

Observed inventory check:

- Approved disabled/skipped tests: `10`
- Current disabled/skipped tests: `10`
- Newly runnable tests: `0`
- Failures: `0`

The check is change-tolerant in the useful direction: approved disabled or
skipped tests may become runnable without failing the gate. New disabled or
skipped tests fail until fixed or explicitly approved. Reason changes fail
because they can hide a test becoming more disabled. The checker rejects
approval manifests that turn off any of those policy rules, placeholder
approved reasons, duplicate current not-run test names, and malformed current
not-run inventory rows.

CTest inventory checker self-test:

```sh
tools/ctest_inventory_selftest.py \
  --output /tmp/freecad-test-results/ctest-inventory-selftest.json
```

Observed result:

- Result: `ok`
- Scenario count: `7`
- Failed scenarios: `0`
- Verified pass scenarios:
  - unchanged approved inventory
  - previously disabled/skipped test becoming runnable
- Verified fail scenarios:
  - new disabled/skipped test
  - disabled/skipped reason change
  - approval manifest with lax policy
  - duplicate current disabled/skipped test name
  - placeholder approved reason

### FreeCAD Registered Tests

Command:

```sh
timeout 3600s xvfb-run -a tools/freecad_venv.sh -t 0
```

Observed result:

- The run did not complete in this environment.
- It produced `2116` passing `... ok` lines before being stopped.
- It produced `42` skipped test lines.
- Last observed stopping area:
  `DraftGuiManualInput.test_unlock_polar_fields_clears_length_and_angle`
- The log contained repeated async GUI/lifetime noise:
  - `71` Python tracebacks
  - `67` deleted-object `ReferenceError`s
  - `72` Qt/PySide quantity-slot `TypeError`s

This battery is valuable but is not currently a reliable full gate. The hang
and noisy GUI errors need to be resolved or isolated before it can support a
style migration claim.

Follow-up isolation:

- The last observed individual test,
  `drafttests.test_manual_input_gui.DraftGuiManualInput.test_unlock_polar_fields_clears_length_and_angle`,
  passes alone in `0.275s`.
- The full `drafttests.test_manual_input_gui` module does not hang when run
  directly, but fails with `4` `Gui.Snapper` setup errors. That means direct
  module execution is not equivalent to the registered suite setup.
- The original `-t 0` stall is therefore more likely related to accumulated
  GUI state, suite ordering, or teardown after preceding registered tests than
  to that single test body.

Suite split:

```sh
tools/freecad_registered_test_harness.py tools/freecad_venv.sh \
  --output-dir /tmp/freecad-test-results/freecad-registered-split \
  --timeout-per-suite 180
```

Observed split result:

- `42` registered suites discovered and run independently.
- `34` suites are clean `ok`.
- `1` suite is `ok_with_process_errors`.
- `4` suites are `process_failed`.
- `1` suite is `traceback`.
- `1` suite is `timeout`.
- `1` suite is `crash`.

Actionable issue suites:

- `TestArch`: result `traceback`, `16` Python tracebacks, `12`
  deleted-object `ReferenceError`s.
- `TestDraftGui`: result `ok_with_process_errors`, `67`
  `Base::Quantity` Qt/PySide type errors despite return code `0`.
- `Workbench`: result `timeout` after `180s`.
- `TestRubberbandSelection`: result `process_failed`, return code `1`,
  `3` tracebacks, `20` `Base::Quantity` Qt/PySide type errors.
- `TestCoinSelectionVisual`: result `crash`, SIGSEGV in the visual selection
  test path.
- `TestArchGui`: result `process_failed`, return code `1`, `9` tracebacks.
- `TestSketcherGui`: result `process_failed`, return code `1`,
  `5` tracebacks.
- `TestCAMGui`: result `process_failed`, return code `1`, `1` traceback.

This makes the registered suite actionable, but not green. Any style-readiness
claim still needs these suites fixed, explicitly quarantined with reasons, or
kept as hard blockers.

Registered issue classification:

```sh
tools/validate_registered_issue_classifications.py \
  --summary /tmp/freecad-test-results/freecad-registered-split/summary.json \
  --classifications tools/freecad_registered_issue_classifications.default.json \
  --output /tmp/freecad-test-results/freecad-registered-issue-classification.json
```

Observed classification result:

- Result: `ok`
- Classified registered-suite issues: `8`
- Unclassified registered-suite issues: `0`
- Hard blockers: `8`

This classification is not an allowlist and does not make the gate pass. It
only proves the current registered-suite failures are known, named, and backed
by required log evidence. The validator rejects classifications that try to
mark observed crash, timeout, nonzero process exit, process-error, or traceback
suites as non-blocking. It also rejects missing evidence lists, blank evidence,
placeholder evidence, missing reasons, and placeholder reasons such as `TODO`.
Those failures remain hard blockers until fixed or deliberately quarantined by
a project-level decision. A suite row labeled `ok` is still treated as an issue
requiring classification if it carries hard process signals such as tracebacks,
segmentation faults, nonzero return codes, timeouts, deleted-object reference
errors, or Qt/PySide quantity conversion errors.

Registered split harness self-test:

```sh
tools/freecad_registered_harness_selftest.py \
  --output /tmp/freecad-test-results/freecad-registered-harness-selftest.json
```

Observed result:

- Result: `ok`
- Scenario count: `16`
- Failed scenarios: `0`
- Proves the split harness classifies `ok`, `failed`, `traceback`,
  `ok_with_process_errors`, `process_failed`, `crash`, `timeout`, and
  `unknown` outputs.
- Proves `ok_with_process_errors` covers both Qt quantity-slot conversion
  errors and deleted-object `ReferenceError` output.
- Proves duplicate discovered suites, duplicate selected suites, log-slug
  collisions, and empty log slugs are hard preflight failures before suite logs
  can be overwritten.

Classification validator self-test:

```sh
tools/registered_classification_selftest.py \
  --output /tmp/freecad-test-results/registered-classification-selftest.json
```

Observed self-test result:

- Result: `ok`
- Scenario count: `20`
- Failed scenarios: `0`
- Verified pass scenarios:
  - valid classification with required log evidence
  - valid classification using a bounded count range
- Verified fail scenarios:
  - unclassified issue
  - `ok` result with hidden traceback evidence but no classification
  - stale classification
  - result mismatch
  - missing required evidence
  - missing required evidence list
  - blank required evidence
  - placeholder required evidence
  - missing expected counts
  - exact expected-count mismatch
  - expected-count range mismatch
  - unknown expected-count field
  - unknown expected-count range field
  - invalid expected-count range
  - missing reason
  - placeholder reason
  - duplicate classification
  - non-blocking classification for a hard failure

The registered-test gate consumes this self-test report before trusting the
current issue classifications.

### Style-Readiness Gate Verdict

Command:

```sh
tools/evaluate_ui_style_gate.py \
  --summary /tmp/freecad-test-results/baseline-summary.json \
  --repo-root . \
  --results-dir /tmp/freecad-test-results \
  --output /tmp/freecad-test-results/ui-style-gate.json
```

Observed result:

- Overall status: `fail`
- Ready for sweeping style change: `false`
- Gate counts: `6` pass, `4` fail, `1` missing

Passing gates:

- Core CTest
- Visual workbench/fixture/dialog/task baselines
- Layout assertion implementation
- Theme/DPI/font matrix
- Conservative GUI exercise plus required stateful workflows
- Optional dependency coverage

Failing gates:

- Registered tests: suite split is actionable, but not green.
- Crash gate: registered split contains crash, timeout, process failure,
  traceback, and process-error suites.
- Image diff workflow: approved visual manifests are legacy/incomplete and
  current checks fail.
- Test infrastructure: full-run provenance is still red for the current
  artifact set.

Missing gate:

- Manual smoke pass artifact: `/tmp/freecad-test-results/manual-smoke.json`

Gate evaluator self-test:

```sh
tools/ui_style_gate_selftest.py \
  --coverage-config tools/ui_style_coverage.default.json \
  --output /tmp/freecad-test-results/ui-style-gate-selftest.json
```

Observed result:

- Result: `ok`
- Scenario count: `41`
- Failed scenarios: `0`
- Proves clean synthetic evidence passes all gates.
- Proves partial dependency coverage blocks overall readiness.
- Proves registered-suite issues block overall readiness.
- Proves registered tracebacks, crashes, timeouts, process-error output, visual
  process failures, and visual unallowlisted tracebacks block the crash gate.
- Proves stale captures without discovered-workbench inventory block the visual
  gate.
- Proves screenshot integrity failures block the visual gate.
- Proves incomplete screenshot integrity self-tests block the visual gate.
- Proves failed or incomplete visual baseline harness self-tests block the
  visual gate.
- Proves dialog/task cleanup failures block the visual gate.
- Proves incomplete workflow coverage self-tests block the GUI exercise gate.
- Proves incomplete provenance and JSON-integrity self-tests block the
  infrastructure gate.
- Proves incomplete dependency smoke self-tests block dependency coverage.
- Proves incomplete CTest disabled/skipped inventory self-tests block the core
  test gate.
- Proves scene config validation errors block the visual gate.
- Proves top-level workbench coverage config errors block the visual gate.
- Proves stale visual-regression report formats and missing review-index files
  block the image-diff gate.
- Proves missing approve-after-change self-test coverage blocks the image-diff
  gate.
- Proves duplicate, blank, or otherwise invalid variant config blocks the
  matrix gate.
- Proves missing variant identity metadata blocks the matrix gate.
- Proves missing manual smoke blocks overall readiness.
- Proves incomplete manual-smoke validator self-tests block the manual smoke
  gate.

Visual coverage expectations are config-driven, not frozen in the evaluator.
`tools/ui_style_coverage.default.json` names the required major workbenches
and references the fixture, dialog, task-panel, and variant JSON configs. The
gate derives required screenshot names from those configs and from the
workbench inventory discovered by the current FreeCAD process.

Coverage config self-test:

```sh
tools/ui_style_coverage_selftest.py \
  --summary /tmp/freecad-test-results/baseline-summary.json \
  --results-dir /tmp/freecad-test-results \
  --output /tmp/freecad-test-results/ui-style-coverage-selftest.json
```

Observed result:

- Result: `ok`
- Scenarios: `14`
- Proves the default config passes current visual/matrix coverage.
- Proves a newly discovered workbench fails visual and matrix gates until it is
  captured.
- Proves adding a required fixture to the config fails visual and matrix gates.
- Proves empty required-workbench coverage fails visual and matrix gates.
- Proves blank and duplicate required workbench entries fail visual and matrix
  gates.
- Proves a missing fixture scene list fails visual and matrix gates.
- Proves missing checklist coverage tags for fixtures, dialogs, and task panels
  fail the visual gate.
- Proves untagged fixture scenes fail the visual gate.
- Proves duplicate fixture scene names fail visual and matrix gates.
- Proves blank dialog names, missing dialog actions, missing task workbenches,
  and missing task fixture files fail the visual gate.
- Proves adding a required variant to the config fails the matrix gate.
- Proves duplicate variant names fail the matrix gate.
- Proves blank variant names, invalid font scales, and missing preference packs
  fail the matrix gate.
- Proves newly required dialog and task scenes fail both the visual and matrix
  gates until captured for every required variant.

The human checklist is also mapped to a machine-readable requirement audit:

```sh
tools/ui_style_requirement_audit.py \
  --summary /tmp/freecad-test-results/baseline-summary.json \
  --gate /tmp/freecad-test-results/ui-style-gate.json \
  --coverage-selftest /tmp/freecad-test-results/ui-style-coverage-selftest.json \
  --gate-selftest /tmp/freecad-test-results/ui-style-gate-selftest.json \
  --requirement-audit-selftest /tmp/freecad-test-results/ui-style-requirement-audit-selftest.json \
  --run-status /tmp/freecad-test-results/ui-style-run-status.json \
  --run-status-selftest /tmp/freecad-test-results/ui-style-run-status-selftest.json \
  --output /tmp/freecad-test-results/ui-style-requirement-audit.json
```

Observed result:

- Overall status: `fail`
- Ready for sweeping style change: `false`
- Requirement counts: `5` pass, `3` fail, `1` missing
- Requirement spec coverage: `pass`; `9` expected, `9` actual, no missing,
  extra, duplicate, or retitled requirement rows.
- Supporting dependency coverage: `pass`
- Supporting coverage config self-test: `pass`
- Supporting gate evaluator self-test: `pass`
- Supporting requirement audit self-test: `pass`
- Supporting run-status self-test: `pass`
- Supporting full runner status: `fail`; the current full-run status has `10`
  failing required steps.

Requirement audit self-test:

```sh
tools/ui_style_requirement_audit_selftest.py \
  --output /tmp/freecad-test-results/ui-style-requirement-audit-selftest.json
```

Observed result:

- Result: `ok`
- Scenario count: `15`
- Expected requirement count: `9`
- Failed scenarios: `0`
- Proves all checklist requirements are present in the audit.
- Proves missing manual smoke and crash-gate failures keep the audit red.
- Proves image-diff audit evidence includes visual manifest quality, approval,
  context identity, review-index, and check failure details.
- Proves missing or failing artifact-provenance selftests keep the audit red.
- Proves missing or failing gate evaluator selftests keep the audit red.
- Proves missing or failing requirement audit selftests keep the audit red.
- Proves missing or failing run-status selftests keep the audit red.
- Proves failing full-run status keeps the audit red.
- Proves adding a new requirement to the requirement spec fails until the audit
  maps it.
- Proves retitling a requirement fails spec coverage.

Final run-status self-test:

```sh
tools/ui_style_run_status_selftest.py \
  --output /tmp/freecad-test-results/ui-style-run-status-selftest.json
```

Observed result:

- Result: `ok`
- Scenario count: `13`
- Failed scenarios: `0`
- Proves all-zero required step statuses pass.
- Proves missing and nonzero required step statuses fail.
- Proves missing current run ids, stale per-step run ids, and missing command
  files fail.
- Proves runner `run_step` entries are discovered and deduplicated.
- Proves duplicate runner `run_step` names fail the final run-status report.
- Proves known approve-only steps are optional only when absent, and checked
  when present.

Baseline runner self-test:

```sh
python3 tools/run_ui_test_baseline_selftest.py \
  --output /tmp/freecad-test-results/run-ui-test-baseline-selftest.json
```

Observed result:

- Result: `ok`
- Scenario count: `8`
- Failed scenarios: `0`
- Proves `run_step` keeps redirected JSON clean.
- Proves runner cleanup does not delete approved visual manifests or unrelated
  probe/doc-inventory artifacts.
- Proves broad GUI interaction remains conservative around combo boxes, item
  views, file dialogs, and unmanaged modal/task-panel state.
- Proves visual approval requires reviewer and approval-note metadata in both
  runner commands and docs.
- Proves approval guard runtime behavior rejects
  `FREECAD_BASELINE_APPROVE_MISSING=1` unless reviewer and note are supplied.
- Proves visual manifests with missing approval metadata, missing
  scene-context identity, lax policy, absolute screenshot paths, or missing
  files are detected as needing reapproval, while complete manifests are left
  alone.
- Proves the runner's final shell exit requires final run-status, final
  requirement-audit, and final JSON integrity success.

Artifact provenance self-test:

```sh
python3 tools/artifact_provenance_selftest.py \
  --output /tmp/freecad-test-results/artifact-provenance-selftest.json
```

Observed result:

- Result: `ok`
- Scenario count: `8`
- Failed scenarios: `0`
- Proves clean provenance passes.
- Proves missing run-id markers fail.
- Proves stale run-id markers fail.
- Proves missing required artifacts fail.
- Proves directory paths cannot stand in for run-id marker files.
- Proves directory paths cannot stand in for required artifact files.
- Proves artifacts modified after their step run-id marker fail.
- Proves an empty current `run.id` fails provenance.

JSON artifact integrity reports now include both a `checked_count` and the
exact relative `checked` path list. This prevents an include-list mistake from
being hidden behind a plausible count. Include lists reject duplicate patterns
and path traversal outside the results directory, so required artifacts cannot
be accidentally double-counted or satisfied by files outside the baseline root.
The final JSON integrity report is run after the final run-status and
requirement-audit files are written, and checks `8` final JSON artifacts.

JSON artifact integrity self-test:

```sh
python3 tools/json_artifact_integrity_selftest.py \
  --output /tmp/freecad-test-results/json-artifact-integrity-selftest.json
```

Observed result:

- Result: `ok`
- Scenario count: `5`
- Failed scenarios: `0`
- Proves strict JSON files pass.
- Proves prefixed/non-JSON output fails.
- Proves include lists ignore unowned JSON files.
- Proves duplicate include patterns fail.
- Proves path-traversal include patterns fail.

Failing or missing checklist requirements:

- Registered FreeCAD tests are actionable but not green:
  `TestArch`, `TestDraftGui`, `Workbench`, `TestRubberbandSelection`,
  `TestCoinSelectionVisual`, `TestArchGui`, `TestSketcherGui`, and
  `TestCAMGui`.
- Crash gate has hard failures from registered-test crash, timeout, process
  failure, traceback, and process-error suites.
- Image diff workflow is failing: workbench, fixture, matrix, dialog, and task
  manifests currently lack approval metadata and scene-context identities, and
  their current visual checks have unapproved failures.
- Manual smoke pass is missing.

Create a manual-smoke artifact template with:

```sh
tools/manual_smoke.py write-template \
  /tmp/freecad-test-results/manual-smoke.json \
  --summary /tmp/freecad-test-results/baseline-summary.json
```

After completing the human smoke pass, fill in tester/build/environment
metadata, completion time, notes, and evidence for every required check. Mark
every required check as `pass`. Validate it with:

```sh
tools/manual_smoke.py validate \
  /tmp/freecad-test-results/manual-smoke.json \
  --summary /tmp/freecad-test-results/baseline-summary.json
```

The evaluator requires schema `freecad-ui-style-manual-smoke-v2`, tester,
created/completed timestamps, build metadata, environment metadata, matching
required check descriptions, `pass` status for all checks, non-empty notes, and
at least one evidence entry for every required smoke check. It also requires
the artifact's FreeCAD version, git revision, and build directory to match the
current baseline summary. `fail`, `blocked`, stale-build, future-dated, or
incomplete checks keep the gate failed. Placeholder notes and placeholder
evidence such as `synthetic://`, `placeholder://`, `todo://`, `TODO`, `TBD`,
`N/A`, or `none` are rejected. Extra unrecognized manual checks are rejected so
the artifact cannot hide gaps by adding unrelated passing rows. Local path and
`file://` evidence must exist and must be modified during the recorded manual
smoke window, so stale files from an older baseline cannot prove the current
manual pass. `http(s)` review links are allowed but cannot be timestamp-checked
locally.

Manual smoke validator self-test:

```sh
tools/manual_smoke_selftest.py \
  --summary /tmp/freecad-test-results/baseline-summary.json \
  --output /tmp/freecad-test-results/manual-smoke-selftest.json
```

Observed result:

- Result: `ok`
- Scenario count: `18`
- Failed scenarios: `0`
- Verified pass scenario:
  - valid manual smoke artifact for the current baseline build
- Verified fail scenarios:
  - stale build metadata
  - stale run metadata
  - missing baseline run metadata
  - future completion time
  - missing per-check evidence
  - `blocked` check status
  - `fail` check status
  - missing required check row
  - changed required check description
  - placeholder evidence
  - stale local file evidence
  - missing evidence file path
  - unsupported evidence URI scheme
  - placeholder notes
  - stale evidence hint
  - too-new local file evidence
  - extra unrecognized check row

### GUI Inventory

Command:

```sh
tools/gui_interaction_harness.py tools/freecad_venv.sh \
  --output-dir /tmp/freecad-test-results/gui-survey-venv \
  --mode survey \
  --max-workbenches 0 \
  --timeout 900
```

Observed result:

- Result: `ok`
- `20` workbenches activated
- `39039` total events
- `10153` actions observed
- `28864` widgets observed
- `7631` discoverable targets
- `1654` risky targets skipped
- `29592` disabled/hidden targets skipped

This is currently the strongest automated source for UI surface inventory. It
can prove that a workbench starts and that exposed Qt objects exist. It cannot
prove that every lazy dialog, task panel, or workflow is reachable or usable.

### GUI Exercise

Command:

```sh
tools/gui_interaction_harness.py tools/freecad_venv.sh \
  --output-dir /tmp/freecad-test-results/gui-exercise-venv \
  --mode exercise \
  --max-workbenches 0 \
  --max-interactions 50 \
  --max-targets 500 \
  --timeout 1200
```

Observed result:

- Result: `ok` for the conservative bounded pass
- `503` events recorded
- Bounded by `50` interactions or `500` scanned targets
- `1` workbench activated before the target cap
- `2` control changes
- Risky/stateful targets are skipped, including file/session commands, web/help
  launches, task-dialog commands, task-panel creation commands, theme changes,
  and menu-bearing toolbar buttons

The earlier broad exercise attempts exposed real hazards: stale Qt wrappers,
accidental browser launch, task-dialog shutdown crashes in Part/Measure, and
long-running BIM/IFC state toggles. The default exercise pass is now deliberately
conservative.

Dedicated stateful workflow command:

```sh
tools/gui_interaction_harness.py tools/freecad_venv.sh \
  --output-dir /tmp/freecad-test-results/gui-workflows-venv \
  --mode workflows \
  --timeout 300
```

Observed workflow result:

- Result: `ok`
- `5` named workflows passed:
  - `switch_workbench`
  - `create_body`
  - `reopen_document`
  - `sketcher_cancel_task`
  - `partdesign_accept_task`
- The workflow run records `workflow_pass` events in
  `/tmp/freecad-test-results/gui-workflows-venv/events.jsonl`.

Required workflow names are read from `tools/gui_workflows.default.json` through
`tools/ui_style_coverage.default.json`, not hardcoded in the gate. The workflow
config is validated: blank required workflow names and duplicate required
workflow names fail the GUI exercise gate. Required workflow detail events must
occur inside that workflow's `workflow_started`/`workflow_pass` window, so
stale detail events from a previous or later flow cannot satisfy the gate.

Workflow coverage self-test:

```sh
tools/gui_workflow_coverage_selftest.py \
  --summary /tmp/freecad-test-results/baseline-summary.json \
  --results-dir /tmp/freecad-test-results \
  --output /tmp/freecad-test-results/gui-workflow-coverage-selftest.json
```

Observed result:

- Result: `ok`
- Scenario count: `11`
- Failed scenarios: `0`
- Proves the default required workflows pass.
- Proves adding a required workflow without a detail contract fails config
  validation.
- Proves adding a required workflow with a detail contract fails until runtime
  events satisfy it.
- Proves missing required workflow details fail.
- Proves workflow details outside the start/pass window fail.
- Proves explicit `workflow_fail` events fail.
- Proves duplicate workflow start/pass events fail.
- Proves malformed workflow event JSON fails.
- Proves workflow event paths that are directories fail.
- Proves invalid detail contracts, duplicate workflow names, and blank workflow
  names fail config validation.

The task close path currently records `resetEdit` because these task panels did
not expose a Python `Gui.Control.activeDialog()` object in this run. This proves
enter/close task-state coverage, but not a literal button-level OK/Cancel click.

### Visual Workbench Capture

Command:

```sh
tools/gui_visual_baseline_harness.py tools/freecad_venv.sh \
  --output-dir /tmp/freecad-test-results/gui-visual-venv \
  --max-workbenches 0 \
  --window-size 1600 1000 \
  --timeout 600
```

Observed result:

- Result: `ok`
- `20` workbenches discovered from the running FreeCAD process
- `20` workbench scenes captured
- Discovered and captured workbench sets match; no workbench is silently
  omitted from the workbench baseline
- Each scene produced a PNG screenshot and JSON metadata file
- Captured PNGs are valid `1854 x 1011` RGB images in this environment
- Captured visible widget count and initial layout findings per scene
- Current aggregate: `1134` initial layout findings across all scenes
- This capture was taken before the OpenSCAD dependency refresh; dependency
  smoke is now green, but a full baseline run is required to refresh visual
  workbench logs and screenshots under the new environment.

The capture summary records both `discovered_workbenches` and
`captured_workbenches`. The readiness gate fails if a successful workbench
capture lacks that inventory, if a discovered workbench is missing a screenshot,
or if the theme/DPI/font matrix omits a discovered workbench scene.

### Visual Fixture Capture

Command:

```sh
tools/gui_visual_baseline_harness.py tools/freecad_venv.sh \
  --output-dir /tmp/freecad-test-results/gui-visual-fixtures \
  --scene-config tools/gui_visual_scenes.default.json \
  --no-workbenches \
  --window-size 1600 1000 \
  --timeout 900
```

Observed result:

- Result: `ok`
- `9` fixture-backed scenes captured
- Covered representative documents for Part, PartDesign, Sketcher, Draft, BIM,
  FEM, CAM, Spreadsheet, and TechDraw
- Each scene produced a PNG screenshot and JSON metadata file
- Captured PNGs are valid `1854 x 1011` RGB images in this environment
- Current aggregate: `587` initial layout findings across fixture scenes

The default fixture list lives in `tools/gui_visual_scenes.default.json`. It is
intentionally data-driven: adding or replacing representative documents should
not require a new harness script.

### Visual Theme/DPI/Font Matrix

Command:

```sh
tools/gui_visual_baseline_harness.py tools/freecad_venv.sh \
  --output-dir /tmp/freecad-test-results/gui-visual-matrix \
  --scene-config tools/gui_visual_scenes.default.json \
  --dialog-config tools/gui_visual_dialogs.default.json \
  --task-config tools/gui_visual_tasks.default.json \
  --variant-config tools/gui_visual_variants.default.json \
  --max-workbenches 0 \
  --window-size 1600 1000 \
  --timeout 1200
```

Default variants:

- `default`
- `freecad-light`, seeded from the real `FreeCAD Light` preference pack
- `freecad-dark`, seeded from the real `FreeCAD Dark` preference pack
- `high-dpi`, using `QT_SCALE_FACTOR=1.5` and `QT_FONT_DPI=144`
- `large-font`, using a `1.25` application font scale

Observed result:

- A full matrix run captured `215` scenes: `5` variants multiplied by `43`
  scene suffixes (`20` discovered workbench scenes, `9` fixture scenes, `4`
  dialog scenes, and `10` task-panel/domain scenes).
- The run completed without process crashes, nonzero FreeCAD exits, or Python
  tracebacks.
- The current matrix regression manifest is legacy/incomplete: it approved
  `145` scenes from the older fixture/workbench-only matrix, so the matrix
  regression check remains red until the expanded dialog/task matrix baseline
  is reviewed and approved.
- The readiness gate verifies every required variant contains all required
  representative fixture scenes, dialog scenes, task-panel/domain scenes,
  configured major-workbench scenes, and every workbench discovered by the
  current FreeCAD process. Current required scene suffix count per variant:
  `43`.
- The matrix summary records the captured variant identity, and the gate checks
  it against `tools/gui_visual_variants.default.json`: light/dark variants must
  show their preference-pack paths, `high-dpi` must show `QT_SCALE_FACTOR=1.5`
  and `QT_FONT_DPI=144`, and `large-font` must show `font_scale=1.25`.
- Variant config is validated before the matrix gate passes: variant names must
  be non-empty and unique, `font_scale` must be a positive number, and
  `preference_pack` paths must exist. Relative preference-pack paths resolve
  from the repository root, matching the capture harness.
- Fixture, dialog, and task-panel scene configs are validated before the visual
  gate passes: scene names must be non-empty and unique, required scene fields
  must be present, dialog scenes must declare an action, and referenced fixture
  or task files must exist.
- Fixture, dialog, and task-panel scenes also declare checklist coverage tags.
  The visual gate fails when required coverage categories such as `part`,
  `preferences`, or `cam-setup-tool` are missing from the scene configs.

The harness now records each FreeCAD child process log, counts Python
tracebacks, and marks the capture `process_failed` when unallowlisted
tracebacks appear. Fixture scenes run before passive workbench cycling to avoid
state leakage from workbench activation into document loading.

Visual baseline harness self-test:

```sh
tools/gui_visual_baseline_harness_selftest.py \
  --output /tmp/freecad-test-results/gui-visual-baseline-harness-selftest.json
```

Observed result:

- Result: `ok`
- Scenario count: `9`
- Failed scenarios: `0`
- Proves stale visual summaries, screenshots, and variant subdirectories are
  removed before a new capture.
- Proves duplicate fixture/dialog/task scene names, output-name collisions,
  empty scene output slugs, duplicate selected workbenches, and duplicate
  variant slugs fail preflight before screenshots can be overwritten or merged.

### Screenshot Integrity

Command:

```sh
tools/gui_screenshot_integrity.py \
  --capture-dir /tmp/freecad-test-results/gui-visual-venv \
  --capture-dir /tmp/freecad-test-results/gui-visual-fixtures \
  --capture-dir /tmp/freecad-test-results/gui-visual-matrix \
  --capture-dir /tmp/freecad-test-results/gui-visual-dialogs \
  --capture-dir /tmp/freecad-test-results/gui-visual-tasks \
  --output /tmp/freecad-test-results/gui-screenshot-integrity.json
```

Observed result:

- Result: `ok`
- Capture sets checked: `5`
- Screenshots checked: `258`
- Failure count: `0`
- The validator fails capture summaries whose source result is not `ok`, scene
  rows that recorded capture errors, missing screenshot paths, missing PNG
  files, unreadable PNGs, too-small images, low-variance/blank-looking
  captures, too-few sampled colors, metadata screen-size mismatches, missing
  captured-widget metadata, scenes with no visible widgets, screenshot or
  metadata paths outside the capture directory, and duplicate screenshot or
  metadata paths.

Screenshot integrity self-test:

```sh
tools/gui_screenshot_integrity_selftest.py \
  --output /tmp/freecad-test-results/gui-screenshot-integrity-selftest.json
```

Observed result:

- Result: `ok`
- Scenario count: `12`
- Failed scenarios: `0`
- Proves valid captures pass.
- Proves blank, missing, and too-small screenshots fail.
- Proves metadata screen-size mismatches fail.
- Proves missing captured-widget metadata fails.
- Proves zero visible-widget metadata fails.
- Proves failed source capture summaries fail.
- Proves scene-level capture errors fail.
- Proves screenshot and metadata paths outside the capture directory fail.
- Proves duplicate screenshot and metadata paths fail.

The readiness gate consumes both the screenshot integrity report and its
self-test. Visual baseline coverage does not pass if screenshots are merely
listed in JSON but missing, unreadable, blank, or geometrically implausible.

### Visual Dialog Capture

Command:

```sh
tools/gui_visual_baseline_harness.py tools/freecad_venv.sh \
  --output-dir /tmp/freecad-test-results/gui-visual-dialogs \
  --dialog-config tools/gui_visual_dialogs.default.json \
  --no-workbenches \
  --window-size 1600 1000 \
  --timeout 300
```

Observed result:

- Result: `ok`
- `4` modal dialog scenes captured
- Covered Preferences, non-native file open, file-open return behavior, and
  non-native file save-as
- Captured widgets:
  - `Gui::Dialog::DlgPreferencesImp` titled `Preferences`
  - `Gui::FileDialog` titled `Open Document`
  - `Gui::FileDialog` titled `Save FreeCAD Document`
- The current dialog regression manifest is legacy/incomplete: it approved `3`
  older dialog scenes, so the dialog regression check remains red until the
  fourth file-open return-path scene is reviewed and approved.
- Each dialog scene requires the expected dialog class and visible text before
  capture. The visual gate also requires cleanup evidence and currently reports
  no missing or failed dialog cleanup.

Modal dialog commands are handled by scheduling screenshot and close timers
before invoking the command. This avoids the Preferences hang where
`Std_DlgPreferences` enters its modal event loop before the driver would
normally reach the capture call.

### Visual Task-Panel Capture

Command:

```sh
tools/gui_visual_baseline_harness.py tools/freecad_venv.sh \
  --output-dir /tmp/freecad-test-results/gui-visual-tasks \
  --task-config tools/gui_visual_tasks.default.json \
  --no-workbenches \
  --window-size 1600 1000 \
  --timeout 300
```

Observed result:

- Result: `ok`
- `10` stateful task-panel/domain scenes captured
- Covered Sketcher edit mode, PartDesign Pad edit parameters, Draft edit,
  BIM Window edit, TechDraw Page/View edit, FEM solver/material edit, CAM Job
  setup, and CAM tool selection
- Captured visible task widgets include:
  - `SketcherGui::TaskSketcherMessages`
  - `SketcherGui::TaskSketcherConstraints`
  - `SketcherGui::TaskSketcherElements`
  - `PartDesignGui::TaskPadParameters`
  - `PartDesignGui::TaskPreviewParameters`
  - `Gui::TaskView::TaskEditControl`
  - `Gui::TaskView::TaskBox`
  - `TechDrawGui::QGVPage`
  - `TechDrawGui::MDIViewPage`
  - `MatGui::MaterialTreeWidget`
  - `Gui::TaskView::TaskPanel`
- The task-panel regression manifest covers `10` scenes, but it is still
  legacy/incomplete approval data and the current regression check remains red
  until it is reviewed and regenerated with required approval metadata and
  scene-context identity.
- Each task scene requires expected domain widget classes to be visible before
  capture. The visual gate also requires cleanup evidence and currently reports
  no missing or failed task cleanup.
- Three task scenes had transient windows/notifications before teardown
  (`task-fem-edit-solver`, `task-cam-setup`, and `task-cam-tool`), and all
  three reported `after_count: 0` after cleanup.

Task-panel scenes are fixture-driven: they open a known document, activate the
target workbench, optionally select a named object, enter edit mode or run a
named command, require expected domain widget classes to be visible, capture
the main window, and then reset edit mode during teardown.

The visual gate checks required task scene names, not just counts. Required CAM
coverage includes both `task-cam-setup` and `task-cam-tool`. The
`task-cam-tool` scene creates the real CAM toolbit selector widget directly
because the `CAM_ToolBitDock` command path timed out under the harness.

### Visual Regression Approval

Create or update an approved manifest from an intentional baseline:

```sh
tools/gui_visual_regression.py approve \
  --capture-dir /tmp/freecad-test-results/gui-visual-venv \
  --manifest /tmp/freecad-test-results/gui-visual-approved.json \
  --reviewer "<name>" \
  --approval-note "<why this visual baseline is intentional>"
```

Approval writes a format-2 manifest and copies approved PNGs into a sibling
baseline-image directory, for example
`/tmp/freecad-test-results/gui-visual-approved.baseline-images`. The manifest
stores paths relative to the manifest location. This keeps approved visual data
portable and reviewable instead of pointing at transient capture screenshots.
The full baseline runner does not auto-create these manifests unless
`FREECAD_BASELINE_APPROVE_MISSING=1` is set with both
`FREECAD_BASELINE_APPROVER` and `FREECAD_BASELINE_APPROVAL_NOTE`. Approval
metadata must name a reviewer and explain why the current screenshots are the
intended baseline; placeholder text is rejected by the checker and readiness
gate.

Check a new capture against that manifest:

```sh
tools/gui_visual_regression.py check \
  --capture-dir /tmp/freecad-test-results/gui-visual-venv \
  --manifest /tmp/freecad-test-results/gui-visual-approved.json \
  --diff-dir /tmp/freecad-test-results/gui-visual-diffs
```

Each check writes both `review-index.json` and `review-index.html` under the
diff directory. The image-diff gate requires those referenced review-index
files to exist, so a readiness report cannot pass with only placeholder paths
or missing diff-review artifacts.

Fixture scenes use the same approval/check workflow with:

```sh
tools/gui_visual_regression.py approve \
  --capture-dir /tmp/freecad-test-results/gui-visual-fixtures \
  --manifest /tmp/freecad-test-results/gui-visual-fixtures-approved.json \
  --reviewer "<name>" \
  --approval-note "<why this fixture baseline is intentional>"

tools/gui_visual_regression.py check \
  --capture-dir /tmp/freecad-test-results/gui-visual-fixtures \
  --manifest /tmp/freecad-test-results/gui-visual-fixtures-approved.json \
  --diff-dir /tmp/freecad-test-results/gui-visual-fixtures-diffs
```

Matrix scenes use a separate manifest:

```sh
tools/gui_visual_regression.py approve \
  --capture-dir /tmp/freecad-test-results/gui-visual-matrix \
  --manifest /tmp/freecad-test-results/gui-visual-matrix-approved.json \
  --reviewer "<name>" \
  --approval-note "<why this matrix baseline is intentional>"

tools/gui_visual_regression.py check \
  --capture-dir /tmp/freecad-test-results/gui-visual-matrix \
  --manifest /tmp/freecad-test-results/gui-visual-matrix-approved.json \
  --diff-dir /tmp/freecad-test-results/gui-visual-matrix-diffs
```

Dialog scenes use a separate manifest:

```sh
tools/gui_visual_regression.py approve \
  --capture-dir /tmp/freecad-test-results/gui-visual-dialogs \
  --manifest /tmp/freecad-test-results/gui-visual-dialogs-approved.json \
  --reviewer "<name>" \
  --approval-note "<why this dialog baseline is intentional>"

tools/gui_visual_regression.py check \
  --capture-dir /tmp/freecad-test-results/gui-visual-dialogs \
  --manifest /tmp/freecad-test-results/gui-visual-dialogs-approved.json \
  --diff-dir /tmp/freecad-test-results/gui-visual-dialogs-diffs
```

Task-panel scenes use a separate manifest:

```sh
tools/gui_visual_regression.py approve \
  --capture-dir /tmp/freecad-test-results/gui-visual-tasks \
  --manifest /tmp/freecad-test-results/gui-visual-tasks-approved.json \
  --reviewer "<name>" \
  --approval-note "<why this task-panel baseline is intentional>"

tools/gui_visual_regression.py check \
  --capture-dir /tmp/freecad-test-results/gui-visual-tasks \
  --manifest /tmp/freecad-test-results/gui-visual-tasks-approved.json \
  --diff-dir /tmp/freecad-test-results/gui-visual-tasks-diffs
```

Policy:

- Exact pixels are not required.
- Default image thresholds are `max_changed_ratio: 0.03` and `max_rms: 8.0`.
- The checker and readiness gate reject manifests that make these thresholds
  more permissive than the defaults.
- Approved baseline PNGs are copied beside the manifest and referenced by
  relative paths.
- The readiness gate fails old or non-portable manifests that still reference
  absolute screenshot paths.
- Approved scenes store a `scene_context_fingerprint` derived from the captured
  scene config, variant, and active workbench. The checker and readiness gate
  fail old manifests that lack this fingerprint, and fail checks where the
  current scene context differs from the approved context.
- Existing layout findings are approved by stable fingerprints.
- Fixed layout findings are accepted.
- New layout findings fail until fixed or explicitly approved.
- Missing approved scenes and unapproved new scenes fail.
- Captures with `result` other than `ok` cannot be approved or checked.
- Unallowlisted Python tracebacks in FreeCAD process output mark visual captures
  as `process_failed`.
- Intentional sweeping visual changes should update the manifest in review,
  not loosen the assertions silently.

Regression workflow self-test:

```sh
tools/gui_visual_regression_selftest.py \
  --output /tmp/freecad-test-results/gui-visual-regression-selftest.json
```

Observed result:

- Result: `ok`
- Scenario count: `14`
- Approved self-test manifest format: `2`
- Absolute screenshot paths in self-test manifest: `0`
- Missing context fingerprints in self-test manifest: `0`
- Missing context identities in self-test manifest: `0`
- Approval metadata present in self-test manifest: `true`
- Current approved visual manifests are legacy/incomplete and not yet
  approval-quality:
  - workbench manifest: `20` missing scene-context identities and no approval
    metadata
  - fixture manifest: `9` missing scene-context identities and no approval
    metadata
  - matrix manifest: `145` older fixture/workbench-only scenes, missing
    scene-context identities and no approval metadata; the current matrix
    capture contains `215` scenes
  - dialog manifest: `3` older dialog scenes, missing scene-context identities
    and no approval metadata; the current dialog capture contains `4` scenes
  - task manifest: `10` missing scene-context identities and no approval
    metadata
- Verified pass scenarios:
  - identical capture
  - small image drift within thresholds
  - harness-only metadata changes that do not alter the represented workflow
  - large intentional visual change after reapproval
  - new layout finding after reapproval
- Verified fail scenarios:
  - large image change
  - new layout finding
  - missing approved scene
  - unapproved new scene
  - changed scene context with otherwise matching screenshot
  - overly permissive manifest policy
  - manifest missing scene-context fingerprints
  - manifest missing scene-context identities
  - manifest missing approval metadata

The image-diff gate consumes this self-test report. It no longer proves only
that the current approved captures match; it also proves the checker catches
the main failure modes expected during a style migration. The gate requires
the named self-test scenarios above, including the approve-after-change
scenario, so a future simplification that silently drops intentional-change
coverage blocks readiness.

Current implemented layout finding kinds:

- visible zero-size controls
- possible clipped text on labels/buttons
- low text contrast for enabled visible text controls
- visible controls outside parent bounds
- visible buttons with neither text nor icon
- obvious overlapping sibling controls
- task panels whose overflowing content has no visible/enabled scroll path

Runtime assertion smoke:

```sh
tools/gui_layout_assertion_smoke.py tools/freecad_venv.sh \
  --required-config tools/gui_layout_assertions.default.json \
  --output /tmp/freecad-test-results/gui-layout-assertion-smoke.json
```

Observed result:

- Result: `ok`
- Process return code: `0`
- Exercised finding kinds:
  - `zero_size`
  - `possible_text_clipping`
  - `missing_button_text_or_icon`
  - `low_text_contrast`
  - `outside_parent_bounds`
  - `obvious_sibling_overlap`
  - `task_panel_no_scroll_path`

The layout gate consumes this smoke report. It no longer passes merely because
the finding names appear in `gui_visual_baseline_driver.py`, or because a
smoke artifact sets a boolean flag. Each required assertion kind must include
at least one example finding whose `kind` matches the assertion, and the smoke
report itself must have result `ok`. Required assertion kinds are read from
`tools/gui_layout_assertions.default.json` through
`tools/ui_style_coverage.default.json`. The layout assertion config is
validated: blank and duplicate required assertion names fail the layout gate.

Layout assertion coverage self-test:

```sh
tools/gui_layout_assertion_coverage_selftest.py \
  --summary /tmp/freecad-test-results/baseline-summary.json \
  --results-dir /tmp/freecad-test-results \
  --output /tmp/freecad-test-results/gui-layout-assertion-coverage-selftest.json
```

Observed result:

- Result: `ok`
- Scenario count: `5`
- Failed scenarios: `0`
- Proves the default required layout assertions pass.
- Proves adding a required layout assertion to config fails the layout gate
  until that assertion is observed.
- Proves duplicate and blank required assertion entries fail config validation.
- Proves a failed layout smoke result fails the layout gate even if examples
  are present.

## Dependency Coverage

Command:

```sh
tools/freecad_dependency_smoke.py \
  --config tools/optional_dependencies.default.json \
  --output /tmp/freecad-test-results/freecad-dependency-smoke.json
```

Observed result:

- Result: `ok`
- Missing dependency count: `0`
- OpenCamLib is available through Ubuntu package `python3-opencamlib`
  (`2023.01.11-4build3`).
- OpenSCAD is available through Ubuntu package `openscad` (`2021.01-6build4`).

These dependencies are now present for CAM rotary/generator/post coverage and
OpenSCAD import/export or executable-backed GUI paths.

The optional dependency list is read from
`tools/optional_dependencies.default.json`, not hardcoded in the smoke script.
The smoke checker validates that config before trusting it: dependency names
must be unique, kinds must be supported, Python modules/executables must name
their probe target, and every dependency must include non-empty `affects`
coverage text. Duplicate or placeholder `affects` entries are rejected so a
dependency cannot claim vague or repeated coverage. Invalid dependency config
is a hard gate failure, not a partial coverage warning.

Dependency smoke self-test:

```sh
tools/freecad_dependency_smoke_selftest.py \
  --output /tmp/freecad-test-results/freecad-dependency-smoke-selftest.json
```

Observed result:

- Result: `ok`
- Scenario count: `10`
- Failed scenarios: `0`
- Proves present Python modules and executables are detected.
- Proves missing Python modules and executables are reported.
- Proves the report is `partial` when any configured dependency is missing.
- Proves duplicate dependency names, missing/placeholder/duplicate `affects`,
  and unsupported dependency kinds fail config validation.

## What Is Testable Now

- C++ and core App/Base/Part/Sketcher/Spreadsheet/etc. unit behavior through
  CTest.
- Registered Python app and GUI tests are split by suite with per-suite
  timeout/crash/traceback/process-error classification.
- Basic FreeCAD GUI startup through `tools/freecad_venv.sh`.
- Workbench activation and passive Qt inventory for exposed widgets/actions.
- Workbench and representative-document screenshot baselines for the current
  configured scene set.
- Theme/DPI/font variant screenshot capture as test data, with hard failure on
  unallowlisted process tracebacks.
- Screenshot artifact integrity: missing, unreadable, blank/low-variance,
  too-small, metadata-mismatched, and no-visible-widget captures fail before
  visual regression approval is trusted.
- Preferences and non-native file open/save dialog screenshots.
- Sketcher, PartDesign, Draft, BIM, TechDraw, FEM, CAM setup, and CAM tool
  task-panel/domain screenshots.
- Dedicated stateful workflow coverage for workbench switching, PartDesign body
  creation, document reopen, Sketcher task close, and PartDesign Pad task close.
- Specific scripted flows that are explicitly written and verified.

## What Is Not Testable Reliably Yet

- Full `FreeCAD -t 0` completion in this environment.
- Full registered-test green status: the suite split is actionable, but
  currently reports crash/timeout/process-failure/traceback issue suites.
- Broad unbounded clicking across all workbenches.
- Lazy task panels and dialogs beyond the current Sketcher, PartDesign, Draft,
  BIM, TechDraw, FEM, Preferences, and file-dialog coverage.
- Complete visual correctness of style changes across all task panels and
  dialogs beyond the initial covered set.
- Command-launched CAM tool-panel automation is not reliable yet:
  `CAM_ToolBitDock` timed out under the harness. CAM tool visual coverage is
  still captured through direct construction of the real toolbit selector
  widget.
- Text clipping, low text contrast, zero-size controls, missing button
  icon/text, parent-bound overflow, obvious sibling overlap, and missing
  task-panel scroll paths are captured for the current scene set. Pixel-level
  icon contrast, custom-painted viewport text, and uncaptured dialogs/task
  panels still need stronger coverage.
- Viewport interaction quality: drag, selection, tool manipulators, and modal
  workflows.
- Literal task-panel OK/Cancel button activation remains weaker than task-state
  enter/close coverage where active dialogs are not exposed to Python.
- Risky file/session/preference/addon commands skipped by the harness.

## Required Data Before Large Style Changes

A style migration should not proceed on the existing test battery alone. Add
or collect these artifacts first:

1. Expand the representative `.FCStd` fixture list beyond the initial Part,
   PartDesign, Sketcher, Draft/BIM, TechDraw, FEM, CAM, and Spreadsheet
   coverage.
2. Expand screenshot baselines for remaining task panels, property editor,
   combo/list popups, report/tree views, and
   domain-specific dialogs beyond the current covered set.
3. Keep extending DPI, font-size, and theme variants as new visual surfaces are
   added to `gui_visual_baseline_harness.py`.
4. Keep tuning automated layout assertions for visible widgets as more surfaces
   are added.
5. Extend contrast checks to icons, custom-painted viewport text, and other
   surfaces where palette roles do not describe the rendered pixels.
6. A stable allowlist/denylist for risky GUI actions.
7. Checked-in or otherwise reproducible approved manifests for intentional
   visual changes.
8. A dependency report that records optional packages and skipped suites.
9. A validated `manual-smoke.json` artifact for interactions that remain too
   stateful for automation.

## Confidence Statement

The current baseline gives high confidence for core non-visual behavior and
moderate confidence that many workbenches can be loaded and inventoried. It
does not give high confidence that large visual/style changes will avoid
rendering something unusable. The harness now detects common layout and text
contrast regressions, but the approved baseline still contains existing
findings and the uncovered dialogs, viewport interactions, and
registered-test failures above remain blocking gaps.
