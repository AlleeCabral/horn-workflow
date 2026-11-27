#!/usr/bin/env bash
# Install or refresh the Superpowers skills for Cline in this project.
# Skills are third-party (github.com/obra/superpowers) and are not committed:
# .cline/skills/ is gitignored, and this script recreates it.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

git clone --depth 1 https://github.com/obra/superpowers.git "$tmp/superpowers"
mkdir -p "$root/.cline/skills"
cp -r "$tmp/superpowers/skills/"* "$root/.cline/skills/"
git -C "$tmp/superpowers" rev-parse --short HEAD > "$root/.cline/skills/.superpowers-version"

echo "Installed skills:"
ls -1 "$root/.cline/skills"
echo "superpowers commit: $(cat "$root/.cline/skills/.superpowers-version")"
