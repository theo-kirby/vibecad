# VibeCAD Goals Spec

## Comprehensive Goal: Native Autonomous CAD Operator

### Objective

Make VibeCAD a FreeCAD-native AI operator that can use the same visible,
workbench-scoped tools a human would use to create, inspect, revise, assemble,
and verify real CAD work inside existing FreeCAD workbenches.

The AI must not be a separate workbench, a text-only assistant, a dead-end
questionnaire, or a shortcut layer that bypasses normal CAD workflows. It should
act as a persistent operator inside FreeCAD: read the active document, choose
reasonable defaults when the user has not supplied details, use explicit native
tools, continue after each tool result, inspect the viewport visually, and keep
working until the requested design is actually present in FreeCAD or a real
blocker is reached.

### Product Promise

A user can ask for useful CAD outcomes such as:

- "Create a 10 mm square sketch."
- "Design a desktop robot arm using NEMA 17 motors."
- "Make me a compact quadcopter drone frame."
- "Design an RC car chassis."
- "Create a printable electronics enclosure with screw bosses and vents."
- "Make a bracket with bolt holes and fillets."
- "Create a wing rib with lightening holes."
- "Lay out a small gearbox assembly."
- "Open this existing model and make the mounting holes larger."

VibeCAD should drive FreeCAD toward a completed model, assembly, drawing,
analysis, or modification using the available workbench tools. If required
information is missing, VibeCAD should make reasonable engineering assumptions
and proceed, only asking the user when a decision materially changes the design
or cannot be inferred safely.

### Non-Negotiable Behavior

- VibeCAD is integrated into existing FreeCAD workbenches and panels. It must
  not be a standalone AI workbench.
- The VibeCAD panel is a normal dockable FreeCAD panel, positioned with the
  existing dock/task-panel model and resizable by the user.
- The AI uses explicit FreeCAD tools equivalent to human operations. No hidden
  "make magic object" shortcuts should replace normal sketch, feature, part,
  placement, assembly, drawing, or inspection workflows.
- Tool calls continue as a loop. Choosing a plane, selecting an object, applying
  a feature, or receiving a tool result must not dead-end the session.
- Conversation state is persistent and document-associated so the AI can answer
  follow-up questions about what the user already asked and what it already did.
- Viewport screenshots are AI feedback, not user deliverables. The AI captures
  screenshots so it can inspect whether the model is visible, coherent,
  assembled, and usable before declaring the task done.
- Provider text is never accepted as proof. Acceptance is based on verified
  FreeCAD document state, tool traces, native objects, assemblies, screenshot
  files, report errors, and workflow-specific checks.
- A silent or unbounded provider run is a failure. Live AI runs need progress
  telemetry, bounded turns, visible tool trace updates, and clear timeout
  classification.

### Required Tool Surface

Core platform tools:

- create, open, save, and inspect documents
- inspect active workbench, selection, object tree, properties, placements, and
  report-view errors
- switch workbenches through native command paths when needed
- capture viewport screenshots for AI visual inspection
- maintain conversation, tool trace, action history, approvals, and undo state

Sketcher and PartDesign tools:

- create sketches on inferred or user-selected planes
- draw constrained lines, rectangles, circles, arcs, slots, and construction
  geometry
- apply dimensions and geometric constraints
- pad, pocket, revolve, loft, pattern, mirror, fillet, chamfer, and edit
  feature parameters through normal FreeCAD APIs
- create and maintain meaningful bodies, sketches, and feature names

Part and shape tools:

- create explicit primitive solids when that is the appropriate human operation
- set placement, orientation, rotations, and alignments
- cut holes, bores, vents, lightening features, and openings
- apply fillets, chamfers, shells, booleans, arrays, and patterns
- verify resulting shapes have nonzero volume and expected topology

Assembly tools:

- create native FreeCAD assemblies
- add components with meaningful labels and hierarchy
- place and orient components coherently
- create or prepare joint groups and assembly relationships
- summarize bill-of-material style component structure

Workbench-specific tools:

- Draft, BIM, TechDraw, FEM, CAM, Mesh, MeshPart, Surface,
  ReverseEngineering, Robot, Spreadsheet, Material, Inspection, OpenSCAD, and
  other workbench tool packs must expose the operations a human would naturally
  use in that workbench.
- Each tool pack must declare what is automatic, approval-gated, unsupported,
  and test-covered.

### Autonomous Workflow Requirements

For a design request, VibeCAD must:

1. Read the active document, workbench, selection, units, and prior
   conversation.
2. Decide whether to create a new document, modify the existing document, or ask
   for a real blocker.
3. Choose reasonable defaults for omitted dimensions, planes, component counts,
   materials, and layout when safe.
