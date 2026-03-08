#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-/Library/Frameworks/Python.framework/Versions/3.10/bin/python3}"
KEEP_COUNT="${1:-30}"
BACKUP_DIR="instance/backups/sqlite"

if ! [[ "$KEEP_COUNT" =~ ^[0-9]+$ ]] || [ "$KEEP_COUNT" -lt 1 ]; then
  echo "invalid keep_count: $KEEP_COUNT (must be integer >= 1)" >&2
  exit 2
fi

mkdir -p "$BACKUP_DIR"

# Create a new canonical backup using the existing Flask CLI command.
"$PYTHON_BIN" -m flask --app finance_app sqlite-backup

# Enforce retention on canonical backup artifacts only.
shopt -s nullglob
files=( "$BACKUP_DIR"/finance_app_*.db )
shopt -u nullglob

if [ "${#files[@]}" -eq 0 ]; then
  echo "retention: no canonical backup files found under $BACKUP_DIR"
  exit 0
fi

IFS=$'\n' sorted=( $(ls -1t "${files[@]}") )
unset IFS

removed=0
for (( i=KEEP_COUNT; i<${#sorted[@]}; i++ )); do
  old="${sorted[$i]}"
  rm -f "$old" "$old-shm" "$old-wal"
  removed=$((removed + 1))
done

echo "retention: kept=$KEEP_COUNT total_before=${#sorted[@]} removed=$removed total_after=$(( ${#sorted[@]} - removed ))"
