# Third-party artwork and research

`src/busybar_codex/assets/provider-openai.png` and `provider-anthropic.png`
are 12×12 white-on-black rasterizations of the corresponding SVGs from
[Simple Icons v14.15.0](https://github.com/simple-icons/simple-icons/tree/14.15.0/icons).
Simple Icons distributes its icon artwork under
[CC0 1.0](https://github.com/simple-icons/simple-icons/blob/14.15.0/LICENSE.md).
Rendered with resvg-py; it is only a build-time tool, not an application dependency.
OpenAI and Anthropic names and marks belong to their respective owners.
This project is independent of those companies and BUSY Bar.

The integration design was compared with the projects listed in
[docs/RESEARCH.md](docs/RESEARCH.md). Their implementation code was not copied or
vendored. The adopted ideas are implemented here against the official interfaces
and tested independently. Existing busylib and other dependencies retain their
own licenses.


## Windows tray dependency

The Windows tray imports unmodified [pystray 0.19.5](https://github.com/moses-palmer/pystray/tree/v0.19.5)
as a separately installed Python dependency. It is licensed under LGPL-3.0-or-later;
its distribution includes `COPYING` and `COPYING.LGPL`. See the upstream
[license](https://github.com/moses-palmer/pystray/blob/v0.19.5/COPYING.LGPL).
The application does not vendor or modify pystray. The small tray bar image is
original Pillow drawing code, not artwork from a third-party app.