4. Execute native FreeCAD tool calls one step at a time.
5. Use visible equivalent operations: sketches for sketch-based parts,
   PartDesign features for feature-based bodies, Part/Assembly operations for
   multi-component layouts, and workbench-native commands where applicable.
6. After each meaningful tool result, refresh context and continue.
7. For complex objects, create multiple named components, place them coherently,
   add details, and assemble them.
8. Capture a viewport screenshot for the AI to inspect before finalizing.
9. Continue revising if the document state, screenshot, or report errors show
   missing geometry, placeholder-only output, broken features, invisible models,
   bad placement, or incomplete assembly.
10. Finish only when verified FreeCAD state satisfies the user's request or when
    a specific blocker is reported with the exact missing capability.

### Acceptance Scenarios

These scenarios define the minimum useful bar. A scenario does not pass because
the provider says it passed; it passes only when FreeCAD state proves it.

- 10 mm square sketch: creates a real sketch on a reasonable default plane,
  draws a constrained 10 mm by 10 mm square, and can answer follow-up questions
  from saved conversation state.
- Desktop NEMA 17 robot arm: creates named base, motor mounts, shoulder, upper
  arm, elbow, forearm, wrist, and end-effector components; places them as a
  coherent mechanism; creates a native assembly; captures a viewport screenshot
  for AI inspection; and verifies component count and visibility.
- Drone frame: creates a central plate, four arms, motor mounts, battery/flight
  controller mounting provisions, holes/patterns, and a coherent assembly or
  part hierarchy.
- RC car chassis: creates a chassis plate, wheel positions, axle/motor mounting
  areas, battery tray, servo/steering provisions, holes, fillets, and sensible
  dimensions.
- Electronics enclosure: creates base and lid geometry, wall thickness, screw
  bosses, venting, cable openings, fillets/chamfers, and separable components.
- Bracket: creates a sketch/feature-based part with correct dimensions, bolt
  holes, edge treatment, and verified solid geometry.
- Wing rib: creates an airfoil-like rib profile, spar slots, lightening holes,
  thickness, and verified cutouts.
- Gearbox: creates housing, shaft positions, gears or gear placeholders with
  correct relative placement, bearing/mounting holes, and assembly hierarchy.
- Existing-model edit: opens or uses an existing document, identifies relevant
  geometry, applies the requested modification, verifies object diffs, and
  preserves unrelated document content.

### Verification Gates

Every accepted scenario must include:

- deterministic unit or integration tests for the exposed tools
- a real FreeCAD GUI/Xvfb audit where UI or viewport behavior matters
- document-state assertions for object count, labels, type IDs, placements,
  volumes/topology, sketches, constraints, features, assemblies, and report
  errors as applicable
- screenshot capture for AI visual inspection when the request creates or
  changes visible geometry
- negative tests proving out-of-scope and unsafe tools are blocked
- timeout tests proving provider/tool stalls cannot hang FreeCAD
- live-provider acceptance tests for at least one complex workflow, with
  progress telemetry and bounded failure reporting

### Current Verified Status

- The deterministic robot assembly GUI audit passes in real FreeCAD under Xvfb:
  it creates one native assembly with 11 modeled components and captures a
  nonempty viewport screenshot for AI inspection.
- The full `TestVibeCAD` suite currently passes: 138 tests.
- The right-side dockable VibeCAD panel behavior is covered by GUI tests and a
  runtime audit. The prompt runner now streams progress events into the dock
  output/status while the provider loop runs, including context reads, provider
  turns, and tool calls, instead of only showing a wait cursor and final text.
- The provider tool surface now includes explicit placement, cylindrical cut,
  fillet, chamfer, primitive-dimension editing, Sketcher dimension-constraint editing,
  PartDesign sketch creation, PartDesign Pad, Pocket, and Revolution creation from sketches,
  native PartDesign Fillet and Chamfer edge finishing,
  PartDesign feature-dimension editing, atomic Sketcher line/circle/arc/slot/constraint
  tools, Draft array/pattern creation, assembly creation and incremental
  component addition, sketch rectangle, document creation/opening, iterative
  object deletion, safe workbench command tools, and a provider-visible
  tool-shape report.
- Viewport screenshots now include a compact provider-readable visual
  observation: sampled foreground ratio, foreground bounding box, center
  offset, blank/nonblank classification, and an inspection summary. The
  screenshot completion gate no longer accepts a saved PNG path alone; the
  screenshot must produce nonblank visual evidence that can feed the next
  provider turn.
- `core.get_tool_shape_report` lets VibeCAD explain its current provider-visible
  CAD capability envelope, missing CAD tool classes, active-workbench command
  sample, and why a result can degrade into primitive geometry when richer
  native tools are not exposed yet.
