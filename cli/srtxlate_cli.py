# cli/srtxlate_cli.py
#!/usr/bin/env python3
import argparse, sys, pathlib

# Make local imports robust whether run from repo root or elsewhere
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
APP = ROOT / "app"
for p in (str(ROOT), str(APP)):
    if p not in sys.path:
        sys.path.insert(0, p)

from srtxlate import translate_srt  # now importable

def main():
    p = argparse.ArgumentParser(description="Translate .srt using Argos or LibreTranslate.")
    p.add_argument("input", type=pathlib.Path, help="Input .srt")
    p.add_argument("-o", "--output", type=pathlib.Path, help="Output .srt (default: input.<target>.srt)")
    p.add_argument("--source", default="en", help="Source language (for Libre you can use 'auto')")
    p.add_argument("--target", default="nb", help="Target language (default: nb)")
    p.add_argument("--engine", default="auto", choices=["auto","argos","libre"], help="Translate engine")
    p.add_argument("--libre-endpoint", default="http://localhost:5000", help="LibreTranslate endpoint")
    p.add_argument("--libre-api-key", default=None, help="LibreTranslate API key (if enabled)")
    args = p.parse_args()

    if args.input.suffix.lower() != ".srt":
        print("Input must be .srt", file=sys.stderr); sys.exit(1)

    raw = args.input.read_bytes()
    out = translate_srt(
        raw,
        source=args.source,
        target=args.target,
        engine=args.engine,
        libre_endpoint=args.libre_endpoint,
        libre_api_key=args.libre_api_key
    )
    outpath = args.output or args.input.with_suffix(f".{args.target}.srt")
    outpath.write_bytes(out)
    print(str(outpath))

if __name__ == "__main__":
    main()
