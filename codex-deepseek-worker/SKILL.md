---
name: codex-deepseek-worker
description: Configure, inspect, test, repair, disable, or uninstall DeepSeek V4 Flash and V4 Pro as native text-only Codex workers. Use when a user asks to add a DeepSeek worker or native DeepSeek subagent to Codex, verify its actual provider routing, repair it after a parent-model change, or remove its managed configuration. Do not trigger for general DeepSeek API questions or ordinary coding tasks after the workers are configured.
---

# Codex DeepSeek

Manage the native `DeepSeek` configuration only. Do not use this Skill as a substitute execution path for daily coding work. Delegate deterministic configuration, catalog, credential, backup, and verification operations to `scripts/deepseek_worker.py`; do not hand-edit TOML, JSON, agent files, or credential stores.

## Preserve these contracts

- Use the Codex desktop app's bundled runtime. Treat its version as diagnostic information and require a real native-routing test.
- Read the current parent model from Codex configuration. Do not hardcode or replace the user's primary model or login.
- Require `multi_agent_version = "v1"` for the current parent model, `deepseek-v4-flash`, and `deepseek-v4-pro`, and keep `features.multi_agent_v2 = false`. A v2 target can encrypt away the cross-provider task payload even when the parent is v1.
- Run `repair` after the parent model changes, then verify again.
- Treat `DeepSeek` as text-only. Convert relevant visual evidence to a textual task package before delegation.
- Keep the first-instance nickname candidates pinned to `DeepSeek-v4-flash` and `DeepSeek-v4-pro`. Codex may add an ordinal suffix when multiple instances share one parent task because child names must remain unique.
- Do not claim to customize the child icon. Native agent role files do not currently expose an icon field; Codex Desktop renders its generic subagent icon.
- For daily work, have the parent Codex agent call:

  ```text
  spawn_agent(agent_type="DeepSeek-v4-flash", fork_turns="none", ...)
  spawn_agent(agent_type="DeepSeek-v4-pro", fork_turns="none", ...)
  ```

- If the active tool schema does not expose `DeepSeek-v4-flash` or `DeepSeek-v4-pro`, ask the user to restart Codex and open a new task. Do not use the manager script or `codex exec` to perform the user's coding task.
- Accept daily work only from the DeepSeek child's returned result. If the child reports a missing assignment, report a handoff failure and run `repair`; the parent must not substitute its own output or present that fallback as DeepSeek work.
- Read [references/worker-routing.md](references/worker-routing.md) when deciding what to delegate. Read [references/compatibility.md](references/compatibility.md) for configuration, routing, and rollback details.

## Follow this workflow

1. Run `status --json` and branch on its structured result.
2. For first-time configuration, run `setup --json`. For parent-model drift or damaged managed configuration, run `repair --json`.
3. If the result is `credential_missing`, request the DeepSeek API key once. Never echo it or write it to a temporary file. Pass it only through standard input with `--api-key-stdin`.
4. Let `setup` or `test` create an isolated validation task through the bundled desktop runtime.
5. Accept `ready` only when the parent, Flash, and Pro catalog entries use plaintext V1; each child-task database record matches the expected provider, model, effort, role, and first-instance nickname; and the children return `NATIVE_DEEPSEEK_WORKER_OK` and `NATIVE_DEEPSEEK_PRO_WORKER_OK` respectively.
6. Report the final status, actual provider, both models, reasoning effort, roles, nicknames, and backup location. Do not print credentials or raw event logs.

## Use the manager

Use `python3` on macOS and `py -3` on Windows:

```text
python3 <skill-dir>/scripts/deepseek_worker.py <command> --json
```

- `status`: Inspect runtime, configuration, catalog, credential, role, and manifest without changing them.
- `setup`: Install the managed provider/catalog/role and perform live verification.
- `test`: Run a direct provider test followed by native `DeepSeek` routing verification.
- `repair`: Reapply the managed configuration for the current parent model and verify it.
- `disable`: Disable the managed worker while preserving provider data and credentials.
- `uninstall`: Remove managed configuration. Pass `--remove-credential` only when explicitly requested.

Use the current `CODEX_HOME` unless the user explicitly provides another location.

## Handle statuses

- `ready`: Direct and native routing checks passed.
- `configured`: Static configuration is complete, but live verification was intentionally skipped.
- `credential_missing`: Request the API key and continue the same flow.
- `operation_in_progress`: Wait and retry; do not modify configuration concurrently.
- `conflict`: Report the exact paths or fields and ask before replacing unrelated configuration.
- `unsupported` or `unsupported_python`: Report the missing capability or runtime requirement. Do not bypass it.
- `partial` or `failed`: Read `checks` and `errors`. If rollback occurred, say so and do not hand-edit the failed transaction.
- `handoff_failed`: The child started but did not receive or complete the assignment. Do not accept a matching parent response as proof; run `repair`, restart Codex, and repeat the desktop smoke test.
