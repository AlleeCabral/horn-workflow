#!/usr/bin/env bash
# hornflow - first push: main, then the current branch, then the PR link.
#
# Prerequisite: an EMPTY repository must exist on GitHub (no README, no
# .gitignore, no licence).  This script refuses to guess; it checks first.
#
# Safe to re-run: it only creates/fast-forwards branches, never force-pushes.
set -euo pipefail

REMOTE="${REMOTE:-origin}"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "not a git repository" >&2
  exit 1
fi

if [ "$BRANCH" = "main" ]; then
  echo "Refusing to run from main: this helper pushes main AND the branch you"
  echo "are currently on.  Switch to the feature branch first (CONTRIBUTING.md)."
  exit 1
fi

echo "== checking the remote =="
if ! git ls-remote "$REMOTE" >/dev/null 2>&1; then
  url="$(git remote get-url "$REMOTE" 2>/dev/null || echo '<no remote>')"
  cat >&2 <<EOF
Cannot reach '$REMOTE' ($url).

Create the empty repository on GitHub first - no README, no .gitignore, no
licence - then re-run this script:

    git remote add origin git@github.com:<you>/<repo>.git   # if not set yet
    tools/first_push.sh
EOF
  exit 1
fi

echo "== pushing main =="
git push -u "$REMOTE" main

echo "== pushing $BRANCH =="
git push -u "$REMOTE" "$BRANCH"

web="$(git remote get-url "$REMOTE" \
  | sed -e 's#^git@github.com:#https://github.com/#' -e 's#\.git$##')"
echo
echo "Open the pull request:"
echo "  $web/compare/main...$BRANCH?expand=1"
