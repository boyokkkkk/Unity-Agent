# Kitchen Chaos Context Ablation and Baseline Task Suite Design

Date: 2026-08-02

## 1. Purpose

This design replaces the broad Group 6 ablation, which currently sets
`context.enabled=false`, with four independently controlled context ablations. It
also generalizes the single hard-coded state-event baseline into a six-task
Kitchen Chaos suite with balanced difficulty.

The resulting experiment must answer two different questions without mixing
them:

1. Which context capability contributes to localization and protocol completion?
2. Does that contribution change with task type and difficulty?

The implementation remains limited to the existing Kitchen Chaos project so the
Unity version, source tree, project graph, asset corpus, and validation runtime
stay fixed.

## 2. Scope

### Included

- A parameterized task registry and a generic controlled baseline runner.
- Six English Kitchen Chaos repair tasks.
- Four independent context ablation switches plus a full-system condition.
- Task-specific reversible defect injection and hidden oracles.
- Treatment-activation telemetry and validity gates.
- A deterministic randomized experiment schedule.
- Pilot and formal experiment runners and analysis outputs.

### Excluded

- Other Unity projects.
- Non-Unity or non-C# projects.
- Chinese task prompts in this experiment.
- Model comparison.
- Changes to the Kitchen Chaos source project outside isolated workspaces.
- A factorial interaction experiment among multiple simultaneously disabled
  context features.

## 3. Chosen Architecture

### 3.1 Task specification

Introduce a `BaselineTaskSpec` abstraction with these responsibilities:

- stable `task_id`;
- English task text;
- difficulty level (`simple`, `medium`, or `hard`);
- relevant files and assets;
- root-cause targets used only by evaluation;
- reversible defect injection;
- an invariant-based patch oracle;
- hidden oracle installation and cleanup;
- task-specific public and hidden validation modes.

Task implementations are registered in a `TaskRegistry`. The registry is the
only place that maps CLI task IDs to task behavior.

### 3.2 Generic runner

Refactor the state-event-specific runner into a `ControlledBaselineRunner`. The
runner owns all shared behavior:

1. create an isolated project workspace;
2. verify the pristine task precondition;
3. inject exactly one defect;
4. verify that the task oracle now fails;
5. execute the agent with a selected condition and seed;
6. evaluate the task invariant;
7. run public Unity validation;
8. install and run the task-specific hidden oracle;
9. remove the hidden oracle;
10. verify that the source project fingerprint is unchanged;
11. emit a common report schema.

The existing state-event baseline becomes the first registered task rather than
a separate execution path.

### 3.3 Proposed module boundaries

```text
src/game_agent/baseline_tasks/
├── __init__.py
├── schema.py
├── registry.py
├── script_tasks.py
├── prefab_tasks.py
├── task_oracles.py
└── hidden_oracles.py
```

`schema.py` contains interfaces and immutable task metadata. `registry.py`
contains registration and lookup only. Script and asset mutation logic remains
separate because Prefab operations require Unity Editor APIs and cannot safely
share raw text-patching code.

## 4. Independent Context Conditions

Every condition keeps `context.enabled=true`, the same project graph file, and
the same graph SHA-256.

| Condition | Single disabled capability |
|---|---|
| C0 `full` | none |
| C1 `no-graph-retrieval` | structured graph candidate scoring and graph expansion |
| C2 `no-semantic-score` | embedding-based semantic score contribution |
| C3 `no-causal-edges` | event subscription, event publication, and state-write causal edges |
| C4 `no-context-assembly` | automatic working-set and compressed-context injection |

### 4.1 C1: graph retrieval

Add `context.graph_retrieval_enabled`. When false:

- structural graph scores and graph expansion are disabled;
- semantic retrieval remains available;
- the graph remains loaded for version verification and treatment-opportunity
  measurement;
- structured filesystem/code tools remain available;
- context assembly remains enabled.

### 4.2 C2: semantic scoring