- The autonomous session loop now has gates for assemblies, screenshots, and
  requested detail/edit/pattern tools so object count alone is not enough.
  Follow-up correction prompts such as changing the length of an existing
  primitive, sketch dimension, or PartDesign feature now require a real edit
  tool in the trace: `part.set_primitive_dimensions`,
  `sketcher.set_constraint_value`, or `partdesign.set_feature_dimensions`.
  Repeated-feature scenarios such as drones, RC cars, vents, bolt-hole
  patterns, and wing ribs require an explicit pattern tool: `draft.create_array`
  for Part/Draft component arrays, `partdesign.linear_pattern` for repeated
  feature-history details, `partdesign.polar_pattern` for bolt circles or
  radial feature-history details, and `partdesign.mirror_feature` for symmetric
  feature-history details.
- Iterative editing is covered by a conversation-backed test: VibeCAD first
  creates a 10 mm cube named `Editable block`, then a follow-up request changes
  the existing object to 20 mm long through `part.set_primitive_dimensions`
  while preserving the original width and height.
- Feature-history editing is now covered by focused tests: VibeCAD edits an
  existing Sketcher dimension datum in place, creates a native PartDesign Pad
  from an existing sketch, creates native Pocket, Revolution, AdditiveLoft,
  AdditivePipe, LinearPattern, PolarPattern, and Mirrored features, applies
  native PartDesign Fillet and Chamfer features, and changes the existing Pad
  length through `partdesign.set_feature_dimensions`.
- Small-step CAD operation is now covered by focused tests: VibeCAD adds
  individual Sketcher lines, circles, arcs, and slot profiles, applies native horizontal,
  vertical, distance, and radius constraints, inspects the resulting sketch, and can
  delete a named/labelled object through `core.delete_object` to correct a bad
  modeling step instead of stacking replacement geometry.
- Edge detailing is covered through provider-runner tests for both
  `part.apply_fillet` and `part.apply_chamfer`, with explicit chamfer/bevel
  prompts gated on `part.apply_chamfer` instead of accepting fillet as a proxy.
- Printable enclosure wall thickness is covered by `part.apply_thickness`, a
  native Part Thickness operation that removes selected faces and applies an
  inward or outward shell thickness instead of leaving enclosure bodies solid.
- Material appearance is covered by `material.apply_appearance`, which directly
  assigns native document-local `ShapeMaterial` color and transparency so
  assemblies can be visually differentiated for both users and AI screenshot
  inspection.
- Assembly construction now has a small-step tool: `assembly.add_component`
  adds one existing object at a time to a native Assembly after creation, with
  tests covering label lookup, internal-name lookup, and duplicate-safe adds.
- A live OpenAI provider acceptance run for the robot-arm scenario now passes a
  stricter verified FreeCAD state gate with the repository `.env` key. The
  `OpenAIAgentsProvider` created 24 document objects, one native assembly with
  14 components, a captured viewport screenshot, and a tool trace proving use
  of `part.set_placement`, `part.cut_cylindrical_hole`, and
  `part.apply_fillet`. The harness records progress events for context
  building, provider turns, tool calls, provider timeouts, assembly creation,
  and screenshot capture, and writes a result JSON file before using immediate
  process exit to avoid FreeCAD GUI shutdown crashes in the standalone audit.
  Remaining live-quality caveat: the model still spends multiple provider
  turns creating primitives before details and assembly, so the next
  improvement is a stronger planner/executor structure and richer detail tools
  for patterns, rotations, feature-based PartDesign workflows, and the drone,
  RC car, enclosure, bracket, wing rib, gearbox, and existing-model scenarios.

### Definition of Done

VibeCAD is ready for broad style/UI refactors only when the test battery can
answer, with evidence, which FreeCAD workflows are covered, which are not, and
whether visual output remains usable. For the AI product itself, VibeCAD is not
done until it can autonomously complete and verify multi-part workflows such as
robot arms, drones, RC cars, enclosures, brackets, wing ribs, gearboxes, and
existing-model edits through native FreeCAD tools with persistent conversation,
AI screenshot inspection, bounded provider execution, and clear failure
reporting.

## Goal 0: Product Definition

### Objective

Define VibeCAD as a FreeCAD-native AI subsystem integrated into the existing
FreeCAD workbenches. It can inspect, explain, modify, and verify FreeCAD
documents through structured tool calls without requiring users to switch to a
separate AI workbench.

### Success Criteria

- VibeCAD has a clear product boundary: native FreeCAD feature integrated into
  existing workbenches, not an external Codex workflow and not a standalone AI
  workbench.
- Codex is documented as a development tool, not the user-facing runtime.
- The first provider is OpenAI, but the internal architecture supports a
  provider abstraction.
- User-facing behavior is tool-driven, reversible, and workbench-aware.

### Deliverables

