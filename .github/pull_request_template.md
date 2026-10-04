## What this changes

<!-- one paragraph: what the change does and why it is needed -->

## Branch and commits

- [ ] work is on a branch off an up-to-date `main` (not committed to `main`)
- [ ] branch name follows `<type>/<slug>` (`CONTRIBUTING.md`)
- [ ] commits follow Conventional Commits, one logical change each

## Evidence

- [ ] `python3 tests/test_theory.py` → 147/147
- [ ] `python3 -m pytest tests/ -q` → green
- [ ] new behaviour is covered by a test that would fail without the change

<!-- paste the two result lines, or say which check you could not run and why -->

## What it costs

<!-- the honest trade-off: what got slower, larger, more complex, or less certain.
     Write "nothing" only if that is actually true. -->

## Deferred / not done

<!-- what you deliberately left out, and where it is recorded -->

## Docs kept current

- [ ] `history.md` session entry
- [ ] `docs/adr.md` (if a decision was made)
- [ ] `docs/migration-notes.md` (if layout/deferrals changed)
- [ ] `handoff.md` (if the next step changed)
