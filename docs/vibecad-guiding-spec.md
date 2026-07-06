# VibeCAD Guiding Spec

## Purpose

VibeCAD is a FreeCAD-native AI subsystem that integrates model creation,
inspection, repair, styling, and automation directly into the existing FreeCAD
workbenches instead of forcing users into a separate AI workbench or external
chatbot.

The core product promise is:

> A user stays inside Sketcher, PartDesign, Draft, BIM, CAM, TechDraw, FEM, or
> any other existing workbench; VibeCAD appears as native commands, task-panel
> assistance, context-menu actions, and a context-sensitive assistant that can
> inspect the active document, choose and execute direct native FreeCAD tools,
> iterate through small verified CAD changes, and verify the result.

Codex remains useful as a development and maintenance tool for the VibeCAD code
base. The user-facing VibeCAD product should be a native Python implementation
inside FreeCAD, backed by the OpenAI API or a compatible provider abstraction.

## Design Principles

1. Native first: VibeCAD lives inside the existing FreeCAD workbenches as
   commands, task-panel extensions, context-menu actions, shared panels,
   preferences, and document-aware services. VibeCAD must not create or require
   a separate standalone workbench.
2. Tool-driven, not text-only: The model must use structured FreeCAD tools for
   document reads and mutations.
3. Workbench-aware: Each FreeCAD workbench gets its own tool namespace,
   vocabulary, guardrails, and context pack.
4. Reversible by default: Mutating actions run inside FreeCAD transactions and
   must be undoable.
5. Explicit for risk: Read-only, view, and safe native CAD tools may run
   automatically; destructive, expensive, or broad mutations require user
   approval or a dedicated non-provider surface.
6. Local state is authoritative: OpenAI decides intent and tool choice; Python
   tools execute native FreeCAD operations and return truthful state.
7. Test-gated development: VibeCAD changes must preserve the UI/style readiness
   gate: CTest, registered split tests, visual captures, and workflow coverage.
8. Provider-portable core: OpenAI is the first-class provider, but the internal
   tool registry and conversation state should not be hardcoded to one provider.

## Product Surfaces

### Hard Product Constraint

VibeCAD must not ship as a new standalone workbench. Every user-facing AI
affordance belongs inside an existing FreeCAD workbench, task panel, command,
context menu, preference page, or shared panel that follows the active existing
workbench. A shared implementation module is allowed; a separate AI workbench is
not.

### Existing Workbench Integrations

Primary user surfaces are embedded into existing workbenches:

- workbench toolbar commands such as `Ask AI`, `Explain Selection`, and
  `Propose Fix`
- task-panel extensions for active modeling workflows
- selection-aware context-menu actions
- command palette actions registered by each workbench integration
- shared status indicator for auth/model/tool-loop state
- approval queue and tool execution log reachable from the active workbench

### Context-Sensitive Assistant Panel

A shared assistant panel may exist, but it follows the active workbench and
selection. It must not require switching to a standalone VibeCAD workbench.

Primary panel responsibilities:

- chat input
- active context summary
- selected object summary
- live tool trace and revision history
- revise, undo, and clear-session controls
- screenshot attachment controls
- tool trace panel
- model/provider selector when allowed by preferences

The assistant panel should not require users to understand prompts, JSON, tools, or
agent internals.

### Task Panel Integrations

For active modeling workflows, VibeCAD should be able to open a task panel that
is specific to the current operation:

- sketch repair
- constraint creation
- feature parameter editing
- CAM operation review
- BIM object classification
- TechDraw annotation assistance
- style/theme migration review

### Preferences

VibeCAD needs a dedicated preferences page:

- authentication status
- provider configuration
- model defaults
- privacy and telemetry controls
- automatic tool-call policy
- approval thresholds
- project-specific context controls
- token/cost limits
- local cache controls

## Authentication

Authentication is the first required system feature.