- `docs/vibecad-guiding-spec.md`
- `docs/vibecad-goals.md`
- Initial terminology:
  - VibeCAD AI Subsystem
  - VibeCAD Workbench Integration
  - VibeCAD Session
  - VibeCAD Tool
  - VibeCAD Tool Pack
  - VibeCAD Transaction
  - VibeCAD Approval

### Non-Goals

- Do not create or register a standalone VibeCAD workbench.
- Do not build a general chat client.
- Do not require users to install or understand Codex.
- Do not expose arbitrary Python execution to normal users by default.

### Current Implementation Status

- VibeCAD is implemented as a shared native Python subsystem under `Mod/VibeCAD`
  and is registered into existing FreeCAD workbenches through their `InitGui.py`
  files.
- No standalone VibeCAD workbench is registered.
- A shared assistant panel, preferences page, auth status command, approval
  queue, provider abstraction, OpenAI Agents SDK provider, and offline provider
  exist.
- The preferences page includes a user API-key setup/logout path. Secrets are
  stored only through an optional OS keyring backend when available; if keyring
  is unavailable VibeCAD reports that state and does not fall back to plaintext
  FreeCAD parameters. Environment variables and configured `.env` files remain
  supported for developer and CI use.
- Workbench tool packs exist for the integrated workbenches, with scoped provider
  tool exposure based on the active workbench.
- Verified model-facing tools are direct native function tools, scoped by active
  workbench. Proposal tools are not registered in the provider surface.
  Current coverage includes document lifecycle, context/screenshot inspection,
  Sketcher geometry and constraints, PartDesign features, Part direct solids
  when explicitly enabled, Draft arrays, material appearance, TechDraw pages and
  views, Assembly objects/components, and read-only summaries for the integrated
  workbenches.
- Provider-safe CAD operations execute directly inside the bounded VibeCAD tool
  loop. Queue/proposal-style functions are excluded from OpenAI request dumps
  and provider-visible tool schemas.
