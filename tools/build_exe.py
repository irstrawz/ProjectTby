"""Build a distributable Windows folder, plus the files the updater needs.

    python tools/build_exe.py                 build into dist/
    python tools/build_exe.py --version 0.2.0 stamp a new version first
    python tools/build_exe.py --no-clean      keep PyInstaller's caches

Produces three things in ``dist/``:

* ``ProjectTby/``          — the app folder, what a player actually runs
* ``ProjectTby-<v>.zip``   — that folder zipped, what the updater downloads
* ``manifest.json``        — version, zip URL, size and SHA-256

Publish the zip and the manifest together; point ``UPDATE_MANIFEST_URL`` in
``game/version.py`` at the manifest.

**One folder, not one file.** ``--onefile`` looks tidier and is the wrong
choice: it unpacks the whole application into a temp directory on every launch,
which is slow, and it makes updating an all-or-nothing download of the entire
bundle rather than a folder copy. One folder also means the updater can swap
files in place.

**Assets are copied, not embedded.** They are data files loaded at runtime, so
they end up in ``_internal/assets`` where the updater replaces them like
anything else.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")
APP_NAME = "ProjectTby"

sys.path.insert(0, ROOT)
from game import version as version_module     # noqa: E402


def stamp_version(new_version):
    """Rewrite VERSION in game/version.py.

    The build reads the version from the source rather than taking it as an
    argument alone, so the number baked into the exe and the number in the
    manifest cannot disagree — which would show up as an update that installs
    successfully and then offers itself again forever.
    """
    path = os.path.join(ROOT, "game", "version.py")
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    updated, count = re.subn(r'^VERSION = "[^"]*"',
                             f'VERSION = "{new_version}"', text, count=1, flags=re.M)
    assert count == 1, "could not find VERSION in game/version.py"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(updated)
    version_module.VERSION = new_version
    return new_version


def run_pyinstaller(clean=True):
    command = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onedir",
        "--noconfirm",
        # No console window behind the game. Swap for --console while debugging
        # a build: without it, a crash before pygame opens its window is silent.
        "--windowed",
        "--distpath", DIST,
        "--workpath", BUILD,
        "--specpath", BUILD,
        # PyInstaller 6 puts bundled data in ``_internal/`` next to the exe and
        # points ``sys._MEIPASS`` at it, for one-folder builds as well as
        # one-file. game/paths.py reads _MEIPASS first for exactly this reason;
        # assuming "beside the exe" gives a path that does not exist.
        "--add-data", f"{os.path.join(ROOT, 'assets')}{os.pathsep}assets",
        os.path.join(ROOT, "main.py"),
    ]
    if clean:
        command.insert(3, "--clean")
    print("  " + " ".join(command[:6]) + " ...")
    subprocess.run(command, check=True, cwd=ROOT)


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def make_zip(app_dir, out_path):
    """Zip the app folder *inside* a top-level directory of the same name.

    The first version of this wrote paths relative to the folder, which suited
    the updater — it extracts straight over an existing install — and was hostile
    to the person the zip is actually for. "Extract All" in Downloads would spray
    an .exe and a 200-file ``_internal`` directory loose among their downloads,
    with nothing to tell them the pieces belong together.

    So the archive is shaped for the human, and ``updater.stage`` strips the
    single common root when it unpacks. One artefact serves both.
    """
    prefix = os.path.basename(app_dir.rstrip(os.sep))
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for directory, _, files in os.walk(app_dir):
            for name in files:
                full = os.path.join(directory, name)
                inside = os.path.relpath(full, app_dir).replace(os.sep, "/")
                archive.write(full, f"{prefix}/{inside}")
    return out_path


PLAYER_README = """Project Tby
===========

To play: open this folder and run ProjectTby.exe.

Keep the whole folder together. ProjectTby.exe needs the _internal folder
beside it, so move or copy the folder as a unit rather than just the .exe.

Windows may show a blue "Windows protected your PC" box the first time,
because this is not signed by a registered publisher. Click "More info" and
then "Run anyway". You only have to do that once.

Your progress is saved outside this folder, in:
    %LOCALAPPDATA%\ProjectTby
so updating or replacing the game will not lose it.

Controls: WASD to move, E to interact, ESC to pause. Settings are on the
title screen.
"""


def main():
    parser = argparse.ArgumentParser(description="Build the distributable.")
    parser.add_argument("--version", help="stamp this version before building")
    parser.add_argument("--no-clean", action="store_true")
    parser.add_argument("--base-url", default="",
                        help="where the zip will be published, for the manifest")
    args = parser.parse_args()

    if args.version:
        print(f"  stamping version {stamp_version(args.version)}")
    release = version_module.VERSION

    app_dir = os.path.join(DIST, APP_NAME)
    if os.path.isdir(app_dir):
        shutil.rmtree(app_dir)
    run_pyinstaller(clean=not args.no_clean)

    exe = os.path.join(app_dir, f"{APP_NAME}.exe")
    assert os.path.exists(exe), f"PyInstaller produced no exe at {exe}"

    # Written into the app folder so it is inside the zip and inside every
    # install, which is the only place someone confused by the folder will look.
    with open(os.path.join(app_dir, "README.txt"), "w", encoding="utf-8") as handle:
        handle.write(PLAYER_README)

    zip_name = f"{APP_NAME}-{release}.zip"
    zip_path = make_zip(app_dir, os.path.join(DIST, zip_name))

    manifest = {
        "version": release,
        "url": (args.base_url.rstrip("/") + "/" + zip_name) if args.base_url else zip_name,
        "sha256": sha256(zip_path),
        "size": os.path.getsize(zip_path),
        "notes": "",
    }
    manifest_path = os.path.join(DIST, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    folder_size = sum(os.path.getsize(os.path.join(d, f))
                      for d, _, fs in os.walk(app_dir) for f in fs)
    print(f"\n  version   {release}")
    print(f"  app       {os.path.relpath(app_dir, ROOT)}  ({folder_size / 1e6:.0f} MB)")
    print(f"  zip       {os.path.relpath(zip_path, ROOT)}  ({manifest['size'] / 1e6:.0f} MB)")
    print(f"  sha256    {manifest['sha256'][:16]}...")
    print(f"  manifest  {os.path.relpath(manifest_path, ROOT)}")
    if not args.base_url:
        print("\n  No --base-url given, so the manifest's url is just the filename.")
        print("  Publish both files together and set UPDATE_MANIFEST_URL in game/version.py.")


if __name__ == "__main__":
    main()
