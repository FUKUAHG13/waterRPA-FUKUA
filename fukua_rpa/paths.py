"""Separate writable user data from bundled read-only application resources."""

import os
import sys
import tempfile
from dataclasses import dataclass
from functools import lru_cache


PORTABLE_FLAG_NAME = "portable.flag"


@dataclass(frozen=True)
class RuntimePathInfo:
    install_dir: str
    data_dir: str
    mode: str


def get_install_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _directory_is_writable(path):
    try:
        os.makedirs(path, exist_ok=True)
        descriptor, probe = tempfile.mkstemp(prefix=".fukua_write_probe_", dir=path)
        os.close(descriptor)
        os.remove(probe)
        return True
    except OSError:
        return False


@lru_cache(maxsize=1)
def runtime_path_info():
    install_dir = get_install_dir()
    if not getattr(sys, "frozen", False):
        return RuntimePathInfo(install_dir, install_dir, "source")
    portable_forced = os.path.isfile(os.path.join(install_dir, PORTABLE_FLAG_NAME))
    if _directory_is_writable(install_dir):
        return RuntimePathInfo(
            install_dir,
            install_dir,
            "portable_forced" if portable_forced else "portable",
        )
    if portable_forced:
        raise RuntimeError(
            "检测到 portable.flag，但程序目录不可写。请把完整软件文件夹移动到有写入权限的位置。"
        )
    local_app_data = os.environ.get("LOCALAPPDATA") or os.path.join(
        os.path.expanduser("~"), "AppData", "Local"
    )
    data_dir = os.path.join(local_app_data, "fukuaRPA")
    os.makedirs(data_dir, exist_ok=True)
    return RuntimePathInfo(install_dir, data_dir, "local_app_data")


def get_base_dir():
    return runtime_path_info().data_dir


def get_resource_path(relative_path):
    """Resolve a bundled read-only asset in both source and PyInstaller builds."""

    if getattr(sys, "frozen", False):
        resource_root = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        resource_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(resource_root, relative_path)


def get_log_path(base_dir=None):
    return os.path.join(base_dir or get_base_dir(), "rpa_debug_log.txt")
