# VibeCAD Live Acceptance Report

This report separates real OpenAI-backed CAD acceptance evidence from
deterministic tool and harness checks.

## Real OpenAI Acceptance Evidence

All rows below were produced by `OpenAIAgentsProvider` through
`tools/vibecad_live_acceptance_matrix.py` or
`tools/vibecad_live_provider_acceptance.py` using the configured local API key.
The request-dump gate requires schema `vibecad-openai-agents-request-v1`, no
generic dispatcher tool including `core.run_workbench_command`, no
`available_tools` context leak, and no proposal/queue functions. The current
gate also rejects provider tool menu context leaks; all rows below have current
strict no-dispatcher request-dump evidence.

| Scenario | Result | Objects | Bodies | Native PartDesign Features | Assembly/Components | TechDraw Pages/Views | Tools/Mutating | Screenshot | Timeouts | Request Dump | Evidence |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | --- |
| mechanical | PASS | 22 | 1 | 7 | 0/0 | 0/0 | 49/44 | yes | 0 | clean | `/tmp/vibecad-live-stale-categories-no-dispatcher-20260630-070032/mechanical/result.json` |
| partdesign | PASS | 19 | 1 | 6 | 0/0 | 0/0 | 29/24 | yes | 0 | clean | `/tmp/vibecad-live-stale-categories-no-dispatcher-20260630-070032/partdesign/result.json` |
| robot | PASS | 54 | 4 | 4 | 1/4 | 0/0 | 31/24 | yes | 0 | clean | `/tmp/vibecad-live-highrisk-strict-context-20260630-063501/robot/result.json` |
| drone | PASS | 59 | 4 | 8 | 1/4 | 0/0 | 36/31 | yes | 0 | clean | `/tmp/vibecad-live-stale-categories-no-dispatcher-20260630-070032/drone/result.json` |
| automotive | PASS | 21 | 1 | 6 | 0/0 | 0/0 | 41/37 | yes | 0 | clean | `/tmp/vibecad-live-stale-categories-no-dispatcher-20260630-070032/automotive/result.json` |
| aerospace | PASS | 17 | 1 | 4 | 0/0 | 0/0 | 29/24 | yes | 0 | clean | `/tmp/vibecad-live-stale-categories-no-dispatcher-20260630-070032/aerospace/result.json` |
| marine | PASS | 20 | 1 | 6 | 0/0 | 0/0 | 35/29 | yes | 0 | clean | `/tmp/vibecad-live-stale-categories-no-dispatcher-20260630-070032/marine/result.json` |
| enclosure | PASS | 37 | 2 | 6 | 1/2 | 0/0 | 30/21 | yes | 0 | clean | `/tmp/vibecad-live-enclosure-state-assembly-20260630-075443/enclosure/result.json` |
| assembly | PASS | 56 | 4 | 5 | 1/4 | 0/0 | 35/29 | yes | 0 | clean | `/tmp/vibecad-live-highrisk-strict-context-20260630-063501/assembly/result.json` |
| revision | PASS | 21 | 1 | 7 | 0/0 | 0/0 | 44/37 | yes | 0 | clean | `/tmp/vibecad-live-stale-categories-no-dispatcher-20260630-070032/revision/result.json` |
| documentation | PASS | 18 | 1 | 3 | 0/0 | 1/1 | 26/20 | yes | 0 | clean | `/tmp/vibecad-live-documentation-clean-context-20260630-063119/documentation/result.json` |
| rocket_engine | PASS | 48 | 3 | 6 | 1/3 | 0/0 | 32/26 | yes | 0 | clean | `/tmp/vibecad-live-highrisk-strict-context-20260630-063501/rocket_engine/result.json` |

## Live Tool-Shape Critique Evidence

The current process now asks the live model to critique its own context and
tool surface before adding more tools.

- Before fix: `tools/vibecad_sketcher_tool_shape_review.py` produced
  `/tmp/vibecad-sketcher-tool-shape-review.json`. The model reported that
  `core.report_tool_shape_gap` was referenced but not exposed as a callable
  function tool in Sketcher context, so it could not report gaps
  machine-readably.
- Fix: exposed `core.report_tool_shape_gap` in provider workbench contexts and
  expanded its schema to accept model-preferred fields:
  `tool_or_class`, `severity`, `why_blocks_quality`, `needed_schema`, and
  `needed_result_data`, while preserving existing compatibility fields.
- After fix: `tools/vibecad_sketcher_tool_shape_review.py` produced
  `/tmp/vibecad-sketcher-tool-shape-review-after-fix.json`. The live model saw
  `core.report_tool_shape_gap` in its 74-tool Sketcher surface and called it 12
  times. The model-reported top gaps were `sketcher.offset_geometry`,
  `sketcher.mirror_geometry`, ambiguous constraint target schemas, ambiguous
  `sketcher.add_slot` length semantics, rotate/scale transforms,
  `sketcher.carbon_copy`, `sketcher.clone_geometry`, conic/alternate geometry
  creation, `sketcher.join_curves`, B-spline editing, solver/DOF localization,
  and `sketcher.add_text`.
