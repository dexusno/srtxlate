# Automatic Subtitle Extraction & Translation Script

This PowerShell script automates the process of checking media files for existing Norwegian or English subtitles, extracting them if necessary, and translating English subtitles into Norwegian Bokmål using the `srtxlate` API.  

**This script can very easily be changed to support the language pair of your choice.  
(for linux version .sh see the bottom of this file)**

## Features

- **Supported containers:** MKV, MP4/MOV, WebM, OGM, AVI.
- **Text-based subtitle handling:** Automatically detects subtitle codecs that can be converted to `.srt`.
- **Language detection:** Checks for Norwegian or English subtitles, skipping files that already have Norwegian.
- **Embedded subtitle extraction:** Extracts English subtitles to `.eng.srt` using `ffmpeg`.
- **Translation:** Sends `.eng.srt` files to a running `srtxlate` server for translation into `.nb.srt`.
- **Progress reporting:** Shows live translation progress via SSE (server-sent events) in the console.
- **HI/SDH preference:** Prefers normal English subtitles over hearing-impaired versions unless only HI versions exist.

## How It Works

1. **Scan folder** for supported media files.
2. **Check for sidecar `.srt` files:**
   - Skip if Norwegian `.no.srt`, `.nb.srt`, or `.nob.srt` exists.
   - Translate English existing `.en.srt` or `.eng.srt` to Norwegian `.nb.srt`.
3. **If no sidecar:** Probe media files for embedded subtitle streams.
   - Skip if Norwegian subtitles exist.
   - Skip if only bitmap English subtitles exist.
   - Extract preferred English text-based subtitle to `.eng.srt`.
   - Translate `.eng.srt` to `.nb.srt`.
4. **Cleanup:** Optionally delete temporary `.eng.srt` after translation.

## Changing the Language Pair

