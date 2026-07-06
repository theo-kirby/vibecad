# VibeCAD Failure Analysis

## What Was Requested

VibeCAD is supposed to be a native AI operator inside FreeCAD.

The user expectation is not a chatbot, not a separate toy workbench, and not a deterministic CAD generator. The expected system is an AI-driven tool loop that can operate FreeCAD the way a skilled human CAD user would:

- Understand a design goal from conversation.
- Inspect the active document, active workbench, task panel, model tree, sketch state, solver state, and viewport.
- Choose the correct native FreeCAD workbench for the next operation.
- Use the same native operations a human would use in that workbench.
- Move between workbenches when needed.
- Iterate in small deliberate steps.
- See the result of its own work.
- Delete, revise, rebuild, and improve existing geometry.
- Continue until the model is meaningfully complete or the user is satisfied.

For PartDesign and Sketcher work, this means the AI should create robust parametric CAD structure:

- Bodies.
- Sketches.
- Constraints.
- Pads.
- Pockets.
- Revolves.
- Lofts.
- Sweeps.
- Fillets.
- Chamfers.
- Patterns.
- Mirrors.
- Named features.
- Valid editable model history.

For assemblies, it should create component bodies, switch to native assembly tooling, position components, and produce a usable assembled design.

The required design capability is complex CAD by default, including robotics, drones, RC vehicles, automotive parts, aerospace-style components, marine components, complex 3D-printable products, and documentation-ready models. Simple primitive block output is not acceptable as the core behavior.

The user also required hard architectural boundaries:

- The AI decides design intent, decomposition, geometry strategy, tool choice, iteration, and completion.
- Python tools execute truthful native FreeCAD operations.
- Deterministic code may enforce only tool and state invariants.
- Deterministic code must not contain design recipes, prompt keyword gates, canned part builders, or fake provider behavior.
- Tests claiming AI workflow confidence must use the real OpenAI provider and real configured authentication.
- Tool schemas and context must be improved using real model failures.
- The full OpenAI request payload must be dumpable for inspection.

## What Was Delivered Instead

The implementation moved in the right direction in several infrastructure areas, but it did not deliver the requested product behavior.

Delivered infrastructure included:

- A dockable VibeCAD panel.
- OpenAI provider integration.
- Conversation persistence work.
- Scoped workbench tool exposure.
- Many one-function provider tools.
- Request dump plumbing.
- Stop/cancel support.
- Some workbench transition checkpoints.
- Sketcher and PartDesign tool wrappers.
- Deterministic tool and GUI smoke tests.

Those pieces are useful, but they are not the same thing as a working AI CAD operator.

The actual user-visible behavior remained unacceptable:

- VibeCAD often produced crude primitive-like geometry.
- It created visually poor flat plates for complex requests.
- It failed to reliably create proper Sketcher-to-PartDesign flows.
- It created empty sketches and then reported them as progress.
- It sometimes had the right tool available but did not call it.
- It described what should happen instead of doing it.
- It asked unnecessary questions when reasonable defaults should have been used.
- It did not consistently revise the existing bad model; it sometimes started another bad model.
- It treated object counts, solver validity, or screenshots as stronger evidence than they were.
- It did not demonstrate complex design competence on the requested classes of parts.

The most important failure case was the drone workflow.

The model was asked for a complete 4-inch drone with motor, flight controller, and battery mounting. It produced a crude flat frame. Later request/context inspection showed the system had a valid constrained sketch and exposed native PartDesign tools such as `partdesign.pad_sketch`, but the model still wrote prose instead of executing the required native feature operation. The loop accepted that non-action too easily.

That is a fundamental product failure.

## Why It Failed

### 1. The System Confused Tool Availability With CAD Competence

Adding many tools did not make the AI good at CAD.

The model needs more than callable functions. It needs:

- Clear state.
- Clear next obligations.
- Clear failure feedback.
- High-quality tool return data.
- Workbench-specific context.
- Visual and structural critique.
- A loop that refuses to accept prose when native action is still required.

The implementation focused too much on exposing more tools and not enough on shaping the operator loop around proof of useful CAD progress.

### 2. The Loop Allowed Talking Instead Of Acting

When verified requirements remained unresolved, the provider was still able to return prose and stop.

That is wrong for this product.

If the context proves a native CAD action is required and the matching tool is available, the loop must strongly surface that required action and treat non-action as a failed provider turn. A CAD operator cannot claim progress by describing the pad, pocket, sketch, assembly, or revision it should make later.

### 3. The Context Did Not Make The Next Native Operation Unavoidable

The context sometimes included useful state, such as:

