# Codex DeepSeek

Run DeepSeek V4 Flash as a native text-only worker inside Codex while keeping your existing Codex model as the orchestrator.

This project is for developers who want more parallel coding capacity, a low-cost long-context worker, or an independent model pass without replacing their primary Codex workflow.

## Why a worker instead of a model switch?

Codex remains responsible for task decomposition, visual inputs, integration decisions, and final verification. `DeepSeek` receives bounded text tasks such as:

- exploring a large repository and returning evidence;
- implementing one isolated change;
- generating or extending focused tests;
- reviewing a diff with a second model;
- drafting technical documentation from source files.

The subagent is deliberately not the final decision-maker. Its agent contract requires a compact `WORKER_REPORT` with changed files, verification evidence, risks, and follow-ups.

## What V1 installs

- Native Codex role: `DeepSeek`
- Model: `deepseek-v4-flash`
- Provider: official DeepSeek API
- Reasoning effort: `high`
- Secure credentials: macOS Keychain or Windows Credential Manager
- Transactional config changes with backups and rollback
- Direct-provider and native-routing verification
- Plaintext V1 handoff on both the parent and DeepSeek model catalog entries
- Parent-model preservation: the top-level Codex model and login are not replaced

V1 supports text tasks only. It does not claim image, screenshot, video, or multimodal support.

## Install

Requirements:

- macOS or Windows
- Python 3.9+ (no separate Python packages to install)
- ChatGPT/Codex desktop app launched at least once
- A DeepSeek API key

Install the Skill globally:

```bash
npx skills add BeatAPI/codex-deepseek-worker -g -y
```

Restart the desktop app, open a new Codex task, and ask:

```text
Use $codex-deepseek-worker to configure DeepSeek as a native Codex worker.
```

The Skill checks the current state before writing anything. If a credential is missing, it requests the API key and passes it to the manager through standard input.

After setup returns `ready`, restart Codex and open a new task so the native role is loaded.

For an end-to-end desktop smoke test, send this in the new task:

```text
@DeepSeek Reply exactly DEEPSEEK_UI_OK and nothing else.
```

Open the completed child task and confirm the child itself received the assignment
and returned `DEEPSEEK_UI_OK`. A completed child that reports a missing assignment
is a failed handoff; the parent must not write the token or requested content itself.

Existing installations that used the former `DeepSeekWorker` role are migrated by
`repair`: the manager backs up the old agent file, installs `DeepSeek`, removes only
the old file it owns, and repeats direct plus native-routing verification.

## Use the worker

Ask the parent Codex agent to delegate a bounded task:

```text
Use DeepSeek to inspect the authentication module, identify the failure path,
and return an evidence-based fix recommendation. Do not edit files.
```

For implementation:

```text
Use DeepSeek to implement the approved parser change and run the focused parser tests.
Return the diff summary, verification, risks, and follow-ups to the parent agent.
```

Codex delegates through the native agent mechanism:

```text
spawn_agent(agent_type="DeepSeek", fork_turns="none", ...)
```

Daily work does not run the setup Skill again.

Accept only the result returned by the DeepSeek child. If the child reports that it
did not receive an assignment, report the handoff failure and run `repair`; never
silently substitute output from the parent model and attribute it to DeepSeek.

## Management commands

The Skill calls these commands when needed.

macOS:

```bash
python3 codex-deepseek-worker/scripts/deepseek_worker.py status --json
python3 codex-deepseek-worker/scripts/deepseek_worker.py setup --api-key-stdin --json
python3 codex-deepseek-worker/scripts/deepseek_worker.py test --json
python3 codex-deepseek-worker/scripts/deepseek_worker.py repair --json
python3 codex-deepseek-worker/scripts/deepseek_worker.py disable --json
python3 codex-deepseek-worker/scripts/deepseek_worker.py uninstall --json
```

Windows:

```powershell
py -3 codex-deepseek-worker\scripts\deepseek_worker.py status --json
py -3 codex-deepseek-worker\scripts\deepseek_worker.py setup --api-key-stdin --json
py -3 codex-deepseek-worker\scripts\deepseek_worker.py test --json
py -3 codex-deepseek-worker\scripts\deepseek_worker.py repair --json
py -3 codex-deepseek-worker\scripts\deepseek_worker.py disable --json
py -3 codex-deepseek-worker\scripts\deepseek_worker.py uninstall --json
```

`uninstall` preserves the API key unless the user explicitly requests `--remove-credential`.

## Verification contract

A successful direct API call is not enough. Native verification must confirm both:

1. the child task returns `NATIVE_DEEPSEEK_WORKER_OK`; and
2. Codex state metadata records:

```text
model_provider = deepseek
model = deepseek-v4-flash
reasoning_effort = high
agent_role = DeepSeek
```

Only then does the manager return `status: ready`.

The merged model catalog must also record `multi_agent_version = "v1"` for both
the current parent model and `deepseek-v4-flash`. Pinning only the parent is not
enough on current Desktop collaboration routing because the target model can select
the encrypted V2 handoff path.

## Model scope

V1 intentionally defaults to DeepSeek V4 Flash. DeepSeek V4 Pro is available through DeepSeek's Chat Completions and Anthropic-compatible APIs, but this project will not expose Pro as a native Codex worker until the exact Codex routing path is independently verified.

## Safety and rollback

- API keys are never written to project files, command arguments, fixtures, or result payloads.
- Config, model catalog, and agent files are backed up before mutation.
- Invalid TOML/JSON, write failures, or failed live setup restore the transaction.
- Existing incompatible DeepSeek configuration is reported as a conflict instead of being overwritten.
- The worker does not change the primary Codex model or authentication method.

See [compatibility and safety](codex-deepseek-worker/references/compatibility.md) and the [worker routing guide](codex-deepseek-worker/references/worker-routing.md).

## Development

```bash
python3 scripts/test_worker_manager.py
python3 -m py_compile codex-deepseek-worker/scripts/deepseek_worker.py
python3 /path/to/skill-creator/scripts/quick_validate.py codex-deepseek-worker
```

## Project ownership

Codex DeepSeek is an open-source developer tool maintained by [BeatAPI](https://beatapi.io). It does not require a BeatAPI account or API key and is not affiliated with or endorsed by OpenAI or DeepSeek.

## License

This project is released under the [MIT License](LICENSE). It is maintained by BeatAPI and includes the MIT-licensed `tomli` compatibility parser for Python 3.9 and 3.10. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for attribution.
