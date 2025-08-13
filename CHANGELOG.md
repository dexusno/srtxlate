# Changelog
All notable changes to this project will be documented in this file.  
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),  
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2025-08-13
### Added
- **Menu-driven setup scripts** (`setup.ps1` and `setup.sh`) for easier installation and usage
- Health check now reports device type, configured model, and loaded model
- Local model preference when `NLLB_MODEL_DIR` is set
- Improved handling of all-caps descriptive subtitle lines
- Subtitle merging and splitting improvements for better translation quality
- Fix for word-splitting issues when writing `.srt` output

### Changed
- Simplified GPU/CPU switching via setup script instead of manual commands

### Bugfixes
- Fixed memory handling for Docker Desktop / WSL2 (windows). System should not lag at all now.

## [1.0.0] - 2025-08-11
### Added
- Initial public release of **SRTXlate** subtitle translation tool.
- Full **multi-language translation support** using the FLORES-200 language list via `flores200.json`.
- Web-based user interface with:
  - Source language selection
  - Target language selection
  - Translation engine selection (NLLB or LibreTranslate)
  - Clear button for easy reset
- CLI support via `curl` for scripted translations without GUI.
- Automatic filename suffix replacement using ISO-639-1 codes where possible.
- Docker-based deployment for easy installation and isolation.
- CPU and GPU modes for NLLB (GPU with `docker-compose.gpu.yml`).
- Preconfigured `flores200.json` containing all FLORES-200 languages.

### Changed
- UI layout improvements for balanced dropdown/button alignment.
- README.md rewritten to include:
  - Full installation instructions (Windows & Linux).
  - Detailed usage examples.
  - GPU/CPU setup guidance.
  - Server-only usage without GUI.
- Project name updated to reflect multilingual capabilities.

### Notes
- NLLB model is **not included** in the repo; it must be downloaded separately.
- No Python CLI wrapper — HTTP API (`curl`) is the recommended method for automation.

---
