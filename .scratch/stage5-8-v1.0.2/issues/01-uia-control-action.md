# UI Automation 控件动作

## Status

Completed

## Comments

- UIA COM 对象集中在一个可停止工作线程，节点、深度、树遍历时间和调用等待均有上限。
- 真实 Win32 Button 已验证 Invoke 成功，调用前后前台窗口未改变。
- 单击失败回退 PostMessage；双击和右键继续使用原有消息语义。

## Acceptance

- 左键单击优先尝试 UIA Invoke/Selection/Toggle/DefaultAction。
- UIA 不可用或失败时回退 PostMessage，绝不移动真实鼠标。
- 检查器显示控件类型、框架、动作、扫描数量和失败说明。
- 工作线程可停止，枚举和等待均有明确上限。
- 真实 Win32 按钮烟雾测试验证后台 Invoke 不改变前台窗口。