- Current focused validation: 135 VibeCAD tests pass under Xvfb, including the
  runtime workbench tool-pack audit, provider tool-scope checks, and native GUI
  action exposure checks for representative C++-backed and Python-backed
  workbenches.
  Deterministic provider-loop coverage proves that `run_prompt` passes scoped
  direct tool schemas and a scoped tool runner to the provider, that provider
  requests contain precise function tools rather than a generic dispatcher, and
  that out-of-scope workbench tools are blocked. The installed venv currently has
  the `agents` module available and `openai` 2.44.0. The OpenAI Agents provider
  now runs in a bounded child process with a parent-side VibeCAD tool bridge so
  SDK/network/tracing stalls cannot hang the FreeCAD UI process; a deterministic
  subprocess test proves child-process tool calls are bridged back into the
  parent VibeCAD tool runner. A live
  OpenAI-backed `run_prompt` smoke using the repository `.env` key returned
  through `OpenAIAgentsProvider`, reported the active workbench, produced no
  pending actions, and did not leak the API key into context. The assistant
  panel now shows the active workbench context instead of every workbench
  context at once, and this is covered by a GUI regression test. A checked-in
  Xvfb audit script, `tools/vibecad_assistant_panel_runtime_audit.py`, now
  activates every runtime workbench, opens the shared VibeCAD assistant through
  the integrated command path, verifies all required assistant controls, checks
  the active workbench and tool-pack labels, verifies the provider tool-trace
  panel, and proves that only the active workbench's domain context is visible.
  Its latest run passed for 20 runtime workbenches with zero failures. The
  provider tool loop now records a local, redacted tool-call trace on each
  `VibeCADResponse`, and the assistant panel renders that trace beside the
  approval queue and action history. Applied and rejected proposals are visible
  in a native action-history panel, and that history is included in provider
  context. Unit coverage proves scoped provider calls, approval-backed
  proposals, blocked out-of-scope calls, visible trace/history panel state,
  document-transaction undo of an applied VibeCAD action, and approving plus
  undoing a queued proposal through the assistant panel with document context
  refresh. Local session state can be cleared from the assistant panel without
  mutating the document; coverage proves pending actions, action history,
  screenshot attachment state, prompt text, and tool trace display are cleared.
  Applied action results now include transaction-level document
  snapshots, object-count deltas, created/deleted/changed object summaries, and
  best-effort report-view error summaries; the native history panel surfaces the
  verification status and object delta. `core.get_report_view_errors` exposes
  report-view diagnostics as a provider-safe read tool, report errors are
  included in prompt context, and the assistant panel includes a native report
  diagnostics box. Tool packs can now be disabled independently through the
  preferences page; disabled workbench packs keep core read tools available but
  hide/block workbench-owned provider tools and contextual mutation proposals,
  and the assistant panel reports the active pack as disabled. Document,
  command, and workbench-object context payloads are bounded and include
  truncation metadata so large documents preserve true counts without dumping
  unbounded object lists into the provider prompt. The assistant panel now
  exposes a native provider-run status, disables prompt/provider/screenshot
  controls while a request is active, restores them after completion, and has
  GUI coverage proving that busy state. The OpenAI Agents subprocess wait loop
  now pumps Qt events from the parent process while waiting for model output,
  and coverage proves both event pumping during delayed SDK runs and stable
  timeout classification. The shared assistant now opens and refreshes when an
  integrated FreeCAD workbench is activated, so switching workbenches surfaces
  the native AI panel without requiring the user to find a separate command.
  The approval controls now include a native Revise step that loads the selected
  pending action into the prompt as a structured revision request while keeping
  the original action pending. The assistant UI has been reorganized into
  native tabs for Chat, Actions, Context, Tools, and Diagnostics; visual captures
  verify the user-facing Chat panel instead of only checking that raw debug
  widgets exist. The Chat panel now includes a native quick-prompt selector and
  insert button for common active-workbench tasks, with GUI coverage proving the
  inserted prompt is scoped to the active workbench. A live OpenAI-backed smoke
  through the repository `.env` key returned
  through `OpenAIAgentsProvider`, bridged a real `core.get_active_document` tool
  call, recorded it in `tool_trace`, and did not leak the API key. A separate
  Xvfb probe verified all five VibeCAD actions in menus and toolbars for every
  activatable runtime workbench. Workbench registration now also adds a native
  `VibeCAD` context-menu group with selection-aware entry points (`Explain
  Selection`, `Open AI Assistant`, and `Ask AI`), and unit coverage verifies that
  existing workbench registrations attach this group without creating a VibeCAD
  workbench. Visual task scenes now capture the VibeCAD assistant in Part and
  Draft workbench contexts, require the tool-trace, report diagnostics,
  action-history, undo, clear-session, and viewport screenshot controls, and
  screenshot integrity passes for those captures. The
  assistant panel can now attach a viewport screenshot to provider context
  through `core.capture_view_screenshot`, and GUI coverage proves the captured
  PNG is written, tracked in context, and does not expose `OPENAI_API_KEY`. Auth
  coverage now includes fake-keyring storage/read/delete, redaction, absence of
  plaintext fallback when keyring is unavailable, preservation of non-secret
  preferences only, validated/invalid/offline credential-validation states using
  the documented bearer-auth `/v1/models` request path, and GUI coverage proving
  the preferences `Save Key`, `Validate`, and `Logout` controls use the keyring
  and validation paths, clear typed keys, redact status text, and do not write
  API keys into FreeCAD parameters. A live validation smoke using the repository
  `.env` key returned `verified` from the OpenAI API without printing the key.
  Earlier GUI/provider smokes cover Part, Mesh,
  Points, Draft, PartDesign, TechDraw, FEM, CAM, Material, Assembly, BIM,
  Inspection, OpenSCAD, Surface, ReverseEngineering, Robot, and MeshPart
  panel/provider paths. MeshPart has native tools, a tool pack, and
  panel context, but this FreeCAD build does not register `MeshPartWorkbench` as
  activatable because `Gui.addWorkbench` remains commented in
  `src/Mod/MeshPart/InitGui.py`; MeshPart provider smoke therefore uses explicit
  MeshPart tool-pack scope.
- Runtime workbench audit under Xvfb currently reports:
  `AssemblyWorkbench`, `BIMWorkbench`, `CAMWorkbench`, `DraftWorkbench`,
  `FemWorkbench`, `InspectionWorkbench`, `MaterialWorkbench`, `MeshWorkbench`,
  `NoneWorkbench`, `OpenSCADWorkbench`, `PartDesignWorkbench`, `PartWorkbench`,
  `PointsWorkbench`, `ReverseEngineeringWorkbench`, `RobotWorkbench`,
  `SketcherWorkbench`, `SpreadsheetWorkbench`, `SurfaceWorkbench`,
  `TechDrawWorkbench`, and `TestWorkbench`.
- GUI modules without runtime workbenches in this build include AddonManager,
  Help, Import, JtReader, Measure, Start, Tux, TemplatePyMod, and MeshPart.
  MeshPart still receives explicit VibeCAD tool-pack coverage because it exposes
  native MeshPart APIs and an `InitGui.py` workbench class, even though the
  workbench registration is disabled.
- Material note: `Materials.MaterialManager()` hung during an automatic probe in
  this build, so Material workbench context must not call material-library scans
  during assistant panel refresh or prompt context construction.

## Goal 1: Native Platform Integration Shell

### Objective

Create the shared FreeCAD-native VibeCAD service layer and integrate the first AI
affordances into existing workbenches.

### Required Features

