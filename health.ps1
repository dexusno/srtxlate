# health.ps1 — matches server.py /healthz schema (configured_model, configured_model_dir, loaded_model)
$ErrorActionPreference = 'Stop'

function Test-Endpoint($name, $url) {
  Write-Host "Checking $name at $url ..."
  try {
    $resp = Invoke-WebRequest -UseBasicParsing -Uri $url -Method GET -TimeoutSec 10
    Write-Host "  [$name] OK ($($resp.StatusCode))"
    return $true
  } catch {
    Write-Host "  [$name] ERROR: $($_.Exception.Message)" -ForegroundColor Red
    return $false
  }
}

function Show-NllbHealth($url) {
  Write-Host "Checking nllb-healthz at $url ..."
  try {
    $json = Invoke-RestMethod -Uri $url -Method GET -TimeoutSec 15
    Write-Host "  [nllb-healthz] OK (200)"

    # Always show device & CUDA
    if ($null -ne $json.device)         { Write-Host "    device:          $($json.device)" }
    if ($null -ne $json.cuda_available) { Write-Host "    cuda_available:  $($json.cuda_available)" }

    # Show configured vs loaded
    $cfgModel = $json.configured_model
    $cfgDir   = $json.configured_model_dir
    $loaded   = $json.loaded_model

    if ($cfgDir)   { Write-Host "    configured_model_dir: $cfgDir" }
    if ($cfgModel) { Write-Host "    configured_model:     $cfgModel" }
    if ($loaded)   { Write-Host "    loaded_model:         $loaded" }

    # Best-effort source hint
    if ($loaded) {
      if ($cfgDir -and ($loaded -like "$cfgDir*")) {
        Write-Host "    source:               local folder ✅"
      } elseif ($cfgModel -and ($loaded -like "$cfgModel*")) {
        Write-Host "    source:               HF Hub ID ✅"
      } else {
        Write-Host "    source:               (could not determine from fields)" -ForegroundColor Yellow
      }
    } else {
      Write-Host "    note: model not yet loaded (no request made?)" -ForegroundColor Yellow
    }
    return $true
  } catch {
    Write-Host "  [nllb-healthz] ERROR: $($_.Exception.Message)" -ForegroundColor Red
    return $false
  }
}

# Defaults for local dev
$appUrl   = "http://127.0.0.1:8080/"
$libreUrl = "http://127.0.0.1:5000/"
$nllbUrl  = "http://127.0.0.1:6100/healthz"

$ok = $true
$ok = (Test-Endpoint "app" $appUrl)              -and $ok
$ok = (Test-Endpoint "libretranslate" $libreUrl) -and $ok
$ok = (Show-NllbHealth $nllbUrl)                 -and $ok

if ($ok) {
  Write-Host "`nAll services look healthy." -ForegroundColor Green
} else {
  Write-Host "`nOne or more services are NOT healthy." -ForegroundColor Red
}

Write-Host "Press Enter to continue..."
[void][System.Console]::ReadLine()
