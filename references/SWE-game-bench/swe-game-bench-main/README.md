# SWEGameBench

An executable benchmark for automated program repair on **Unity game repositories**.
Each benchmark instance is a real GitHub issue from an open-source Unity project,
pinned to the commit just before the developers fixed it (`base_sha`), plus a
hidden NUnit test suite that **fails on the base commit and passes once the real
fix (`fix_sha`) is applied**. A repair agent is scored by whether the patch it
generates makes those hidden tests pass.

The current dataset covers 84 instances across nine repos. The 24 validated
Golden instances are tagged with `benchmark_set: "golden"`.

| repo key         | project                                  | instances | Unity editors                          |
|------------------|------------------------------------------|-----------|----------------------------------------|
| `fungus`         | snozbot/fungus                           | 10        | 2018.4.36f1, 2019.2.21f1, 2019.4.12f1, 2019.4.36f1 |
| `aottg`          | AoTTG-2/AoTTG-2                          | 11        | 2020.1.5f1, 2020.2.7f1, 2020.3.48f1    |
| `miragenet`      | MirageNet/Mirage                         | 34        | 2019.2.21f1, 2019.3.6f1, 2019.3.7f1, 2019.3.10f1, 2019.4.3f1, 2020.1.5f1, 2020.1.9f1, 2020.1.14f1, 2020.1.17f1 |
| `ress3d`         | RE-SS3D/SS3D                             | 18        | 2019.3.12f1, 2019.4.30f1, 2021.3.0f1, 2021.3.15f1 |
| `rpr`            | hackerspace-ntnu/Red-Planet-Rampage      | 6         | 2022.2.15f1                            |
| `janoarg`        | FFF40/JANOARG                            | 2         | 2022.3.46f1                            |
| `moorestech`     | moorestech/moorestech                    | 1         | 2022.3.1f1                             |
| `goldplayer`     | Hertzole/gold-player                     | 1         | 2018.4.36f1                            |
| `gothicvr`       | GothicVRProject/GothicVR                 | 1         | 2022.2.18f1                            |

Unity 6 (6000.x) projects are excluded: those editors cannot be activated via
the manual `.ulf` license flow this benchmark's containers rely on.

## Layout

```
src/swe_game_bench/    the evaluation harness (pip-installable, CLI: swe-game-bench)
benchmark/             the dataset (pure data, no code except repo hooks)
  instances.json       all instances; IDs like "fungus-879"
  repos.yaml           per-repo config: URLs, scrub steps, Unity image buckets
  issues/<id>.txt      issue title + body the agent sees (nothing else; no hints)
  tests/<id>/...       hidden NUnit test tree injected at evaluation time
  oracle_patches/      the developers' real fix, restricted to the target file(s)
  hooks/               repo-specific source surgery (e.g. AoTTG URP scrubs)
  configs/             SWE-agent baseline configuration
  docker/              parametrized Dockerfile + generated compose file
tools/                 one-time migration scripts
```

## Install

```bash
git clone this repo && cd swe-game-bench
pip install -e .            # installs the swe-game-bench CLI
```

Requirements on the host: Python ≥ 3.10, git, Docker (Compose v2).

Verify the installation and see every available command:

```bash
swe-game-bench --help
```

Every subcommand also provides its own help, for example:

```bash
swe-game-bench evaluate-predictions --help
```

### Unity license

Evaluation runs Unity headlessly inside `unityci/editor` containers, which need a
Unity **personal license file** (`Unity_lic.ulf`). Create a directory containing
your `Unity_lic.ulf` and point `LICENSE_PATH` at it (defaults to
`./unity_license_data`). To obtain a `.ulf`: generate an activation file (`.alf`)
with the target editor version, upload it at https://license.unity3d.com/manual,
and download the resulting license.

### Environment setup

The CLI reads a `.env` file from the repository root. Copy `.env.example` to
`.env` and uncomment only what your task needs — every variable, its default, and
when to set it is documented there.

At a minimum: evaluating existing patches needs only a Unity license (no API
key); running the bundled SWE-agent baseline also needs an API key for the
selected model provider. `GITHUB_TOKEN` is optional (dataset enrichment and
authenticated repo access).

