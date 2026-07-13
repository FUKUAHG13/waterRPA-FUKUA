# ADR 0002：运行生命周期与不可变快照

- 状态：已接受
- 日期：2026-07-11

## 决策

每次运行通过 `RunLifecycle.reserve()` 获得唯一编号，使用线程安全状态机管理准备、运行和停止。
主窗口在启动时生成 `RunRequest` 深拷贝，统一解析为 `EngineRunConfig`，再交给 `RunController`
创建 Worker。只有相同 `run_id` 可以结束该运行。

## 原因

界面编辑、重复热键、延迟停止和 Worker 异常可能发生并发。散落的布尔变量无法防止旧 Worker
结束新运行，重复解析设置也可能造成验证值和实际值不一致。

## 后果

不得绕过 `RunController` 从主窗口直接创建 Worker。停止是请求而不是强制终止；资源清理必须
位于 `finally`，并接受重复调用。