- After slot fix: `tools/vibecad_sketcher_tool_shape_review.py` produced
  `/tmp/vibecad-sketcher-tool-shape-review-after-slot-fix.json`. The model
  still saw the 74-tool Sketcher surface, called `core.report_tool_shape_gap`,
  and no longer reported `sketcher.add_slot` length semantics as a gap. Its
  remaining highest-priority gaps were offset/mirror derived-profile creation,
  rotate/scale/polar/clone transforms, carbon copy, conic tools, advanced
  B-spline/join-curve tools, sketch remap/reorient, generic constraint schema,
  regular polygon/profile constructors, and text geometry.

## Deterministic Regression Evidence

These tests do not claim AI design competence. They verify tool behavior,
provider-surface invariants, request-dump gates, and acceptance-harness checks.

Current prompt/tool-surface cleanup:

- Removed stale proposal-oriented wording from model-facing workbench tool-pack
  instructions.
- Tightened the provider instruction toward outcome-driven native FreeCAD
  operation without adding design-specific Python recipes.
- Confirmed the default provider model remains `gpt-5.5` and reasoning effort
  remains `high`; no turn-level provider timeout is configured by default.
- Reworked `core.get_tool_shape_report` to expose a structured Sketcher human
  command coverage matrix. It now reports covered Sketcher geometry,
  constraint, solver, profile-validation, trim/extend/split/fillet, and
  external-reference tools separately from real missing classes such as carbon
  copy, bulk copy/clone/transform, rectangular arrays, offsets, advanced
  B-spline editing, and text geometry.
- Added native `sketcher.delete_all_geometry` and
  `sketcher.delete_all_constraints` tools with explicit provider function-tool
  wrappers. Bulk Sketcher cleanup is now partially covered; axes-alignment
  cleanup is still reported as missing.
- Added native `sketcher.transform_geometry` with an explicit provider
  function-tool wrapper. Bulk translation is now available in both Sketcher and
  PartDesign-scoped sketch context.
- Added native `sketcher.copy_geometry` with an explicit provider function-tool
  wrapper.
- Added native `sketcher.rectangular_array` with an explicit provider
  function-tool wrapper. Sketcher duplicate/copy/rectangular-array workflows are
  now partially covered; clone/linked duplicate behavior remains reported as
  missing.
- Added native `sketcher.mirror_geometry` and `sketcher.offset_geometry` with
  explicit provider function-tool wrappers. The Sketcher offset/derived-profile
  coverage row now reports covered instead of missing for offset and mirror.
- Exposed and reshaped `core.report_tool_shape_gap` so the live model can
  report tool/context weaknesses during a provider run.
- Addressed the live model's `sketcher.add_slot` length-semantics critique:
  `length` is now optional and explicitly documented as overall end-to-end
  length. The tool accepts explicit `overall_length`, `center_distance`, and
  `length_mode`. Results now return `overall_length`, `center_distance`,
  `straight_segment_length`, `radius`, `arc_centers`, `profile_points`, and a
  full slot bounding box.
- Added state-based provider tool scoping for active requests. This does not
  choose design intent from prompts; it only routes visible function tools by
  current FreeCAD state. Verified examples: Sketcher with no active sketch now
  exposes 15 of 76 Sketcher-scoped tools, and PartDesign setup exposes 15 of 96
  PartDesign-scoped tools. Full workbench inventories remain available for
  reports and tests, but active OpenAI requests receive the smaller scoped
  `provider_tool_schemas` plus `provider_tool_scope` metadata. The
  model-visible scope includes active tool names and counts, but not the full
  omitted-tool menu.
- Further split active Sketcher and PartDesign scopes by document/sketch/body
  state. Current static phase sizes are: Sketcher no-sketch 15, geometry
  authoring 28, open-profile authoring 48, constraint solving 45, and
  feature/revision 69. PartDesign setup is 15, sketch authoring 29, profile
  authoring 53, constraint solving 50, base feature creation 23, and
  feature/revision 36. These are state gates only; they do not infer design
  features from prompt text.
- Added a request-construction regression proving the `agent.tools` list is
  built from the active scoped surface. In PartDesign setup, the request tool
  list includes setup tools such as `partdesign.create_body` and
  `partdesign.create_sketch`, and excludes later-phase tools such as
  `sketcher.add_line` and `partdesign.pad_sketch`.
- Added a PartDesign state regression that creates a real Body, real Sketch,
  constrained rectangle, and native Pad. Before the Pad, the request surface is
  `partdesign_base_feature_creation` and exposes native feature creation such
  as Pad/Pocket/Revolve while excluding Sketcher authoring and feature-revision
  tools. After the Pad exists, the surface advances to
  `partdesign_feature_and_revision` and exposes feature revision/pattern tools
  while excluding low-level Sketcher constraint/edit tools.
- Added an autonomous-loop regression proving the scoped surface refreshes
  between provider turns after real document mutation. A first turn in
  `partdesign_setup` can create a Body, then the next turn receives
  `partdesign_sketch_authoring` with Sketcher authoring tools exposed.

