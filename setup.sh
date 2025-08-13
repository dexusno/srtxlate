#!/usr/bin/env bash
# Run from repo root: ./setup.sh
set -euo pipefail

require_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing command: $1"; exit 1; }; }
read_env_var() {
  local key="$1" file=".env"
  [[ -f "$file" ]] || { echo ""; return 0; }
  local line; line=$(grep -E "^[[:space:]]*$key[[:space:]]*=" "$file" | head -n1 || true)
  [[ -n "$line" ]] || { echo ""; return 0; }
  echo "${line#*=}" | xargs
}

download_model () {
  local model_id="$1" target_dir="$2"
  mkdir -p "models/${target_dir}"
  echo; echo "Downloading ${model_id} -> ./models/${target_dir}"; echo
  docker run --rm -it \
    -e MODEL_ID="${model_id}" \
    -e HF_HUB_DISABLE_TELEMETRY=1 \
    -e HF_HUB_ENABLE_XET=0 \
    -v "$PWD/models/${target_dir}:/download" \
    python:3.11-slim \
    bash -lc '
set -e
pip install --no-cache-dir huggingface_hub==0.23.2
python - <<PY
import os
from huggingface_hub import snapshot_download
mid = os.environ["MODEL_ID"]
print("Fetching:", mid)
snapshot_download(repo_id=mid, local_dir="/download", local_dir_use_symlinks=False, resume_download=True)
print("Done:", mid, "-> /download")
PY
'
  echo; echo "✅ Completed: ${model_id}"; echo
  read -r -p "Press Enter to return to the menu" _
}

download_menu () {
  while true; do
    clear
    echo "Which model would you like to download?"
    echo
    echo "  1) nllb-200-3.3B"
    echo "  2) nllb-200-distilled-1.3B"
    echo "  3) nllb-200-distilled-600M"
    echo "  4) Done (exit download menu)"
    echo
    read -r -p "Enter choice (1-4): " choice
    case "$choice" in
      1) download_model "facebook/nllb-200-3.3B"           "nllb-200-3.3B" ;;
      2) download_model "facebook/nllb-200-distilled-1.3B" "nllb-200-distilled-1.3B" ;;
      3) download_model "facebook/nllb-200-distilled-600M" "nllb-200-distilled-600M" ;;
      4) break ;;
      *) echo; echo "Invalid choice."; sleep 1 ;;
    esac
  done
}

check_or_offer_download () {
  local local_name; local_name="$(read_env_var NLLB_MODEL_LOCAL || true)"
  [[ -z "$local_name" ]] && return 0
  local path="models/${local_name}"
  if [[ ! -d "$path" ]]; then
    echo "No local model found: ${path}"
    read -r -p "Open model download menu now? (y/N) " ans
    case "$ans" in
      y|Y|yes|YES) download_menu ;;
      *) echo "Skipping local model download (will use HF Hub fallback if configured)." ;;
    esac
    [[ -d "$path" ]] || { echo "Model still not found after download attempt."; return 1; }
  fi
  return 0
}

has_gpu () { docker run --rm --gpus all nvidia/cuda:12.1.1-base nvidia-smi >/dev/null 2>&1; }
run_health () { [[ -x "./health.sh" ]] && ./health.sh || { echo "health.sh not found/executable."; return 1; }; }

require_cmd docker

while true; do
  clear
  echo "SRTXlate Setup"
  echo
  echo "  1) Download models only"
  echo "  2) Build & Start GPU stack"
  echo "  3) Build & Start CPU stack"
  echo "  4) Start GPU stack (no rebuild)"
  echo "  5) Start CPU stack (no rebuild)"
  echo "  6) Run health checks"
  echo "  7) Exit"
  echo
  read -r -p "Enter choice (1-7): " opt
  case "$opt" in
    1) download_menu ;;
    2) check_or_offer_download || exit 1; if ! has_gpu; then echo "Warning: Docker GPU runtime not detected. GPU stack may fail."; fi; docker compose -f docker-compose.gpu.yml up -d --build ;;
    3) check_or_offer_download || exit 1; docker compose -f docker-compose.yml up -d --build ;;
    4) docker compose -f docker-compose.gpu.yml up -d ;;
    5) docker compose -f docker-compose.yml up -d ;;
    6) run_health ;;
    7) exit 0 ;;
    *) echo "Invalid choice."; sleep 1 ;;
  esac
done
