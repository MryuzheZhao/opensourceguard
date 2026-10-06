# 依赖与许可证合规报告

- 仓库：`C:\Users\Administrator\Documents\Codex\2026-09-20\wo\outputs\opensourceguard\examples\polyglot_demo`
- 项目许可证：**MIT**（来源 package.json，置信度 medium）
- 依赖清单：requirements.txt, package.json
- 依赖数量：6（已解析许可证 6，未知 0）
- 问题统计：高 0 · 中 3 · 低 4

## 发现的问题

### [中] paramiko
- 类型：license
- 识别到的许可证：LGPL-2.1
- 说明：依赖为 LGPL-2.1（弱 Copyleft）。动态链接通常可接受，但静态链接或修改其源码后，需要按 LGPL-2.1 的条款开放相应部分。
- 建议：保持动态依赖、不修改其源码；如需修改请单独开源该部分。
- 来源：requirements.txt

### [中] left-pad
- 类型：dependency
- 识别到的许可证：WTFPL
- 说明：该包曾因从 npm 撤回导致大规模构建失败，功能可用 String.prototype.padStart 替代。
- 建议：评估是否可以移除或替换该依赖，并锁定版本。
- 来源：package.json

### [中] .gitignore
- 类型：file
- 说明：缺少 .gitignore，容易误提交虚拟环境、缓存或凭据。
- 建议：添加 .gitignore，至少排除 .env、虚拟环境和构建产物。
- 来源：repository root

### [低] left-pad
- 类型：license
- 识别到的许可证：WTFPL
- 说明：依赖使用 WTFPL，部分企业合规流程不接受该许可。
- 建议：若面向企业用户分发，建议替换为 MIT/Apache-2.0 等主流许可。
- 来源：package.json

### [低] CONTRIBUTING.md
- 类型：file
- 说明：缺少贡献指南，新贡献者不知道如何参与。
- 建议：添加 CONTRIBUTING.md，说明开发环境、提交规范和评审流程。
- 来源：repository root

### [低] CODE_OF_CONDUCT.md
- 类型：file
- 说明：缺少行为准则，社区协作缺少共同约定。
- 建议：可直接采用 Contributor Covenant。
- 来源：repository root

### [低] SECURITY.md
- 类型：file
- 说明：缺少安全披露政策，漏洞报告没有明确渠道。
- 建议：添加 SECURITY.md，说明私下报告渠道和响应时限。
- 来源：repository root

## 依赖清单

| 名称 | 版本 | 生态 | 范围 | 许可证 |
|---|---|---|---|---|
| requests | ==2.31.0 | pypi | runtime | Apache-2.0 |
| pyyaml | ==6.0.1 | pypi | runtime | MIT |
| paramiko | ==3.4.0 | pypi | runtime | LGPL-2.1 |
| lodash | ^4.17.21 | npm | runtime | MIT |
| left-pad | ^1.3.0 | npm | runtime | WTFPL |
| jest | ^29.7.0 | npm | dev | MIT |

## 边界说明

- 本审计基于清单声明与内置对照表，属于快速初筛，不构成法律意见。
