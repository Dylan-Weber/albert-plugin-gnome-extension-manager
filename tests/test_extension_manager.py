"""
Tests for the Extension Manager extension. Run from the extension folder with

    python3 -m unittest discover -s tests -v

The extension is loaded with a fake ``albert`` module (see fake_albert.py) and every test runs with
temporary XDG dirs, a fake PATH and stubbed gsettings, so results do not depend on the host system.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))
import fake_albert  # noqa: E402

sys.modules["albert"] = fake_albert

_spec = importlib.util.spec_from_file_location("extension_manager", TESTS_DIR.parent / "__init__.py")
em = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(em)

DASH = "dash-to-dock@micxgx.gmail.com"
APPINDICATOR = "appindicatorsupport@rgcjonas.gmail.com"


class EnvTestCase(unittest.TestCase):

    def setUp(self):
        fake_albert.reset()
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.user_data = self.home / ".local/share"
        self.sys_data = self.tmp / "usr/share"
        self.bin = self.tmp / "bin"
        for d in (self.user_data, self.sys_data, self.bin):
            d.mkdir(parents=True)
        env = mock.patch.dict(os.environ, {
            "HOME": str(self.home),
            "XDG_DATA_HOME": str(self.user_data),
            "XDG_DATA_DIRS": str(self.sys_data),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "PATH": str(self.bin),
        })
        env.start()
        self.addCleanup(env.stop)
        self.gsettings = {"enabled-extensions": "['%s']" % DASH,
                          "disabled-extensions": "@as []",
                          "disable-user-extensions": "false"}
        run = mock.patch.object(em.subprocess, "run", side_effect=self._fake_run)
        run.start()
        self.addCleanup(run.stop)

    def _fake_run(self, args, **kwargs):
        if args[:3] == ["gsettings", "get", "org.gnome.shell"] and self.gsettings is not None:
            return SimpleNamespace(returncode=0, stdout=self.gsettings[args[3]] + "\n")
        raise FileNotFoundError(args[0])

    def add_extension(self, uuid, name=None, data_dir=None, prefs=False, metadata=None):
        path = (data_dir or self.user_data) / "gnome-shell/extensions" / uuid
        path.mkdir(parents=True)
        md = {"uuid": uuid, "name": name or uuid, "description": f"{name} description\nmore"}
        if metadata is not None:
            md = metadata
        (path / "metadata.json").write_text(json.dumps(md) if not isinstance(md, str) else md)
        if prefs:
            (path / "prefs.js").write_text("")
        return path

    def add_bin(self, name):
        path = self.bin / name
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
        return path


class UriTest(unittest.TestCase):

    def test_at_sign_is_percent_encoded(self):
        # Unencoded, GLib parses "dash-to-dock" as user info and "micxgx.gmail.com" as host
        self.assertEqual(em.extension_uri(DASH), "gnome-extensions://dash-to-dock%40micxgx.gmail.com")


class ParseStrvTest(unittest.TestCase):

    def test_values(self):
        self.assertEqual(em._parse_strv("['a@b', 'c']\n"), ["a@b", "c"])
        self.assertEqual(em._parse_strv("@as []"), [])
        self.assertEqual(em._parse_strv("garbage"), [])


class LoadExtensionsTest(EnvTestCase):

    def test_user_and_system_sorted_by_name(self):
        self.add_extension(DASH, "Dash to Dock", prefs=True)
        self.add_extension(APPINDICATOR, "AppIndicator Support", data_dir=self.sys_data)
        exts = em.load_extensions()
        self.assertEqual([e.uuid for e in exts], [APPINDICATOR, DASH])
        self.assertEqual(exts[0].type, em.SYSTEM)
        self.assertEqual(exts[1].type, em.USER)
        self.assertTrue(exts[1].has_prefs)
        self.assertFalse(exts[0].has_prefs)

    def test_user_shadows_system(self):
        self.add_extension(DASH, "User copy")
        self.add_extension(DASH, "System copy", data_dir=self.sys_data)
        exts = em.load_extensions()
        self.assertEqual([(e.name, e.type) for e in exts], [("User copy", em.USER)])

    def test_bad_metadata_skipped_and_fallbacks(self):
        self.add_extension("broken@x", metadata="{not json")
        self.add_extension("noname@x", metadata={"description": 3})
        exts = em.load_extensions()
        self.assertEqual([(e.uuid, e.name, e.description) for e in exts], [("noname@x", "noname@x", "")])

    def test_missing_dirs(self):
        self.assertEqual(em.load_extensions(), [])


class ShellSettingsTest(EnvTestCase):

    def ext(self, uuid=DASH, type=em.USER):
        return em.ShellExtension(uuid, uuid, "", type, Path("/"), False)

    def test_enabled(self):
        s = em.read_shell_settings()
        self.assertTrue(s.is_enabled(self.ext()))
        self.assertFalse(s.is_enabled(self.ext(APPINDICATOR)))

    def test_disabled_list_wins(self):
        self.gsettings["disabled-extensions"] = "['%s']" % DASH
        self.assertFalse(em.read_shell_settings().is_enabled(self.ext()))

    def test_user_extensions_disabled(self):
        self.gsettings["disable-user-extensions"] = "true"
        s = em.read_shell_settings()
        self.assertFalse(s.is_enabled(self.ext()))
        self.assertTrue(s.is_enabled(self.ext(type=em.SYSTEM)))

    def test_no_gsettings(self):
        self.gsettings = None
        self.assertIsNone(em.read_shell_settings())


class CommandTest(EnvTestCase):

    def test_native_preferred(self):
        native = self.add_bin("extension-manager")
        self.add_bin("flatpak")
        (self.user_data / "flatpak/app" / em.APP_ID / "current").mkdir(parents=True)
        self.assertEqual(em.extension_manager_command(), [str(native)])

    def test_user_flatpak(self):
        self.add_bin("flatpak")
        (self.user_data / "flatpak/app" / em.APP_ID / "current").mkdir(parents=True)
        self.assertEqual(em.extension_manager_command(), ["flatpak", "run", em.APP_ID])

    def test_not_installed(self):
        self.add_bin("flatpak")
        # Keep the system flatpak dir out of the test even if the host has it
        with mock.patch.object(em, "SYSTEM_FLATPAK_DIR", self.tmp / "var/lib/flatpak"):
            self.assertIsNone(em.extension_manager_command())


class ItemTest(EnvTestCase):

    def item(self, has_prefs=True, em_command=("extension-manager",), enabled=True, type=em.USER):
        ext = em.ShellExtension(DASH, "Dash to Dock", "Dock for the dash\nsecond", type, Path("/"),
                                has_prefs)
        return em.ExtensionItem(ext, enabled, list(em_command) if em_command else None)

    def test_actions_and_commands(self):
        item = self.item()
        actions = item.actions()
        self.assertEqual([a.id for a in actions], ["open", "prefs", "copy-uuid"])
        for a in actions:
            a.callable()
        self.assertEqual(fake_albert.detached_processes, [
            ["extension-manager", "gnome-extensions://dash-to-dock%40micxgx.gmail.com"],
            ["gnome-extensions", "prefs", DASH],
        ])
        self.assertEqual(fake_albert.clipboard, [DASH])

    def test_without_prefs_or_extension_manager(self):
        self.assertEqual([a.id for a in self.item(has_prefs=False).actions()], ["open", "copy-uuid"])
        self.assertEqual([a.id for a in self.item(em_command=None).actions()], ["prefs", "copy-uuid"])
        self.assertEqual(self.item(em_command=None).icon(), ("theme", "application-x-addon"))

    def test_subtext(self):
        self.assertEqual(self.item().subtext(), "Enabled · Dock for the dash")
        self.assertEqual(self.item(enabled=False, type=em.SYSTEM).subtext(),
                         "Disabled · System · Dock for the dash")
        self.assertEqual(self.item(enabled=None).subtext(), "Dock for the dash")


class PluginTest(EnvTestCase):

    def query(self, plugin, text):
        return plugin.rankItems(SimpleNamespace(query=text))

    def test_query_matches_name_and_rescans_on_change(self):
        self.add_bin("extension-manager")
        self.add_extension(DASH, "Dash to Dock", prefs=True)
        plugin = em.Plugin()
        self.assertEqual([r.item.text() for r in self.query(plugin, "dock")], ["Dash to Dock"])
        self.assertEqual(len(self.query(plugin, "")), 1)
        self.assertEqual(self.query(plugin, "blur"), [])

        path = self.add_extension("blur-my-shell@aunetx", "Blur my Shell")
        # mtime resolution can be coarse, so make sure the folder looks changed
        ext_dir = path.parent
        st = ext_dir.stat()
        os.utime(ext_dir, (st.st_atime, st.st_mtime + 5))
        results = self.query(plugin, "blur")
        self.assertEqual([r.item.id() for r in results], ["blur-my-shell@aunetx"])
        self.assertFalse(results[0].item.enabled)

    def test_matches_uuid(self):
        self.add_extension(DASH, "Dash to Dock")
        self.assertEqual(len(self.query(em.Plugin(), "micxgx")), 1)


class SystemSmokeTest(unittest.TestCase):
    """Loads the extensions really installed on this machine, if any."""

    def test_load(self):
        fake_albert.reset()
        exts = em.load_extensions()
        if not exts:
            self.skipTest("No GNOME Shell extensions installed")
        for e in exts:
            self.assertTrue(e.uuid and e.name)


if __name__ == "__main__":
    unittest.main()