Current focused command:

```bash
timeout 300s tools/freecad_venv.sh tools/vibecad_selected_tests.py \
  TestVibeCAD.TestVibeCADPreferences.test_preferences_normalize_reasoning_effort \
  TestVibeCAD.TestVibeCADCore.test_service_has_core_read_tools \
  TestVibeCAD.TestVibeCADCore.test_openai_provider_request_uses_precise_function_tools_not_generic_dispatcher \
  TestVibeCAD.TestVibeCADCore.test_openai_request_tool_list_uses_active_scoped_surface \
  TestVibeCAD.TestVibeCADCore.test_provider_context_tool_is_explicit_module_backed_function_tool \
  TestVibeCAD.TestVibeCADCore.test_openai_provider_has_no_inline_function_tool_context_helper \
  TestVibeCAD.TestVibeCADCore.test_provider_safe_tool_schemas_expose_only_command_write_tools \
  TestVibeCAD.TestVibeCADCore.test_provider_tool_modules_cover_provider_safe_tools \
  TestVibeCAD.TestVibeCADCore.test_provider_tool_registry_contains_only_direct_model_tools \
  TestVibeCAD.TestVibeCADCore.test_provider_safe_tool_schemas_are_workbench_scoped \
  TestVibeCAD.TestVibeCADCore.test_provider_tool_scope_reduces_sketcher_no_sketch_surface \
  TestVibeCAD.TestVibeCADCore.test_provider_tool_scope_progresses_sketcher_by_state_not_prompt \
  TestVibeCAD.TestVibeCADCore.test_provider_tool_scope_reduces_partdesign_setup_surface \
  TestVibeCAD.TestVibeCADCore.test_provider_tool_scope_progresses_partdesign_by_model_state \
  TestVibeCAD.TestVibeCADCore.test_autonomous_loop_refreshes_scoped_tool_surface_between_turns \
  TestVibeCAD.TestVibeCADCore.test_part_primitive_provider_tools_are_opt_in \
  TestVibeCAD.TestVibeCADCore.test_provider_tool_runner_rejects_part_primitives_in_partdesign \
  TestVibeCAD.TestVibeCADCore.test_tool_shape_report_explains_available_and_missing_provider_capabilities \
  TestVibeCAD.TestVibeCADCore.test_native_sketcher_tools_create_edit_and_delete_geometry \
  TestVibeCAD.TestVibeCADCore.test_typed_sketcher_constraint_and_move_tools_execute_natively \
  TestVibeCAD.TestVibeCADCore.test_sketcher_slot_accepts_explicit_center_distance
```

Result: `21/21` passed.

Targeted live-critique feedback-tool command:

```bash
timeout 300s tools/freecad_venv.sh tools/vibecad_selected_tests.py \
  TestVibeCAD.TestVibeCADCore.test_provider_safe_tool_schemas_expose_only_command_write_tools \
  TestVibeCAD.TestVibeCADCore.test_provider_tool_modules_cover_provider_safe_tools \
  TestVibeCAD.TestVibeCADCore.test_provider_safe_tool_schemas_are_workbench_scoped \
  TestVibeCAD.TestVibeCADCore.test_provider_can_report_tool_shape_gaps_during_run \
  TestVibeCAD.TestVibeCADCore.test_provider_can_report_tool_shape_gap_with_model_preferred_fields
```

Result: `5/5` passed.

Last focused command:

```bash
timeout 300s tools/freecad_venv.sh tools/vibecad_selected_tests.py \
  TestVibeCAD.TestVibeCADCore.test_loop_requirements_do_not_parse_prompt_for_scenario_gates \
  TestVibeCAD.TestVibeCADCore.test_loop_requirements_require_assembly_for_multi_body_state \
  TestVibeCAD.TestVibeCADCore.test_provider_safe_tool_schemas_expose_only_command_write_tools \
  TestVibeCAD.TestVibeCADCore.test_provider_tool_registry_contains_only_direct_model_tools \
  TestVibeCAD.TestVibeCADCore.test_provider_safe_tool_schemas_are_workbench_scoped \
  TestVibeCAD.TestVibeCADCore.test_live_provider_acceptance_reports_request_dump_evidence
```

Result: `6/6` passed.

Build and syntax checks:

```bash
python3 -m py_compile src/Mod/VibeCAD/VibeCADProvider.py src/Mod/VibeCAD/VibeCADWorkbenchTools.py
python3 -m py_compile src/Mod/VibeCAD/tool_impl/sketcher/delete_all_geometry.py src/Mod/VibeCAD/tool_impl/sketcher/delete_all_constraints.py src/Mod/VibeCAD/tool_impl/service/core_get_tool_shape_report.py
python3 -m py_compile src/Mod/VibeCAD/VibeCADSession.py src/Mod/VibeCAD/TestVibeCAD.py tools/vibecad_live_provider_acceptance.py tools/vibecad_live_acceptance_matrix.py
cmake --build build/release --target VibeCADScripts -j$(nproc)
cmake --build build/release -j$(nproc)
```

Result: passed.
