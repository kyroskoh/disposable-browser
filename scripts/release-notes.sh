#!/usr/bin/env bash
# Print CHANGELOG.md sections as release notes.
#   usage: scripts/release-notes.sh <version> [<older version>...]   e.g. v0.2.2 0.2.1 0.2.0
# The first version's section is printed without a heading; each older version (for tags
# that never got a GitHub Release) follows under its own "## <version>" heading.
# CHANGELOG (env) overrides the changelog path.
set -euo pipefail

changelog="${CHANGELOG:-CHANGELOG.md}"

section() {
  local notes
  notes="$(awk -v ver="$1" '
    /^## \[/ { if (found) exit; if (index($0, "## [" ver "]") == 1) { found = 1; next } }
    /^\[[^]]+\]: / { if (found) exit }
    found { sub(/\r$/, ""); print }
  ' "$changelog")"
  if [ -z "$(printf '%s' "$notes" | tr -d '[:space:]')" ]; then
    echo "no CHANGELOG entry for $1" >&2
    return 1
  fi
  # Drop leading and trailing blank lines.
  printf '%s\n' "$notes" | sed -e '/./,$!d' | sed -e ':a' -e '/^\n*$/{$d;N;ba' -e '}'
}

section "${1#v}"
shift
for older in "$@"; do
  printf '\n## %s\n\n' "v${older#v}"
  # Older sections use ### headings already; nest them one level deeper.
  section "${older#v}" | sed -e 's/^### /#### /'
done