- Shared VibeCAD Python service module loaded by FreeCAD without network calls.
- Preferences page for AI settings and auth state.
- Context-sensitive assistant panel that follows the active workbench.
- Status indicator for auth/model/tool-loop state.
- Empty session state.
- Workbench integration API used by existing workbenches.
- First command entries registered into existing workbenches:
  - explain current selection
  - ask AI in current workbench
  - open AI assistant panel
  - open VibeCAD preferences
  - show auth status

### Acceptance Criteria

- VibeCAD does not create or register a standalone workbench.
- At least one existing workbench exposes native AI commands.
- The shared assistant panel opens and closes without errors.
- Preferences page opens and persists non-secret settings.
- Existing workbench activation tests remain green.
- No network call is made during workbench activation or command registration.

### Tests

- Add registered GUI test for AI command registration in an existing workbench.
- Add preference open/close test.
- Add visual baseline scene for the assistant panel inside an existing workbench.

## Goal 2: Authentication

### Objective

Provide persistent, safe authentication for OpenAI-backed VibeCAD sessions.

### Required Features

- Auth state machine:
  - `not_configured`
  - `configured_unverified`
  - `verified`
  - `invalid`
  - `offline`
- Read `OPENAI_API_KEY` for developer mode.
- User-entered API key setup flow.
- OS keyring storage when available.
- Logout/revoke local credential.
- Credential validation call.
- Redacted logging.

### Acceptance Criteria

- User can configure an API key once and stay logged in across FreeCAD restarts.
- API key is not stored in FreeCAD user parameters.
- API key is not written to document files, logs, crash reports, screenshots, or
  tool traces.
- Missing key produces a clear offline/no-auth state.
- Invalid key produces a clear recoverable error.

### Tests

- Fake-keyring unit tests.
- Environment variable auth tests.
- Redaction tests.
- Preference persistence tests.
- Offline mode tests.

### Open Questions

- Which keyring dependency is acceptable for all FreeCAD packaging targets?
- Do we need a no-dependency encrypted fallback, or should fallback be
  environment-variable-only?

## Goal 3: Provider Runtime

### Objective

Implement the first AI runtime using a native Python provider abstraction.

### Required Features

- `VibeCadProvider` interface.
- OpenAI provider implementation.
- Model configuration.
- Streaming response support.
- Retry and timeout policy.
- Provider error normalization.
- Tool schema export.
- Tool-result submission.

### Acceptance Criteria

- VibeCAD can send a read-only prompt and display a response.
- Provider workflow confidence comes from real OpenAI live acceptance tests;
  deterministic provider doubles are limited to error and invariant tests.
- Provider calls can be disabled in offline mode.
- Timeouts and API errors do not freeze the FreeCAD UI.

### Tests

- Real OpenAI live acceptance tests.
- Timeout tests.
- Error mapping tests.
- UI responsiveness smoke test.
- No-auth blocks provider call test.

### Non-Goals

- Do not implement multi-agent orchestration yet.
- Do not hardcode OpenAI request details into UI code.

## Goal 4: Session and Context Model

### Objective

Create a compact, structured representation of the active FreeCAD state for AI
requests.

### Required Features

- `VibeCadSession`
- `VibeCadContextBuilder`
- Active document summary.
- Active workbench summary.
- Selection summary.
- Object property summary.
- View/camera summary.
- Report-view error summary.
- Optional viewport screenshot capture.

### Acceptance Criteria

- Context can be generated without network access.
- Context is bounded in size.
- Context does not include secrets.
- Context updates when selection or active document changes.
- Screenshots are included only when explicitly requested or needed by the
  selected workflow.

### Tests

- Context generation tests with empty document.
- Context generation tests with selected objects.
- Redaction tests.
- Screenshot opt-in tests.
- Large-document truncation tests.

## Goal 5: Core Tool Registry

### Objective

Implement the central tool registry and the first set of cross-workbench tools.

### Required Core Tools

- `core.get_active_document`
- `core.get_document_tree`
- `core.get_selection`
- `core.get_object_properties`
- `core.get_object_shape_summary`
- `core.get_view_state`
- `core.capture_viewport`
- `core.list_workbenches`
- `core.activate_workbench`
- `core.list_workbench_commands`
- `core.get_report_view_errors`

### Acceptance Criteria

- Tools have stable names and JSON schemas.
- Tool arguments are validated before execution.
- Tool output is structured and serializable.
- Tool errors are captured and returned without crashing FreeCAD.
- Read-only tools can run without approval.

### Tests

- Schema validation tests.
- Tool dispatch tests.
- Tool error handling tests.
- Read-only tool no-mutation tests.

## Goal 6: Transactional Mutation Engine

### Objective

Allow AI-requested FreeCAD mutations through explicit, reversible transactions.

### Required Features

