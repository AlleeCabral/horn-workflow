# HornFlow handoff to Cline (VS Code, WSL)

- **Part A** is for you, the human: the one-off setup on your machine.
- **Part B** is the prompt you paste into Cline.

---

## Part A: one-off setup (you)

Run these in a WSL terminal.

### A1. Get the project with its history

You received `hornflow.bundle`, a git bundle that holds `main` plus the `docs/audit-and-roadmap` branch with the audit, the plans and these Cline rules. Copy it into WSL (for example from `/mnt/c/Users/<you>/Downloads/`), then:

```bash
cd ~/projects
git clone -b docs/audit-and-roadmap ~/hornflow.bundle horn-workflow
cd horn-workflow
git remote set-url origin https://github.com/AlleeCabral/horn-workflow.git
git fetch origin
git config core.hooksPath .githooks
```

### A2. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt -r requirements-dev.txt
python3 tests/test_theory.py && python3 -m pytest tests -q
```

Expected: `147/147 checks passed`, then `198 passed, 34 errors`. The 34 errors are known (audit T1) and are the first thing Phase 0 fixes.

### A3. Superpowers skills for Cline

```bash
bash tools/setup_cline_superpowers.sh
```

This fills `.cline/skills/` (gitignored). The rules in `.clinerules/` tell Cline to use them. Run the script again whenever you want newer skills.

### A4. GitHub login (for pushing and pull requests)

```bash
sudo apt install gh        # if it is not installed yet
gh auth login              # GitHub.com, HTTPS, "Login with a web browser"
gh auth setup-git
git push -u origin docs/audit-and-roadmap
```

### A5. Jira

1. **Create the site:** https://www.atlassian.com/software/jira/free (free plan, up to 10 users).
2. **Create the project:** Projects, then Create project, then Kanban, then team-managed. Name it **HornFlow**, with key **HORN**.
3. **Link Jira to GitHub so branches and pull requests appear on issues:**
   - In Jira, open Apps, then Explore more apps, and install **GitHub for Atlassian**.
   - Connect your GitHub account and choose the `horn-workflow` repository.
   - From then on, any branch, commit or pull request containing `HORN-<n>` shows on that issue automatically.
4. **Connect Cline to Jira** through the Atlassian Remote MCP server.
   - In VS Code, open Cline, then MCP Servers, then Configure (this edits `cline_mcp_settings.json`). Add:

```json
{
  "mcpServers": {
    "atlassian": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp.atlassian.com/v1/sse"]
    }
  }
}
```

   - A browser window opens for the Atlassian login the first time it starts. Approve access to your site.
   - Needs Node.js in WSL: `sudo apt install nodejs npm`, or install via nvm.
   - If Atlassian has moved the endpoint, take the current URL from Atlassian's "Remote MCP Server" documentation. The rest of the setup stays the same.

### A6. Model note (DeepSeek)

DeepSeek does not pick skills up automatically the way Claude Code does. The rules in `.clinerules/00-superpowers.md` make it list and read the skills explicitly. If it skips them, remind it: "List the applicable skills from `.cline/skills/` and read their SKILL.md first."

---

## Part B: prompt to paste into Cline

```text
You are continuing the HornFlow project (a horn loudspeaker design tool) in this repository.
Follow .clinerules/ at all times.

READ FIRST, in this order:
1. .clinerules/00-superpowers.md and .clinerules/10-hornflow-workflow.md
2. docs/superpowers/specs/2026-11-26-hornflow-roadmap-design.md   (what and why)
3. docs/superpowers/plans/2026-11-26-hornflow-roadmap.md          (all phases, skill workflow)
4. docs/superpowers/plans/2026-11-26-phase0-trustworthy-core.md   (the 16 tasks you will execute)
5. docs/audit/2026-11-26-hornflow-audit.md                         (evidence; finding IDs)
Then list the skills in .cline/skills/ and read: using-superpowers, executing-plans,
test-driven-development, systematic-debugging, requesting-code-review,
verification-before-completion, finishing-a-development-branch.

SETUP CHECKS (stop and ask me for anything missing; never guess credentials):
a. `gh auth status` succeeds and `git remote -v` points to AlleeCabral/horn-workflow.
   If not: ask me to run `gh auth login` (I log in), then continue.
b. The Atlassian MCP server is connected and you can see Jira project HORN.
   If not: tell me exactly which step of docs/cline/HANDOFF.md section A5 is missing, wait.
c. `python3 tests/test_theory.py && python3 -m pytest tests -q` gives 147/147 and
   198 passed, 34 errors (all in tests/test_app_api.py). Report the real output.
d. Push docs/audit-and-roadmap if it is not on origin, and open a pull request
   "HORN-<n> docs: audit, roadmap and Phase 0 plan" after creating that Jira issue.

JIRA STRUCTURE (create once, show me the list before creating, wait for my OK):
- One Epic per roadmap phase: "Phase 0 Trustworthy core", "Phase 1 Bench, diary, honesty labels",
  "Phase 2 Interactive bending", "Phase 3 Headless BEM", "Phase 4 Build companion and telescoping horn",
  "Phase 5 Measurement loop", "Phase 6 Consolidation and docs", "Phase 7 Nothing to install".
- One Task per Phase 0 plan task (Tasks 1 to 16) under the Phase 0 epic. Title = plan task title.
  Description = the task's Files and Interfaces blocks plus a link to the plan file and section.
- One Task per open decision D1 to D8 (label needs-decision), under the epic that needs it.

EXECUTION (Phase 0, plan order; Task 1 and 2 first):
For each task:
 1. Move its Jira issue to In Progress. Create branch <type>/HORN-<n>-<slug> from main
    (or from the branch it depends on; say so).
 2. Follow the plan task exactly, test first (test-driven-development). Run the failing test,
    show it fail, implement, show it pass, run the full suite.
 3. On any unexpected failure use systematic-debugging; do not guess.
 4. Commit with "HORN-<n> <type>: <summary>". Push. Open a PR titled "HORN-<n> ...",
    body from .github/pull_request_template.md, linking the Jira issue and plan task.
 5. Review: tell me to open a NEW Cline task with this text, and wait for its verdict:
    "Use .cline/skills/requesting-code-review. Review PR <url> against plan task <N> in
     docs/superpowers/plans/2026-11-26-phase0-trustworthy-core.md and the spec. Report
     only real problems with file:line."
    Handle its findings with receiving-code-review.
 6. Move the issue to In Review. Ask me to merge (or merge when I say so), then Done.
Stop after Task 2 and report, before continuing with the rest.

RULES: one task at a time; paste real command output before claiming success;
never commit to main; never store tokens in files; ask me whenever a login, permission
or decision (D1 to D8) is needed.
```