If you want to try it with your own language options its easy to change the translation source and/or target:
- Modify `$SourceCode` and `$TargetCode` near the top of the script.
- Use [FLORES language codes](https://huggingface.co/facebook/nllb-200-distilled-600M) (e.g., `eng_Latn`, `fra_Latn`, `deu_Latn`).
- Example for English → French:
  ```powershell
  $SourceCode = "eng_Latn"
  $TargetCode = "fra_Latn"
  ```

---
```powershell
[CmdletBinding(SupportsShouldProcess)]
param(
  [Parameter(Mandatory=$true)]
  [string]$Path
)

$ErrorActionPreference = 'Stop'

# =======================
# Config
# =======================
# Only scan containers that can carry TEXT-based subs:
# MKV (Matroska), MP4/MOV (mov_text), WebM (webvtt), OGM, AVI (rarely text)
$VideoExt  = @('.mkv','.mp4','.mov','.webm','.ogm','.avi')

$NorLangs  = @('no','nor','nob','nb')        # treat these as "Norwegian present"
$EngLangs  = @('en','eng')

# Text subtitle codecs we can convert to .srt with ffmpeg:
$TextSubCs = @('subrip','ass','ssa','mov_text','webvtt','text')

# Image/bitmap subs to skip (require OCR, not supported here):
$BitmapCs  = @('hdmv_pgs_subtitle','dvd_subtitle','xsub')

# srtxlate API
$AppBaseUrl = "http://localhost:8080"
$ApiUrl     = "$AppBaseUrl/translate"
$SourceCode = "eng_Latn"
$TargetCode = "nob_Latn"
$Engine     = "nllb"

# Behavior
$DeleteTempExtractedEng = $true  # delete temp *.eng.srt created from embedded subs on success

# =======================
# Tool checks
# =======================
function Require-Tool($name, $hint) {
  $cmd = Get-Command $name -ErrorAction SilentlyContinue
  if (-not $cmd) { throw "$name not found. $hint" }
  return $cmd.Path
}

$ffprobe = Require-Tool "ffprobe" "Install FFmpeg (ffprobe) and ensure it's in PATH."
$ffmpeg  = Require-Tool "ffmpeg"  "Install FFmpeg and ensure it's in PATH."
$curlExe = (Get-Command curl.exe -ErrorAction SilentlyContinue)?.Source
if (-not $curlExe) { throw "curl.exe not found. Install curl or add it to PATH." }

# =======================
# Helpers
# =======================
function Get-SubtitleStreams {
  param([Parameter(Mandatory=$true)][string]$File)
  $args = @(
    '-v','error',
    '-show_entries','stream=index,codec_type,codec_name:stream_tags=language,title',
    '-of','json', $File
  )
  $out = & $ffprobe @args 2>$null
  if (-not $out) { return @() }
  try { $j = $out | ConvertFrom-Json } catch { return @() }
  if (-not $j.streams) { return @() }
  $j.streams | Where-Object { $_.codec_type -eq 'subtitle' } | ForEach-Object {
    [PSCustomObject]@{
      index      = $_.index
      codec_name = $_.codec_name
      language   = ($_.tags.language)
      title      = ($_.tags.title)
    }
  }
}

function Has-NorwegianSub {
  param([Parameter(Mandatory=$true)]$Subs)
  $Subs | Where-Object {
    $_.language -and ($NorLangs -contains $_.language.ToLower())
  } | Select-Object -First 1 | ForEach-Object { return $true }
  return $false
}

function Test-IsHI {
  param($Sub)
  $title = [string]$Sub.title
  $lang  = [string]$Sub.language
  $patterns = @(
    'sdh', 'hearing', 'hearing-impaired', 'hearing impaired',
    'hi', 'cc', 'closed captions', 'closed-captions', 'captions'
  )
  foreach ($p in $patterns) {
    if ($title -match $p) { return $true }
  }
  if ($lang -match 'sdh|hi|cc') { return $true }
  return $false
}

function Get-FirstEnglishTextSub {
  param([Parameter(Mandatory=$true)]$Subs)
  $engText = $Subs | Where-Object {
    ($_.language -and ($EngLangs -contains $_.language.ToLower())) -and
    ($TextSubCs -contains $_.codec_name)
  }
  if (-not $engText) { return $null }
  $nonHi = $engText | Where-Object { -not (Test-IsHI $_) } | Select-Object -First 1
  if ($nonHi) { return $nonHi }
  return ($engText | Select-Object -First 1)
}

function Find-SidecarSubs {
  param(
    [Parameter(Mandatory=$true)][string]$Dir,
    [Parameter(Mandatory=$true)][string]$BaseName
  )
  $map = @{}
  Get-ChildItem -LiteralPath $Dir -File -Filter "$BaseName.*.srt" | ForEach-Object {
    $m = [regex]::Match($_.Name, '^[\s\S]+\.([A-Za-z]{2,3})\.srt$', 'IgnoreCase')
    if ($m.Success) {
      $lang = $m.Groups[1].Value.ToLower()
      if ($NorLangs + $EngLangs -contains $lang) { $map[$lang] = $_.FullName }
    }
  }
  return $map
}

function Show-ProgressSSE {
  param(
    [Parameter(Mandatory=$true)][string]$SseUrl,
    [Parameter(Mandatory=$true)][string]$Activity
  )
  $handler = [System.Net.Http.HttpClientHandler]::new()
  $client  = [System.Net.Http.HttpClient]::new($handler)
  $client.Timeout = [TimeSpan]::FromMinutes(120)
  $stream = $null
  $reader = $null
  try {
    $stream = $client.GetStreamAsync($SseUrl).GetAwaiter().GetResult()
    $reader = [System.IO.StreamReader]::new($stream)
    $lastPct = -1
    while (($line = $reader.ReadLine()) -ne $null) {
      if ($line.StartsWith("data:")) {
        $json = $line.Substring(5).Trim()
        try {
          $obj = $json | ConvertFrom-Json
          $total    = [int]($obj.total)
          $done     = [int]($obj.done)
          $remaining= [int]($obj.remaining)
          $finished = [bool]($obj.finished)
          $pct = if ($total -gt 0) { [int](($done * 100) / $total) } else { 0 }
          if ($pct -ne $lastPct) {
            Write-Progress -Activity $Activity -Status "$done / $total ($remaining left)" -PercentComplete $pct
            $lastPct = $pct
          }
          if ($finished) { break }
        } catch { }
      }
    }
  } finally {
    Write-Progress -Activity $Activity -Completed
    if ($reader) { $reader.Dispose() }
    if ($stream) { $stream.Dispose() }
    $client.Dispose()
  }
}

function Invoke-TranslateSrt {
  param(
    [Parameter(Mandatory=$true)][string]$InputSrt,
    [Parameter(Mandatory=$true)][string]$OutputSrt,
    [Parameter(Mandatory=$true)][string]$DisplayName
  )
  if (Test-Path -LiteralPath $OutputSrt) {
    $len = (Get-Item -LiteralPath $OutputSrt).Length
    if ($len -gt 0) { Write-Host "[SKIP] Exists: $OutputSrt"; return $true }
    else { Remove-Item -LiteralPath $OutputSrt -ErrorAction SilentlyContinue }
  }
  $uuid   = [guid]::NewGuid().ToString()
  $sseUrl = "$AppBaseUrl/translate_sse?key=$uuid"
  $formFile   = 'file=@"{0}"' -f $InputSrt
  $formSource = "source=$SourceCode"
  $formTarget = "target=$TargetCode"
  $formEngine = "engine=$Engine"
  $formKey    = "progress_key=$uuid"
  Write-Host "[XLATE] $DisplayName  →  $([System.IO.Path]::GetFileName($OutputSrt))" -ForegroundColor Cyan
  $job = Start-Job -ScriptBlock {
    param($curlExe,$ApiUrl,$OutputSrt,$formFile,$formSource,$formTarget,$formEngine,$formKey)
    & $curlExe $ApiUrl `
      --fail --retry 3 --retry-delay 2 --retry-connrefused `
      --max-time 7200 `
      --form $formFile `
      --form $formSource `
      --form $formTarget `
      --form $formEngine `
      --form $formKey `
      -o "$OutputSrt" `
      -sS
    if ($LASTEXITCODE -ne 0) { throw "curl exited with code $LASTEXITCODE" }
  } -ArgumentList $curlExe,$ApiUrl,$OutputSrt,$formFile,$formSource,$formTarget,$formEngine,$formKey
  try { Show-ProgressSSE -SseUrl $sseUrl -Activity $DisplayName } catch { Write-Warning "Progress SSE error: $($_.Exception.Message)" }
  try {
    Wait-Job $job | Out-Null
    Receive-Job $job -ErrorAction Stop | Out-Null
    if (Test-Path -LiteralPath $OutputSrt) { Write-Host "✅ Wrote: $OutputSrt" -ForegroundColor Green; return $true }
    Write-Host "❌ No output file produced." -ForegroundColor Red; return $false
  } catch {
    Write-Host "❌ Translate failed: $($_.Exception.Message)" -ForegroundColor Red
    return $false
  } finally {
    Remove-Job $job -Force -ErrorAction SilentlyContinue | Out-Null
  }
}

