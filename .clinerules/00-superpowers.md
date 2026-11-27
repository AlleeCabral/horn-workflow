# Superpowers bootstrap

Skills live in `.cline/skills/<name>/SKILL.md`. Install or refresh them with `bash tools/setup_cline_superpowers.sh`.

When the user asks to build, change, debug, test, plan, review or finish software:
1. First list the applicable skills from `.cline/skills/`.
2. Read and follow their `SKILL.md` instructions before editing files.

Before starting any non-trivial implementation task:

1. Inspect the available skills under `.cline/skills/`.
2. Read the relevant `SKILL.md` files before acting.
3. For any feature, refactor, debugging task or multi-step change:
   - Start with `brainstorming`, unless an approved plan already covers the task. In that case, open the plan instead.
   - Produce an implementation plan with `writing-plans`.
   - Use `test-driven-development` where tests are feasible.
   - Use `systematic-debugging` rather than guessing.
   - Use `verification-before-completion` before claiming anything is done.
4. Do not write production code before the intended outcome and acceptance criteria are clear.
5. Keep tasks small, reversible and independently verifiable.

If a requested task is trivial, state why the full Superpowers workflow is unnecessary, then proceed directly.

## Name mapping

Plans in `docs/superpowers/plans/` name skills as `superpowers:<name>` (Claude Code style). In Cline, that is the folder `.cline/skills/<name>/`; for example, `superpowers:writing-plans` means `.cline/skills/writing-plans/SKILL.md`.

`subagent-driven-development` needs subagents that Cline does not have. Use `executing-plans` instead. After each task, do the review step of `requesting-code-review` in a **new Cline task** that sees only the diff, the plan task and the spec. That approximates a fresh reviewer.
