# fukuaRPA v1.0.11

## 支持范围

- Windows 10 1809 及以上版本（仅 x64）
- Windows 11 x64
- 同一套源码维护完整版多文件版和完整版单文件版；精简版已终止

## 开发运行

```powershell
python fukuaRPA.py
```

源码运行时，配置、自动备份、导入图片、凭据和日志保存在项目目录。冻结版所在目录可写时保持
便携布局；目录不可写时自动使用 `%LOCALAPPDATA%\fukuaRPA`，并在首次发生时提示。用户可在 EXE
旁创建 `portable.flag` 强制数据留在程序目录，此时目录不可写会明确报错。界面也可通过
`RPAWindow(base_dir=...)` 显式指定作业目录，自动化测试使用这一方式隔离用户配置。

## 界面设计

程序使用项目内置的 Qt 主题，不增加第三方 UI 运行库。主窗口、步骤行、设置窗口、
状态栏和辅助浮层共用同一套颜色、间距、圆角和交互状态，并继续支持用户设置的界面倍率。
阶段划分与维护约束见 `docs/UI_MODERNIZATION.md`。
长期功能与质量路线见 `ROADMAP.md`。

启动采用三段式加载：先显示可响应的轻量准备窗口，再导入完整工作区，最后后台初始化 OpenCV 等
运行后端。PyAutoGUI 和 UI Automation 继续延迟到首次需要；运行按钮会在后端就绪后自动启用。

## 验证

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m unittest discover -s tests -v
python -m ruff check fukuaRPA.py fukua_rpa tests scripts --select F,E9,E722
python scripts\benchmark_core.py --rounds 10 --assert-limits
python scripts\benchmark_vision.py --rounds 10 --assert-limits
python scripts\benchmark_native_scheduler.py --rounds 10 --assert-limits
python scripts\smoke_native_vision.py
python scripts\smoke_uia_control.py
python scripts\smoke_startup.py --assert-limits
python scripts\soak_runtime.py --rounds 20000 --assert-limits
```

其中 `tests/test_ui_modernization.py` 会检查主题加载、关键控件语义、最小窗口宽度、
设置页横向溢出、垂直对齐、界面倍率和后台映射回归。

程序还提供不启动 GUI、不联网的离线环境自检：

```powershell
python fukuaRPA.py --self-test-file self-test.json
python fukuaRPA.py --native-smoke
```

设置页的“导出诊断”会额外包含最近运行的 P50/P95、截图/模板缓存统计和有界运行轨迹，
但不会导出步骤内容、图片路径、输入文本或映射坐标。

步骤支持执行前断点、条件断点、暂停、继续和单步越过。“设置变量”和“判断表达式”只使用内置的
受限表达式解释器，不执行 Python 代码；流程检查器会提示某条跳转路径上可能尚未赋值的变量。

后台单次左键点击会先尝试 UI Automation 控件动作，再按兼容情况回退 PostMessage；超时且
动作结果未知时不会重复发送第二次点击。游戏、浏览器画布、DirectX、自绘和高权限窗口仍可能不兼容。
步骤还可直接启动程序、等待/激活/关闭标题匹配的窗口，并可选取标准 Windows 控件执行点击、写值
或读取到运行变量。UIA 控件动作有固定节点、深度和时间上限，失败不会退化成误点前台鼠标。

“输入秘密文本”只在方案中保存凭据名称。秘密值由当前 Windows 用户的 DPAPI 加密保存在本地
`credentials.dat`，不会进入日志、普通导出或全量导出；普通文本与秘密文本均使用 Unicode 键盘
事件输入，不覆盖用户剪贴板。换电脑或 Windows 用户后需要重新创建同名凭据。

方案使用版本化迁移和签名备份。主配置损坏或上次写入只完成一半时，会依次尝试当前原子备份
和 `profiles_history` 中的有限历史快照。

## 日志模式

设置页提供简易、详细、完全三个稳定预设，以及可逐项勾选的自定义模式。点击“内容...”可选择
运行进度、步骤结果、流程分支、动作、识别、坐标、参数、耗时、底层后端、画面唤醒/缩放记忆、
界面事件和本地时间；修改任一项目会自动进入自定义，菜单底部可恢复三个预设。错误、急停和
严重警告始终输出，不能被自定义选项关闭。自定义选择会随方案、普通导出和全量导出保存。

## 原生识别核心

```powershell
powershell -ExecutionPolicy Bypass -File native_core\build_native_core.ps1
```

输出为 `fukua_rpa_core.dll`。DLL 加载失败或某次识别无法安全完成时，执行引擎会
自动回退到 OpenCV/Python 路径。API 11200 使用整次调用共享的有界任务池，并支持“快速一个”按
手动优先倍率和本次启动期间学习到的多个常用倍率依次检查，全部未命中后仍在同一截图上完整回退；
画面变化唤醒使用 DXGI 通知和分块指纹确认，常用倍率专搜失败后仍进入完整范围。DLL 同时报告
稳定能力位、ABI/构建信息和返回码。学习记录不写入磁盘，设置中的自动策略只影响算法
选择历史容量和优先倍率数量的倾向，也可由熟悉行为的用户显式自定义上限。连续普通失败三次后
只在本次脚本运行停用 DLL，下次运行会重新尝试。
OpenCV 在所有路径中统一使用最多 2 个工作线程，避免高核心数处理器为单次匹配创建过多工作线程。

## 应用图标

图标源文件为 `assets/fukuaRPA.svg`。修改源文件后运行：

```powershell
python scripts\build_icon.py
```

脚本会生成预览 PNG 和包含 16-256 像素图层的 Windows ICO。程序窗口、任务栏和
PyInstaller EXE 共用这份 ICO。

## 完整版构建

```powershell
# 默认只构建推荐的完整多文件版
python scripts\build_release.py

# 只有明确需要时才构建单文件版或两种格式
python scripts\build_release.py --format onefile
python scripts\build_release.py --format all
```

多文件目录名固定为 `fukuaRPA_v1.0.11`，单文件名固定为
`fukuaRPA_v1.0.11_single.exe`。两者来自同一套完整版源码、功能和质量门，项目不再包含或生成精简版。
多文件版启动更快、发布物料和程序文件可逐项校验，作为推荐版本；单文件版便于携带，但首次启动和
每次冷启动需要解压内置运行库，因此更慢，也更容易触发杀毒软件的启发式检查。
同一解压目录只能运行一个实例；如需并行运行互不影响的配置，可以复制到不同目录。
发布目录包含 `BUILD_INFO.json` 和 `RUNTIME_CLOSURE.json`，记录源码指纹、依赖、DLL API、
构建边界以及全部 EXE/DLL/PYD 的 AMD64 与包内依赖闭包；相邻目录会生成
便携 ZIP、逐文件目录清单和二者的 `SHA256SUMS`。目录内同时包含 CycloneDX SBOM、第三方声明、许可证汇总、真实签名状态
和可由设置页后台执行的包内完整性清单。当前构建没有作者代码签名证书，因此明确保持未签名，
不会用测试证书伪装签名；内部哈希校验也不冒充作者身份认证。
单文件版同样内置 Python、Qt、OpenCV、UI Automation 辅助 DLL 和原生识别 DLL，不要求新电脑安装
Python 或 VC++ 运行库；构建门会直接从冻结 EXE 运行环境自检、UIA 与原生/OpenCV 对照烟雾测试。
