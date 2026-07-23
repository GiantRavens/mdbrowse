"""Platform-aware user data paths for mdbrowse.

Keep generated stores out of the visible home directory by default,
while preserving explicit env var overrides for scripted workflows.
"""

import os
import subprocess
import sys
from urllib.parse import unquote, urlparse

APP_NAME = "mdbrowse"


def _home(env) -> str:
    return env.get("HOME") or env.get("USERPROFILE") or os.path.expanduser("~")


def app_data_dir(app_name: str = APP_NAME, env=None, platform: str = None) -> str:
    """Per-user application data directory.

    macOS follows the Application Support convention; Unix follows XDG;
    Windows follows LocalAppData. MDBROWSE_HOME overrides the base for
    all mdbrowse user-data stores.
    """
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform

    if env.get("MDBROWSE_HOME"):
        return os.path.expanduser(env["MDBROWSE_HOME"])

    home = _home(env)
    if platform == "darwin":
        return os.path.join(home, "Library", "Application Support", app_name)
    if platform.startswith("win"):
        base = (env.get("LOCALAPPDATA") or env.get("APPDATA")
                or os.path.join(home, "AppData", "Local"))
        return os.path.join(base, app_name)

    base = env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(base, app_name)


def data_path(name: str, env_var: str = None, env=None,
              platform: str = None) -> str:
    """Path for one mdbrowse data store, with a store-specific override."""
    env = os.environ if env is None else env
    if env_var and env.get(env_var):
        return os.path.expanduser(env[env_var])
    return os.path.join(app_data_dir(env=env, platform=platform), name)


def downloads_dir(env=None, platform: str = None,
                  safari_path: str = None) -> str:
    """The user's visible download folder.

    Precedence is explicit mdb override, Safari's configured download path
    on macOS, then the platform-neutral ``~/Downloads`` convention.
    ``safari_path`` is injectable so resolution stays cheap and testable.
    """
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    home = _home(env)
    if env.get("MDBROWSE_DOWNLOADS"):
        path = env["MDBROWSE_DOWNLOADS"]
    else:
        path = safari_path or ""
        if platform == "darwin" and safari_path is None:
            try:
                result = subprocess.run(
                    ["defaults", "read", "com.apple.Safari", "DownloadsPath"],
                    text=True, capture_output=True, timeout=1, check=False)
                if result.returncode == 0:
                    path = result.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                pass
        if path.startswith("file://"):
            path = unquote(urlparse(path).path)
        if not path:
            path = os.path.join(home, "Downloads")
    if path == "~":
        return home
    if path.startswith("~/"):
        return os.path.join(home, path[2:])
    return os.path.expanduser(path)
