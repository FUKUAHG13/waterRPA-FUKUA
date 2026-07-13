# fukuaRPA v1.0.12 架构说明

## 设计边界

`fukuaRPA.py` 是薄启动入口。业务实现全部位于 `fukua_rpa` 包内，模块依赖方向为：

```text
入口 -> 轻量启动窗 -> 主窗口 -> UI 组件 / 控制器 -> Worker -> 执行引擎
                           -> 方案 / 预览 / 映射 / 全量包服务
执行引擎 -> 调度核心 -> 截图匹配 / 条件 / 坐标路径 / 动作 mixin
```

底层模块不得反向导入主窗口或入口文件。执行引擎不得直接读写 Qt 控件，只能使用
回调向 `WorkerThread` 报告日志、状态和点击位置。

## 目录职责

```text
fukuaRPA.py                    # DPI 初始化、离线烟雾入口、轻量首帧与异步工作区启动
fukuaRPA_onedir.spec           # 完整多文件构建
fukuaRPA_onefile.spec          # 同源完整单文件构建
assets/
  fukuaRPA.svg                 # 可编辑的应用图标源文件
  fukuaRPA.ico                 # 窗口、任务栏和 EXE 使用的多尺寸图标
  version_info.txt             # 多文件 EXE 产品与版本资源
  version_info_onefile.txt     # 单文件 EXE 产品与版本资源
scripts/
  audit_runtime_closure.py     # 全部 PE 的 x64 架构与包内依赖闭包审计
  build_icon.py                # 从 SVG 重建 PNG/ICO
  build_release.py             # 原生核心、双格式冻结包与质量门的一键发布
  runtime_pruning.py           # onedir/onefile 共用的已验证可选运行载荷过滤与回归检查
  create_build_record.py       # 运行源码、测试、公开文档、资产、依赖与构建环境指纹
  create_sbom.py               # CycloneDX SBOM、第三方声明和许可证汇总
  create_release_info.py       # 发布哈希与真实 Authenticode 状态
  create_release_readme.py     # 最终用户解压、离线与未签名边界说明
  create_payload_hashes.py     # 发布包内部完整性清单与离线核验
  create_release_manifest.py   # 发布目录外部逐文件 SHA-256 清单
  create_release_archive.py    # 流式创建并逐成员复核便携 ZIP
  create_release_checksums.py  # ZIP 与外部清单的 SHA256SUMS
  verify_release.py            # 源码检查与构建产物离线冒烟
  benchmark_core.py            # 5000 步纯逻辑性能基线
  benchmark_vision.py          # 1080p/2K/4K 与原生识别基准
  compare_performance.py       # 10 轮报告与相对性能基线比较
  smoke_native_vision.py       # 真实屏幕正向模板匹配烟雾测试
  smoke_uia_control.py         # 不抢前台的真实 Win32 控件 Invoke 烟雾测试
  smoke_startup.py             # 源码/冻结 EXE 的分阶段启动时序与耗时烟雾
  soak_runtime.py              # 生命周期、内存和模拟引擎耐久测试
fukua_rpa/
  constants.py                # 产品名称、兼容范围、资源上限和格式标识
  commands.py                 # 步骤编号、名称和能力的唯一注册表
  paths.py                    # 安装资源目录与可写用户数据目录选择
  config_schema.py            # 默认方案、数据版本和向前迁移
  config_store.py             # 签名、原子保存、历史备份和损坏恢复
  profile_model.py            # 与 Qt 无关的有序方案集合
  profile_package.py          # 带资产哈希的全量包导入导出
  workflow_document.py        # 稳定步骤 ID、跳转引用和复制/删除修复
  recording_model.py          # 双击、滚轮、组合键和拖拽录制语义归并
  preview_model.py            # 坐标预览点和连线的纯计算
  run_config.py               # 严格校验的运行设置与运行快照
  runtime_state.py            # 线程安全运行编号、状态和停止事件
  runtime_trace.py            # 不含脚本内容的有界运行轨迹
  debug_session.py            # 条件变量驱动的断点、暂停、继续与单步协调
  opencv_runtime.py           # 进程级 OpenCV 线程预算
  pyautogui_runtime.py        # 首次鼠标/键盘动作时才导入 PyAutoGUI
  performance.py              # 有界计时、P50/P95、计数器与摘要
  scale_memory.py             # 会话内有界多倍率学习、手动优先项与动态容量
  scene_wake.py               # 分块灰度画面指纹、灵敏度与变化评分
  scheduler.py                # 可测试的循环调度纯函数
  validation.py               # 与 UI 无关的步骤和资源预算验证
  workflow_analysis.py        # 流程图、不可达步骤和循环风险分析
  expressions.py             # 不执行 Python 代码的 AST 白名单表达式
  credentials.py             # 当前 Windows 用户 DPAPI 加密凭据库
  text_input.py              # 不占用剪贴板的 Win32 Unicode 文本输入
  window_actions.py          # 有界窗口启动、等待、激活和关闭动作
  mapping_backend.py          # Win32 显式目标窗口绑定、解析和后台点击
  uia_backend.py              # 专用 COM 线程中的有界 UI Automation 控件动作
  uia_smoke.py                # 源码与冻结 EXE 共用的真实控件自检
  native_smoke.py             # 源码与冻结 EXE 共用的原生/OpenCV 对照自检
  window_diagnostics.py       # 目标控件枚举、权限与兼容性诊断
  diagnostics.py              # 源码/打包环境离线自检
  integrity.py                # 包内哈希清单的路径安全与流式核验
  task_model.py               # 步骤字段解析、坐标序列和路径计算
  win32_api.py                # 热键、Hook、窗口与 64 位 Win32 声明
  coordinates.py              # Qt 逻辑坐标和物理桌面坐标转换
  vision.py                   # 模板安全检查、缓存估算和可选 DLL
  engine.py                   # 生命周期、循环和跳转调度
  engine_vision.py            # 截图、缓存、模板匹配和多目标查找
  engine_conditions.py        # “直到条件成立”的图像与区域条件
  engine_coordinates.py       # 坐标序列和步进运行状态
  engine_expressions.py       # 单次运行变量与表达式上下文
  engine_actions.py           # 鼠标、键盘、拖拽、截图与单步动作
  worker.py                   # 执行线程桥接和急停看门狗
  logging_service.py          # 异步日志和未捕获异常记录
  log_policy.py               # 日志预设、分类、自定义过滤和强制错误策略
  log_telemetry.py            # 完全日志的参数、阶段耗时与安全格式化
  ui/
    components.py             # 通用/响应式设置组件与步骤设置窗口
    input_tools.py            # 区域/坐标/窗口选择、原生热键捕获和操作录制
    overlays.py               # 预览、运行状态和点击位置覆盖层
    startup.py                # 首次绘制后才触发完整工作区导入的轻量启动窗口
    integrity_worker.py       # 不阻塞设置页的发布包完整性校验线程
    task_row.py               # 步骤行与拖放列表
    theme.py                  # 无额外依赖的统一主题和控件语义样式
    controllers/run_controller.py # Worker 与 run_id 配对
    main_window.py            # 界面组装、方案编排和用户反馈
native_core/
  fukua_rpa_core.cpp
  build_native_core.ps1
tests/
  test_core_regressions.py
  test_module_boundaries.py
  test_ui_modernization.py
  test_stability_foundation.py
  test_profile_package.py
  test_preview_and_mapping_models.py
  test_scale_memory.py
  test_startup_architecture.py
```

