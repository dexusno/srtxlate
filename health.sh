#!/usr/bin/env bash
set -euo pipefail

test_endpoint () {
  local name="$1" url="$2"
  echo "Checking ${name} at ${url} ..."
  if curl -fsS -m 10 -o /dev/null "${url}"; then
    echo "  [${name}] OK (200)"
    return 0
  else
    echo "  [${name}] ERROR"
    return 1
  fi
}

show_nllb_health () {
  local url="$1"
  echo "Checking nllb-healthz at ${url} ..."
  if out="$(curl -fsS -m 10 "${url}")"; then
    echo "  [nllb-healthz] OK (200)"
    # pretty print snippets if jq is present
    if command -v jq >/dev/null 2>&1; then
      echo "$out" | jq -r '["device: \(.device // "")",
                            "model_dir: \(.model_dir // "")",
                            "model_id: \(.model_id // "")",
                            "resolved_model: \((.resolved_model.source // "") + " -> " + (.resolved_model.value // ""))"][]'
    else
      # fallback manual parse
      echo "$out" | sed -E 's/^/    /'
    fi
    return 0
  else
    echo "  [nllb-healthz] ERROR"
    return 1
  fi
}

app_url="http://127.0.0.1:8080/"
libre_url="http://127.0.0.1:5000/"
nllb_url="http://127.0.0.1:6100/healthz"

ok=true
test_endpoint "app" "$app_url" || ok=false
test_endpoint "libretranslate" "$libre_url" || ok=false
show_nllb_health "$nllb_url" || ok=false

if $ok; then
  echo
  echo "All services look healthy."
else
  echo
  echo "One or more services are NOT healthy."
  exit 1
fi
