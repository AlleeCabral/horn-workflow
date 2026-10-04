# Contributing to hornflow

## The one rule

**`main` is read-only.** Every change — code, tests, docs, config — starts on a
short-lived branch and lands through a pull request. `main` must always be green
(`147/147` legacy checks + `122` pytest checks) and always deployable-with-a-clone.

A local `pre-commit` hook enforces this (`.githooks/pre-commit`). It refuses to
commit while `HEAD` is `main`.

## Branches

```bash
git switch -c feat/workflow-tab          # branch off an up-to-date main
# ... work, commit, test ...
git push -u origin feat/workflow-tab     # GitHub prints the "Compare & pull request" link
```

Start from a fresh `main`:

```bash
git switch main && git pull
git switch -c <type>/<slug>
```

| type | use for |
|---|---|
| `feat` | a new capability (e.g. `feat/m4-local-host`) |
| `fix` | a defect fix (e.g. `fix/vips-crlf-parse`) |
| `docs` | documentation only |
| `test` | tests only |
| `refactor` | behaviour-preserving change |
| `perf` | performance |
| `build` / `ci` | packaging, dependencies, automation |
| `chore` | everything else |

Slug rules: lowercase, `-` separated, ≤ 40 chars, describes the change not the
ticket. One branch = one logical change. Delete the branch after the merge.

## Commits

Conventional Commits, imperative mood, ≤ 72 characters in the subject:

```
<type>(<scope>): <summary>

<why it was needed, and what it costs>
```

Scopes are the package names: `app`, `bem`, `fold`, `mfg`, `viz`, `workflow`,
`docs`, `tests`, `deps`.

```
feat(app): emit the workflow view model from state.json
fix(bem): keep .vips line endings intact on checkout
docs(adr): record ADR-0011 (local-first UI, no Jira)
test(fold): pin the J-fold centreline length
```

Rules:
* one logical change per commit; do not mix a refactor with a feature;
* never rewrite published history (`main` is never force-pushed);
* a commit that changes behaviour must say *why* in the body, and must record any
  regression risk.

## Before you push

```bash
python3 tests/test_theory.py       # 147 legacy checks - must stay 147/147
python3 -m pytest tests/ -q        # pytest suite - must stay green
```

Both must pass on the branch tip. **Do not weaken a numerical tolerance to make a
test pass** — if a tolerance looks wrong, fix the premise and say so in the commit
body (see the `%.10g` duplicate-grid case in `history.md`).

If you touch the acoustic core, `tests/test_baseline.py` must still match the frozen
JBL numbers byte-for-byte.

## What belongs in git

`.gitignore` is the contract. The short version:

* **tracked:** `hornflow/`, `tests/` (including `tests/fixtures/`), `params/`,
  `docs/`, `tools/`, the `requirements*.txt` files, the top-level docs, and the
  vendored three.js under `hornflow/viz/viewer/vendor/`;
* **ignored:** `runs/` and `results/` (both generated), `AKABAK/` (426 MB of
  third-party Windows binaries), `.hypothesis/`, `.pytest_cache/`, `__pycache__/`.

Test data that the suite *reads* lives under `tests/fixtures/` — that is why the
real AKABAK `.vips` exports are copied to `tests/fixtures/bem_export/` rather than
read out of `results/`.

`.gitattributes` pins line endings: `tests/fixtures/**` and `*.vips` are marked
`-text` so nothing is ever normalised, because `tests/test_baseline.py` asserts
their sha256.

## The working documents

Four files carry the project's memory; keep them current in the same PR as the
change they describe:

| file | role |
|---|---|
| `history.md` | run-book: commands, paths, ground rules, and a dated session entry per change |
| `handoff.md` | the prompt to resume work in a fresh session |
| `docs/adr.md` | architecture decisions (problem → alternatives → decision → consequences → validation) |
| `docs/migration-notes.md` | layout, run map, and what is deliberately deferred |

A change that alters behaviour without touching one of these is incomplete.

## Dependencies

Production stays on `numpy`, `scipy`, `PyYAML`, `matplotlib`. Adding anything else
needs an explicit decision recorded in `docs/adr.md`, with its licence, its effect
on reproducibility, and the tests that validate the integration.
