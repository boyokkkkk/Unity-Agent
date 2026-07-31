# Evidence-control semantic fix and real E2E validation

Date: 2026-07-31

## Changes

The iteration changed three control boundaries:

1. `code_file_read` now succeeds semantically only when the source exists and
   the result contains a valid path, SHA-256, non-empty content, valid line
   bounds, an evidence claim, and evidence sources.
2. Empty search/read results no longer create completed actions, disable the
   failed action, or resolve evidence slots.
3. Search results are retained as concrete path/node candidates. Replan
   alternatives use the union of recent search candidates and the working set.
4. The implementation-source slot is resolved only by a successful
   graph-backed read whose action carries a known `node_id`; a path-only read
   remains useful evidence but cannot unlock mutation tools.

## Pre-run exit gate

All 57 relevant unit, protocol, context, retrieval, replay, and telemetry tests
passed.

An offline run against the real KitchenChaos graph reproduced the former
`GameManager.cs` mistake and verified:

```json
{
  "missing_completed": false,
  "first_alternative": {
    "tool": "code_file_read",
    "arguments": {
      "node_id": "cs-file:82431c0fae3cf24c0583",
      "path": "Assets/Scripts/KitchenGameManager.cs"
    }
  },
  "read_returncode": 0,
  "read_path": "Assets/Scripts/KitchenGameManager.cs",
  "open_slots": [],
  "profile": "implementation"
}
```

This satisfied the precondition for one paid real-model E2E.

## Fixed evaluation criteria

The run was required to meet all three process gates:

- read the actual root-cause source by tool call 6;
- record zero empty/missing reads as completed evidence;
- execute at least one mutation.

Hidden-oracle verified success remained the final outcome criterion.

## Real E2E result

- Run ID: `real-e2e-controlfix-20260731-a`
- Model: DashScope `qwen-plus`
- Unity: `2021.3.45f1c1`
- Experiment valid: true
- Exit: `TotalTokenLimitExceeded`
- Total tokens: 81,839
- Model calls: 9
- ACI calls: 12
- Mutation calls: 0
- Root-cause source actually read: no
- Public validation: passed
- Hidden validation: failed
- Verified success: false

The run failed two of the three process gates: the root-cause source was not
read by call 6, and no mutation occurred. The empty-result completion bug did
not recur.

All nine model calls remained in the localization tool profile. The agent read
`GameInput.cs` and `MainMenuUI.cs`, but both actions supplied only a path and
not a graph node ID, so the implementation-source slot correctly remained
open. The model repeatedly searched for main-menu and countdown concepts
instead of selecting a concrete graph-backed source.

## Metric comparison

| Metric | Before semantic fix | After semantic fix |
|---|---:|---:|
| Tokens | 73,050 | 81,839 |
| Model calls | 8 | 9 |
| ACI calls | 11 | 12 |
| Root-cause rank | 4 | 5 |
| Relevant recall | 1.000 | 0.667 |
| Navigation precision | 0.136 | 0.083 |
| Blocked-action recovery | 0.667 | 1.000 |
| Admissible-action acceptance | 0.000 | 0.000 |
| Mutation calls | 0 | 0 |
| Verified success | false | false |

The semantic fix improved truthfulness and prevented premature phase
transition. It did not improve task completion and increased token consumption
because the localization phase had no active completion policy.

## Decision

Do not revert the evidence semantics. The old behavior was unsound.

Do not continue tuning filename-similarity weights or running more paid seeds
with the current passive localization loop. The predeclared exit criterion
failed.

The next iteration should change the localization control policy while keeping
the overall evidence-conditioned direction:

1. Allow at most two unconstrained search actions.
2. Compile the resulting evidence into a small `candidate_frontier`.
3. Temporarily mask search tools and expose only reads/references for frontier
   candidates.
4. Require the next successful action to consume one frontier candidate. The
   controller should inject the candidate `node_id`; it should not depend on
   the model copying it correctly.
5. After two distinct implementation reads, require a structured diagnosis:
   target node, causal observation, proposed change, and missing evidence.
6. Re-open search only when that diagnosis declares a specific unresolved
   evidence gap.

This is a shift from a passive evidence gate to an executable localization
state machine. It remains within the research thesis—memory and graph evidence
change the admissible action space—but removes the assumption that the model
will voluntarily consume an advisory candidate list.

No additional paid E2E should run until an offline replay demonstrates that
the state machine forces `KitchenGameManager.cs` into the read frontier within
six tool calls without encoding the oracle filename in task-specific rules.
