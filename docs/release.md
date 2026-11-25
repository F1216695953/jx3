# 打包与发布

## GitHub Actions

`.github/workflows/build.yml` 监听 `v*` tag，运行测试、构建安装包并发布 GitHub Release。`pyappify.yml` 配置应用名、图标、Python 3.12 和两个安装 profile（China、Global）；两个 profile 的更新源均指向当前仓库。

当前工作流不使用 CNB 同步或 MirrorChyan，也不需要这些服务的专用 secrets。发布 tag 前先确认 GitHub 仓库的 Actions 权限已启用。

## 发布步骤

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p '*.py'
git status
git add .
git commit -m "Configure JX3 daily planner"
git push origin master
git tag v0.1.0
git push origin v0.1.0
```

tag 推送后，Actions 将构建并发布两个 profile 的安装包。版本文件名以 `jx3-wujie-daily-assistant-win32-<profile>-setup-<version>.exe` 为前缀。
