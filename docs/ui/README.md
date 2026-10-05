# Workflow tab - review screenshots

`workflow-before-*` is the pre-Phase-2 Workflow tab (commit `bdfb7a5`);
`workflow-after-*` is the accordion redesign.  Both are rendered from the same JBL
1200B example by the same headless browser, so the comparison is like-for-like.

| file | width | what it shows |
|---|---|---|
| `workflow-before-375px.png` | 375 px | the regression: eight bands stacked, W4 claiming "wave A complete" with blank values, `operating_orientationUNKNOWN` collisions, the strip clipped at the right edge |
| `workflow-before-1440px.png` | 1440 px | the same, wide: every group expanded at once |
| `workflow-after-375px.png` | 375 px | summary + nine collapsed stages, the current one open, one column, nothing clipped |
| `workflow-after-1440px.png` | 1440 px | the same, wide: two-column field grid, "report only / complete" engineering stages collapsed |
| `workflow-live-375px.png` | 375 px | **M4**: the same page served by `python3 -m hornflow.app` and connected to a live host — editable fields, the run box, the real manual-BEM checkpoint |
| `workflow-live-1440px.png` | 1440 px | the same, wide: a frozen brief (20/20 answers), 15/16 gates passed, `GUI_REQUIRED`, next action "Copy AKABAK checklist" with the exact command |

The `-live-` pair is the vertical slice of Phase 3: the brief was frozen over
`POST /api/brief/freeze` and the run started over `POST /api/run`, and the page shows
the resulting state read back from disk.

## Regenerating

```bash
tools/shoot_ui.sh runs/<run_id> /tmp/shots          # TAB=workflow HEIGHT=1500
TAB=viewer tools/shoot_ui.sh runs/<run_id> /tmp/shots
```

The script uses `google-chrome --headless=new --screenshot` directly - there is no
browser-automation dependency.  The same browser tool backs the DOM smoke tests in
`tests/test_workflow_ui.py` (`--dump-dom`), so the assertions run against a real
rendered document, not against string templates.

## Acceptance widths

375 / 768 / 1280 / 1440 / 1920 px.  At each width the requirements are: no
overlapping text, no clipped labels or values, no horizontal page overflow, usable
buttons, understandable stage state, and a visible keyboard focus ring.  The first
three are structurally enforced (`#pane-workflow { overflow-x: hidden }`,
`min-width: 0` on flex children, a single-column grid below 900 px, `pre.cmd`
wrapping), and the CSS is asserted in `tests/test_workflow_ui.py`.