## Quickstart: evaluate your own patch

```bash
swe-game-bench list                                  # see all instance IDs

# 1. Build + start the Unity container for the instance's editor version
swe-game-bench prepare --instance-id fungus-879

# 2. Prove the instance gate works: hidden test FAILs on base, PASSes on the real fix
swe-game-bench validate --instance-id fungus-879

# 3. Score your agent's patch (a plain unified diff against the base commit)
swe-game-bench evaluate --instance-id fungus-879 --patch-file candidate_patch.patch
```

`validate` and `evaluate` need the Unity editor, which only exists inside the
containers — when run anywhere else they automatically forward themselves into
the instance's container via `docker exec` (force with `--docker` / `--local`).

`evaluate` exits 0 on PASS, 1 on FAIL, and writes `*_results.xml` (NUnit),
the Unity log, and a summary under `runs/<instance-id>/`.

Your agent can be anything: check out `base_sha` of the instance's repo, hand the
agent **only** `benchmark/issues/<id>.txt`, and collect its diff. The hidden test
in `benchmark/tests/<id>/` must stay unknown to the agent.

Run commands inside the container directly (without `--docker`) via
`swe-game-bench docker shell --repo fungus --bucket 2019.4.36f1`.

## Batch-evaluate external predictions

For leaderboard-style runs, do not ask users to run `evaluate` one patch at a
time. Have them submit a JSONL file with one patch attempt per row:

```jsonl
{"instance_id":"fungus-879","run_id":1,"agent":"aider","model":"claude-sonnet-4","temperature":"0.4","model_patch":"diff --git a/file.cs b/file.cs\n..."}
{"instance_id":"fungus-879","run_id":2,"agent":"aider","model":"claude-sonnet-4","temperature":"0.4","model_patch":"diff --git a/file.cs b/file.cs\n..."}
{"instance_id":"fungus-879","run_id":10,"agent":"aider","model":"claude-sonnet-4","temperature":"0.4","model_patch":"diff --git a/file.cs b/file.cs\n..."}
```

For an official public-set submission, the file must contain exactly 10 rows per
instance in the selected public set. Golden currently has 24 instances, so a
complete Golden submission has 240 rows. The candidate pool currently has 60
instances, so a complete candidate submission has 600 rows. The `agent` and
`model` fields must be present on every row and must be consistent across the
file. `temperature` is optional because not every model or agent exposes it. If
used, it must be present and consistent on every row; otherwise omit it from
every row. Public `--set golden` and `--set candidates` submissions always use
`--k 10`.

For example, a model without a temperature setting can submit:

```jsonl
{"instance_id":"fungus-879","run_id":1,"agent":"codex","model":"o3","model_patch":"diff --git a/file.cs b/file.cs\n..."}
```

Reports preserve an omitted temperature as JSON `null`; they do not silently
turn it into temperature zero. Use an explicit `model` label such as `none` or
`multi-model` when that accurately describes a non-LLM or multi-model system.

Evaluate those patches with:

```bash
swe-game-bench evaluate-predictions \
  --predictions all_preds.jsonl \
  --set golden
```

`evaluate-predictions` uses Docker by default. Pass `--apptainer` if you want to
use Apptainer instead. For local smoke tests on one or a few instances, use
`--instances ...`; add `--allow-incomplete` only when intentionally testing fewer
than `k` rows. Official `--set golden` and `--set candidates` runs reject missing,
extra, duplicate, partial, non-pass@10, or mixed-metadata submissions.

The command writes each attempt to:

```text
runs/<golden|candidates>/predictions/<experiment>/<repo>/<issue>/run<N>/candidate.patch
```

Then it calls the normal single-patch evaluator internally, records one pass/fail
bit per attempt, and writes:

```text
runs/<golden|candidates>/predictions/<experiment>/pass_at_k_report.json
runs/<golden|candidates>/predictions/<experiment>/pass_at_k_details.json
```

Generate leaderboard-ready reports from either SWE-agent pass@k runs or external
prediction runs with:

```bash
swe-game-bench report --set golden
```

External prediction reports are marked `verified: false` by default. Maintainers
can rerun the same predictions with `--verified` after an official audit.

## Baseline: SWE-agent + pass@k

```bash
# generating patch no evalution
swe-game-bench generate --instance-id fungus-879

# k independent generate+evaluate runs per instance, unbiased pass@k estimator
swe-game-bench pass-at-k --instances fungus-879 --k 10

# Run only the curated 24-instance Golden set
swe-game-bench pass-at-k --set golden --k 10

# Run the candidate pool (Golden and candidate instances cannot be mixed)
swe-game-bench pass-at-k --set core --k 10

# aggregate all pass@k reports into a global index and per-configuration reports
swe-game-bench report
```

The command writes `runs/leaderboard.{json,csv}` for the website index and
individual reports under
`runs/reports/<candidates|golden>/<model>_t<temperature>/leaderboard.{json,csv}`.
Each individual CSV and JSON lists every expected instance in the selected set,
marks missing results explicitly, and includes a recomputed aggregate plus
coverage metadata. The global `runs/leaderboard.{json,csv}` index includes only
complete experiments by default, so partial smoke tests and interrupted runs do
not become public leaderboard rows. Use `--include-incomplete` only for local
diagnostics. Summaries expose `parseable@10` (at least one non-empty unified
diff that applies cleanly), `filehit@10` (at least one attempt touching every
oracle target file), and `pass@10`. The looser `filehit_any@10` value remains
available under per-configuration diagnostics but is not published as a
leaderboard score. The composite `score` is the product of the three canonical
metrics and remains in `[0, 1]`. `logs` and `logs_url` are publication
placeholders and default to unavailable; when present in an experiment report
they are copied into the global leaderboard entry.

Generate or refresh one configuration and upsert it into the global index:

```bash
swe-game-bench report --model gpt-5.2 --temperature 0.8 --set golden
```

The model comes from `--model`, else `SWE_MODEL` in `.env`, else `gpt-5.2`;
sampling temperature from `SWE_MODEL_TEMPERATURE` (default 0.4). Results are
scoped per benchmark set and experiment —
`runs/<candidates|golden>/passk/<model>_t<temperature>/<repo>/<issue>/runN/`
— so changing model or temperature starts a separate result tree instead of
overwriting the previous one.

`pass_at_k_report.json` holds the model/temperature, per-instance pass bits and
pass@1..k; `pass_at_k_details.json` adds patch-application status, per-test-case
results, and both all-target and any-target file-level localization.

## Dataset maintenance

```bash
swe-game-bench enrich [ids] [--force]   # regenerate issue texts (title+body only,
                                        # images replaced by vision-model descriptions)
swe-game-bench oracle [--instance-id X] # regenerate oracle patches from git history
swe-game-bench docker generate          # regenerate compose from repos.yaml
```

### Adding a new instance

1. Add an entry to `benchmark/instances.json` (`instance_id`, SHAs, `target_files`,
   `test_class`, `test_platform`, `unity_bucket`). For cases spanning multiple
   Unity test platforms, use `test_suites`; `benchmark_set` can label a subset.
2. Put the hidden NUnit test tree under `benchmark/tests/<instance_id>/`, mirroring
   in-repo paths (e.g. `Assets/InjectedPRTests/Editor/MyTests.cs` + `.asmdef`).
   In `.asmdef` references, the token `__MAIN_ASMDEF__` resolves at inject time to
   the repo's main assembly (configured in `repos.yaml`).
3. `swe-game-bench enrich <instance_id>` and `swe-game-bench oracle --instance-id <instance_id>`.
4. Gate it: `swe-game-bench validate --instance-id <instance_id> --docker` must
   report base FAIL + oracle PASS before the instance counts. Validation artifacts
   are stored under `runs/<candidates|golden>/validate/<instance_id>/`.

New repos additionally need an entry in `repos.yaml` (clone URL, Unity buckets,
prepare/scrub steps, optional `hooks/<repo>.py`).