OpenAI API access uses bearer credentials from API keys or short-lived access
tokens. API keys are secrets and must not be exposed in client-side code. In a
desktop application, VibeCAD must treat the user machine as the trusted runtime
and store credentials using the operating system credential store when possible.

Reference:

- OpenAI API authentication: https://developers.openai.com/api/reference/overview/
- OpenAI projects and API keys: https://help.openai.com/en/articles/9186755-managing-your-work-in-the-api-platform-with-projects

### Auth Modes

VibeCAD should support these modes, in this order:

1. User-provided API key
   - User pastes a project API key.
   - Key is stored in OS keyring, not plain FreeCAD parameters.
   - FreeCAD preferences store only non-secret metadata.

2. Environment variable
   - Reads `OPENAI_API_KEY`.
   - Good for developers, CI, and power users.
   - Never writes this value back to preferences.

3. Managed organization mode
   - Future enterprise mode.
   - Admin provides policy, provider, and credential broker.
   - Desktop client receives short-lived credentials or routes through a managed
     proxy.

4. Offline/no-auth mode
   - VibeCAD UI loads.
   - Read-only local tools and documentation remain available.
   - AI calls are disabled with clear status.

### Auth Requirements

- Login/setup wizard on first use.
- Persistent logged-in state.
- Credential validation call.
- Clear logout/revoke action.
- Redacted logs.
- No API keys in document files, crash reports, screenshots, traces, or tool
  logs.
- Per-user credentials, not per-document credentials.
- Project files may reference VibeCAD settings but must not contain secrets.

## AI Runtime

VibeCAD should start with a native Python runtime that calls the OpenAI API
through a provider boundary. The initial implementation should use the OpenAI
Agents SDK pattern from the official quickstart: define an agent, expose Python
functions as tools, and run the agent through the SDK runner. The provider
boundary must still keep the UI independent from OpenAI-specific request code.

References:

- Responses/API tools and function calling:
  https://developers.openai.com/api/docs/guides/function-calling
- OpenAI tools overview:
  https://developers.openai.com/api/docs/guides/tools
- Agents SDK guidance:
  https://developers.openai.com/api/docs/guides/agents

### Runtime Components

1. `VibeCadProvider`
   - Provider abstraction.
   - Handles model calls, streaming, tool schemas, retries, and errors.

2. `VibeCadSession`
   - Conversation state.
   - Active document reference.
   - Workbench context.
   - Tool-call history.
   - Approval history.

3. `VibeCadToolRegistry`
   - Registers core tools and workbench tools.
   - Exposes JSON schemas to the model.
   - Routes tool calls to Python handlers.

4. `VibeCadExecutionEngine`
   - Runs tool calls.
   - Enforces safety policy.
   - Wraps mutations in transactions.
   - Captures outputs, exceptions, screenshots, and document diffs.

5. `VibeCadContextBuilder`
   - Builds compact context from the active document, selected objects,
     workbench, viewport, and user request.

6. `VibeCadApprovalController`
   - Decides whether a tool call can run automatically or requires user
     confirmation.

7. `VibeCadAuditLog`
   - Stores local, redacted tool traces for debugging and support.

## Tool Loop

The VibeCAD loop is:

1. User asks for something.
2. Context builder summarizes current FreeCAD state.
3. Model responds with either a user-facing answer or tool calls.
4. Tool registry validates requested tools.
5. Approval controller gates risky actions.
6. Execution engine runs tools in FreeCAD.
7. Results return to the model.
8. Model continues until it has a final answer or proposed change.
9. User reviews/applies/undoes as needed.

### Tool Categories

Read-only tools:

- inspect document
- inspect selection
- inspect object properties
- inspect placement/shape metadata
- inspect workbench commands
- capture screenshot
- list available tools
- summarize errors

Low-risk mutation tools:

- create document object
- set object property
- add sketch geometry
- add constraint
- run command with narrow scope
- change view/camera

