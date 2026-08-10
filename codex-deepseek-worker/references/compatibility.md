# Compatibility and safety

## Supported V1 surface

- macOS and Windows
- Python 3.9+ with the bundled TOML compatibility parser
- ChatGPT/Codex desktop app launched at least once
- Official DeepSeek Responses-compatible endpoint used by Codex
- `deepseek-v4-flash`
- Reasoning effort `high`
- Text input and output only

V4 Pro is not exposed by V1 until its native Codex path is verified with the same metadata checks used for Flash.

## Managed locations

The default `CODEX_HOME` is `~/.codex`:

- Codex config: `$CODEX_HOME/config.toml`
- Merged model catalog: `$CODEX_HOME/models-with-deepseek.json`
- Subagent role: `$CODEX_HOME/agents/DeepSeek.toml`
- Manifest and backups: `$CODEX_HOME/codex-deepseek-worker/`
- Credential target: `codex-deepseek-worker-api-key`

The manager does not change the top-level `model` or `model_provider`.

## Role-name migration

Version 1 originally installed `$CODEX_HOME/agents/DeepSeekWorker.toml`. A current
`repair` recognizes that file only when its content hash matches the manager's
manifest, includes it in the transaction backup, replaces it with
`$CODEX_HOME/agents/DeepSeek.toml`, and verifies the new `DeepSeek` role. An
unrecognized or user-modified legacy file is reported as a conflict and preserved.

## Native routing

On macOS, the manager discovers the desktop app's bundled Codex runtime from the standard app locations. It does not search `PATH` or trust environment-variable install roots. On Windows, the caller must pass the exact trusted desktop runtime path explicitly with `--codex-bin`; the manager never automatically executes a discovered file.

The manager reads the active parent model, disables `features.multi_agent_v2`, and sets that parent model's catalog entry to `multi_agent_version = "v1"`. This is required by the currently validated cross-provider plaintext routing path. Run `repair` whenever the parent model changes.

Daily tasks must be delegated by the parent Codex agent:

```text
spawn_agent(agent_type="DeepSeek", fork_turns="none", ...)
```

If the current task does not recognize the custom role, restart Codex and open a new task. The management script is not a fallback coding agent.

## Verification evidence

`setup` and `test` create an isolated validation task. Readiness requires both:

1. child-task metadata from the `threads` table in `$CODEX_HOME/state_*.sqlite`:

   ```text
   model_provider = deepseek
   model = deepseek-v4-flash
   reasoning_effort = high
   agent_role = DeepSeek
   ```

2. the exact child response `NATIVE_DEEPSEEK_WORKER_OK`.

A model self-report or a successful direct API call alone is insufficient.

## Credentials

Read the API key from standard input. Store it in macOS Keychain or Windows Credential Manager. Never put it in command arguments, config files, temporary files, fixtures, raw result payloads, or final summaries.

## Transactions and conflicts

Before writing, create a timestamped backup. Validate generated TOML and JSON before atomic replacement. Restore the transaction on installation, write, or live-test failure.

Do not silently overwrite incompatible existing DeepSeek provider or role configuration. Compatible existing configuration may be adopted and must be recorded in the manifest.

## Visual inputs

`DeepSeek` is text-only in V1. The parent agent must inspect images, screenshots, or video and provide only the relevant textual facts. The subagent must not imply that it saw the original visual input.