## 不可破坏的约束

1. `NativeVisionCore` 返回 `None` 表示原生调用失败，需要回退；返回空列表表示搜索
   成功但未命中，不得再次重复 OpenCV 搜索。
2. 每次运行先 `reserve_run()`，并由相同 `run_id` 在 `finally` 中 `finish_run()`；
   `stop()` 只设置停止请求。
3. 配置和脚本坐标使用 Windows 虚拟桌面的物理像素；覆盖层负责转换为 Qt 坐标。
4. 配置先写原子 JSON 备份，再更新 `QSettings`；导入内容必须通过结构和资源上限校验。
5. 新配置字段必须同步默认值、步骤行序列化、运行前验证、执行引擎和全量导出路径重写。
6. 新格式写入 `fukuaRPA` 标识，但继续读取旧 `waterRPA` 备份、全量包和剪贴板键。
7. UI 颜色和控件状态优先通过 `theme.py` 与动态属性表达；不要在业务代码中散落临时
   `setStyleSheet()`，也不要用主题覆盖用户选择的界面倍率。
8. 后台映射的点击坐标和目标窗口必须分开采集。目标窗口只能由用户显式点选，并在已有
   目标根窗口时直接从该根窗口解析控件；不得用点击坐标处的最上层窗口覆盖已保存目标，
   失败时也不得回退真实鼠标点击。
9. `assets/fukuaRPA.svg` 是图标唯一源文件；修改后必须运行 `scripts/build_icon.py`，
   并同时验证运行时 `QIcon` 和 PyInstaller 的 `icon`/`datas` 配置。
10. 配置版本与 `APP_VERSION` 无关；未来版本方案必须拒绝读取，未知字段不得在迁移时丢弃。
11. 主配置与原子备份通过相同签名握手；备份领先时表示上次写入未完成，应采用备份。
12. Worker 只能通过 `RunController` 启动；运行参数只从 `RunRequest` 快照读取。
13. `commands.py` 是步骤编号和名称的唯一来源，持久编号不得重排或复用。
14. 全量包 v3 的资产必须通过大小和 SHA-256 校验；旧 v2 包继续兼容读取。
15. PyInstaller 的 onedir 与 onefile 构建都关闭 UPX，并必须通过 `--self-test-file`、
    `--uia-smoke-file`、`--native-smoke-file` 和 `--startup-smoke-file` 四类发行态冒烟。
    `uiautomation` 的 x64 位图辅助 DLL 必须显式收集；UI Automation COM 核心由受支持 Windows 自带。
