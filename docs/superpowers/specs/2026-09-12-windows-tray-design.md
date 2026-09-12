# Windows tray and login startup

The user approved a Windows tray-only launch mode and optional login startup after releasing 0.1.2. The character theme is deferred.

## Design

Use pystray as an unmodified Windows-only dependency for a native notification-area icon. A Qt application adds unnecessary size; direct Win32 menu code adds avoidable platform maintenance. Reuse Pillow for an original simple bar icon. Keep the existing CLI daemon available.

The tray owns a worker thread running the existing daemon with a cooperative stop Event. Start, Stop, Restart, Show display, Hide display, Start with Windows, and Exit are the menu actions. The daemon remains the only device controller and retains its shared-state instance lock. A second tray is rejected by a separate state-directory lock. An existing console daemon is reported without killing it. Exit stops only the worker owned by this tray, clears our display through the existing cleanup, and releases locks. Stop/Restart are asynchronous so the menu remains responsive; restart waits for old cleanup before starting a new worker.

A `busybar-codex tray --env-file .env` command launches the current environment's pythonw.exe without a console, using a bounded launch profile containing absolute paths only. The profile retains the working directory, optional env/config paths and state directory. It contains no environment dump or token values. The explicit .env is read at startup with interpolation disabled and only supported app settings accepted; normal environment settings override it. GUI entry-point startup failures show fixed safe messages. Hooks never import tray libraries.

Login startup uses one application-owned HKCU Run value pointing to pythonw and the launch profile. It defaults off, needs no administrator rights, and can be disabled in the menu. Preserve any conflicting value. Reject enabling startup for registry command lines over Microsoft's documented 260-character limit while retaining manual tray launch. Profile filenames are scoped by a hash of the resolved state directory. The application folder and Python environment must stay in place. Volatile shell settings are not copied to the profile; persistent startup settings must live in the selected env/TOML file.

## Validation

Synthetic tests cover cooperative stop/restart, single ownership, failure reporting without raw exception text, controls, headless launch path quoting, bounded profiles, env filtering, and startup enable/disable/conflict behavior. Run all project quality gates offline, package and smoke-test the GUI entry point. Perform a real Windows tray smoke check without injecting AI sessions. Full logoff/login and AI-client end-to-end checks remain separate.

## References

- https://pystray.readthedocs.io/en/latest/usage.html
- https://github.com/moses-palmer/pystray/blob/master/COPYING.LGPL
- https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys
- https://docs.python.org/3.13/library/subprocess.html
