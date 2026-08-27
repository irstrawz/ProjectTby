"""What build this is, and where to look for a newer one.

Kept in its own module with no imports so that the build script, the updater and
the title screen can all read it without dragging pygame in.
"""

VERSION = "0.2.0"

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
UPDATE_MANIFEST_URL = ""


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


def is_newer(candidate, current=VERSION):
    return parse(candidate) > parse(current)
