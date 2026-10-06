# 真实 Issue 基准结果

生成时间：2026-10-05T23:30:59.301876+00:00

- 用例数：**6**（跳过 0）
- Top-1 定位：**66.7%**
- Top-3 定位：**66.7%**
- Top-5 定位：**83.3%**
- 函数名命中：**16.7%**
- 平均耗时：**0.63s/条**

## 方法与局限

评测集来自公开仓库的真实已修复 Issue（pallets/click#824、pallets/flask#2735、pallets/flask#2118、pallets/werkzeug#2364、pallets/werkzeug#2021、pallets/jinja#1400），定位答案取自报告者自己贴出的 traceback 帧，不由本项目标注。每个目标仓库均为临时浅克隆，工具从未见过修复提交。运行模式为离线规则模式（heuristic），未接入模型。

局限：样本量小（GitHub 匿名 API 限额下仅收集 6 条，提供 Token 后可用 eval/build_real_benchmark.py 一键扩展到 30 条）；真实 Issue 常不含完整 traceback，弱信号用例（如 jinja#1400 仅一行描述）会拉低命中率。

## 分仓库结果

| 仓库 | 用例 | Top-1 | Top-3 |
| --- | --- | --- | --- |
| pallets/click | 1 | 100% | 100% |
| pallets/flask | 2 | 100% | 100% |
| pallets/jinja | 1 | 0% | 0% |
| pallets/werkzeug | 2 | 50% | 50% |

## 逐条明细

| 用例 | 期望文件 | Top-1 | Top-3 | Top-5 | 函数 | 耗时 |
| --- | --- | --- | --- | --- | --- | --- |
| #824 ValueError: I/O operation on closed file | `src/click/testing.py` | Y | Y | Y | Y | 0.7s |
| #2735 flask.abort() behavioral change in debug | `src/flask/app.py` | Y | Y | Y | - | 0.45s |
| #2364 ResponseCacheControl.s_maxage raises err | `src/werkzeug/datastructures/cache_control.py` | - | - | Y | - | 0.86s |
| #2021 DechunkedInput.read returns more than wh | `src/werkzeug/serving.py` | Y | Y | Y | - | 0.86s |
| #2118 config.from_pyfile crashes on Python 3 | `src/flask/config.py` | Y | Y | Y | - | 0.43s |
| #1400 Markup.__init__ causes error | `src/jinja2/utils.py` | - | - | - | - | 0.51s |