High-risk mutation tools:

- delete objects
- batch edit many objects
- run arbitrary Python
- modify preferences
- modify external files
- run CAM post-processing
- export files
- install dependencies

High-risk tools require explicit user confirmation by default.

## Core Tools

These tools should exist independent of workbench:

- `core.get_active_document`
- `core.get_document_tree`
- `core.get_selection`
- `core.get_object_properties`
- `core.get_object_shape_summary`
- `core.get_view_state`
- `core.capture_viewport`
- `core.run_freecad_command`
- `core.begin_transaction`
- `core.commit_transaction`
- `core.rollback_transaction`
- `core.undo_last_vibecad_action`
- `core.set_property`
- `core.create_object`
- `core.delete_object`
- `core.list_workbenches`
- `core.activate_workbench`
- `core.list_workbench_commands`
- `core.get_report_view_errors`
- `core.run_focused_tests`

`core.run_python` should exist only as a developer or advanced tool and must be
disabled by default for normal users.

## Workbench Tool Packs

Each workbench gets a tool pack. Tool packs define:

- available tool schemas
- system instructions for that workbench
- domain vocabulary
- object types owned by the workbench
- validation rules
- example workflows
- risky operations
- focused tests

### Sketcher

Initial tools:

- create sketch
- add line, circle, arc, rectangle
- add constraint
- inspect constraints
- find under/over-constrained geometry
- suggest constraints
- repair invalid constraints
- capture sketch viewport

Guardrails:

- Never silently delete geometry.
- Prefer adding constraints over moving geometry.
- Report degrees of freedom when available.

### Part and PartDesign

Initial tools:

- create primitive
- create body
- create pad/pocket/revolve
- inspect feature tree
- edit feature parameters
- validate body tip
- detect broken dependencies

Guardrails:

- Preserve parametric history.
- Avoid destructive shape conversion unless confirmed.
- Keep Body scope valid.

### Draft

Initial tools:

- create line, wire, rectangle, circle, dimension, text
- inspect working plane
- change snap settings
- convert Draft object
- clone/object array helpers

Guardrails:

- Keep placement and working plane explicit.
- Avoid global snap/preference changes without approval.

### BIM

Initial tools:

- create wall, slab, door, window, structure, space, site
- classify IFC type
- inspect host relationships
- validate wall/window openings
- inspect quantities
- IFC import/export assistant

Guardrails:

- IFC import/export is high risk.
- Host relationships must be previewed before mutation.
- Avoid hidden recompute tracebacks.

### TechDraw

Initial tools:

- create page
- add view
- add dimension
- inspect template
- update page
- export drawing

Guardrails:

- Export requires confirmation.
- Preserve existing annotations unless asked.

### CAM

Initial tools:

- inspect job
- inspect tool controllers
- inspect operations
- validate feeds/speeds
- generate operation proposal
- post-process preview

Guardrails:

- Posting G-code is high risk and requires confirmation.
- Machine and toolhead assumptions must be explicit.

### FEM

Initial tools:

- inspect analysis
- inspect material, constraints, mesh
- suggest missing setup
- run solver only with confirmation

Guardrails:

- Solver execution can be expensive.
- Results must state assumptions.

### Spreadsheet

Initial tools:

- inspect cells
- set cell value
- create alias
- explain dependency
- detect broken expressions

Guardrails:

- Batch edits require preview.
- Formula edits require before/after display.

## Context Model

VibeCAD should not dump the entire FreeCAD document into every model call.
Context should be compact, structured, and scoped.

Context layers:

1. Session context
   - user request
   - current workbench
   - active document name
   - active task/dialog state

2. Selection context
   - selected object names/types
   - important properties
   - shape summary

3. Document context
   - object tree summary
   - dependencies
   - recompute state
   - report view errors

4. Visual context
   - screenshot when needed
   - viewport camera
   - visible objects