- `VibeCadExecutionEngine`
- `VibeCadApprovalController`
- Transaction wrapper.
- Mutation preview.
- Apply/reject flow.
- Undo last VibeCAD action.
- Affected-object reporting.
- Report-view error check after mutation.

### Initial Mutation Tools

- `core.set_property`
- `core.create_object`
- `core.run_freecad_command`
- `core.delete_object`
- `core.undo_last_vibecad_action`

### Acceptance Criteria

- Every mutation is wrapped in a FreeCAD transaction.
- User can reject a proposed mutation before it runs.
- User can undo an applied VibeCAD mutation.
- Destructive tools require explicit confirmation.
- Failed mutations roll back or leave a clear recovery path.

### Tests

- Transaction commit test.
- Transaction rollback test.
- Undo test.
- Rejected approval test.
- Destructive approval test.
- Failed mutation recovery test.

## Goal 7: Existing Workbench AI Tool Packs

### Objective

Make VibeCAD native to each existing FreeCAD workbench by adding domain-specific
AI tool packs and UI integrations inside those workbenches.

### Required Existing Workbench Packs

VibeCAD must integrate into existing FreeCAD workbenches. It must not solve this
by adding a new AI workbench. Every runtime workbench returned by
`Gui.listWorkbenches()` must have a scoped native AI tool pack or an explicit
documented exclusion with a test.

Current required runtime packs:

1. Assembly
2. BIM
3. CAM
4. Draft
5. FEM
6. Inspection
7. Material
8. Mesh
9. NoneWorkbench
10. OpenSCAD
11. Part
12. PartDesign
13. Points
14. ReverseEngineering
15. Robot
16. Sketcher
17. Spreadsheet
18. Surface
19. TechDraw
20. Test

Current non-runtime explicit coverage:

1. MeshPart: provide native tool-pack, provider, panel, and tests even though
   this build does not register `MeshPartWorkbench` as activatable.

### Tool Pack Requirements

Each tool pack must define:

- tool schemas
- context builder extensions
- workbench-owned object filters
- object/property inspection tools
- approval-backed proposal tools
- task-panel context surfaces inside the existing workbench
- workbench-specific instructions
- safety policy
- focused tests
- example workflows
- unsupported operations

### Initial Acceptance Criteria

- VibeCAD can detect the active workbench.
- VibeCAD exposes only tools relevant to the active existing workbench by
  default.
- VibeCAD can switch tool packs when the active workbench changes.
- VibeCAD lists active-document objects owned by the active workbench tool pack.
- VibeCAD can inspect properties for a named active-document object.
- VibeCAD can propose low-risk workbench-owned object edits without applying
  them until user approval.
- Existing workbenches can register their own AI commands and task-panel
  integrations.
- Tool packs can be disabled independently.

### Initial Tool Pack Priority

1. Sketcher: constraints, geometry inspection, repair suggestions.
2. PartDesign: body/feature inspection, safe parameter edits.
3. Draft: simple 2D object creation and property edits.
4. BIM: object classification and host relationship inspection.
5. CAM: read-only job/tool/operation inspection first.

## Goal 8: Approval and Safety Policy

### Objective

Create a clear policy for which AI tools can run automatically and which require
user confirmation.

### Safety Levels

- `read`: automatic
- `view`: automatic
- `safe_write`: configurable
- `write`: confirmation required initially
- `destructive`: confirmation always required
- `external`: confirmation always required
- `developer`: disabled by default

### Acceptance Criteria

- Every tool declares a safety level.
- Approval UI shows tool name, arguments, affected objects, and expected result.
- User can approve once, approve for session, reject, or revise.
- Safety policy can be configured conservatively in preferences.
- Developer tools are hidden unless explicitly enabled.

### Tests

- Safety classification tests.
- Approval UI state tests.
- Confirm/reject/revise tests.
- Developer-tool disabled tests.

## Goal 9: Verification Loop

### Objective

Give VibeCAD a built-in way to check whether its actions worked.

### Required Features

- Capture viewport before/after action.
- Compare document object count and affected properties.
- Check report-view errors.
- Run focused registered tests when available.
- Ask model for post-action self-check with tool results.

### Acceptance Criteria

- VibeCAD reports whether a mutation appears successful.
- VibeCAD surfaces FreeCAD errors after an action.
- VibeCAD can suggest rollback when verification fails.
- Verification does not run expensive tests unless user approves.

### Tests

- Successful mutation verification test.
- Failed mutation verification test.
- Report-view error capture test.
- Screenshot capture test.

## Goal 10: Logging, Privacy, and Debugging

### Objective

Make VibeCAD diagnosable without leaking secrets or private model data.

### Required Features

- Redacted local audit log.
- Tool trace viewer.
- Provider request/response metadata without secrets.
- Optional prompt/debug mode for developers.
- Export diagnostic bundle with redaction.

