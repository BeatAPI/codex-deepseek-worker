# Worker routing guide

Use `DeepSeek` when the task is bounded, text-only, and benefits from long-context reading, parallel capacity, or an independent model pass.

## Good worker tasks

- Trace one request path through a repository and cite the relevant files.
- Implement one approved change with a clear file boundary.
- Generate focused tests for an existing behavior.
- Review a diff independently and return prioritized findings.
- Summarize source-controlled technical behavior into documentation.

## Keep with the parent Codex agent

- Ambiguous product decisions or work that still needs scope negotiation.
- Visual inspection, image editing, browser UI judgment, or video analysis.
- Final integration across multiple worker results.
- Production deployment, publishing, credential policy, or destructive actions.
- Security, legal, financial, or other high-impact final decisions.

## Build a bounded assignment

Include:

1. objective and non-goals;
2. relevant files or repository area;
3. whether edits are allowed;
4. required verification;
5. constraints on unrelated changes;
6. the expected evidence in `WORKER_REPORT`.

Do not ask the worker to “fix everything” or infer permission for broad refactors.

## Review the result

The parent agent must inspect the diff and verification evidence before accepting the work. Compare claims with files, tests, and command output. Treat missing evidence, skipped tests, and inferred behavior as open items.
