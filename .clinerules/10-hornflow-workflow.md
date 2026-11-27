# HornFlow project rules

## Where things are

- **Design spec:** `docs/superpowers/specs/2026-11-26-hornflow-roadmap-design.md`.
- **Roadmap (all phases):** `docs/superpowers/plans/2026-11-26-hornflow-roadmap.md`.
- **Phase 0 plan (detailed, ready):** `docs/superpowers/plans/2026-11-26-phase0-trustworthy-core.md`.
- **Audit (finding IDs such as S1, P3, B2):** `docs/audit/2026-11-26-hornflow-audit.md`.
- **Handoff and start prompt:** `docs/cline/HANDOFF.md`.

## One task = one Jira issue = one branch = one pull request

- Every plan task has a Jira issue in project **HORN**. Create it before the branch if it is missing.
- Branch name: `<type>/HORN-<n>-<short-slug>`, where type is `fix`, `feat`, `docs`, `test` or `chore`. Example: `test/HORN-12-run-fixture`.
- Branch from the latest `main`. When a task depends on an unmerged earlier task, branch from that task's branch and say so in the pull request.
- Every commit message starts with the issue key: `HORN-12 test: self-contained run fixture`.
- The pull request title starts with the issue key. The body links the Jira issue and the plan task, and fills `.github/pull_request_template.md`.
- Move the Jira issue to In Progress when the branch is created, to In Review when the pull request opens, and to Done when it merges.
- Never commit to `main` (the `.githooks/pre-commit` hook enforces this; enable it with `git config core.hooksPath .githooks`).

## Logins and connections

Never guess or skip credentials. When a step needs GitHub, Atlassian, an MCP server or any other login, **stop and ask the user to do it**, with exact instructions. Then wait.

Never write tokens into files, commits, rules or chat.

## Tests

- **Full suite:** `python3 tests/test_theory.py && python3 -m pytest tests -q`.
- **Single test:** `python3 -m pytest tests/<file>.py::<test> -q`.
- **Baseline before Phase 0:** 147/147 theory checks; pytest 198 passed, 34 errors, all in `tests/test_app_api.py` (missing `runs/`). Phase 0 Task 1 fixes those errors.
- Paste real command output before claiming a task is done.

## Conventions (from the spec's Global Constraints)

- All rms/peak and Xmax conversions go through `hornflow/domain/excursion.py`.
- All `state.json` writes go through `hornflow/io/state_store.py`.
- The browser never computes completion, verdicts or physics; the Python model does.
- No new production dependencies. Optional ones go in `requirements-optional.txt` and are imported lazily.
- No absolute paths in code or generated files.
- Generated report and UI text uses no em dashes or en dashes.
