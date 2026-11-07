# GNOME Extension Manager

Albert extension that searches your installed GNOME Shell extensions by name (or UUID) and opens
the selected one in [Extension Manager](https://github.com/mjakeman/extension-manager).

- **Open in Extension Manager** (default): opens the extension's page in Extension Manager, with
  its settings button, toggle, versions and reviews.
- **Open extension settings**: opens the extension's own settings window directly, for extensions
  that have one. This is the same window Extension Manager's gear button opens (it belongs to
  GNOME Shell), just one step shorter.
- **Copy UUID**

Results show in the global query and under the `ext ` trigger, with the enabled/disabled state.

## How it works

- Extensions are read from `~/.local/share/gnome-shell/extensions` and the system
  `gnome-shell/extensions` folders. The list is re-read whenever one of those folders changes, so
  newly installed extensions show up without restarting Albert.
- Enabled state comes from `gsettings` (`org.gnome.shell enabled-extensions`, ...), re-read only
  when the dconf database changes.
- Extension Manager handles `gnome-extensions://<uuid>` URIs. The UUID is percent-encoded, because
  the `@` in it would otherwise be parsed as URI user info and the wrong extension would open.
- Extension Manager is launched as `extension-manager` if it is on `PATH`, otherwise as the
  `com.mattjakeman.ExtensionManager` Flatpak (user or system install). If neither is installed only
  the settings action is offered.

## Install

```sh
ln -s "$PWD" ~/.local/share/albert/python/plugins/extension_manager
```

Then enable *GNOME Extension Manager* under Albert → Settings → Plugins → Python.

## Tests

The tests run without Albert, using a fake `albert` module, and only need Python's standard library:

```sh
python3 -m unittest discover -s tests -v
```

## License

MIT, see [LICENSE](LICENSE).
