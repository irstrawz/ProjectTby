"""Check for a newer build, download it, and swap it in.

The flow is: fetch a small JSON manifest, compare versions, download the zip it
names, verify its SHA-256, extract to a staging folder, then hand off to a
script that waits for this process to exit before replacing the app folder and
relaunching. Nothing is touched until the hash matches.

**This feature downloads code and then runs it.** That is the entire point of an
auto-updater and also its entire risk, so three rules are enforced rather than
documented:

* **HTTPS only**, for the manifest and the zip. Plain HTTP means anyone between
  the player and the server chooses what gets installed.
* **The SHA-256 in the manifest must match** the bytes downloaded, checked
  before anything is extracted. This is what makes the zip URL untrusted-ish: a
  swapped file fails rather than installs.
* **Zip entries are checked for path traversal** before extraction. A crafted
  archive containing ``..\\..\\Windows\\System32\\...`` would otherwise write
  wherever it liked.

None of that helps if the manifest URL itself is compromised — whoever controls
it controls what runs on your players' machines — so it should point somewhere
you own. Signing the manifest would be the next step up, and is worth doing if
this ever goes further than friends.

Nothing here runs unless the player asks: no background polling, no silent
installs. The game checks once at startup only to *tell* you a version exists.
"""

import hashlib
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from . import paths
from . import version as version_module

TIMEOUT = 15
STAGING_NAME = "_update_staging"
USER_AGENT = f"ProjectTby/{version_module.VERSION}"


class UpdateError(Exception):
    """Anything that stops an update, phrased for a player to read."""


class Update:
    """A newer release that is available to install."""

    def __init__(self, version, url, sha256, size=0, notes=""):
        self.version = version
        self.url = url
        self.sha256 = (sha256 or "").lower()
        self.size = size
        self.notes = notes

    @property
    def size_mb(self):
        return self.size / 1e6 if self.size else 0.0


def _require_https(url, what):
    if not url.lower().startswith("https://"):
        raise UpdateError(f"{what} is not an https:// address; refusing to fetch it")


def _open(url):
    """Open an https URL with certificate verification.

    Never swap the default context for an unverified one to make a self-signed
    server work — that removes the only guarantee the bytes came from where the
    URL says they did. Tests inject a different *fetcher* instead (below), which
    leaves this path exactly as it ships.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=TIMEOUT,
                                  context=ssl.create_default_context())


def _https_fetch(url):
    """The shipping transport: enforce https, then stream the bytes."""
    _require_https(url, "The address")
    return _open(url)


def check(manifest_url=None, fetch=None):
    """Return an ``Update`` if one is newer than this build, else None.

    Every failure is turned into ``UpdateError`` with something a player could
    act on. A game that dies on startup because a release server is down would
    be a far worse bug than the one this feature fixes.
    """
    manifest_url = manifest_url or version_module.UPDATE_MANIFEST_URL
    fetch = fetch or _https_fetch
    if not manifest_url:
        raise UpdateError("No update URL is configured for this build")

    try:
        with fetch(manifest_url) as response:
            raw = response.read(1 << 20)          # a manifest is a few hundred bytes
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError(f"Could not reach the update server ({exc})") from exc

    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("The update server sent something that is not a manifest") from exc

    latest = str(data.get("version", "")).strip()
    if not latest:
        raise UpdateError("The manifest does not say what version it is")
    if not version_module.is_newer(latest):
        return None

    url = str(data.get("url", "")).strip()
    if not url:
        raise UpdateError("The manifest does not say where to download the update")
    if "://" not in url:
        # Manifests written without --base-url carry a bare filename; resolve it
        # against the manifest's own location so publishing both files side by
        # side just works.
        url = urllib.parse.urljoin(manifest_url, url)

    digest = str(data.get("sha256", "")).strip().lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise UpdateError("The manifest has no usable checksum, so the download "
                          "could not be verified")

    return Update(latest, url, digest, int(data.get("size") or 0),
                  str(data.get("notes") or ""))


def download(update, on_progress=None, fetch=None):
    """Fetch the zip to a temp file and verify it. Returns the path.

    Hashed while streaming rather than afterwards, so a large download is not
    read from disk twice, and deleted on any failure so a corrupt file cannot
    be picked up by a later attempt.
    """
    fetch = fetch or _https_fetch
    digest = hashlib.sha256()
    handle, temp_path = tempfile.mkstemp(prefix="projecttby-update-", suffix=".zip")
    os.close(handle)

    try:
        with fetch(update.url) as response, open(temp_path, "wb") as target:
            total = update.size or int(response.headers.get("Content-Length") or 0)
            fetched = 0
            while True:
                block = response.read(1 << 16)
                if not block:
                    break
                target.write(block)
                digest.update(block)
                fetched += len(block)
                if on_progress and total:
                    on_progress(min(1.0, fetched / total))
    except (urllib.error.URLError, OSError) as exc:
        os.unlink(temp_path)
        raise UpdateError(f"The download failed ({exc})") from exc

    if digest.hexdigest() != update.sha256:
        os.unlink(temp_path)
        raise UpdateError("The download did not match its checksum and was discarded")
    return temp_path


def _safe_members(archive, destination):
    """Yield entries that stay inside ``destination``.

    ``ZipFile.extractall`` does sanitise names in modern Python, but this is
    cheap, explicit, and does not depend on remembering which version fixed
    what — and the failure it prevents is writing files anywhere on the disk.
    """
    destination = os.path.realpath(destination)
    for member in archive.infolist():
        target = os.path.realpath(os.path.join(destination, member.filename))
        if target != destination and not target.startswith(destination + os.sep):
            raise UpdateError(f"The update archive contains an unsafe path "
                              f"({member.filename!r}) and was rejected")
        yield member


def _common_root(names):
    """The single top-level directory every entry sits under, or None.

    Release zips wrap everything in a folder so that extracting one by hand
    produces a tidy directory rather than loose files. The updater has to undo
    that, or an update would install into ``app/ProjectTby/`` instead of over
    ``app/``. Returns None when entries sit at the root or under several
    different folders, so a flat archive still works.
    """
    roots = set()
    for name in names:
        head = name.replace("\\", "/").split("/", 1)
        if len(head) == 1 or not head[1]:
            return None            # a file at the archive root: no common folder
        roots.add(head[0])
        if len(roots) > 1:
            return None
    return roots.pop() if roots else None


def stage(zip_path, app_dir=None):
    """Extract a verified zip into a staging folder beside the app."""
    app_dir = app_dir or paths.app_dir()
    staging = os.path.join(app_dir, STAGING_NAME)
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    os.makedirs(staging, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            members = list(_safe_members(archive, staging))
            root = _common_root([m.filename for m in members])
            for member in members:
                if member.is_dir():
                    continue
                relative = member.filename.replace("\\", "/")
                if root:
                    relative = relative[len(root) + 1:]
                if not relative:
                    continue
                target = os.path.join(staging, *relative.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with archive.open(member) as source, open(target, "wb") as sink:
                    shutil.copyfileobj(source, sink)
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"The update could not be unpacked ({exc})") from exc
    return staging


SWAP_SCRIPT = r"""@echo off
rem Written by game/updater.py. Replaces the application folder once the game
rem has exited, then restarts it.
rem
rem This exists because Windows will not let a running .exe be overwritten, so
rem the swap has to outlive the process doing the updating.
setlocal