# =======================
# Main
# =======================
$media = Get-ChildItem -LiteralPath $Path -Recurse -File | Where-Object {
  $VideoExt -contains $_.Extension.ToLower()
}

foreach ($m in $media) {
  $dir  = $m.DirectoryName
  $base = $m.BaseName
  $sidecars = Find-SidecarSubs -Dir $dir -BaseName $base
  if ($sidecars.Keys | Where-Object { @('no','nb','nob') -contains $_ }) {
    Write-Host "[HAS NOR SIDEcar] $($m.Name) — skip" -ForegroundColor DarkGreen
    continue
  }
  $enPath = $null
  if     ($sidecars.ContainsKey('eng')) { $enPath = $sidecars['eng'] }
  elseif ($sidecars.ContainsKey('en'))  { $enPath = $sidecars['en']  }
  $outNb = Join-Path $dir ($base + ".nb.srt")
  if ($enPath) {
    [void](Invoke-TranslateSrt -InputSrt $enPath -OutputSrt $outNb -DisplayName $m.Name)
    continue
  }
  $subs = Get-SubtitleStreams -File $m.FullName
  if (-not $subs -or $subs.Count -eq 0) {
    Write-Host "[NO SUBS EMBEDDED] $($m.Name) — skip"
    continue
  }
  if (Has-NorwegianSub -Subs $subs) {
    Write-Host "[HAS NOR EMBEDDED] $($m.Name) — skip" -ForegroundColor DarkGreen
    continue
  }
  $hasEngBitmap = $subs | Where-Object {
    ($_.language -and ($EngLangs -contains $_.language.ToLower())) -and
    ($BitmapCs -contains $_.codec_name)
  } | Select-Object -First 1
  if ($hasEngBitmap) {
    Write-Host "[ENG EMBEDDED IS BITMAP] $($m.Name) — skip (needs OCR)" -ForegroundColor Yellow
    continue
  }
  $eng = Get-FirstEnglishTextSub -Subs $subs
  if (-not $eng) {
    Write-Host "[NO ENG TEXT SUB] $($m.Name) — skip"
    continue
  }
  $tmpEng = Join-Path $dir ($base + ".eng.srt")
  if (-not (Test-Path -LiteralPath $tmpEng)) {
    $ffArgs = @('-y','-i', $m.FullName, '-map', "0:$($eng.index)", '-c:s','srt', $tmpEng)
    Write-Host "[EXTRACT ENG→SRT] $($m.Name) (codec=$($eng.codec_name), idx=$($eng.index)) -> $(Split-Path -Leaf $tmpEng)"
    & $ffmpeg @ffArgs 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $tmpEng)) {
      Write-Warning "  Extraction failed: $($m.FullName)"
      continue
    }
  } else {
    Write-Host "[REUSE] existing $([System.IO.Path]::GetFileName($tmpEng))"
  }
  $ok = Invoke-TranslateSrt -InputSrt $tmpEng -OutputSrt $outNb -DisplayName $m.Name
  if ($ok -and $DeleteTempExtractedEng) {
    try { Remove-Item -LiteralPath $tmpEng -ErrorAction SilentlyContinue } catch { }
  }
}

