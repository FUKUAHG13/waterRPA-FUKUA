# ADR 0022：冻结运行载荷采用验证驱动删减

## 状态

已接受，2026-07-13。

## 背景

标准 PyInstaller 钩子会保守收集 OpenCV 视频后端、Qt 可选插件、Pillow 可选扩展及
PyAutoGUI 间接依赖。fukuaRPA 不调用其中多数功能，但直接从现有目录删除文件无法证明
模块图仍然成立，尤其 `mouseinfo`、`pymsgbox` 与 Tcl/Tk 存在间接导入关系。

## 决策

- onedir 与 onefile 共同使用 `scripts/runtime_pruning.py`，分析阶段排除未使用的纯 Python
  辅助模块，Analysis 完成后再按目标路径过滤二进制和数据文件。
- 删除 OpenCV FFmpeg、Qt Quick/QML/PDF/虚拟键盘链、Pillow AVIF/WebP/CMS/Tk/数学及
  FreeType 可选扩展、Tcl/Tk 和非中文 Qt 翻译。
- 保留 `PIL.ImageFont` 纯 Python 模块，因为 PyScreeze 的截图导入链需要它；仅删除其
  可选 `_imagingft` 扩展。
- 明确保留 Qt Core/Gui/Widgets、`qwindows`、`qoffscreen`、`qjpeg` 与 `opengl32sw`。
- 正式 onedir 校验必须拒绝删减载荷重新出现，避免依赖升级或 PyInstaller 钩子变化造成
  静默体积回退。

## 验证

实验冻结构建通过启动、22 项离线自检、PyAutoGUI 坐标/屏幕/1×1 截图、真实 UIA 控件、
原生/OpenCV 对照识别及全部 PE 依赖闭包检查。`_internal` 从 257.29 MiB 降至
186.76 MiB，净减 70.52 MiB；该实验目录不属于正式发布物。

## 后果

完整版功能源码保持一套，单文件与多文件只在封装形式上不同。未来启用视频、Qt PDF、
WebP/AVIF、Tk 弹窗或字体渲染前，必须先修改删减策略并补充冻结态功能烟雾，不能只恢复
单个 DLL。
