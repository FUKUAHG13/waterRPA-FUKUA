# 发布可信度与离线校验

## Status

Completed

## Comments

- 最终 onedir 包含 26 个依赖组件的 CycloneDX SBOM、第三方声明和约 500 KB 许可证汇总。
- 包内 1218 项哈希与包外 1219 项逐文件清单均通过独立复核，额外可执行文件会使校验失败。
- 冻结 EXE 的离线自检、原生 API 10600、x64 UIA 辅助 DLL和真实 UIA Invoke 全部通过。
- Authenticode 真实状态为 `NotSigned`；构建没有使用测试证书，也没有启动或自动更新联网。

## Acceptance

- 生成 CycloneDX SBOM、第三方声明和许可证文本。
- 记录 EXE/SBOM/构建记录哈希及真实 Authenticode 状态。
- 包内清单可由设置页后台校验，不阻塞 UI；清单外可执行文件视为失败。
- 外部逐文件清单支持独立 `--check`，篡改必须被发现。
- 明确内部哈希不等同数字签名，不添加启动联网。
