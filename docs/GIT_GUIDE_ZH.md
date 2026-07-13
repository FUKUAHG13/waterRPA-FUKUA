# fukuaRPA Git 新手指南

Git 是项目的“修改历史记录”。每次提交（commit）都保存一份可追踪的代码快照，方便查看谁在何时改了什么、比较版本或恢复到以前的状态。

## 当前仓库约定

- 默认分支叫 `main`。
- 源码、测试、文档、图标和构建脚本进入 Git。
- `dist/`、`build/`、Python 缓存、日志、会话令牌、凭据和本机方案不会进入 Git。
- Git 只记录源码；发布用的 EXE 和 ZIP 仍由发布脚本生成，并上传到 GitHub Releases。

## 最常用的四个命令

在 PowerShell 中先进入项目目录：

```powershell
cd D:\Desktop\waterRPA\fukuaRPA
```

查看有哪些文件发生变化：

```powershell
git status
```

把本次要保存的变化加入提交：

```powershell
git add -A
```

创建一次带说明的代码快照：

```powershell
git commit -m "简要说明本次修改"
```

把本地提交上传到已经连接的 GitHub 仓库：

```powershell
git push
```

通常只需依次执行：`git status`、`git add -A`、`git commit`、`git push`。提交说明应写清本次完成了什么，例如 `修复快捷键录入并增加窗口绑定测试`。

## 查看和恢复历史

查看简洁历史：

```powershell
git log --oneline --decorate --graph -20
```

查看尚未提交的具体改动：

```powershell
git diff
```

误改文件时不要随便使用 `git reset --hard`。先运行 `git status`，再让熟悉 Git 的人或 AI 根据现场状态选择恢复方法，避免覆盖尚未保存的工作。

## GitHub 与原创记录

本地 Git 历史非常适合开发和回退，但提交者可以修改本机时间，因此它本身不是绝对的法律证明。更稳妥的做法是：

1. 定期把提交推送到自己控制的 GitHub 仓库。
2. 为公开发布版本建立版本标签，例如 `v1.0.12`。
3. 后续配置 Git 签名，并为重要发布创建签名标签。
4. 保存原项目许可证、来源链接和自己修改内容的说明，遵守上游许可证。

## 当前提交签名

本仓库已经配置为使用 SSH 签名提交。GitHub 账户登记的是签名公钥，签名私钥只保存在当前 Windows 用户目录：

```text
%USERPROFILE%\.ssh\fukuaRPA_signing_ed25519
```

仓库中的 `.git_allowed_signers` 只包含可以公开的验证公钥，用于在本地运行 `git verify-commit`。不要上传、发送或手动复制没有 `.pub` 后缀的私钥文件；私钥也已经被排除在项目仓库之外。

查看最近一次提交的本地签名验证结果：

```powershell
git verify-commit HEAD
```

## 发布版本标签

完成发布并确认版本号后，可以创建标签：

```powershell
git tag -a v1.0.12 -m "fukuaRPA v1.0.12"
git push origin v1.0.12
```

不要给尚未验证或尚未发布的代码提前打正式版本标签。
