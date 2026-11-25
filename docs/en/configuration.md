# App Configuration

## Current Settings

`src/config.py` is configured with:

- Window title: JX3 Unbounded Daily Planner.
- Windows process: `JX3ClientX3DX64.exe`.
- Minimum target resolution: `1280×720`, aspect ratio `16:9`.
- No window class was provided, so `hwnd_class` is omitted and default matching is used.
- No icon was provided; `icons/icon.png` and `icons/icon.ico` remain the template files.
- GitHub links point to `https://github.com/F1216695953/jx3`.

## Update Source

Both China and Global profiles in `pyappify.yml` use this GitHub repository as their update source, suitable for early testing. If you later create a dedicated update repository, update the corresponding profile and build workflow.

MirrorChyan and CNB synchronization are disabled. Releases are published directly to GitHub.

## Resolution

`supported_resolution` in `src/config.py` uses a `16:9` ratio and a `1280×720` minimum. Do not guess the window class; add `hwnd_class` after obtaining the actual client window information.
