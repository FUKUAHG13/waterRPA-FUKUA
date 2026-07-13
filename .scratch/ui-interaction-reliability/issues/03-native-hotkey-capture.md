# 原生热键录入

## Status

Completed

## Work

- 使用 WH_KEYBOARD_LL 捕获 WM_KEYDOWN 与 WM_SYSKEYDOWN。
- 从 Hook 维护的按下键集合生成组合，避免 Qt 焦点和菜单键影响。
- 正确停止 Hook 并增加组合键回归测试。

## Comments

- 2026-07-11：旧弹窗只实现 keyPressEvent，Alt/Ctrl 组合可能被 Qt/Windows 快捷键分发提前处理。
- 2026-07-11：源码 Hook 联调通过 Ctrl+A、Alt+A、Ctrl+Shift+A、Ctrl+Alt+A、Ctrl+Shift+Alt+A；打包版实测 Ctrl+Alt+Shift+A 一次录入成功。