rem Wait for the game to close. tasklist is used rather than a fixed sleep so a
rem slow shutdown does not race the copy.
:wait
tasklist /fi "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
  ping -n 2 127.0.0.1 >nul
  goto wait
)

rem /mir mirrors: copy everything, and delete anything in the destination the
rem new version no longer ships. Without the purge, a file dropped between
rem releases lingers on every machine that ever installed the old one — which is
rem how an install ends up in a state the developer has never seen.
rem
rem /xd keeps the staging folder itself out of the mirror. It lives inside the
rem application folder, so without this /mir would try to delete the very
rem directory it is copying from.
rem
rem /is /it force same and "tweaked" files to be copied too; robocopy otherwise
rem skips files it judges identical, and a rebuilt-but-byte-identical file would
rem be left as the old one.
robocopy "{staging}" "{app}" /mir /is /it /xd "{staging}" /njh /njs /ndl /nfl /nc /ns >nul
if errorlevel 8 goto failed

rmdir /s /q "{staging}"
start "" "{exe}"
del "%~f0"
exit /b 0

:failed
rem No "pause" here. This script is launched detached and windowless, so there
rem is no console for anyone to press a key at — pause would simply hang a
rem hidden process forever. Write the reason down and leave the install alone.
echo Update failed: robocopy returned %errorlevel%. > "{log}"
echo The existing installation was left unchanged. >> "{log}"
rmdir /s /q "{staging}"
start "" "{exe}"
del "%~f0"
exit /b 1
"""


def apply_and_restart(staging, app_dir=None, exe_path=None):
    """Hand the swap to a detached script and ask the caller to quit.

    Returns the script path. The caller must exit promptly — the script is
    already waiting for this process id to disappear.
    """
    app_dir = app_dir or paths.app_dir()
    exe_path = exe_path or sys.executable
    script = os.path.join(tempfile.gettempdir(), "projecttby-apply-update.bat")
    log = os.path.join(tempfile.gettempdir(), "projecttby-update-failed.txt")
    with open(script, "w", encoding="ascii", errors="replace") as handle:
        # ASCII: the script is run by cmd.exe, which reads batch files in the
        # console codepage, not UTF-8. A non-ASCII character in a path would be
        # mangled and the copy would target the wrong folder.
        handle.write(SWAP_SCRIPT.format(pid=os.getpid(), staging=staging,
                                        app=app_dir, exe=exe_path, log=log))

    creation = 0
    if os.name == "nt":
        # Detached and console-less: the script must survive this process and
        # must not flash a window in the player's face.
        creation = getattr(subprocess, "DETACHED_PROCESS", 0) | \
                   getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(["cmd", "/c", script], close_fds=True, creationflags=creation,
                     cwd=tempfile.gettempdir())
    return script


def check_in_background(on_result, manifest_url=None, fetch=None):
    """Run ``check`` off the main thread and hand the result back.

    The game must not stall on a network call at startup: a server that accepts
    the connection and then never answers would hang the window for the full
    timeout with nothing drawn.
    """
    def worker():
        try:
            on_result(check(manifest_url, fetch), None)
        except UpdateError as exc:
            on_result(None, str(exc))
        except Exception as exc:                      # noqa: BLE001 - never crash the game
            on_result(None, f"Update check failed ({exc})")

    thread = threading.Thread(target=worker, name="update-check", daemon=True)
    thread.start()
    return thread
