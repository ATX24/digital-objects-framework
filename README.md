# Digital Objects

A digital object is a BAML harness that improves by proposing and evaluating changes to its own source. The harness owns its tools, prompts, data models, agent interactions and memory policy. A small Python host owns isolation, immutable revisions and the learning experiment.

```text
run harness → query native traces → evaluate → propose source edits
      ↑                                         ↓
retained revision ← compare on fixed panels ← candidate
```

Tools are ordinary BAML functions. Agents run `Function@spec(...)` through the stdlib `ai.Agent`. There is no tool registry, custom agent protocol or second trace database. The evaluator and optimizer are replaceable functions paired by `Campaign`.

## Start

Requires macOS, Git and Python 3.11+. Execution refuses to run without the macOS sandbox. The installer downloads BAML `0.20.2-nightly.20260929.a` and Gitleaks `8.24.3`, checking embedded SHA-256 digests.

```sh
sh scripts/install-tools.sh
sh scripts/test.sh
export DO_BAML_BINARY="$PWD/.tools/baml/bin/baml-cli"
export PYTHONPATH="$PWD"
python3 -m digital_objects evolve --object ../8VC-media-harness --rounds 1
python3 -m digital_objects inspect --object ../8VC-media-harness
python3 -m digital_objects audit --object ../8VC-media-harness
```

Clone the companion [media object](https://github.com/ATX24/8VC-media-harness) beside this repository; access is required. Its checkout path is passed explicitly, so another directory layout works too. Default mode is **fixture**: scripted model responses, zero paid calls, no publishing. The HTML report contains source diffs, comparison results and native trace references. Scripted improvement verifies the mechanics; it says nothing about real media performance.

Use `--state PATH` for separate experiments, `--resume` to continue completed comparison panels, and `rollback --version HASH` to restore a retained snapshot. Source files in the working checkout are never overwritten by evolution. Interrupted partial panels rerun; completed panels are checkpointed. Use one process per state directory.

## Define an object

| File | Responsibility |
| --- | --- |
| `baml_src/ns_harness/*.baml` | Mutable source; export `run(input: json, client: ai.Client) -> json` |
| `baml_src/evaluation.baml` | Fixed `evaluate_main` objective, fed native outputs and trace span names |
| `task.json` | Objective, evaluator files, models, budgets and case splits |
| `cases/{feedback,selection,audit}/*.json` | Frozen inputs and optional scripted model replies |
| `fixtures/optimizer.json` | Optional exact source-edit proposal for offline testing |

The media repository provides a complete example. Only the `ns_harness` namespace is mutable. Evaluator files and the objective are hashed separately. Feedback cases inform the proposer; selection cases compare parent and candidate on at least two distinct seeds. Audit cases never enter proposal context. Invalid, incomplete or missing evidence cannot promote a candidate.

The default optimizer asks a BAML model function for exact edits with parent/file hashes and unique search strings. Applying edits is atomic. Every retained version has a source hash, parent, diff, objective version and comparison evidence. This is reward-driven source search, not neural-network backpropagation or model-weight training.

For another optimizer or objective, pass callbacks as `DigitalObject(..., evaluator=..., optimizer=...)`. The evaluator receives `(Execution, case, seed)` and returns `Evaluation`; the optimizer receives `(Version, feedback, history)` and returns an edit proposal. The host remains independent of media content.

## Models and evidence

`--mode explore` enables fresh Claude calls through the native `ClaudeCodeClient`, using an installed, authenticated Claude Code CLI. `--max-calls N` bounds fresh calls, including evaluator and optimizer calls. The default 32-call limit can be too small for a complete live comparison; exhaustion leaves the candidate unpromoted. `--mode replay` requires exact cached requests and never falls back to inference.

Generated code receives no Claude credentials or network access. A bounded file mailbox forwards the native client's exact tool-free CLI request to a trusted broker. The stdlib still owns schemas, parsing, journals and tool dispatch; the transport does not implement an agent loop.

The evaluator queries native local BTEL using `baml query`, correlates captured run IDs, checks process completion and re-reads the submission. The included BCS `/v1/query` adapter decodes cloud wire frames, but **cloud deployment and Studio parity are not configured or verified**. Setting a cloud trace source fails explicitly. Local artifacts may contain sensitive prompts and evidence; keep them private.

## Verification and delivery

`scripts/test.sh` runs compiler checks, native `baml test`, Python contract tests and confinement regressions without model calls. Set `DO_MEDIA_OBJECT` to a media checkout to include the complete episode, trace evaluation, two-panel selection, resume and audit tests; these two integration tests otherwise skip. Media CI supplies this checkout and pins this framework by commit.

`scripts/security.sh` scans the committed source with Gitleaks and checks Python with Bandit. CI runs these same checks on macOS. Passing builds produce a source archive and checksum. Pushing a `v*` tag publishes those verified files as a GitHub release. CI never invokes Claude or deploys a posting service.

See [SECURITY.md](SECURITY.md) for boundaries and residual limitations. The design follows the source-adaptation mechanism described in [Harness Learning Enables Generalizable Test-Time Adaptation](https://arxiv.org/abs/2609.35738); it does not reproduce proposer training or the paper's benchmarks.
