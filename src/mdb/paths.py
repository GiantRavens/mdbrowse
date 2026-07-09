"""Platform-aware user data paths for mdbrowse.

Keep generated stores out of the visible home directory by default,
while preserving explicit env var overrides for scripted workflows.
"""

import os
import sys

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
