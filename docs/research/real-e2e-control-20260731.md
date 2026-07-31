# Real-model E2E after the Day 1–10 control work

Date: 2026-07-31

## Run

- Run ID: `real-e2e-control-20260731-a`
- Variant: innovation
- Model: DashScope `qwen-plus` through the OpenAI-compatible API
- Unity: `2021.3.45f1c1`
- Task: KitchenChaos `state-event-v1`
- Configuration: role-aware MMR retrieval, evidence/action compiler, structured
  replan, dynamic tool exposure, typed mutations, and validation gates
- Artifact root:
  `artifacts/baselines/state-event-v1/real-e2e-control-20260731-a`

The experiment ran in an isolated project copy. The source KitchenChaos project
fingerprint was unchanged after the run. The hidden oracle was removed after
validation.

## Outcome

| Field | Result |
|---|---:|
| Experiment valid | true |
| Agent submitted | false |
| Exit | `TotalTokenLimitExceeded` |
| Oracle patch match | false |
| Public validation | passed |
| Hidden validation | failed |
| Verified success | false |
| Model calls | 8 |
| ACI tool calls | 11 |
| Total tokens | 73,050 |
| Root-cause rank | 4 |
| Relevant-file recall | 1.0 |
| Navigation precision | 0.136 |
| Duplicate-action ratio | 0.273 |
| Blocked-action recovery rate | 0.667 |
| Admissible-action acceptance | 0.0 |
| Mutation calls | 0 |
| Protocol-gate completion | 0.0 |

Public compile, EditMode, and PlayMode checks passed because no source was
modified and the public tests do not encode the injected event contract. Both
hidden tests failed, so the hidden validation correctly prevented a false
verified-success result.

## What improved

1. ACI calls are now visible in unified telemetry. The previous innovation run
   reported zero tool calls; this run reports all 11 calls and reconstructs T1,
   T2, and T3.
2. Repetition no longer immediately terminates the agent. Three repeated reads
   were blocked and converted into structured replans. Two were followed by a
   different action, giving a measured recovery rate of 0.667.
3. Dynamic exposure worked in the live provider protocol. The first two calls
   used the five-tool localization profile (1,282 estimated schema tokens);
   the next six calls used the seven-tool implementation profile (1,568
   estimated schema tokens). The all-tools schema was not sent.
4. Retrieval covered the root-cause file at rank 4 with three distinct paths
   among four candidates. This is better than the former rank-5 baseline.
5. Evidence writes were reliable: evidence-write recall was 1.0 and six unique
   evidence items were persisted.

## Primary failure

The graph search result explicitly contained
`Assets/Scripts/KitchenGameManager.cs`, but the model shortened the name to the
non-existent `Assets/Scripts/GameManager.cs`. The first empty query returned:

```json
{
  "status": "ok",
  "total": 0,
  "results": [],
  "reason": "No matching indexed C# file or symbol."
}
```

`EvidenceActionCompiler.observe` currently treats every return-code-zero
structured result whose status is not `error`, `unavailable`, or `blocked` as a
success. It therefore:

- recorded the missing path as `code_file_read completed successfully`;
- resolved localization and implementation-source slots without evidence;
- disabled `code_file_read:Assets/Scripts/GameManager.cs:1-*:missing`;
- described later attempts as a source range already read successfully.

This is a false-positive completion transition. A zero-result or missing-path
read must remain a failed evidence slot and must never satisfy a read gate.

## Secondary failure

The structured replan alternatives were `OptionUI.cs` and `GamePauseUI.cs`.
They came from the current working set, while the already observed
`KitchenGameManager.cs` candidate was not offered. Consequently:

- admissible-action acceptance stayed at 0.0;
- evidence utilization stayed at 0.0;
- the agent spent six calls in the implementation profile without reading the
  root-cause source;
- all 73,050 tokens were consumed before any mutation.

The controller solved the old hard-stop failure but did not yet provide a
causally useful recovery frontier.

## Recommended fixes before the next paid run

1. Define per-tool semantic success predicates. For `code_file_read`, require
   an existing path, non-empty source payload, SHA-256, and valid line range.
   Treat `total=0`, `source_missing`, and missing SHA as failed reads.
2. Never create a completed action or resolve an evidence slot without a
   non-empty evidence ID for evidence-producing tools.
3. Build replan alternatives from the union of the working set and the latest
   successful search results. Rank exact-name and task-term matches before
   generic working-set relevance.
4. Preserve the concrete graph candidate path in the controller prompt. Do not
   rely on the model to reconstruct filenames from a truncated search result.
5. Keep localization active until the implementation target has been read
   successfully. This run switched to implementation after reading
   `GameInput.cs`, even though the causal target remained unresolved.
6. Add a bounded no-evidence-progress budget, separate from the total-token
   budget, so repeated empty reads trigger forced candidate selection before
   tens of thousands of tokens are spent.

## Comparison with earlier real runs

| Run | Exit | Tokens | Model calls | Tool calls | Root rank | Verified |
|---|---|---:|---:|---:|---:|---:|
| baseline `real-baseline-20260731-b` | token limit | 78,006 | 19 | 19 | 5 | false |
| old innovation `real-innovation-20260731-e` | repeated action | 23,238 | 3 | 0 in old telemetry | n/a | false |
| current control `real-e2e-control-20260731-a` | token limit | 73,050 | 8 | 11 | 4 | false |

The Day 1–10 work improved observability, retrieval rank, schema exposure, and
recovery from repeated actions. It did not improve end-task success in this
run. The next bottleneck is now sharply localized to semantic evidence
completion and recovery-candidate construction, rather than context length or
the raw repetition threshold.