Write-Host "Done."

```
## Linux Version (bash) ##  

### Quick Usage:  
Make executable and run on a library folder using
```
chmod +x scriptname.sh
```
```
./scriptname.sh /path/to/folder
```

### Environment overrides (optional): ###
```
APP_BASE_URL=http://localhost:8080 \
SOURCE_CODE=eng_Latn \
TARGET_CODE=nob_Latn \
ENGINE=nllb \
DELETE_TEMP_EXTRACTED_ENG=1 \
./media-sub-xlate.sh /media/library

```
## Script: ##

```
#!/usr/bin/env bash
# media-sub-xlate.sh
# Scan a folder tree for media files, extract/translate English subtitles to Norwegian Bokmål via srtxlate API.
# Requirements: bash, ffprobe, ffmpeg, curl, jq, uuidgen (or /proc UUID fallback)

set -euo pipefail

# ---------------------------
# Config
# ---------------------------
# Containers that can hold TEXT-based subs
VIDEO_EXT=("mkv" "mp4" "mov" "webm" "ogm" "avi")

# Language tags
NOR_LANGS=("no" "nor" "nob" "nb")
ENG_LANGS=("en" "eng")

# Subtitle codecs
TEXT_SUB_CS=("subrip" "ass" "ssa" "mov_text" "webvtt" "text")
BITMAP_CS=("hdmv_pgs_subtitle" "dvd_subtitle" "xsub")

# srtxlate API
APP_BASE_URL="${APP_BASE_URL:-http://localhost:8080}"
API_URL="${APP_BASE_URL}/translate"
SOURCE_CODE="${SOURCE_CODE:-eng_Latn}"
TARGET_CODE="${TARGET_CODE:-nob_Latn}"
ENGINE="${ENGINE:-nllb}"

# Behavior
DELETE_TEMP_EXTRACTED_ENG="${DELETE_TEMP_EXTRACTED_ENG:-1}" # 1=true, 0=false

# ---------------------------
# Helpers
# ---------------------------