Use the existing `context.semantic_search_enabled` as the sole treatment. When
false:

- embedding cache lookup and semantic score contribution are disabled;
- lexical and structural graph scores remain active;
- graph nodes, ordinary edges, and causal edges remain available;
- context assembly remains enabled.

### 4.3 C3: causal edges

Add `context.causal_edges_enabled`. When false:

- causal edge kinds used for event subscription, event publication, and state
  writes are filtered from query decomposition, graph expansion, and causal fact
  construction;
- nodes and non-causal structural edges remain available;
- semantic and lexical scores remain unchanged;
- the graph file itself is not rewritten.

### 4.4 C4: context assembly

Add `context.context_assembly_enabled`. When false:

- graph and semantic query tools still execute and return their normal results;
- project-store lookup remains available;
- automatic working-set selection, durable evidence summaries, and compressed
  context injection into model prompts are disabled;
- ordinary model conversation and direct tool observations remain intact.

This condition must not set `context.enabled=false` or clear `graph_path`.

## 5. Treatment-Activation Contract

A configuration value alone is not sufficient evidence that an ablation was
executed. Each run records treatment opportunities and observed contributions.

### C0

- at least one context retrieval opportunity;
- structural graph scoring enabled;
- semantic scoring enabled when the task has semantic documents;
- causal edges available for causal tasks;
- at least one automatic context assembly event.

### C1

- at least one graph-retrieval opportunity;
- structural graph score contribution equals zero;
- graph expansion count equals zero;
- semantic retrieval remains enabled and observable.

### C2

- at least one semantic-retrieval opportunity;
- semantic score contribution equals zero;
- structural graph candidates are still returned.

### C3

- the source graph contains at least one task-relevant causal edge;
- causal edges returned to the agent equal zero;
- non-causal structural edges remain observable.

### C4

- graph or semantic queries return candidates;
- automatic context injection count equals zero;
- direct tool results remain visible to the model.

If a condition has no treatment opportunity or violates its activation
contract, the report contains:

```text
experiment_valid=false
infrastructure_error=treatment_not_activated
```

Such a run is not counted as an ordinary agent failure.

## 6. Six-Task Suite

The suite uses two simple, two medium, and two hard tasks.

### T1: state-event-publication (simple)

- Defect: remove `OnStateChanged` publication after the start interaction changes
  state to `CountdownToStart`.
- Smallest repair: one event-publication statement.
- Hidden invariant: interaction changes state, publishes exactly once, hides the
  tutorial, and displays the countdown UI.
- Primary context signal: state-write and event-publication causal edges.

English task:

> After the player presses the interact key on the start screen, the game enters
> the countdown state internally, but the tutorial remains visible and the
> countdown UI does not appear. Locate the broken state-to-UI notification chain,
> apply the smallest repair, and validate it.

### T5: options-sfx-button-listener (simple)

- Defect: remove the `soundEffectsButton.onClick.AddListener` block in
  `OptionUI.Awake`.
- Smallest repair: restore one listener with the original two effects.
- Hidden invariant: one click changes volume by exactly one step and refreshes the
  displayed value without duplicate listener registration.
- Primary context signal: semantic scoring and local callback structure.

English task:

> Clicking the Sound Effects button in the options menu no longer changes the
> volume or refreshes its displayed value. Other option buttons still work.
> Locate the missing callback behavior, make the smallest repair, and validate
> the button interaction.

### T2: delivery-result-subscription (medium)

- Defect: remove both delivery success and failure subscriptions from
  `DeliveryResultUI.Start`.
- Smallest repair: restore the two subscriptions.
- Hidden invariant: success and failure events activate the same UI with the
  corresponding visual state; polling or duplicated delivery logic is rejected.
- Primary context signal: subscription edges and cross-file observer context.

English task:

> Delivering a recipe updates the delivery manager, but neither the success nor
> failure popup appears. Diagnose the broken notification path between recipe
> delivery and the result UI, make the smallest repair, and validate both
> outcomes.