- Sketch is closed.
- Sketch is fully constrained.
- Sketch is ready for pad.
- No native PartDesign feature exists yet.
- Remaining outcome says a native feature must be created.

But that information was not shaped as a direct operator obligation.

The model should have received an explicit, model-visible field like:

```json
{
  "required_action_now": {
    "tool": "partdesign.pad_sketch",
    "arguments": {
      "sketch_name": "Sketch"
    },
    "reason": "Sketch is closed, fully constrained, ready_for_pad=true, and no native PartDesign feature exists yet."
  }
}
```

That is not a deterministic design recipe. It is a CAD execution invariant. The AI still decides what to design. The system enforces that a ready native CAD state cannot be ignored.

### 4. Valid Geometry Was Treated As Good Geometry

The system overvalued low-level validity checks.

A sketch can be closed, constrained, and still be a bad sketch. A body can be valid and still be a useless body. A viewport can contain visible geometry and still show a terrible design.

The loop lacked enough model-visible quality diagnostics for generic CAD issues:

- Faceted profiles where arcs should be considered.
- Empty sketches.
- Featureless bodies.
- Placeholder geometry.
- Poor use of native PartDesign history.
- Missing expected mounting/detail structure implied by the model's own design plan.

This caused the model to confuse "FreeCAD accepted it" with "the CAD result is good."

### 5. Workbench Transitions Were Not Treated As First-Class Control Flow Soon Enough

The AI should operate inside the current workbench tool surface, then intentionally checkpoint when a different workbench is needed.

For example:

1. PartDesign creates or selects a Body.
2. PartDesign creates a Sketch.
3. Tool surface refreshes into Sketcher.
4. Sketcher draws and constrains the profile.
5. Sketcher closes the sketch.
6. Tool surface refreshes into PartDesign.
7. PartDesign pads, pockets, revolves, patterns, or otherwise consumes the sketch.

The implementation eventually started moving toward this, but too much earlier behavior assumed one provider turn could reason through unavailable tools or recover from missing workbench state without a clean transition contract.

### 6. Tests Proved Infrastructure, Not Product Capability

Many tests verified that wrappers, panels, schemas, and basic tool calls worked.

Those tests did not prove that VibeCAD could autonomously produce complex useful CAD.

The product needed two clearly separated test layers:

- Deterministic tests for tool invariants.
- Live OpenAI acceptance tests for actual AI CAD behavior.

The live tests needed to validate real end-to-end outcomes: document structure, sketch quality, feature history, assembly structure, screenshots, and ability to revise existing work. Earlier testing did not provide enough confidence in those outcomes.

### 7. The Implementation Sometimes Optimized For Visible Output Instead Of Engineered Output

The system made it too easy for the model to create something visible and report progress.

That is not enough for VibeCAD.

The target behavior is engineered CAD:

- Correct workbench.
- Correct native feature chain.
- Meaningful named objects.
- Editable construction history.
- Usable proportions.
- Functional details.
- Iteration after visual and structural inspection.

The implementation did not sufficiently punish or correct shallow visible output.

## The Correct Direction

The next implementation work must focus on the AI operator loop, not just more tools.

Required corrections:

1. Add explicit `required_action_now` context when FreeCAD state proves a native operation is mandatory.
2. Treat no-tool provider turns with unresolved verified requirements as failed turns and retry with stricter action context.
3. Make workbench transitions a first-class loop mechanism.
4. Add generic model-visible CAD quality diagnostics.
5. Improve tool return data so every mutating tool returns useful state for the next decision.
6. Continue moving tools into precise single-purpose modules.
7. Keep tool groups scoped by workbench and phase.
8. Use live OpenAI failures to tune context and schemas.
9. Remove fake provider confidence from AI workflow claims.
10. Validate against complex prompts, including drones, robot arms, vehicles, aerospace-style parts, marine parts, and revision workflows.

## Non-Negotiable Standard Going Forward

VibeCAD should not claim success unless the FreeCAD document proves meaningful CAD progress.

For any substantial design request, acceptable evidence includes:

- Native document objects exist.
- Sketches contain real geometry.
- Sketches are constrained when they should be.
- Sketches are consumed into native PartDesign features when appropriate.
- Bodies have real feature history.
- Assemblies use native assembly objects when appropriate.
- Empty placeholder sketches are not counted as progress.
- Screenshots are captured and inspected by the AI.
- The model can revise existing geometry instead of abandoning it.
- The final report distinguishes completed work from unresolved gaps.

The failure was not that the goal was impossible. The failure was that the implementation did not yet force the AI loop to behave like a real FreeCAD operator. The next code changes must close that gap directly.
