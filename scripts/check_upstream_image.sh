#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
CURRENT=$(sed -n 's|^[[:space:]]*image:[[:space:]]*yym68686/chatgpt@\(sha256:[0-9a-f]*\).*|\1|p' "$ROOT/docker-compose.yml" | head -1)
TMP=$(mktemp /tmp/gptbot-manifest.XXXXXX)
trap 'rm -f "$TMP"' EXIT

resolved=false
for attempt in 1 2 3; do
  if docker manifest inspect --verbose yym68686/chatgpt:latest > "$TMP" 2>/dev/null; then
    resolved=true
    break
  fi
  sleep "$attempt"
done

if [ "$resolved" != true ]; then
  echo "registry_query_failed"
  exit 2
fi

LATEST=$(python3 -c 'import json,sys; data=json.load(open(sys.argv[1])); rows=data if isinstance(data,list) else [data]; print(next((r["Descriptor"]["digest"] for r in rows if r.get("Descriptor",{}).get("platform",{}).get("architecture")=="amd64"),""))' "$TMP")
if [ -z "$CURRENT" ] || [ -z "$LATEST" ]; then
  echo "unable_to_resolve_digest"
  exit 2
fi

echo "current=$CURRENT"
echo "latest_amd64=$LATEST"
if [ "$CURRENT" = "$LATEST" ]; then
  echo "up_to_date"
else
  echo "update_available"
fi
