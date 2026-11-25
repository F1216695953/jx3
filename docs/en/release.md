# Packaging and Release

## GitHub Actions

`.github/workflows/build.yml` watches `v*` tags, runs tests, builds installers, and publishes a GitHub Release. `pyappify.yml` defines the app name, icon, Python 3.12, and two installer profiles (China and Global); both profiles use this repository as their update source.

The workflow does not use CNB synchronization or MirrorChyan, and requires no dedicated secrets for those services. Make sure GitHub Actions is enabled for the repository before pushing a release tag.

## Release Steps

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p '*.py'
git status
git add .
git commit -m "Configure JX3 daily planner"
git push origin master
git tag v0.1.0
git push origin v0.1.0
```

After the tag is pushed, Actions builds and publishes both profiles. Installer names start with `jx3-wujie-daily-assistant-win32-<profile>-setup-<version>.exe`.