### T6: plates-scriptableobject-reference (medium)

- Defect: replace `PlatesCounter.plateKitchenObjectSO` with `Bread.asset` in the
  PlatesCounter Prefab.
- Smallest repair: restore the Plate `KitchenObjectSO` reference.
- Hidden invariant: the field references `Plate.asset`, whose object name is
  `Plate` and whose Prefab contains `PlateKitchenObject`; interaction produces a
  plate.
- Primary context signal: Prefab-to-ScriptableObject dependency and asset
  semantics.

English task:

> The plates counter visually accumulates plates, but interacting with it gives
> the player the wrong kitchen object. Locate the incorrect asset dependency,
> repair only the broken serialized reference, and validate the spawned object
> type.

### T3: stove-progress-reference (hard)

- Defect: use Unity `SerializedObject` to redirect the nested ProgressBarUI
  `hasProgressGameObject` reference to an object that does not implement
  `IHasProgress`.
- Smallest repair: restore the StoveCounter GameObject reference.
- Hidden invariant: the reference is non-null, resolves to a component that
  implements `IHasProgress`, and progress events change `Image.fillAmount`.
- Primary context signal: nested Prefab override, serialized-reference edge, and
  interface implementation.

English task:

> Food continues frying on the stove, but the stove progress bar never updates
> and an IHasProgress source error is reported. Locate the incorrect prefab
> wiring, repair only the broken reference, and validate the progress UI.

### T4: stove-visual-component (hard)

- Defect: remove `StoveCounterVisual` from the StoveCounter Prefab using Unity
  Prefab APIs.
- Smallest repair: restore one component and its three serialized references.
- Hidden invariant: exactly one component exists; all references are valid;
  Frying/Fried enable the stove visuals and Idle/Burned disable them.
- Primary context signal: component attachment, serialized references, and
  event-observer relationships.

English task:

> The stove cooks food correctly, but its active and particle visuals never
> respond to frying or fried states. Locate the missing prefab behavior, restore
> the smallest required component configuration, and validate the visual state
> transitions.

## 7. Defect Injection and Oracles

### 7.1 Script defects

Script injectors use AST or stable source anchors. Every injection manifest
records:

- pre-injection and post-injection SHA-256;
- AST anchor;
- removed or replaced statement;
- changed path;
- allowed repair targets;
- oracle invariants.

### 7.2 Asset defects

Prefab and asset injectors use Unity Editor APIs, including
`LoadPrefabContents`, `SerializedObject`, and `SaveAsPrefabAsset`. They do not
replace YAML by line number or hard-code transient file IDs.

Injection must fail closed if the pristine precondition differs from the
expected component or reference. After injection, the asset is reloaded and the
task oracle must fail before the agent starts.

### 7.3 Hidden oracles

Hidden oracles validate behavior or structural invariants, not exact patch text.
They are installed only after the agent stops, run through isolated EditMode and
PlayMode validation, and are removed before the workspace is retained or
discarded.

## 8. Experiment Matrix

### 8.1 Pilot

Ten smoke runs are excluded from formal statistics:

- C0 on all six tasks;
- C1 on T3;
- C2 on T5;
- C3 on T1;
- C4 on T2.

The pilot verifies defect injection, treatment activation, agent execution,
hidden oracle behavior, cleanup, and report completeness.

### 8.2 Formal study

```text
5 conditions x 6 tasks x 5 seeds = 150 runs
```

Formal seeds are `101`, `202`, `303`, `404`, and `505`.

A checked-in manifest contains all 150 cells in a deterministic randomized and
interleaved order. Conditions must not execute as five contiguous blocks. The
schedule generator uses a documented schedule seed and records its SHA-256.

### 8.3 Fixed controls