5. Workbench context
   - active tool pack
   - relevant commands
   - focused rules

## Safety and Approval

Tool safety levels:

- `read`: no approval
- `view`: no approval
- `safe_write`: approval configurable
- `write`: approval required initially
- `destructive`: approval always required
- `external`: approval always required
- `developer`: disabled by default

Every mutation should produce:

- natural-language summary
- structured diff where possible
- undo transaction id
- affected objects
- validation result

## Persistence

Persist locally:

- auth metadata
- provider/model preferences
- redacted session history
- tool trace summaries
- user approval policy
- workbench tool settings

Do not persist:

- raw API keys in FreeCAD parameters
- unredacted prompts containing secrets
- screenshots unless user enables history
- tool outputs with external file contents unless approved

## Testing Requirements

VibeCAD development must keep the current readiness gates green:

- CTest
- registered split harness
- visual baseline captures
- visual regression checks
- screenshot integrity checks
- UI/style requirement audit

New VibeCAD-specific tests:

- auth storage self-test with isolated keyring/test doubles only for credential invariants
- real OpenAI live acceptance tests for provider workflow confidence
- tool schema validation tests
- provider request-dump tests
- transaction rollback tests
- workbench tool pack tests
- screenshot/context redaction tests
- no-secret-in-log tests
- offline mode tests

## MVP Milestones

### Milestone 0: Foundation

- Add shared VibeCAD service module.
- Add context-sensitive assistant panel that follows the active workbench.
- Add preferences page placeholder.
- Add first existing-workbench command integration.
- Add local settings model.
- Add auth status state machine.

### Milestone 1: Auth

- Support `OPENAI_API_KEY`.
- Support user-entered API key.
- Store API key in OS keyring when available.
- Add logout.
- Add validation call.
- Add no-auth offline mode.

### Milestone 2: Read-Only AI

- Add provider abstraction.
- Add OpenAI Agents SDK provider.
- Add session model.
- Add read-only tools:
  - document summary
  - selection summary
  - property inspection
  - screenshot capture
- Let VibeCAD answer questions about the active model without modifying it.

### Milestone 3: Controlled Mutations

- Add transaction wrapper.
- Add direct native write tools with precise schemas.
- Add `set_property`, `create_object`, `run_command` only where they are native,
  scoped, and safe for the active workbench.
- Add undo integration.
- Require state verification after mutation.

### Milestone 4: Existing Workbench Tool Packs

- Add Sketcher integration pack.
- Add Part/PartDesign integration pack.
- Add Draft integration pack.
- Add BIM integration pack.
- Add CAM integration pack.
- Add TechDraw integration pack.

### Milestone 5: Verification Loop

- Add screenshot-after-action verification.
- Add focused test hooks.
- Add report-view error summarization.
- Add model self-check step.

### Milestone 6: Product Polish

- Streaming responses.
- Better progress UI.
- Tool trace viewer.
- Session history.
- Prompt/context debugging tools for developers.
- Provider/model policy controls.

## Open Questions

- Should VibeCAD ship with OpenAI-only support first, or a provider interface
  from day one?
- Which keyring libraries are acceptable for FreeCAD packaging targets?
- Should enterprise deployments use direct API keys, short-lived credentials, or
  a local/network proxy?
- How much session history should be stored by default?
- Should `run_python` ever be available in normal user builds?
- Should workbench tool packs live in each workbench module or in one VibeCAD
  module with adapters?
- How should VibeCAD handle add-on workbenches?
- What is the minimum manual smoke test for the first public preview?

## Initial Recommendation

Build VibeCAD as a native FreeCAD Python subsystem with a provider abstraction,
native integrations inside existing workbenches, OpenAI as the first provider,
the Agents SDK as the initial model/tool-loop runtime, and a strict FreeCAD
transaction/approval layer.

Do not require users to use Codex to use VibeCAD. Use Codex to build, test,
review, and maintain VibeCAD.
