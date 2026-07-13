# fukuaRPA 领域上下文

## 仓库与发布边界

- 公开仓库为 `https://github.com/FUKUAHG13/waterRPA-fukuaRPA`。
- `main` 可以公开仍在真实场景测试的模块化 fukuaRPA 源码，方便熟悉 Python 的用户提前查看和自行构建；这不自动等同于正式二进制发布。
- GitHub Releases 保存经过明确发布流程验证的安装包。重构前 waterRPA 的最终源码位于 `waterRPA/`，对应历史标签继续固定在其归档提交。
- 日常开发分支不得因为公开 `main` 而自动获得上游；新改动必须在测试完成并得到明确发布指令后再同步。

## 核心术语

- **方案（Profile）**：一组全局设置、按键映射和步骤的可保存配置。
- **步骤（Task/Step）**：由稳定浮点编号标识的单个自动化命令；编号与名称统一定义在 `commands.py`。
- **运行请求（RunRequest）**：启动瞬间从界面数据深拷贝得到的不可变运行快照。
- **运行生命周期（RunLifecycle）**：管理唯一 `run_id`、准备/运行/停止状态和停止事件的线程安全对象。
- **原子备份（Atomic Backup）**：更新 `QSettings` 前完整替换的 `profiles_backup.json`。
- **历史备份（Profile History）**：原子备份被替换前保存的有限数量只读快照。
- **识别回退（Vision Fallback）**：原生 DLL 无法安全完成时改用 Python/OpenCV；原生成功但无结果时不回退。
- **物理坐标（Physical Coordinate）**：Windows 虚拟桌面像素坐标，可包含副屏负坐标。
- **Qt 坐标（Qt Coordinate）**：仅用于界面与覆盖层绘制的逻辑坐标。
- **显式窗口绑定（Explicit Window Binding）**：用户单击目标程序得到的窗口身份，与映射点击坐标分开保存和验证。
- **Hook 键状态（Hook Key State）**：由低级键盘 Hook 的按下/抬起事件维护的修饰键集合，不依赖异步状态读取时序。
- **全量包（Full Package）**：包含方案、图片资产、清单和完整性哈希的可移植 ZIP。
- **性能快照（Performance Snapshot）**：每项最多保留 256 个耗时样本的 P50/P95、计数器和缓存统计。
- **运行轨迹（Run Trace）**：最多 2000 项、不记录步骤值或路径的步骤结果与跳转序列。
- **窗口检查器（Window Inspector）**：读取已绑定根窗口、目标控件、子控件和完整性级别的诊断视图。
- **UIA 控件动作（UIA Control Action）**：在专用 COM 线程中对坐标处标准控件执行 Invoke/Selection/Toggle/DefaultAction。
- **调试会话（Debug Session）**：协调步骤前断点、暂停、继续、单步和停止唤醒的线程安全状态。
- **条件断点（Conditional Breakpoint）**：仅当安全表达式为真时在步骤执行前暂停的断点；求值错误也暂停并解释原因。
- **运行变量（Runtime Variable）**：仅在一次脚本运行内存在、由受限表达式读写的值。
- **发布物料（Release Materials）**：构建记录、SBOM、许可证、签名状态、PE 依赖闭包、包内哈希和包外清单的集合。
- **运行时闭包（Runtime Closure）**：发行目录中全部 EXE/DLL/PYD 的 AMD64 架构及非系统导入均可在包内解析的状态。
- **原生能力掩码（Native Capability Mask）**：DLL API 11200 声明截图、匹配、缓存、计时、ABI、有界任务池、指定倍率专搜和画面变化监听能力的稳定位集合。
- **原生任务池（Native Match Job Pool）**：一次 DLL 调用内统一调度缩放档位、区域和结果行块的最多 8 线程工作队列，不绑定具体 CPU 核心。
- **缩放记忆（Scale Memory）**：快速一个模式在本次进程内按频率、近期程度和质量学习多个常用倍率；手动项排在学习项之前，失败后继续完整范围。
- **画面变化唤醒（Scene Wake）**：只在自适应额外等待中用 DXGI 通知加分块指纹确认变化，确认后尝试常用倍率专搜，未命中仍立即完整搜索。
- **启动阶段（Startup Stage）**：轻量首帧、完整工作区可见、运行后端就绪三个可独立计时和验证的启动节点。
- **原生 ABI 契约（Native ABI Contract）**：DLL 与 Python 对指针位数、结构体大小和构建标志的机器可验证约定。
- **便携发行归档（Portable Release Archive）**：以构建目录为唯一根、按外部清单逐成员复核的完整 onedir ZIP。
- **双构建边界（Dual Package Boundary）**：同一套完整版源码分别生成 onedir 与 onefile；两种构建共享功能、版本和发行态烟雾测试。
- **OpenCV 线程预算（OpenCV Thread Budget）**：进程级最多 2 个 OpenCV 工作线程，与识别频率等待相互独立。
- **日志策略（Log Policy）**：简易/详细/完全预设或用户自定义类别组成的运行快照；在异步入队前过滤，严重错误与急停始终输出。

## 关系

```text
Profile -> RunRequest -> EngineRunConfig + detached Tasks
Tasks -> RunController -> WorkerThread -> RPAEngine -> action/vision mixins
Profile -> atomic backup -> QSettings -> bounded history
MainWindow -> ProfileCollection / PreviewModel / WindowMappingBackend
Engine -> PerformanceMetrics / RunTrace
Engine -> LogPolicy -> LoggingService / LogTelemetry
Engine -> DebugSession / SafeExpression / ScaleMemoryStore / SceneWake / NativeVisionCore
WindowMappingBackend -> WindowInspector / UIAutomationBackend / PostMessage
ReleaseBuilder -> RuntimeClosure / BuildRecord / SBOM / PayloadHashes / ExternalManifest -> PortableArchive / SHA256SUMS
```

## 兼容承诺

- 只发布 Windows 10 1809+ x64 和 Windows 11 x64 完整版；同时维护多文件版和单文件版，精简版停更。
- 同一产品主版本内继续读取并向前迁移旧方案；跨主版本不承诺无限兼容，结构性破坏必须通过大版本边界发布。
- 不受支持的方案明确拒绝并进入只读保护，不能半加载或覆盖原配置；当前 v1 仍读取已有 `waterRPA` 配置、全量包和剪贴板键。
- 原生 DLL 始终是可选加速层，Python/OpenCV 回退不可删除。
