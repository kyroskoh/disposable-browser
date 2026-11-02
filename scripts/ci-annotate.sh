#!/usr/bin/env bash
# Run a CI step; if it fails, publish its last output lines as a GitHub error
# annotation, so the failure can be read on the run page and from the public
# check-runs API without downloading logs.
#   usage: scripts/ci-annotate.sh <title> <command> [args...]
set -uo pipefail

title="$1"
shift
log="$(mktemp)"
"$@" 2>&1 | tee "$log"
rc=${PIPESTATUS[0]}
if [ "$rc" -ne 0 ]; then
  # Annotation messages encode newlines as %0A and percent signs as %25.
  body="$(tail -n 60 "$log" | sed -e 's/%/%25/g' | awk '{printf "%s%%0A", $0}')"
  echo "::error title=${title} failed (exit ${rc})::${body}"
fi
rm -f "$log"
exit "$rc"
