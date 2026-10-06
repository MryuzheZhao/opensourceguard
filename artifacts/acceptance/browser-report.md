# OpenSourceGuard 修复报告

- 仓库：`C:\Users\Administrator\Documents\Codex\2026-09-20\wo\outputs\opensourceguard\examples\buggy_csv`
- 问题类型：bug
- 严重程度：high
- 验证状态：verified

## Issue 分析

读取空 CSV 文件时 parse_csv 崩溃，应该返回空列表

预期行为：返回空列表

实际行为：读取空 CSV 文件时 parse_csv 崩溃，

## 代码证据

- `parser.py:1-6`（1.00）：符号 parse_csv 与 Issue 关键词和代码内容匹配
- `parser.py:1-6`（0.88）：符号 <module> 与 Issue 关键词和代码内容匹配

## 复现测试

```python
import unittest
from parser import parse_csv


class ReproductionTests(unittest.TestCase):
    def test_empty_csv_returns_empty_list(self):
        self.assertEqual(parse_csv(""), [])

```

## 候选补丁

```diff
--- a/parser.py
+++ b/parser.py
@@ -3,4 +3,4 @@
     rows = []
     for line in text.splitlines():
         rows.append([cell.strip() for cell in line.split(",")])
-    return rows[0] if len(rows) <= 1 else rows
+    return [] if not rows else (rows[0] if len(rows) == 1 else rows)

```

## 验证结果

- baseline：失败；运行 1 项，失败 0，错误 1
```text
test_empty_csv_returns_empty_list (osg_reproduction.ReproductionTests.test_empty_csv_returns_empty_list) ... ERROR

======================================================================
ERROR: test_empty_csv_returns_empty_list (osg_reproduction.ReproductionTests.test_empty_csv_returns_empty_list)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "C:\Users\ADMINI~1\AppData\Local\Temp\osg-verify-lq1lxpjm\baseline\test_osg_reproduction.py", line 7, in test_empty_csv_returns_empty_list
    self.assertEqual(parse_csv(""), [])
                     ^^^^^^^^^^^^^
  File "C:\Users\ADMINI~1\AppData\Local\Temp\osg-verify-lq1lxpjm\baseline\parser.py", line 6, in parse_csv
    return rows[0] if len(rows) <= 1 else rows
           ~~~~^^^
IndexError: list index out of range

----------------------------------------------------------------------
Ran 1 test in 0.001s

FAILED (errors=1)
OSG_TEST_RESULT={"tests_run": 1, "failures": 0, "errors": 1, "skipped": 0, "infrastructure_error": false}

```
- candidate_patch：通过；运行 1 项，失败 0，错误 0
```text
test_empty_csv_returns_empty_list (osg_reproduction.ReproductionTests.test_empty_csv_returns_empty_list) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.000s

OK
OSG_TEST_RESULT={"tests_run": 1, "failures": 0, "errors": 0, "skipped": 0, "infrastructure_error": false}

```
- candidate_full：通过；运行 3 项，失败 0，错误 0
```text
test_empty_csv_returns_empty_list (test_osg_reproduction.ReproductionTests.test_empty_csv_returns_empty_list) ... ok
test_multiple_rows (test_parser.ParserTests.test_multiple_rows) ... ok
test_regular_input (test_parser.ParserTests.test_regular_input) ... ok

----------------------------------------------------------------------
Ran 3 tests in 0.000s

OK
OSG_TEST_RESULT={"tests_run": 3, "failures": 0, "errors": 0, "skipped": 0, "infrastructure_error": false}

```

## 安全扫描

未命中内置规则，不代表没有漏洞。

## 分析说明

- 当前报告不会修改目标仓库；补丁只会在临时副本中校验。
## 下一步

- 候选补丁已在临时副本通过验证，可生成 Draft PR 供维护者审核。
- 人工确认代码证据与 Issue 是否对应。
- 把复现测试模板改成真实输入，并确认原始版本先失败。
- 在隔离分支生成补丁，运行复现测试、全量测试和安全扫描。
- 通过 GitHub/Gitee Draft PR 提交给维护者审核。
