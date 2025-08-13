# Run from repo root:  .\setup.ps1
$ErrorActionPreference = 'Stop'

function Require-Cmd($name) { if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { throw "$name not found on PATH." } }
function Read-EnvVar([string]$key) {
  $envPath = Join-Path (Get-Location).Path ".env"
  if (-not (Test-Path -LiteralPath $envPath)) { return $null }
  $line = (Get-Content $envPath) | Where-Object { $_ -match "^\s*$key\s*=" } | Select-Object -First 1
  if (-not $line) { return $null }
  ($line -replace "^\s*$key\s*=\s*", "").Trim()
}
function Ensure-Dir([string]$p){ if(-not(Test-Path -LiteralPath $p)){ New-Item -ItemType Directory -Path $p | Out-Null } }

function Download-Model([string]$modelId,[string]$folderName){
  $root = (Get-Location).Path
  $modelsRoot = Join-Path $root "models"
  $targetDir = Join-Path $modelsRoot $folderName
  Ensure-Dir $modelsRoot
  Ensure-Dir $targetDir
  Write-Host "`nDownloading $modelId -> $targetDir`n"
  docker run --rm `
    -e MODEL_ID="$modelId" `
    -e HF_HUB_DISABLE_TELEMETRY=1 `
    -e HF_HUB_ENABLE_XET=0 `
    -v "${targetDir}:/download" `
    python:3.11-slim `
    bash -lc @'
set -e
pip install --no-cache-dir "huggingface_hub==0.23.2"
python - << "PY"
import os
from huggingface_hub import snapshot_download
mid = os.environ["MODEL_ID"]
print(f"Fetching: {mid}")
snapshot_download(repo_id=mid, local_dir="/download",
                  local_dir_use_symlinks=False, resume_download=True)
print(f"Done: {mid} -> /download")
PY
'@
  Write-Host "`n✅ Completed: $modelId`n"
}

function Download-Menu(){
  while($true){
    Clear-Host
    Write-Host "Which model would you like to download?`n"
    Write-Host "  1) nllb-200-3.3B"
    Write-Host "  2) nllb-200-distilled-1.3B"
    Write-Host "  3) nllb-200-distilled-600M"
    Write-Host "  4) Done (exit download menu)"
    $choice = Read-Host "Enter choice"
    switch($choice){
      "1" { Download-Model "facebook/nllb-200-3.3B"           "nllb-200-3.3B";               Pause }
      "2" { Download-Model "facebook/nllb-200-distilled-1.3B" "nllb-200-distilled-1.3B";     Pause }
      "3" { Download-Model "facebook/nllb-200-distilled-600M" "nllb-200-distilled-600M";     Pause }
      "4" { return }
      default { Write-Host "Invalid choice."; Pause }
    }
  }
}

function Check-Or-Offer-Download() {
  $local = Read-EnvVar "NLLB_MODEL_LOCAL"
  if (-not $local) { return $true }
  $folder = Join-Path (Get-Location).Path ("models\" + $local)
  if (-not (Test-Path -LiteralPath $folder)) {
    Write-Host "No local model found: $folder" -ForegroundColor Yellow
    $ans = Read-Host "Open model download menu now? (y/N)"
    if ($ans -in @("y","Y","yes","YES")) {
      Download-Menu
      if (-not (Test-Path -LiteralPath $folder)) {
        Write-Host "Model still not found after download." -ForegroundColor Red
        return $false
      }
    } else {
      Write-Host "Skipping local model download (will use HF Hub fallback if configured)." -ForegroundColor Yellow
    }
  }
  return $true
}

function Has-GPU() {
  try { $null = docker run --rm --gpus all nvidia/cuda:12.1.1-base nvidia-smi 2>$null; return $LASTEXITCODE -eq 0 } catch { return $false }
}

Require-Cmd docker

while ($true) {
  Clear-Host
  Write-Host "SRTXlate Setup`n"
  Write-Host "  1) Download models only"
  Write-Host "  2) Build & Start GPU stack"
  Write-Host "  3) Build & Start CPU stack"
  Write-Host "  4) Start GPU stack (no rebuild)"
  Write-Host "  5) Start CPU stack (no rebuild)"
  Write-Host "  6) Run health checks"
  Write-Host "  7) Exit"
  $opt = Read-Host "Enter choice"
  switch ($opt) {
    "1" { Download-Menu; continue }
    "2" {
      if (-not (Check-Or-Offer-Download)) { exit 1 }
      if (-not (Has-GPU)) { Write-Host "Warning: Docker GPU runtime not detected. GPU stack may fail." -ForegroundColor Yellow }
      docker compose -f docker-compose.gpu.yml up -d --build
      continue
    }
    "3" {
      if (-not (Check-Or-Offer-Download)) { exit 1 }
      docker compose -f docker-compose.yml up -d --build
      continue
    }
    "4" { docker compose -f docker-compose.gpu.yml up -d; continue }
    "5" { docker compose -f docker-compose.yml up -d; continue }
    "6" {
      if (Test-Path -LiteralPath ".\health.ps1") { & .\health.ps1 } else { Write-Host "health.ps1 not found." -ForegroundColor Yellow }
      Pause; continue
    }
    "7" { exit 0 }
    default { Write-Host "Invalid choice."; Pause }
  }
}
