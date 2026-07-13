# fukuaRPA 运行库体积审计

审计基线：`fukuaRPA_v1.0.9` 完整版多文件包。便携 ZIP 为 108.35 MiB，解压目录为
264.77 MiB；其中 `_internal` 为 257.29 MiB。候选已在隔离的 v1.0.10 onedir 冻结构建中
逐组及累计验证，正式 `dist` 未在本轮更新。

## 已验证删减项

| 项目 | 原始体积 | 预计 ZIP 体积 | 处理方式 | 验证结果 |
|---|---:|---:|---|---|
| OpenCV FFmpeg | 27.25 MiB | 11.60 MiB | 过滤 `opencv_videoio_ffmpeg*.dll` | 通过 OpenCV 导入、启动和原生/OpenCV 对照烟雾 |
| Qt Quick/QML/PDF/虚拟键盘链 | 19.36 MiB | 8.55 MiB | 按闭包过滤 8 个 Qt DLL 与 2 个插件入口 | 通过启动、主界面、UIA、原生识别烟雾 |
| Pillow 可选扩展 | 10.28 MiB | 5.52 MiB | 排除未使用插件并过滤 6 个扩展；保留 PyScreeze 导入所需的纯 Python `ImageFont` | 通过 1×1 截图后端与原生识别烟雾 |
| Tcl/Tk | 7.43 MiB | 2.73 MiB | 分析阶段排除 `mouseinfo`、`pymsgbox`、`tkinter`，再过滤 Tk 载荷 | 通过坐标、屏幕尺寸、截图和完整启动烟雾 |
| 非中文 Qt 翻译 | 6.07 MiB | 1.72 MiB | 仅保留简体/繁体中文 6 个 `.qm` 文件 | 通过启动、窗口和标准控件烟雾 |

实验构建 `_internal` 为 186.76 MiB，较基线净减 70.52 MiB（27.4%），与理论值一致；
整个未附发布材料的实验目录为 193.22 MiB。未生成 ZIP，因此 30.12 MiB 仍是根据旧包
逐项压缩结果得到的估算值，不作为正式包承诺。

累计构建通过首帧/运行后端启动时序、22 项离线自检、PyAutoGUI 输入和 1×1 截图、真实
UIA 控件绑定、原生/OpenCV 对照识别，以及 132 个 PE、819 条导入引用的闭包检查；没有
缺失依赖、错误架构或 PE 解析错误。`scripts/verify_release.py` 会拒绝这些载荷重新出现。

## 第二批中风险候选

- `opengl32sw.dll`：19.68 MiB。QWidget 界面通常不主动使用软件 OpenGL，但它是显卡驱动异常、
  虚拟机和远程桌面的兼容回退，不能仅凭本机启动成功删除。
- Qt 平台插件：`qwindows.dll` 必须保留，`qoffscreen.dll` 被冻结发布测试使用；
  `qdirect2d.dll`、`qminimal.dll` 是否保留需要真实 Win10、远程桌面和无硬件加速环境验证。
- Qt 图片插件：`qjpeg`、`qico` 与当前 JPG/图标路径有关；GIF、TIFF、TGA、WBMP、ICNS 等
  可继续审计，但总收益较小。
- `_ssl.pyd` 与 `libssl-3.dll`：约 0.94 MiB。程序不主动联网，但依赖导入和未来功能可能使用；
  `libcrypto-3.dll` 被 `_hashlib` 和完整性校验依赖，不应列入同一删除项。

## 高收益高成本项

- `cv2.pyd`：71.35 MiB。标准 OpenCV 包包含 dnn、calib3d、features2d、stitching、video 等
  未使用模块；只有定制 OpenCV 构建或进一步扩大原生核心职责才能明显缩小。
- NumPy OpenBLAS：19.47 MiB，被 NumPy 核心扩展直接链接，不能从现有 wheel 中单独删除。
  需要定制 NumPy 或移除 Python/OpenCV 回退，后者违反当前可选 DLL 回退约束。

## 不应优先处理

- CPython、QtCore/QtGui/QtWidgets、`qwindows.dll`：便携运行与主 GUI 的基础。
- `fukua_rpa_core.dll`：仅 0.29 MiB，却承载原生截图、多区域、多倍率和多核识别。
- MSS、psutil、UIAutomation、comtypes、pyperclip：总体体积很小，并分别承载快速截图、
  资源监测/窗口诊断、后台控件动作和文本输入。
