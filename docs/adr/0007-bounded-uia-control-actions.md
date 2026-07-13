# ADR 0007：有界 UI Automation 控件动作

- 状态：已接受
- 日期：2026-07-12

## 决策

标准控件的单次左键后台操作优先尝试 UI Automation 的 Invoke、Selection、Toggle 或
Legacy DefaultAction，再回退到既有 `PostMessage`。所有 COM 对象只存在于专用工作线程，
树遍历设置节点、深度、时间和请求队列上限，跨线程只传递普通值与同步令牌。

UIA 超时后会取消尚未开始的动作；若动作结果未知，则报告失败并禁止再发 `PostMessage`，
避免一次用户操作被目标程序执行两遍。任何失败都不得回退真实鼠标。

## 原因

`PostMessage` 对标准 Win32 控件以外的程序并不可靠，而 UI Automation 可以调用控件语义，
且无需抢占前台。COM 调用也可能阻塞或延迟完成，因此必须有界并处理超时后的重复动作风险。

## 后果

游戏、浏览器画布、DirectX、自绘控件和更高权限窗口仍可能不兼容。发布门必须运行真实
Win32 Button 的后台 Invoke 烟雾测试，并确认调用前后前台窗口句柄不变。
