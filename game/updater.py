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
    # Prefix distinct from the swap script's log, which used to share it and
    # made a leftover log indistinguishable from a leaked partial download.
    handle, temp_path = tempfile.mkstemp(prefix="projecttby-download-", suffix=".zip")
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
rem has let go of its files, then restarts it.
rem
rem This exists because Windows will not let a running .exe be overwritten, so
rem the swap has to outlive the process doing the updating.
setlocal

rem A breadcrumb written before anything else and deleted on success. If an
rem update ever fails silently, whether this file exists says immediately
rem whether the script ran at all.
echo Started. > "{log}"

rem A moment for the caller to quit. It hands off and then exits immediately,
rem so this is usually already true; robocopy's retries cover the rest.
ping -n 4 127.0.0.1 >nul

rem /R:20 /W:2 retries a locked file for about forty seconds. That is the whole
rem synchronisation strategy, and it replaced waiting on a process id.
rem
rem The previous version polled `tasklist /fi "PID eq N" | find "N"`. That hangs
rem forever when the filter does not apply for any reason — tasklist then prints
rem every process, and "N" reliably turns up somewhere in the memory or handle
rem columns, so `find` keeps matching a game that exited long ago. It was
rem observed doing exactly that, wedged, with the game long gone.
rem
rem Retrying the copy needs no notion of who is running: the only thing that
rem actually matters is whether the files can be written yet, and that is what
rem this asks.
robocopy "{staging}" "{app}" /mir /is /it /xd "{staging}" /R:20 /W:2 /njh /njs /ndl /nfl /nc /ns >nul
if errorlevel 8 goto failed

rmdir /s /q "{staging}"
del "{log}" 2>nul
start "" "{exe}"
del "%~f0"
exit /b 0

:failed
rem No "pause" here. This script is launched detached and windowless, so there
rem is no console for anyone to press a key at. Write the reason down, put the
rem old build back in front of them, and get out of the way.
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
        handle.write(SWAP_SCRIPT.format(staging=staging, app=app_dir,
                                        exe=exe_path, log=log))

    creation = 0
    if os.name == "nt":
        # Detached and console-less: the script must survive this process and
        # must not flash a window in the player's face.
        creation = getattr(subprocess, "DETACHED_PROCESS", 0) | \
                   getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    # stdin/stdout/stderr are pinned to DEVNULL rather than inherited, and that
    # is load-bearing rather than tidiness.
    #
    # A --windowed PyInstaller build has no console, so there are no valid
    # standard handles to hand on. Combined with DETACHED_PROCESS — which also
    # denies the child a console of its own — cmd.exe starts with invalid
    # handles and dies immediately. Popen still returns a process object without
    # raising, so the caller concludes the handoff worked and quits, and the
    # update silently never happens: the old build stays installed, the staging
    # folder is orphaned, and nothing anywhere records why.
    #
    # This cost a full round trip on a real install to find, because every test
    # run from source had a console to inherit and worked perfectly.
    subprocess.Popen(["cmd", "/c", script], close_fds=True, creationflags=creation,
                     cwd=tempfile.gettempdir(),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
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
