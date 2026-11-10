"""Build the isolated installation from verified upstream artifacts."""

from importlib.util import MAGIC_NUMBER
from pathlib import Path, PurePosixPath
import py_compile
import re
import shutil
import sys
import warnings
from zipfile import ZipFile


PATCHES = {
    "core/bar_manager.pyc": "bar_manager.py",
    "core/widgets/services/control_center/sections/quick_actions.pyc": "quick_actions.py",
    "core/widgets/yasb/custom.pyc": "custom.py",
}
ROOT = Path(__file__).resolve().parents[1]


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


def patch_yasb(archive, build):
    patched = archive.with_suffix(".new.zip")
    with ZipFile(archive) as original, ZipFile(patched, "w") as output:
        replacements = {}
        for entry, source in PATCHES.items():
            if original.namelist().count(entry) != 1 or original.read(entry)[:4] != MAGIC_NUMBER:
                raise ValueError(f"Unexpected YASB bytecode: {entry}")
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
                output.writestr(member, original.read(member) if content is None else content)
    patched.replace(archive)


def main():
    install, downloads = (Path(value).resolve() for value in sys.argv[1:3])
    config = install / "config"
    if sys.argv[3] == "standard":
        path = config / "config.yaml"
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"^komorebi:\n(?:  [^\n]*\n)+\n", "", text, flags=re.M)
        text = re.sub(r'^ {10}"komorebi_(control|workspaces)",\n', "", text, flags=re.M)
        path.write_text(text, encoding="utf-8", newline="\n")

    install_wheels(downloads, config / "dynamic-island" / "runtime")
    patch_yasb(install / "yasb" / "lib" / "library.zip", downloads)
    print("Installed the Dynamic Island runtime and compiled the YASB integration.")


if __name__ == "__main__":
    main()
