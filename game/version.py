"""What build this is, and where to look for a newer one.

Kept in its own module with no imports so that the build script, the updater and
the title screen can all read it without dragging pygame in.
"""

VERSION = "0.5.0"

# Where the updater looks for the latest release. It fetches a small JSON
# manifest — see ``tools/build_exe.py`` for the exact shape it writes.
#
# Point this at whatever you publish to. With GitHub Releases the usual trick is
# a tag that always means "newest", so the URL never changes:
#
#     https://github.com/<you>/<repo>/releases/latest/download/manifest.json
#
# **HTTPS only.** The updater refuses anything else, and refuses a download
# whose SHA-256 does not match the manifest. Both matter for the same reason:
# this feature downloads a zip and replaces the game with its contents, so
# whoever controls this URL controls what runs on your players' machines.
UPDATE_MANIFEST_URL = (
    "https://github.com/irstrawz/ProjectTby/releases/latest/download/manifest.json"
)


def parse(text):
    """"1.2.3" -> (1, 2, 3). Missing or odd parts sort as 0.

    Compared as a tuple of integers rather than as a string, because "0.10.0" is
    newer than "0.9.0" and string comparison says the opposite.
    """
    parts = []
    for chunk in str(text).strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer(candidate, current=None):
    """Is ``candidate`` a later version than ``current`` (default: this build)?

    ``current`` resolves inside the function rather than as ``current=VERSION``
    in the signature. A default argument is evaluated once when the module is
    imported, so the signature form freezes whatever VERSION was at import and
    silently ignores any later change to it. Nothing reassigns VERSION at
    runtime today, but the frozen form is a trap: it makes the function
    untestable against any version other than the built-in one, and the failure
    looks like the comparison being wrong rather than the default being stale.
    """
    return parse(candidate) > parse(VERSION if current is None else current)
