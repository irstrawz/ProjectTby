"""Where things live, whether running from source or from a built .exe.

Four modules used to compute their own paths from ``__file__``. That works
exactly until the game is frozen, at which point ``__file__`` points inside the
bundle and the answers quietly become wrong. Everything asks here instead.

The distinction that actually matters is **read-only content versus the
player's own data**, because an update replaces the whole application folder.

* ``resource_path`` — art, sound, music. Ships with the app, replaced wholesale
  by an update, never written to.
* ``user_data_path`` — the save file. Must live *outside* the application
  folder, or the first update anyone installs deletes their progress. That is a
  bug you only discover from a player who has already lost everything, so it is
  worth getting right before the first build rather than after.
"""

import os
import sys

APP_NAME = "ProjectTby"


def is_frozen():
    """True when running from a PyInstaller build rather than source."""
    return getattr(sys, "frozen", False)


def app_dir():
    """The folder the application lives in.

    Frozen: the directory holding the .exe — the thing an update replaces.
    Source: the repository root.
    """
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(*parts):
    """A read-only file that ships with the game.

    ``sys._MEIPASS`` is where PyInstaller puts bundled data, and it is set for
    one-folder builds too — the files land in ``_internal/`` beside the exe, not
    next to it, which is easy to get wrong by assuming otherwise. Falling back
    to ``app_dir`` covers running from source, where they really are at the
    root.
    """
    base = getattr(sys, "_MEIPASS", None) or app_dir()
    return os.path.join(base, *parts)


def user_data_dir():
    """Per-player state, outside the application folder so updates cannot eat it.

    ``%LOCALAPPDATA%`` on Windows, ``~/.local/share`` elsewhere. Running from
    source keeps using the repository root, so development does not scatter save
    files into the real user profile and a working copy stays self-contained.
    """
    if not is_frozen():
        return app_dir()
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        root = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"),
                                                               ".local", "share")
    directory = os.path.join(root, APP_NAME)
    os.makedirs(directory, exist_ok=True)
    return directory


def user_data_path(*parts):
    return os.path.join(user_data_dir(), *parts)


def legacy_user_data_path(*parts):
    """Where per-player state used to live: beside the application.

    Kept so an existing save can be moved rather than abandoned. Anyone who
    played a pre-packaged build has their progress here.
    """
    return os.path.join(app_dir(), *parts)
