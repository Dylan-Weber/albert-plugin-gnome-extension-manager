# -*- coding: utf-8 -*-

"""
Search the installed GNOME Shell extensions and open them in Extension Manager
(https://github.com/mjakeman/extension-manager).

Extensions are read from the ``gnome-shell/extensions`` folders in the XDG data dirs, the same
places GNOME Shell loads them from, so the list is always current (it is re-read whenever one of
those folders changes).

Extension Manager registers itself as the handler of ``gnome-extensions://<uuid>`` URIs and opens
the detail page of that extension, which is what the default action uses. Note that the UUID has
to be percent-encoded: UUIDs contain an ``@``, which would otherwise be parsed as the user info
part of the URI and Extension Manager would open the wrong (or no) extension.

The extension's own settings window belongs to GNOME Shell (Extension Manager's gear button calls
``org.gnome.Shell.Extensions.LaunchExtensionPrefs`` too), so the second action opens it directly.
"""

import ast
import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from albert import *

md_iid = "5.0"
md_version = "1.0"
md_name = "Extension Manager"
md_description = "Open installed GNOME Shell extensions in Extension Manager"
md_license = "MIT"
md_authors = ["@Dylan-Weber"]
md_platforms = ["Linux"]

APP_ID = "com.mattjakeman.ExtensionManager"
SYSTEM_FLATPAK_DIR = Path("/var/lib/flatpak")
URI_SCHEME = "gnome-extensions"

# Extension types, as in GNOME Shell's ExtensionType
SYSTEM = "system"
USER = "user"


def _user_data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")


def _system_data_dirs() -> list[Path]:
    dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [Path(d) for d in dirs.split(":") if d]


def extension_dirs() -> list[tuple[Path, str]]:
    """Folders extensions are installed in, in order of precedence, with their extension type."""
    dirs = [(_user_data_dir() / "gnome-shell/extensions", USER)]
    dirs += [(d / "gnome-shell/extensions", SYSTEM) for d in _system_data_dirs()]
    return dirs


def extension_manager_command() -> list[str] | None:
    """The command that launches Extension Manager, native install first, then Flatpak."""
    native = shutil.which("extension-manager")
    if native:
        return [native]
    if shutil.which("flatpak"):
        installs = [_user_data_dir() / "flatpak", SYSTEM_FLATPAK_DIR]
        if any((d / "app" / APP_ID / "current").exists() for d in installs):
            return ["flatpak", "run", APP_ID]
    return None


def extension_uri(uuid: str) -> str:
    return f"{URI_SCHEME}://{quote(uuid, safe='')}"


def _parse_strv(text: str) -> list[str]:
    """Parses gsettings' printout of a string array, e.g. ``['a', 'b']`` or ``@as []``."""
    text = text.strip().removeprefix("@as").strip()
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return []
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def _gsettings_get(key: str) -> str | None:
    try:
        result = subprocess.run(["gsettings", "get", "org.gnome.shell", key],
                                capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError) as e:
        debug(f"gsettings get {key} failed: {e}")
        return None
    return result.stdout if result.returncode == 0 else None


@dataclass
class ShellSettings:
    enabled: set[str]
    disabled: set[str]
    user_extensions_disabled: bool

    def is_enabled(self, ext: "ShellExtension") -> bool:
        if ext.uuid in self.disabled:
            return False
        if ext.type == USER and self.user_extensions_disabled:
            return False
        return ext.uuid in self.enabled


def read_shell_settings() -> ShellSettings | None:
    enabled = _gsettings_get("enabled-extensions")
    if enabled is None:
        return None
    disabled = _gsettings_get("disabled-extensions") or ""
    user_disabled = (_gsettings_get("disable-user-extensions") or "").strip() == "true"
    return ShellSettings(set(_parse_strv(enabled)), set(_parse_strv(disabled)), user_disabled)


@dataclass
class ShellExtension:
    uuid: str
    name: str
    description: str
    type: str
    path: Path
    has_prefs: bool