die() { echo "Error: $*" >&2; exit 1; }

need() { command -v "$1" >/dev/null 2>&1 || die "$1 not found in PATH"; }

lower() { awk '{print tolower($0)}'; }

array_contains() {
  local needle="$1"; shift
  local x
  for x in "$@"; do [[ "$x" == "$needle" ]] && return 0; done
  return 1
}

gen_uuid() {
  if command -v uuidgen >/dev/null 2>&1; then uuidgen
  elif [[ -r /proc/sys/kernel/random/uuid ]]; then cat /proc/sys/kernel/random/uuid
  else date +%s%N
  fi
}

# path helpers
dir_of() { dirname -- "$1"; }
base_of() { basename -- "$1"; }
strip_ext() { local f="$1"; echo "${f%.*}"; }
ext_of() { local f="$1"; f="${f##*.}"; echo "${f,,}"; } # lower ext

# Check required tools
need ffprobe
need ffmpeg
need curl
need jq

usage() {
  cat <<EOF
Usage: $(basename "$0") /path/to/folder

Environment overrides:
  APP_BASE_URL                 (default: ${APP_BASE_URL})
  SOURCE_CODE                  (default: ${SOURCE_CODE})
  TARGET_CODE                  (default: ${TARGET_CODE})
  ENGINE                       (default: ${ENGINE})
  DELETE_TEMP_EXTRACTED_ENG    (default: ${DELETE_TEMP_EXTRACTED_ENG}, 1=true)
EOF
  exit 1
}

