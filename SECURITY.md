# Security boundaries

The object definition, evaluator, runtime installation and host account are trusted. Proposed harness code is confined before both compilation and execution. The host passes explicit case inputs; local files outside the worker are not available to the harness.

- macOS `sandbox-exec` denies network and permits writes only to worker scratch, local trace storage and model IPC. Source, request and sandbox policy files are read-only. No unconfined fallback exists.
- The model broker uses a retained directory descriptor and no-follow file opens, checks regular files and size, and atomically returns replies. Replacing IPC paths cannot redirect host reads/writes.
- The broker accepts only the native tool-free Claude command shape, fixes the model and enforces fresh-call and per-episode limits. Fixture/replay modes cannot make fresh calls.
- Child process groups have wall-clock and output limits and are killed after completion. This is not a VM: scratch-disk quotas and comprehensive process/memory quotas are not implemented. Do not expose execution to anonymous hostile users.
- Exact source edits stay within one namespace; stale parents, ambiguous edits, overlaps and oversized bundles fail. Missing, failed or partial trace evidence cannot promote a candidate.
- BCS requires HTTPS, bounds responses and refuses redirects to protect authorization headers. Its deployment remains unverified.
- Git memory uses one writer, a clean-state check and parent revision verification. It rejects path traversal and symlinks. Human preferences are also validated by task-owned BAML policy.

Native trace storage is writable by the worker runtime. Traces provide reproducibility and diagnostics, **not cryptographic attestation against actively malicious trace forgery**. The frozen evaluator validates outputs separately; stronger adversarial isolation would require external trace capture and a VM/container boundary. A trusted local user can also change the objective, cases or cache.

Live Claude authentication stays in the trusted broker. Claude runs with no native tools. Prompts and output caches can contain task data; do not publish `.digital-object`, `.baml`, runtime state or exports. The source-release workflow archives only committed files and uses read-only permissions except the tag-release job.

## Scan policy

Gitleaks scans committed source with redacted output. Bandit 1.9.4 scans all runtime Python; the gate fails on skipped files, scan errors or medium/high findings. Its low-severity `B404`, `B603` and `B607` subprocess notices remain visible. These sites intentionally invoke BAML, Git and the native Claude CLI using argument arrays and no shell. Executable discovery and host PATH are trusted. The IPC, sandbox, output-limit and redirect tests exercise the relevant boundaries rather than suppressing those findings.

These scans and regression tests are not an independent penetration test. Report vulnerabilities privately to repository maintainers; do not include credentials, model caches or private traces in public issues.