def _read_extension(path: Path, ext_type: str) -> ShellExtension | None:
    try:
        metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        debug(f"Skipping {path}: {e}")
        return None
    if not isinstance(metadata, dict):
        return None
    uuid = metadata.get("uuid")
    if not isinstance(uuid, str) or not uuid:
        uuid = path.name
    name = metadata.get("name")
    description = metadata.get("description")
    return ShellExtension(
        uuid=uuid,
        name=name if isinstance(name, str) and name.strip() else uuid,
        description=description if isinstance(description, str) else "",
        type=ext_type,
        path=path,
        has_prefs=(path / "prefs.js").is_file(),
    )


def load_extensions() -> list[ShellExtension]:
    """All installed extensions; a user extension shadows a system one with the same UUID."""
    extensions: dict[str, ShellExtension] = {}
    for ext_dir, ext_type in extension_dirs():
        try:
            entries = sorted(ext_dir.iterdir())
        except OSError:
            continue
        for path in entries:
            if not path.is_dir():
                continue
            ext = _read_extension(path, ext_type)
            if ext is not None:
                extensions.setdefault(ext.uuid, ext)
    return sorted(extensions.values(), key=lambda e: e.name.lower())


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0].strip() if text.strip() else ""


class ExtensionItem(Item):

    def __init__(self, ext: ShellExtension, enabled: bool | None, em_command: list[str] | None):
        Item.__init__(self)
        self.ext = ext
        self.enabled = enabled
        self.em_command = em_command

    def id(self):
        return self.ext.uuid

    def text(self):
        return self.ext.name

    def subtext(self):
        parts = []
        if self.enabled is not None:
            parts.append("Enabled" if self.enabled else "Disabled")
        if self.ext.type == SYSTEM:
            parts.append("System")
        description = _first_line(self.ext.description)
        parts.append(description or self.ext.uuid)
        return " · ".join(parts)

    def inputActionText(self):
        return self.ext.name

    def icon(self):
        return Icon.theme(APP_ID if self.em_command else "application-x-addon")

    def open_in_extension_manager(self):
        runDetachedProcess([*self.em_command, extension_uri(self.ext.uuid)])

    def open_settings(self):
        runDetachedProcess(["gnome-extensions", "prefs", self.ext.uuid])

    def actions(self):
        actions = []
        if self.em_command:
            actions.append(Action("open", "Open in Extension Manager",
                                  self.open_in_extension_manager))
        if self.ext.has_prefs:
            actions.append(Action("prefs", "Open extension settings", self.open_settings))
        actions.append(Action("copy-uuid", "Copy UUID", lambda: setClipboardText(self.ext.uuid)))
        return actions


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


class ExtensionCache:
    """
    Caches the scanned extensions and shell settings, rescanning only when the extension folders
    or the dconf database changed. Queries run in background threads, hence the lock.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._ext_key = None
        self._extensions: list[ShellExtension] = []
        self._settings_key = None
        self._settings: ShellSettings | None = None

    def _extensions_key(self):
        return tuple((str(d), _mtime(d)) for d, _ in extension_dirs())

    def _dconf_key(self):
        config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        return _mtime(config / "dconf/user")

    def get(self) -> tuple[list[ShellExtension], ShellSettings | None]:
        with self._lock:
            key = self._extensions_key()
            if key != self._ext_key:
                self._extensions = load_extensions()
                self._ext_key = key
                debug(f"Found {len(self._extensions)} GNOME Shell extensions")
            dconf_key = self._dconf_key()
            if dconf_key is None or dconf_key != self._settings_key:
                self._settings = read_shell_settings()
                self._settings_key = dconf_key
            return self._extensions, self._settings


class Plugin(PluginInstance, GlobalQueryHandler):

    def __init__(self):
        PluginInstance.__init__(self)
        GlobalQueryHandler.__init__(self)
        self.fuzzy = False
        self.cache = ExtensionCache()

    def defaultTrigger(self):
        return "ext "

    def synopsis(self, query):
        return "<extension name>"

    def supportsFuzzyMatching(self):
        return True

    def setFuzzyMatching(self, enabled):
        self.fuzzy = enabled

    def rankItems(self, context):
        extensions, settings = self.cache.get()
        em_command = extension_manager_command()
        matcher = Matcher(context.query, MatchConfig(fuzzy=self.fuzzy))
        rank_items = []
        for ext in extensions:
            match = matcher.match(ext.name, ext.uuid)
            if match:
                enabled = settings.is_enabled(ext) if settings else None
                rank_items.append(RankItem(ExtensionItem(ext, enabled, em_command), match))
        return rank_items