16. 同一便携目录只允许一个主程序实例，避免多个进程同时写配置；互不相同的解压目录可独立运行。
17. 发布目录生成逐文件 SHA-256 清单；没有作者证书时保持未签名，不得使用测试证书冒充发布者。
18. 组合键录入由低级键盘 Hook 自己维护按下键集合，同时处理普通键与系统键消息；不要在
    Hook 回调中只依赖 `GetAsyncKeyState` 推断 Ctrl/Alt/Shift 状态。
19. 性能计时和运行轨迹必须有固定内存上限；诊断导出不得包含步骤值、图片路径、文本输入
    或按键映射坐标。
20. DLL API 10700+ 将屏幕捕获和积分图放在缩放循环外；同一调用每个区域只能捕获一次，
    并通过稳定能力位声明可用功能。API 10800 将缩放、区域和行块交给整次调用共享的有界任务池。
    API 10900 可按顺序接收多个优先倍率；API 11000 增加指定倍率专搜；API 11200 增加
    低分辨率指纹和 DXGI 变化通知。专搜未命中后，调度层仍必须执行完整范围搜索。
    工作预算返回固定 `-2`，必须在截图前回退并缓存本次运行的拒绝。
21. 窗口检查器只做读取和兼容性判断，不自动提权；目标权限更高或自绘画布时必须明确警告。
22. 正式发布由 `scripts/build_release.py` 编排，目录内必须有 `BUILD_INFO.json`，目录外必须有
    逐文件 SHA-256 清单；无作者证书时继续明确标记为未签名。
23. UIA COM 对象不得跨线程传递；树遍历和请求必须有界。动作超时且结果未知时不得再发送
    `PostMessage`，避免目标收到重复操作。
24. 断点发生在步骤执行前，停止必须唤醒暂停线程；暂停时长不计入全局运行时限。调试变量值
    只允许进入当前 UI，不得写入轨迹、日志或诊断。
25. 表达式只允许通过 `expressions.py` 的 AST 白名单解释，禁止 `eval`/`exec`、调用、属性、
    下标、导入及文件/网络访问；自定义变量只存在于一次运行。
26. 包内完整性清单不等于作者签名。清单外普通配置可警告，但任何清单外可执行代码必须失败；
    包外清单必须在全部发布物料生成后创建并独立复核。
27. 原生普通失败连续三次后仅在本次运行熔断；成功和权威空结果清零连续计数，下一次运行重新探测。
28. OpenCV 线程数由 `opencv_runtime.py` 统一限制为最多 2 个；引擎、诊断、基准和原生对照烟雾
    必须走同一配置入口，不得在其他模块临时改回逻辑核心数。
29. UIA 候选首先匹配用户绑定的目标 HWND；否则按层级深度、控件面积和动作能力排序。离屏控件
    不得成为点击目标，超时结果未知时仍禁止 PostMessage 二次发送。
30. 条件断点只通过安全表达式求值并发生在步骤执行前。求值错误必须暂停并显示有界详情，不能
    静默跳过；断点条件引用的变量必须进入确定赋值分析。
31. 便携 ZIP 必须由最终发布目录流式生成，并针对外部逐文件清单复核路径、数量、大小、SHA-256
    和 CRC；ZIP 与目录清单的外部 SHA256SUMS 必须在归档后生成并再次验证。
32. API 10700 及以上 DLL 必须公开指针位数、结构体大小和构建标志。发布只接受 64 位、结构体
    完全一致、MSVC C++17、Windows 10 目标且 `/MT` 的 DLL，并检查 PE 导入表不存在动态 VC/UCRT。
33. 发布目录中所有 EXE/DLL/PYD 必须通过 AMD64 与依赖闭包审计；直接导入的 MSVC 运行库必须
    在包内找到，系统 DLL/API Set 可由 Windows 提供，无法解析或包外依赖会阻止发布。
34. 当前完整多文件版和完整单文件版来自同一套 `fukua_rpa` 源码。多文件版额外执行逐文件闭包、
    清单和 ZIP 复核；单文件版额外核对 x64 启动器、冻结资源解压、可写目录仍位于 EXE 旁，
    以及内置原生/UIA 组件的发行态烟雾。新的产品变体应明确记录差异，不应暗中改变同名产物。
35. `scripts/build_release.py` 当前默认生成 onedir，也可通过 `--format onefile` 或 `--format all`
    构建其他现有格式；三个入口共享版本身份、业务源码和相应的发行态验证。