- English task text;
- qwen-plus model and endpoint;
- temperature 0.0;
- 81,920 total-token limit;
- graph path and SHA-256;
- Unity editor version;
- compile, public EditMode/PlayMode, and hidden EditMode/PlayMode validation;
- isolated source workspace strategy.

## 9. CLI and Artifacts

The baseline CLI gains explicit task, condition, and seed inputs:

```powershell
game-agent-baseline `
    --project <KitchenChaos> `
    --config <condition-config> `
    --editor <UnityEditor> `
    --task-id <task-id> `
    --condition-id <condition-id> `
    --seed <seed> `
    --task-language en `
    --output-root <artifact-root>
```

Configuration layout:

```text
configs/context-ablation/
├── c0-full.json
├── c1-no-graph-retrieval.json
├── c2-no-semantic-score.json
├── c3-no-causal-edges.json
└── c4-no-context-assembly.json
```

Artifact layout:

```text
artifacts/baselines/context-ablation-pilot/
artifacts/baselines/context-ablation-formal/
artifacts/analysis/context-ablation-formal/
```

Every run includes the task ID, difficulty, condition ID, seed, schedule hash,
task manifest, treatment evidence, source fingerprints, agent result, stage
metrics, public validation, hidden validation, and final report.

## 10. Validation Sequence

For each run:

1. verify pristine task preconditions;
2. inject one defect;
3. verify changed paths equal the injection manifest;
4. prove the task oracle fails;
5. verify the treatment-activation precondition;
6. run the agent;
7. evaluate the repair invariant;
8. run compile validation;
9. run public EditMode and PlayMode tests;
10. install and run hidden EditMode and PlayMode tests;
11. clean the hidden oracle;
12. verify source-project and graph fingerprints;
13. finalize experiment validity independently from task success.

## 11. Metrics and Analysis

### Primary outcome

- `verified_success`.

### Secondary outcomes

- root-cause rank;
- relevant-file recall and navigation precision;
- diagnosis, mutation, validation, review, and submission completion;
- total tokens, rounds, and wall time;
- mutation type and failure counts;
- treatment opportunities and activation;
- exit status and failure stage.

### Stratification

Report results by:

- all tasks;
- simple, medium, and hard tasks;
- individual task;
- individual condition;
- condition by difficulty.

Use Wilson 95% intervals for proportions. Compare each ablation with C0 using
Fisher exact tests with Holm correction. Preserve run-level data so a later
multi-task, multi-seed analysis can use task and seed blocks or a mixed-effects
logistic model.

## 12. Testing Strategy

### Unit tests

- each context flag changes only its intended behavior;
- treatment telemetry reports opportunity and contribution correctly;
- causal-edge filtering preserves ordinary edges;
- context-assembly disabling preserves direct tool observations;
- registry rejects duplicate or unknown task IDs;
- schedule generation is deterministic and balanced.

### Task contract tests

For all six tasks:

- pristine precondition passes;
- injection changes only declared paths;
- oracle fails after injection;
- reference repair passes the oracle;
- hidden oracle installation and cleanup are reversible;
- source project remains unchanged.

### Integration tests

- CLI resolves task, condition, and seed;
- prepared config preserves all fixed controls;
- invalid treatment activation makes the experiment invalid;
- task failure remains distinct from infrastructure failure;
- reports and analysis collectors support every task type.

### Real smoke tests

The ten-run pilot is the gate before the 150-run formal study. Formal execution
must not start until all ten pilot reports are complete and valid, even if an
agent legitimately fails the repair task.

## 13. Acceptance Criteria

Implementation is ready for the formal study when:

- all five condition configs differ by exactly their declared treatment;
- all six task injections and hidden oracles pass reversibility tests;
- all ten pilot runs produce complete reports;
- every pilot run satisfies its treatment-activation contract;
- no run changes the source Kitchen Chaos project;
- aggregation produces task-, difficulty-, condition-, and interaction-level
  tables without manual artifact edits;
- the randomized 150-cell schedule is checked in with a stable hash.