### Acceptance Criteria

- API keys never appear in logs.
- User can clear local session history.
- Diagnostic export is opt-in.
- Screenshots are not persisted unless enabled.

### Tests

- No-secret-in-log tests.
- Clear-history test.
- Diagnostic redaction test.

## Goal 11: Packaging and Dependency Strategy

### Objective

Ship VibeCAD in a way that works with FreeCAD packaging constraints.

### Required Decisions

- Whether OpenAI SDK is vendored, optional, or installed externally.
- Whether keyring support is hard dependency or optional.
- Whether provider calls run in-process or via local sidecar.
- How Linux, Windows, and macOS credential stores are handled.

### Initial Recommendation

- Native Python in-process runtime for MVP.
- Optional dependency path for OpenAI SDK if packaging permits.
- No alternate fake or HTTP provider fallback for CAD work. If the OpenAI SDK
  packaging is blocked, VibeCAD must report the provider as unavailable and keep
  FreeCAD usable; live AI acceptance remains blocked until the real provider is
  available.
- Keyring optional but preferred.
- Environment-variable auth always supported for development and CI.

### Acceptance Criteria

- FreeCAD starts even if AI dependencies are missing.
- VibeCAD reports missing optional dependencies clearly.
- No import-time network calls.
- No workbench activation crash when provider dependencies are absent.

## Goal 12: Test Gate Integration

### Objective

Keep VibeCAD development inside the test-readiness system already created.

### Required Gates

- CTest
- registered split harness
- VibeCAD auth tests
- VibeCAD provider request-dump tests
- VibeCAD tool schema tests
- VibeCAD transaction tests
- GUI visual baseline scenes
- screenshot integrity
- UI/style readiness audit

### Acceptance Criteria

- VibeCAD has focused tests that can run without real OpenAI credentials.
- Real provider tests are opt-in.
- No test requires paid API usage by default.
- Visual baselines include:
  - logged-out panel
  - logged-in empty session
  - approval prompt
  - tool trace panel
  - workbench-specific panel state

## Goal 13: MVP Definition

### Objective

Deliver the smallest useful VibeCAD preview.

### MVP Features

- Shared VibeCAD AI subsystem.
- Context-sensitive assistant panel integrated into existing workbenches.
- Preferences page.
- Auth via `OPENAI_API_KEY` and user-entered key.
- OpenAI provider.
- Read-only AI questions about active document and selection.
- Core read-only tools.
- Viewport screenshot tool.
- Redacted tool trace.
- Offline/no-auth mode.

### MVP Non-Goals

- No automatic model mutation.
- No CAM post-processing.
- No arbitrary Python tool.
- No enterprise credential broker.
- No add-on workbench support.
- No multi-agent orchestration.

### MVP Acceptance Criteria

- User can log in or use `OPENAI_API_KEY`.
- User can ask, "What is selected?" and receive a correct answer.
- User can ask, "What is wrong with this document?" and receive context-aware
  guidance based on document state and report-view errors.
- User can attach a viewport screenshot to a request.
- VibeCAD works in offline/no-auth mode with clear status.
- CTest and registered split harness remain green.

## Goal 14: Mutation Preview Release

### Objective

Add safe, confirmed AI-driven edits.

### Required Features

- Proposed property edits.
- Proposed object creation.
- Transaction preview.
- Apply/reject.
- Undo.
- Post-action verification.

### Acceptance Criteria

- User can ask VibeCAD to create a simple object and approve the action.
- User can ask VibeCAD to change a selected object's property and approve the
  action.
- User can undo the VibeCAD action.
- VibeCAD reports verification results after the action.

## Goal 15: Existing-Workbench-Native Release

### Objective

Make VibeCAD meaningfully useful inside specific FreeCAD workbenches.

### Required Features

- Sketcher tool pack.
- PartDesign tool pack.
- Draft tool pack.
- BIM read-only plus low-risk tools.
- CAM read-only inspection tools.

### Acceptance Criteria

- Active existing workbench changes available tools, UI actions, and model
  context.
- Sketcher assistant can inspect constraints and suggest fixes.
- PartDesign assistant can inspect body/feature state.
- Draft assistant can create simple confirmed geometry.
- BIM assistant can inspect classification and host relationships.
- CAM assistant can inspect jobs without posting output.

## Global Done Criteria

VibeCAD is not considered ready for broad use until:

- auth is persistent and safe;
- no secret appears in logs or documents;
- AI can inspect active FreeCAD state through structured tools;
- mutations are undoable;
- destructive actions require confirmation;
- workbench-specific tools exist for the first priority workbenches;
- all VibeCAD tests run without real API credentials;
- CTest passes;
- registered split harness passes;
- visual baselines cover the VibeCAD UI states.
