# 从源码运行与构建 fukuaRPA

仓库 `main` 分支中的 fukuaRPA 是模块化重构版源码预览。它会继续接受真实场景测试和调整，不等同于 Releases 中已经打包的稳定版本。只想直接使用软件的用户应优先下载 Release；熟悉 Python 环境、愿意提前体验的用户可以按本文运行或自行打包。

## 系统与工具

- Windows 10 1809 及以上版本（仅 x64），或 Windows 11 x64。
- CPython 3.14.3 x64。
- Git，用于克隆和更新源码；也可以直接下载 GitHub 的源码 ZIP。
- 自行打包时需要 Visual Studio 2022 Build Tools，并安装“使用 C++ 的桌面开发”、MSVC v143 和 Windows 10/11 SDK。仅从源码运行时可直接使用仓库已有的原生 DLL，不要求安装编译器。

## 获取源码

```powershell
git clone https://github.com/FUKUAHG13/waterRPA-fukuaRPA.git
cd waterRPA-fukuaRPA
```

## 创建独立 Python 环境

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

所有直接依赖都在 `requirements.txt` 中固定版本。使用独立环境可以避免与电脑上其他 Python 软件的依赖相互影响。

## 从源码运行

```powershell
.\.venv\Scripts\python.exe fukuaRPA.py
```

源码运行时，程序数据默认保存在项目目录；请勿把自己的 `config.ini`、凭据、日志或导入图片提交到 Git 仓库。

## 自行打包

推荐构建完整版多文件版：

```powershell
.\.venv\Scripts\python.exe scripts\build_release.py
```

只有明确需要单文件版时再执行：

```powershell
.\.venv\Scripts\python.exe scripts\build_release.py --format onefile
```

同时构建两种格式：

```powershell
.\.venv\Scripts\python.exe scripts\build_release.py --format all
```

构建脚本会先重新编译 x64 原生识别核心，并默认执行源码测试、静态检查、性能门、耐久测试、冻结包启动测试、运行库闭包和完整性校验。多文件版输出到 `dist` 下以当前 `BUILD_NAME` 命名的目录，并同时生成便携 ZIP、目录清单和 SHA-256 校验文件。

`--skip-quality` 只适合开发者临时排查打包问题，不应把跳过质量检查生成的文件当作正式发布包。

## 常见问题

- 找不到 `cl.exe` 或 `vcvars64.bat`：补装 Visual Studio 2022 Build Tools 的 C++ 工作负载。
- 启动后原生识别不可用：确认仓库中的 `fukua_rpa_core.dll` 未被杀毒软件隔离；程序仍会自动回退到 OpenCV/Python 路径。
- 单文件版启动较慢：这是内置运行库解压造成的正常现象，日常测试建议使用多文件版。
- Windows SmartScreen 提示：当前项目没有商业代码签名证书，源码构建的 EXE 也不会自动获得可信发布者签名。
