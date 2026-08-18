# Codex DeepSeek

Run DeepSeek V4 Flash and V4 Pro as native text-only workers inside Codex while keeping your existing Codex model as the orchestrator.

**Bring DeepSeek V4 Pro's flagship agentic coding and 1M-token context into Codex
without replacing your primary Codex model, login, or orchestration workflow.**

Use the explicit worker names to choose the right tier per task:

| Worker | Best for |
| --- | --- |
| `DeepSeek-v4-flash` | Fast repository exploration, focused tests, routine implementation, and economical parallel work |
| `DeepSeek-v4-pro` | Difficult coding, deeper reasoning, long-context synthesis, and high-value independent review |

DeepSeek describes V4 Pro as its flagship model with enhanced agentic coding,
reasoning, and knowledge capabilities. This project makes that model a verified
native Codex subagent instead of asking you to replace Codex wholesale.

## Why a worker instead of a model switch?

Codex remains responsible for task decomposition, visual inputs, integration decisions, and final verification. `DeepSeek` receives bounded text tasks such as:

- exploring a large repository and returning evidence;
- implementing one isolated change;
- generating or extending focused tests;
- reviewing a diff with a second model;
- drafting technical documentation from source files.

The subagent is deliberately not the final decision-maker. Its agent contract requires a compact `WORKER_REPORT` with changed files, verification evidence, risks, and follow-ups.

## What it installs

- Native Codex roles: `DeepSeek-v4-flash` and `DeepSeek-v4-pro`
- First child display names in each new parent task use those same explicit model names
- Models: `deepseek-v4-flash` and `deepseek-v4-pro`
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
Use the DeepSeek-v4-flash subagent exactly once. Ask it to reply exactly DEEPSEEK_UI_OK,
wait for it, and return only its result. The parent must not answer on its behalf.
```

Open the completed child task and confirm the child itself received the assignment
and returned `DEEPSEEK_UI_OK`. A completed child that reports a missing assignment
is a failed handoff; the parent must not write the token or requested content itself.

The first Flash child in a new parent task is displayed as `DeepSeek-v4-flash`,
while the first Pro child is displayed as `DeepSeek-v4-pro`. Codex
requires child instance names to be unique, so additional DeepSeek children under
the same parent task may receive ordinal suffixes.
The child icon is currently owned by Codex Desktop's generic agent UI; native agent
role configuration does not expose a custom icon field.

Existing installations that used the former `DeepSeekWorker` role are migrated by
`repair`: the manager backs up the old agent file, installs `DeepSeek-v4-flash`,
removes only the old file it owns, and repeats direct plus native-routing verification.
Existing `DeepSeek` roles are migrated the same way to the explicit Flash name.

## Use the worker

Ask the parent Codex agent to delegate a bounded task:

```text
Use DeepSeek-v4-flash to inspect the authentication module, identify the failure path,
and return an evidence-based fix recommendation. Do not edit files.
```

For implementation:

```text
Use DeepSeek-v4-flash to implement the approved parser change and run the focused parser tests.
Return the diff summary, verification, risks, and follow-ups to the parent agent.
```

Use Pro for a bounded task where the stronger model is worth the higher API cost:

```text
Use DeepSeek-v4-pro to trace the cross-package failure, implement the smallest safe fix,
and run the focused tests. Return a WORKER_REPORT to the parent agent.
```

Codex delegates through the native agent mechanism:

```text
spawn_agent(agent_type="DeepSeek-v4-flash", fork_turns="none", ...)
spawn_agent(agent_type="DeepSeek-v4-pro", fork_turns="none", ...)
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

A successful direct API call is not enough. Native verification runs once for each
worker and must confirm both the exact child response and matching Codex metadata.

Flash:

1. the child task returns `NATIVE_DEEPSEEK_WORKER_OK`; and
2. Codex state metadata records:

```text
model_provider = deepseek
model = deepseek-v4-flash
reasoning_effort = high
agent_role = DeepSeek-v4-flash
agent_nickname = DeepSeek-v4-flash
```

Pro returns `NATIVE_DEEPSEEK_PRO_WORKER_OK` and records:

```text
model_provider = deepseek
model = deepseek-v4-pro
reasoning_effort = high
agent_role = DeepSeek-v4-pro
agent_nickname = DeepSeek-v4-pro
```

Only then does the manager return `status: ready`.

The merged model catalog must also record `multi_agent_version = "v1"` for the
current parent model, `deepseek-v4-flash`, and `deepseek-v4-pro`. Pinning only the
parent is not enough on current Desktop collaboration routing because the target
model can select the encrypted V2 handoff path.

## Model scope

The `DeepSeek-v4-flash` role stays on V4 Flash for fast, economical work. The
`DeepSeek-v4-pro` role exposes V4 Pro for demanding coding, reasoning, and long-context
tasks. Both are text-only and use the official DeepSeek API. The manager derives
Pro's Codex transport metadata from DeepSeek's official V4 Flash Codex template,
then accepts it only after direct and native-routing verification pass.

DeepSeek documents both model IDs, their shared 1M context, thinking modes, and
tool-call support in its [V4 release](https://api-docs.deepseek.com/news/news260424/)
and [model list](https://api-docs.deepseek.com/api/list-models/).

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
---

<sub>Maintained by <a href="https://github.com/BeatAPI"><b>BeatAPI</b></a> · <a href="https://beatapi.io">beatapi.io</a> — async AI video APIs for music videos and product ads.</sub>