36. 自动学习的缩放倍率只允许驻留当前进程内，不写入方案、备份或全量包。手动优先倍率属于用户
    配置；无论自动或手动优先项是否命中，快速一个都必须保留完整范围回退，全部匹配不得使用捷径。
37. GUI 启动首帧前不得导入完整主窗口、OpenCV、NumPy、PyAutoGUI 或 UI Automation。工作区类
    可在后台导入，但 QWidget 只能在主线程实例化；运行按钮在后端初始化完成前必须保持不可用。
38. 画面变化唤醒只允许缩短自适应降频的额外等待。DXGI 脏矩形必须再经分块指纹确认；指定倍率
    专搜命中可缓存到紧接着的正常识别，未命中必须立即保留完整搜索，全部匹配和同点上限不得走捷径。
39. 日志事件时间必须在生产者提交时捕获，由 `logging_service.py` 统一格式化；详细、完全以及
    启用时间项的自定义 UI 日志显示本地毫秒时间，文件日志始终带时间。命令模块不得再手工拼接
    时分秒。完整步骤日志同时保留易读阶段和全部计时增量；这些指标存在包含关系，不能相加解释为总耗时。
40. 主界面资源监测继续使用 Qt 定时器调用 psutil 的非阻塞采样，不为轻量采样额外创建线程。
    用户可选择 0.5/1/2/3/5 秒、跟随省电模式或关闭；显示系统整体与本进程占用，不得把 GUI
    线程瞬时所在的处理器编号描述成“逻辑核心占用”。
41. `log_policy.py` 是日志类别与三个预设的唯一来源。自定义模式必须在日志入队前过滤，错误、急停
    和严重警告不可关闭；未分类的旧调用按步骤结果处理。配置版本 2 保存模式和自定义项目，并由
    普通方案、原子备份及全量包原样携带。新增日志调用必须显式标注类别。
42. 方案兼容以产品主版本为边界。`MIN_SUPPORTED_PROFILE_SCHEMA_VERSION` 只能在大版本提高；
    原始签名必须先于迁移验证，迁移前保留旧备份。不受支持的方案进入只读保护，任何自动保存、
    退出保存或默认方案都不得覆盖其主配置和自动备份。
43. 界面倍率必须同时缩放字体、样式和控件内容宽度。无固定最大宽度的文字按钮以 100% 内容
    `sizeHint` 为基准，并在目标倍率按最终字体提示兜底；不得为单个被裁切的按钮堆叠倍率专用宽度。
    日志内容菜单允许连续勾选，只有点击外部、再次切换弹层或按 Esc 才关闭。
44. onedir 与 onefile 必须共同使用 `scripts/runtime_pruning.py`。载荷删减只接受源码调用审计、
    分析阶段排除、冻结 EXE 功能烟雾和 PE 依赖闭包共同证明；PyAutoGUI 自检必须实际读取输入
    后端并完成 1×1 截图，不能只检查模块导入。Qt 平台/JPEG 插件与 `opengl32sw.dll` 保留为
    Windows、远程桌面和异常显卡环境的兼容回退。
45. 步骤跳转的真实身份由 `step_id` 与 `*_target_id` 保存，界面步号仅是当前顺序的显示值。拖动、
    插入和复制不得把外部引用改成别的步骤；删除被引用步骤必须确认并明确清除引用。“直到条件”
    的引用字段只对指令 15 生效，普通步骤携带的默认字段不得产生隐藏跳转。
46. 普通文本与秘密文本不得写入日志、轨迹或诊断。秘密只允许以凭据名称进入方案，值由当前
    Windows 用户 DPAPI 加密到 `credentials.dat`；凭据文件不得进入普通或全量方案导出。文本
    输入优先使用 Unicode `SendInput`，不得为输入功能覆盖用户剪贴板。
47. 冻结程序目录可写时保持便携数据布局；不可写且没有 `portable.flag` 时使用
    `%LOCALAPPDATA%\\fukuaRPA`。`portable.flag` 表示用户明确要求数据留在程序目录，不得静默回退。
    只读资源继续通过 `_MEIPASS`/安装目录加载，不能误从用户数据目录寻找发布载荷。
48. 全量导出发现任何引用图片缺失时必须在替换目标文件前失败，不能生成标记为成功但换电脑无法
    运行的残缺包。发布性能门同时保留绝对上限和 `docs/PERFORMANCE_BASELINE.json` 相对基线；
    基线比较只在用户明确要求打包或完整发布验证时运行。

## 后续拆分

`ui/main_window.py` 仍是最大的模块，但方案模型、Win32 映射、预览计算、全量包和运行控制已经
独立。后续优先继续抽离 UI 构建器和热键控制器；不要为减少行数而把共享 Qt 状态搬进互相引用的 mixin。