[[ $# -eq 1 ]] || usage
ROOT="$1"
[[ -d "$ROOT" ]] || die "Folder not found: $ROOT"

# ---------------------------
# ffprobe helpers
# ---------------------------

get_subtitle_streams_json() {
  local file="$1"
  ffprobe -v error -show_entries \
    stream=index,codec_type,codec_name:stream_tags=language,title \
    -of json -- "$file" 2>/dev/null || true
}

# returns 0 if any subtitle stream has Norwegian language
has_norwegian_sub() {
  local json="$1"
  local langs
  langs=$(echo "$json" | jq -r '.streams[]? | select(.codec_type=="subtitle") | (.tags.language // empty) | ascii_downcase')
  while IFS= read -r l; do
    [[ -z "$l" ]] && continue
    for n in "${NOR_LANGS[@]}"; do [[ "$l" == "$n" ]] && return 0; done
  done <<< "$langs"
  return 1
}

# determine if a given title/lang indicates HI/SDH
is_hi_marker() {
  local s="$1"
  [[ "$s" =~ sdh|hearing|hearing[-\ ]impaired|hi|cc|closed[\ ]?captions ]] && return 0 || return 1
}

# pick first English TEXT subtitle, prefer non-HI; outputs "index codec_name language title"
pick_english_text_sub() {
  local json="$1"
  # Build list of candidates
  local rows
  rows=$(echo "$json" | jq -r '
    .streams[]? | select(.codec_type=="subtitle") |
    {index, codec_name, language: (.tags.language // ""), title: (.tags.title // "")} |
    "\(.index)\t\(.codec_name)\t\(.language|ascii_downcase)\t\(.title|ascii_downcase)"
  ')
  local best_hi="" best_nonhi=""
  while IFS=$'\t' read -r idx codec lang title; do
    [[ -z "$idx" ]] && continue
    # Filter English languages
    local lang_lc="${lang,,}"
    local ok_lang=1
    for e in "${ENG_LANGS[@]}"; do [[ "$lang_lc" == "$e" ]] && ok_lang=0; done
    [[ $ok_lang -ne 0 ]] && continue
    # Filter text codecs
    local is_text=1
    for c in "${TEXT_SUB_CS[@]}"; do [[ "$codec" == "$c" ]] && is_text=0; done
    [[ $is_text -ne 0 ]] && continue
    # HI?
    if is_hi_marker "$title" || is_hi_marker "$lang_lc"; then
      [[ -z "$best_hi" ]] && best_hi="$idx"$'\t'"$codec"$'\t'"$lang_lc"$'\t'"$title"
    else
      [[ -z "$best_nonhi" ]] && best_nonhi="$idx"$'\t'"$codec"$'\t'"$lang_lc"$'\t'"$title"
    fi
  done <<< "$rows"
  if [[ -n "$best_nonhi" ]]; then
    echo "$best_nonhi"
    return 0
  elif [[ -n "$best_hi" ]]; then
    echo "$best_hi"
    return 0
  fi
  return 1
}

# check if English subs exist but only bitmap
has_english_bitmap_only() {
  local json="$1"
  local any_eng=0 any_text=0
  local rows
  rows=$(echo "$json" | jq -r '
    .streams[]? | select(.codec_type=="subtitle") |
    {codec_name, language: (.tags.language // "")} |
    "\(.codec_name)\t\(.language|ascii_downcase)"
  ')
  while IFS=$'\t' read -r codec lang; do
    [[ -z "$codec" ]] && continue
    # Only consider English
    local lang_lc="${lang,,}"
    local is_eng=1
    for e in "${ENG_LANGS[@]}"; do [[ "$lang_lc" == "$e" ]] && is_eng=0; done
    [[ $is_eng -ne 0 ]] && continue
    any_eng=1
    # Text? bitmap?
    local is_text=1
    for c in "${TEXT_SUB_CS[@]}"; do [[ "$codec" == "$c" ]] && is_text=0; done
    if [[ $is_text -eq 0 ]]; then any_text=1; fi
  done <<< "$rows"
  # bitmap-only if we saw English but no text
  [[ $any_eng -eq 1 && $any_text -eq 0 ]]
}

# ---------------------------
# Translation with SSE progress
# ---------------------------

show_progress_sse() {
  local sse_url="$1" activity="$2"
  # consume SSE and display simple progress line
  local total=0 done=0 remaining=0 finished=false
  # curl -N to stream, grep lines starting with data:
  curl -sS -N "$sse_url" | while IFS= read -r line; do
    [[ "$line" != data:* ]] && continue
    local json="${line#data: }"
    total=$(echo "$json" | jq -r '.total // 0') || total=0
    done=$(echo "$json" | jq -r '.done // 0') || done=0
    remaining=$(echo "$json" | jq -r '.remaining // 0') || remaining=0
    finished=$(echo "$json" | jq -r '.finished // false') || finished=false
    local pct=0
    if [[ "$total" -gt 0 ]]; then pct=$(( (done*100)/total )); fi
    printf "\r[%s] %d/%d (%d left) %d%%" "$activity" "$done" "$total" "$remaining" "$pct"
    if [[ "$finished" == "true" ]]; then
      echo
      break
    fi
  done
}

translate_srt() {
  local in_srt="$1" out_srt="$2" display="$3"

  if [[ -s "$out_srt" ]]; then
    echo "[SKIP] Exists: $out_srt"
    return 0
  else
    # remove zero-byte file if present
    [[ -e "$out_srt" ]] && rm -f -- "$out_srt"
  fi

  local uuid; uuid="$(gen_uuid)"
  local sse_url="${APP_BASE_URL}/translate_sse?key=${uuid}"

  echo "[XLATE] $display  ->  $(basename -- "$out_srt")"

  # start translation in background
  (
    curl -sS --fail --retry 3 --retry-connrefused --retry-delay 2 \
      -F "file=@${in_srt}" \
      -F "source=${SOURCE_CODE}" \
      -F "target=${TARGET_CODE}" \
      -F "engine=${ENGINE}" \
      -F "progress_key=${uuid}" \
      -o "$out_srt" \
      "$API_URL"
  ) &
  local curl_pid=$!

  # progress in foreground
  show_progress_sse "$sse_url" "$(basename -- "$display")" || true

  wait $curl_pid || { echo "❌ Translate failed (${display})"; rm -f -- "$out_srt"; return 1; }

  if [[ -s "$out_srt" ]]; then
    echo "✅ Wrote: $out_srt"
    return 0
  else
    echo "❌ No output produced: $out_srt"
    return 1
  fi
}

# ---------------------------
# Main
# ---------------------------

shopt -s nullglob

# Walk files with allowed extensions
while IFS= read -r -d '' f; do
  fname="$(basename -- "$f")"
  dir="$(dirname -- "$f")"
  ext="$(ext_of "$f")"

  # skip disallowed extensions (defense-in-depth; find already filters)
  allowed=0
  for e in "${VIDEO_EXT[@]}"; do [[ "$ext" == "$e" ]] && allowed=1; done
  [[ $allowed -eq 0 ]] && continue

  base="${fname%.*}"
  # 1) Sidecar scan (.srt only)
  declare -A sidecars=()
  for srt in "$dir"/"$base".*.srt; do
    [[ -e "$srt" ]] || continue
    srtname="$(basename -- "$srt")"
    # capture last dot language code: base.<lang>.srt
    lang="${srtname##*.}"      # srt
    lang="${srtname%.*}"       # base.<lang>
    lang="${lang##*.}"         # <lang>
    lang="${lang,,}"
    # consider only Norwegian/English codes
    for n in "${NOR_LANGS[@]}"; do [[ "$lang" == "$n" ]] && sidecars["$lang"]="$srt"; done
    for e2 in "${ENG_LANGS[@]}"; do [[ "$lang" == "$e2" ]] && sidecars["$lang"]="$srt"; done
  done

  # If Norwegian sidecar exists -> skip
  for n in "${NOR_LANGS[@]}"; do
    if [[ -n "${sidecars[$n]:-}" ]]; then
      echo "[HAS NOR SIDEcar] $fname — skip"
      continue 2
    fi
  done

  # If English sidecar exists (.eng or .en) -> translate
  en_path=""
  [[ -n "${sidecars[eng]:-}" ]] && en_path="${sidecars[eng]}"
  [[ -z "$en_path" && -n "${sidecars[en]:-}" ]] && en_path="${sidecars[en]}"
  out_nb="${dir}/${base}.nb.srt"
  if [[ -n "$en_path" ]]; then
    translate_srt "$en_path" "$out_nb" "$fname" || true
    continue
  fi

  # 2) No sidecars: probe embedded subs
  json="$(get_subtitle_streams_json "$f")"
  streams_count="$(echo "$json" | jq '.streams | length' 2>/dev/null || echo 0)"
  if [[ "$streams_count" -eq 0 ]]; then
    echo "[NO SUBS EMBEDDED] $fname — skip"
    continue
  fi

  if has_norwegian_sub "$json"; then
    echo "[HAS NOR EMBEDDED] $fname — skip"
    continue
  fi

  if has_english_bitmap_only "$json"; then
    echo "[ENG EMBEDDED IS BITMAP] $fname — skip (needs OCR)"
    continue
  fi

  # pick English text sub, prefer non-HI
  pick_line="$(pick_english_text_sub "$json" || true)"
  if [[ -z "$pick_line" ]]; then
    echo "[NO ENG TEXT SUB] $fname — skip"
    continue
  fi
  IFS=$'\t' read -r idx codec lang title <<< "$pick_line"

  # extract to .eng.srt (force srt codec)
  tmp_eng="${dir}/${base}.eng.srt"
  if [[ ! -s "$tmp_eng" ]]; then
    echo "[EXTRACT ENG→SRT] $fname (codec=${codec}, idx=${idx}) -> $(basename -- "$tmp_eng")"
    if ! ffmpeg -y -i "$f" -map "0:${idx}" -c:s srt "$tmp_eng" >/dev/null 2>&1; then
      echo "  Extraction failed: $f" >&2
      continue
    fi
  else
    echo "[REUSE] existing $(basename -- "$tmp_eng")"
  fi

  # translate extracted
  if translate_srt "$tmp_eng" "$out_nb" "$fname"; then
    if [[ "$DELETE_TEMP_EXTRACTED_ENG" == "1" ]]; then rm -f -- "$tmp_eng"; fi
  fi

done < <(find "$ROOT" -type f \( $(printf -- '-iname "*.%s" -o ' "${VIDEO_EXT[@]}") -false \) -print0)

echo "Done."
```


