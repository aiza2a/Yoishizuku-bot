#!/bin/sh
set -eu

ROOT=/root/data/docker_data/gptbot
DEST=/root/backups/gptbot/daily
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
TMP="$DEST/.tmp-$STAMP"
FINAL="$DEST/$STAMP"

mkdir -p "$TMP"
chmod 700 /root/backups /root/backups/gptbot "$DEST" "$TMP"

python3 "$ROOT/scripts/backup_memory.py" "$TMP/memory.sqlite3"
tar -czf "$TMP/private-config.tar.gz" -C "$ROOT" .env data/user_configs data/access data/roles
chmod 600 "$TMP/private-config.tar.gz"
git -C "$ROOT" bundle create "$TMP/source.bundle" --all
chmod 600 "$TMP/source.bundle"
cp "$ROOT/RUNBOOK.md" "$TMP/RUNBOOK.md"
chmod 600 "$TMP/RUNBOOK.md"

git -C "$ROOT" bundle verify "$TMP/source.bundle"
tar -tzf "$TMP/private-config.tar.gz" > /dev/null
(
  cd "$TMP"
  sha256sum RUNBOOK.md memory.sqlite3 private-config.tar.gz source.bundle > SHA256SUMS
  sha256sum -c SHA256SUMS
)
chmod 600 "$TMP/SHA256SUMS"
mv "$TMP" "$FINAL"

find "$DEST" -mindepth 1 -maxdepth 1 -type d -name '20*T*Z' -printf '%T@ %p\n' \
  | sort -rn \
  | awk 'NR>14 {print $2}' \
  | xargs -r rm -rf

echo "$FINAL"
