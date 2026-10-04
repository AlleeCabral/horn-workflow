#!/usr/bin/env bash
# Render the local UI at the acceptance widths, headless, for review.
#
#   tools/shoot_ui.sh <run_dir> [out_dir]
#
# Uses google-chrome's headless screenshot - no new dependency, no browser
# automation library.  Widths are the ones the Workflow tab is accepted at.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="${1:?usage: shoot_ui.sh <run_dir> [out_dir]}"
OUT="${2:-/tmp/hf_ui_shots}"
TAB="${TAB:-workflow}"
HEIGHT="${HEIGHT:-2400}"
CHROME="${CHROME:-google-chrome}"

HTML="$(realpath "$RUN")/deliverables/viewer/viewer.html"
[ -f "$HTML" ] || { echo "no viewer.html in $RUN" >&2; exit 1; }
# file:// needs an absolute path with the spaces percent-encoded
URL="file://$(printf '%s' "$HTML" | sed 's/ /%20/g')?tab=$TAB"
mkdir -p "$OUT"

for W in 375 768 1280 1440 1920; do
  PNG="$OUT/${TAB}-${W}px.png"
  "$CHROME" --headless=new --disable-gpu --no-sandbox --hide-scrollbars \
     --force-device-scale-factor=1 --virtual-time-budget=4000 \
     --window-size="$W,$HEIGHT" --screenshot="$PNG" "$URL" >/dev/null 2>&1 || true
  if [ -s "$PNG" ]; then
    echo "wrote $PNG ($(stat -c%s "$PNG") bytes)"
  else
    echo "FAILED $PNG" >&2
  fi
done
