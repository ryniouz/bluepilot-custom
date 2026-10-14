#!/usr/bin/env python3
"""
Build system/hardware/tici/updater_console: the Console OS update screen (bluepilot/ui/console/updater.py)
as a self-contained zipapp, like the stock updater_magic (release/pack.py) but with only what the screen
needs: the UI library, hardware, fonts, Wi-Fi icons and bluepilot.ui. Run from the repo root:

  python tools/console_updater/build.py [-o system/hardware/tici/updater_console]

then `updater_console --check` must print "ok". system/hardware/tici/updater runs that check on the device
before using it and otherwise falls back to updater_magic.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXTS = {".py", ".png", ".ttf", ".fnt", ".json", ".capnp", ".mo"}
# (source, destination in the archive); openpilot.* is the repo root seen through the openpilot/ symlinks
TREES = [
  ("cereal", "cereal"),
  ("common", "openpilot/common"),
  ("system", "openpilot/system"),
  ("selfdrive/assets/fonts", "openpilot/selfdrive/assets/fonts"),
  ("selfdrive/assets/icons", "openpilot/selfdrive/assets/icons"),
  ("selfdrive/ui/translations", "openpilot/selfdrive/ui/translations"),
  ("selfdrive/ui/bp/lib", "openpilot/selfdrive/ui/bp/lib"),  # Wi-Fi favourites
  ("bluepilot/ui", "bluepilot/ui"),
]
FILES = [
  ("openpilot/__init__.py", "openpilot/__init__.py"),
  ("selfdrive/__init__.py", "openpilot/selfdrive/__init__.py"),
  ("selfdrive/ui/__init__.py", "openpilot/selfdrive/ui/__init__.py"),
  ("selfdrive/ui/bp/__init__.py", "openpilot/selfdrive/ui/bp/__init__.py"),
  ("bluepilot/__init__.py", "bluepilot/__init__.py"),
]
SKIP_DIRS = {"__pycache__", "tests", "test"}


def copy_tree(src: Path, dst: Path) -> None:
  for p in src.rglob("*"):
    if p.is_file() and p.suffix in EXTS and not SKIP_DIRS & set(p.relative_to(src).parts):
      out = dst / p.relative_to(src)
      out.parent.mkdir(parents=True, exist_ok=True)
      shutil.copy2(p, out)


def main() -> int:
  ap = argparse.ArgumentParser()
  ap.add_argument("-o", "--output", default=str(ROOT / "system/hardware/tici/updater_console"))
  args = ap.parse_args()
  with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    for src, dst in TREES:
      copy_tree(ROOT / src, t / dst)
    for src, dst in FILES:
      if (ROOT / src).is_file():
        (t / dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / src, t / dst)
    zipapp.create_archive(t, target=args.output, interpreter="/usr/bin/env python3",
                          main="bluepilot.ui.console.updater:main")
  out = subprocess.run([sys.executable, "-I", args.output, "--check"], capture_output=True, text=True)
  print(f"built {args.output} ({Path(args.output).stat().st_size / 1e6:.1f} MB); --check: {out.stdout.strip() or out.stderr.strip()[-400:]}")
  return 0 if out.stdout.strip() == "ok" else 1


if __name__ == "__main__":
  sys.exit(main())
