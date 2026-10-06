# OpenSourceGuard 评测基准报告

- 运行时间：2026-09-28T19:02:48+08:00
- 执行模式：`local`
- Python：3.12.6（Windows-11-10.0.26200-SP0）
- 用例数量：8
- 总耗时：0.516 秒

## 核心指标

| 指标 | 数值 | 说明 |
|---|---|---|
| Top-1 定位准确率 | 100% | 首条证据文件与标注一致 |
| Top-3 定位准确率 | 100% | 标注文件出现在前 3 条证据 |
| 符号级准确率 | 80% | 首条证据的函数/方法名与标注一致 |
| 安全规则召回率 | 100% | 6/6 条预期规则命中 |
| Issue 分类准确率 | 88% | bug / security / feature 判定 |
| 干净仓库误报数 | 0 | 负对照组上的中/高风险误报 |
| 补丁生成率 | 100% | 标注可修复的用例中产出候选补丁 |
| 补丁验证通过率 | 100% | 复现测试与全量测试同时通过 |

## 分语言表现

| 语言 | 用例数 | Top-1 定位 |
|---|---|---|
| java | 1 | 100% |
| javascript | 1 | 100% |
| python | 6 | 100% |

## 分类表现

| 类别 | 用例数 | Top-1 定位 |
|---|---|---|
| bug | 3 | 100% |
| negative | 1 | 100% |
| security | 4 | 100% |

## 逐用例明细

| 用例 | 语言 | 定位 | 符号 | 命中规则 | 验证状态 | 耗时(s) |
|---|---|---|---|---|---|---|
| csv-empty-crash | python | ✅ | ✅ | — | verified | 0.14 |
| pagination-off-by-one | python | ✅ | ✅ | — | no_patch | 0.051 |
| shell-injection | python | ✅ | — | PY-SHELL, PY-SECRET | no_patch | 0.052 |
| sql-injection | python | ✅ | ❌ | PY-SQL-FORMAT | no_patch | 0.054 |
| unsafe-deserialize | python | ✅ | — | PY-PICKLE, PY-MD5 | no_patch | 0.056 |
| polyglot-js-crash | javascript | ✅ | ✅ | — | infrastructure_error | 0.052 |
| polyglot-java-sql | java | ✅ | ✅ | JAVA-SQL-CONCAT | infrastructure_error | 0.052 |
| clean-negative-control | python | ✅ | — | — | no_patch | 0.059 |

## 未达预期的用例

全部用例均满足标注预期。

## 边界说明

- 本基准使用 `examples/` 下的自建标注用例，衡量的是本工具在这些用例上的表现，不能与 SWE-bench 等公开基准直接比较。
- 非 Python 语言使用启发式符号定位，证据位置可能存在偏移。
- 未配置模型 API 时全部走本地规则；配置模型后指标会随模型能力变化。
- `--execute skip`（默认）不运行仓库代码，因此补丁验证通过率为 0；需要验证请使用 `--execute local` 或 `--execute docker`。
