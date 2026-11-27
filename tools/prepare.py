"""Build the isolated installation from verified upstream artifacts."""

from importlib.util import MAGIC_NUMBER
from copy import copy
from pathlib import Path, PurePosixPath
import hashlib
import json
import py_compile
import re
import shutil
import sys
import warnings
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
PATCHES = json.loads((ROOT / 'patches/manifest.json').read_text(encoding='utf-8'))


def install_wheels(downloads, runtime):
    for wheel in sorted(downloads.glob("*.whl")):
        with ZipFile(wheel) as package:
            for entry in package.infolist():
                if entry.is_dir():
                    continue
                parts = PurePosixPath(entry.filename).parts
                # This Qt Widgets app does not load QML or its build artifacts.
                if parts[:2] == ("PySide6", "qml"):
                    continue
                if parts[0].endswith(".data"):
                    if parts[1] not in {"platlib", "purelib"}:
                        continue
                    parts = parts[2:]
                target = runtime.joinpath(*parts).resolve()
                if not target.is_relative_to(runtime):
                    raise ValueError(f"Wheel entry outside the runtime: {entry.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(entry) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination)


def read_catalog_modules():
    expected = {
        entry: patch["precompiled_sha256"]
        for entry, patch in PATCHES.items()
        if "precompiled_sha256" in patch
    }
    with ZipFile(ROOT / "patches" / "catalog-runtime.zip") as bundle:
        if sorted(bundle.namelist()) != sorted(expected):
            raise ValueError("Unexpected theme catalog runtime entries")
        prepared = {}
        for entry, digest in expected.items():
            payload = bundle.read(entry)
            if payload[:4] != MAGIC_NUMBER or hashlib.sha256(payload).hexdigest() != digest:
                raise ValueError(f"Unexpected theme catalog bytecode: {entry}")
            prepared[entry] = payload
    return prepared


def patch_yasb(archive, build):
    catalog_modules = read_catalog_modules()
    patched = archive.with_suffix(".new.zip")
    with ZipFile(archive) as original, ZipFile(patched, "w") as output:
        replacements = {}
        for entry, patch in PATCHES.items():
            source = patch['source']
            if Path(source).name != source or not entry.startswith('core/') or not entry.endswith('.pyc'):
                raise ValueError(f'Invalid patch target: {entry}')
            expected = patch['upstream_sha256']
            if expected is None:
                if entry in original.namelist():
                    raise ValueError(f'New module already exists: {entry}')
            elif (original.namelist().count(entry) != 1 or
                  original.read(entry)[:4] != MAGIC_NUMBER or
                  hashlib.sha256(original.read(entry)).hexdigest() != expected):
                raise ValueError(f"Unexpected YASB bytecode: {entry}")
            if entry in catalog_modules:
                replacements[entry] = catalog_modules[entry]
                continue
            compiled = build / (source + "c")
            py_compile.compile(
                str(ROOT / "patches" / source),
                cfile=str(compiled), dfile=entry.removesuffix("c"), doraise=True,
            )
            replacements[entry] = compiled.read_bytes()
        with warnings.catch_warnings():
            # The stock cx_Freeze archive can contain duplicate package entries.
            warnings.filterwarnings("ignore", message="Duplicate name:", category=UserWarning)
            for member in original.infolist():
                content = replacements.get(member.filename)
                output.writestr(copy(member), original.read(member) if content is None else content)
            for entry, content in replacements.items():
                if entry not in original.namelist():
                    output.writestr(entry, content)
    with ZipFile(patched) as check:
        if check.testzip() is not None:
            raise ValueError('Patched runtime verification failed')
    patched.replace(archive)


def main():
    install, downloads = (Path(value).resolve() for value in sys.argv[1:3])
    config = install / "config"
    if sys.argv[3] == "standard":
        path = config / "config.yaml"
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"^komorebi:\n(?:[ \t]+[^\n]*\n)+", "", text, flags=re.M)
        text = re.sub(r'(      left:\n)(.*?)(      center:)',
                      lambda m: m[1] + re.sub(r'^      - (?:komorebi_(?:control|active_layout|workspaces)|bar_divider)\n', '', m[2], flags=re.M) + m[3],
                      text, count=1, flags=re.S)
        path.write_text(text, encoding="utf-8", newline="\n")
        preferences = config / 'bar-settings.json'
        options = json.loads(preferences.read_text(encoding='utf-8'))
        options['komorebi']['mode'] = 'off'
        preferences.write_text(json.dumps(options, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

    install_wheels(downloads, config / "dynamic-island" / "runtime")
    patch_yasb(install / "yasb" / "lib" / "library.zip", downloads)
    print("Installed the Dynamic Island runtime and compiled the YASB integration.")


if __name__ == "__main__":
    main()
