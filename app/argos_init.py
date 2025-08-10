# app/argos_init.py
import argostranslate.package as pkg
import argostranslate.translate as tr

FROM = "en"
TO = "nb"  # Norwegian Bokmål

def ensure_model():
    pkg.update_package_index()
    available = pkg.get_available_packages()
    matches = [
        p for p in available
        if getattr(p, "from_code", None) == FROM and getattr(p, "to_code", None) == TO
    ]
    if not matches:
        raise SystemExit(f"No Argos package for {FROM}->{TO} found in index.")
    model = matches[0]

    installed = pkg.get_installed_packages()
    if not any(
        getattr(p, "from_code", None) == FROM and getattr(p, "to_code", None) == TO
        for p in installed
    ):
        path = model.download()
        pkg.install_from_path(path)

if __name__ == "__main__":
    ensure_model()
