# OpenSourceGuard

面向开源项目维护者的 AI Issue 定位与可信修复 MVP。

它把一次 Issue 处理拆成可追踪的步骤：仓库索引 → Issue 结构化 → 代码定位 → 复现测试建议 → 补丁计划 → 测试验证 → 修复报告。默认使用 Python 标准库运行，不绑定某一家模型；接入 OpenAI-compatible API 后，模型可以参与定位、测试和补丁生成。

## 5 分钟试用

```powershell
cd opensourceguard
python -m opensourceguard.cli demo
```

分析任意本地 Python 仓库：

```powershell
python -m opensourceguard.cli analyze `
  --repo C:\path\to\repo `
  --issue "读取空 CSV 文件时 parse_csv 崩溃，应该返回空列表" `
  --output .\artifacts\report.json
```

默认只做静态分析；对内置示例执行临时副本验证：

```powershell
python -m opensourceguard.cli analyze `
  --repo .\examples\buggy_csv `
  --issue "读取空 CSV 文件时 parse_csv 崩溃，应该返回空列表" `
  --execute local
```

启动本地 Web API：

```powershell
python -m opensourceguard.cli serve --repo C:\path\to\repo --port 8787
```

浏览器打开 `http://127.0.0.1:8787/` 可以使用可视化工作台。**首页就是诊断工作台**：输入框已预填示例 Issue，点“使用演示账号进入”后直接点“开始分析”，页面会显示代码证据、安全扫描、候选补丁和基线/补丁后测试结果。左侧主导航只有“诊断与修复”和“体检报告”两项，其余工具（项目与平台、Issue 总结、评分明细、发布与分享、Agent 对比）收在“更多工具”折叠面板里。

首次打开会进入本地工作区登录页。可以填写工作区名称和本地解锁码，也可以使用演示账号直接体验；登录信息只保存在浏览器本地，不会发送给 GitHub、Gitee、GitLab 或模型服务。右上角可以退出登录。这个入口是本机工作区会话，不等同于平台 OAuth 登录。

### 真实可用边界

- `--execute local` 会把仓库复制到临时目录，先运行原始版本，再应用候选补丁，最后运行复现测试和原仓库全量测试；目标仓库不会被修改。生产环境建议使用 `--execute docker`，并准备好本地 Docker 镜像。
- `skip` 是静态分析，报告会明确标记“未执行代码”，不能把它当成测试通过。
- 开源发布助手只生成 Git 命令、README 草稿和个人网站卡片，不会自动创建远程仓库、推送代码或改写网站。没有填写用户名时，`YOUR_USERNAME` 是占位符，不能直接复制执行。
- Draft PR 接口默认只预览；只有显式传 `confirm: true` 才会向平台发起真实创建，且固定 `draft: true`。**任何情况下都不会替你 push 代码。**
- Agent 竞技场使用依赖-free 的规则评分，HTTP Agent 只收到 `case_id` 和题目文本，不会获得本地仓库或命令权限；分数用于同一任务集内比较，不能代替人工评审或生产验收。
- 项目中心会统一读取 GitHub、Gitee、GitLab 和自定义兼容 API 的项目与 Issue。没有 Token 时显示本地演示项目；Agent 介入先生成方案，只有明确确认后才会把评论写回平台，或修改当前本地仓库。
- 未配置 `OSG_MODEL_BASE_URL` 和 `OSG_MODEL_NAME` 时使用本地规则分析；模型服务失败会回退到本地规则，并在报告中说明。API Key 只在本地服务进程内读取，不会发送到浏览器、报告或日志。

运行完整验收：

```powershell
python -X utf8 -m unittest discover -s tests -v
python -X utf8 eval/browser_acceptance.py --libraries C:\path\to\playwright --browser "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
```

然后请求：

```powershell
Invoke-RestMethod http://localhost:8787/health
Invoke-RestMethod -Method Post http://localhost:8787/analyze `
  -ContentType 'application/json' `
  -Body '{"issue":"读取空 CSV 文件时 parse_csv 崩溃，应该返回空列表"}'
```

Webhook 入口为 `POST /webhook`，可直接接收 GitHub/Gitee 风格的 `issue.title` 和 `issue.body` 字段。OpenClaw 可以定时调用该入口并把 JSON 结果发送给维护者。

生成 Draft PR 请求体（不直接调用平台 API）：

```powershell
Invoke-RestMethod -Method Post http://localhost:8787/draft-pr `
  -ContentType 'application/json' `
  -Body '{"issue":{"title":"空 CSV 崩溃","body":"应该返回空列表"},"head":"ai/fix-empty-csv","base":"main"}'
```

## 创建真实的 Draft PR

上面这条命令只是**预览**：返回将要发送的请求体，不会发起任何网络写入。确认维护者认可后，再带 `confirm` 发起真实创建：

```powershell
$env:OSG_GITHUB_TOKEN = "ghp_..."
Invoke-RestMethod -Method Post http://localhost:8787/draft-pr `
  -ContentType 'application/json' `
  -Body '{"issue":"读取空 CSV 文件时 parse_csv 崩溃，应该返回空列表","platform":"github","repo":"owner/repo","head":"ai/fix-empty-csv","base":"main","confirm":true}'
```

规则：

- `confirm` 缺省时永远只预览，请求头一次都不会发出（`eval/verify_draft_pr_e2e.py` 对此有断言）；
- PR 固定以 `draft: true` 创建，正文自动带上定位证据、基线/补丁后测试结论和安全扫描结果；
- **本工具不 push 代码**：`head` 分支必须已存在于远程，且内容就是通过验证的那份补丁。分支不存在时返回 HTTP 404 并提示；
- `head` 与 `base` 相同会被直接拒绝；
- Token 只由本地服务读取，不进入浏览器、报告或日志；
- GitLab 使用 `merge_requests` 接口，draft 通过标题前缀约定（GitLab 建 PR 时不接受 `draft` 字段）。

只读地确认 PR 是否真的存在：

```powershell
Invoke-RestMethod -Method Post http://localhost:8787/projects/pulls `
  -ContentType 'application/json' -Body '{"platform":"github","repo":"owner/repo"}'
```

网页端对应位置：分析结果卡片底部的「把这套结果变成一个可审核的 PR」区块。


安全扫描演示：

```powershell
python -m opensourceguard.cli analyze `
  --repo .\examples\security_demo `
  --issue "检查仓库是否存在命令注入和硬编码凭据"
```

## 项目结构

```text
opensourceguard/
  opensourceguard/
    cli.py       命令行、demo 和 HTTP API
    indexer.py   Python 文件、函数、测试和关键词索引
    pipeline.py  Issue → 定位 → 测试 → 补丁 → 验证工作流
    model.py     可选 OpenAI-compatible 模型适配器
    providers.py GitHub/Gitee/GitLab/兼容 API 项目与 Issue 连接层
    sandbox.py   受限测试执行器（Windows/Linux 均可用）
    security.py  依赖-free Python 安全规则扫描
    integrations.py GitHub/Gitee/Webhook 归一化和 Draft PR 请求体
    onboarding.py Git 管理、开源发布和个人网站项目卡片
    arena.py     Agent 竞技场和可解释评测
    report.py    JSON/Markdown 报告
    types.py     结构化数据模型
  examples/      可现场演示的故障仓库
    security_demo/ 可现场演示的安全风险仓库
  eval/          公开评测样例和评测脚本
  PITCH.md       三分钟现场演示和答辩指标
  Dockerfile
  pyproject.toml
  web/index.html  浏览器工作台
  web/styles.css  液态玻璃视觉与响应式布局
  web/app.js      路由、表单交互、报告渲染、复制与下载
```

浏览器工作台由本地服务同时提供页面、样式和脚本。直接双击 `web/index.html` 也可以预览视觉效果；要使用分析、发布助手和 Agent 竞技场，请先启动 `serve`，页面会自动检测 `http://127.0.0.1:8787`。

### 界面结构

主导航刻意保持两项，把注意力集中在"贴 Issue → 看证据 → 验补丁"这一条主线上：

| 入口 | 路由 | 说明 |
| --- | --- | --- |
| 诊断与修复（首页） | `#diagnose` | Issue 输入 + 代码证据 + 候选补丁 + 验证结果 |
| 体检报告 | `#report` | 五维健康评分与合规审计 |
| 更多工具 → 项目与平台 | `#projects` | 跨平台项目、Issue 与 Agent 介入 |
| 更多工具 → Issue 总结 | `#issues` | 把多条反馈聚类成主题并排序 |
| 更多工具 → 评分明细 | `#health` | 评分明细（与体检报告同源） |
| 更多工具 → 发布与分享 | `#publish` | Git 命令、README 草稿、网站卡片、魔搭上传 |
| 更多工具 → Agent 对比 | `#arena` | 同一批任务下的规则评测 |

`#home`、`#repair` 和 `#health` 作为旧书签的兼容入口保留，会自动跳转到对应的新页面。

所有页面共用一套工作区控件：侧栏项目卡片上的「切换工作项目」按钮可以更换当前分析的本地仓库（`POST /repo/select`，带凭据目录拦截）；顶栏的「模型服务设置」用于接入真实模型 API。切换工作项目后，诊断、体检报告、Issue 总结与 Agent 竞技场都会作用于新仓库。

## 可信边界

默认流程不会自动写入目标仓库。分析器会计算仓库快照指纹；验证时只复制到临时目录，严格限制补丁只能修改现有 Python 实现文件。默认不执行不可信仓库代码；local 仅适合完全信任的示例，生产环境应使用 Docker 的无网络、只读挂载、低权限用户、超时和资源配额。

## 接入模型

推荐直接在浏览器里配置：点击任意页面顶栏的「模型服务设置」按钮，填入 Base URL、模型名、API Key 和接口风格（auto / Chat Completions / Responses），保存后在「代码体检」页测试连接即可。配置写入 `~/.opensourceguard/model.json`（仅当前用户可读）；API Key 只保存在本机，永远不会回显到页面或接口响应——保存时 Key 留空表示沿用已保存的 Key，「清除配置」会删除本地文件并回退到环境变量。对应接口：`GET /model/status`、`POST /model/config`、`POST /model/test`。

也可以改用环境变量（界面保存的配置优先于环境变量）：

```powershell
$env:OSG_MODEL_BASE_URL = "https://api.example.com/v1/chat/completions"
$env:OSG_MODEL_NAME = "your-model"
$env:OSG_MODEL_API_KEY = "..."
# 可选：Responses API 用 https://api.openai.com/v1/responses，并设置
$env:OSG_MODEL_API_STYLE = "responses"
# 可选：请求超时（秒，默认 45，最大 180）
$env:OSG_MODEL_TIMEOUT = "45"
```

启动服务后，在“代码体检”页面点击“测试模型连接”。也可以检查 `GET /model/status` 或调用 `POST /model/test`。连接测试只发送最小 JSON 请求；响应只接受 `reproduction_test`、`patch_plan`、`patch` 和 `warnings` 字段。未设置模型时，系统使用可解释的本地启发式分析，保证 Demo 和评测可以离线运行。

## 项目中心与平台连接

平台 Token 只由本地服务读取，不要写入前端、仓库或 Issue 内容。按需设置：

```powershell
$env:OSG_GITHUB_TOKEN = "ghp_..."
$env:OSG_GITEE_TOKEN = "..."
$env:OSG_GITLAB_TOKEN = "glpat-..."
# 自定义兼容 API 还需要：
$env:OSG_GENERIC_API_URL = "https://your-host.example/api"
$env:OSG_GENERIC_TOKEN = "..."
```

重启服务后打开“项目中心”。页面会先列出项目，再加载 Issue；点击“让 Agent 介入”会生成复现测试、补丁计划和候选 diff。对于本地演示项目，可以确认后应用到当前本地仓库；对于远程项目，当前版本支持确认后写入 Issue 评论，远程代码修改仍需通过审核后的分支或 Draft PR 完成。

对应接口是 `GET /projects`、`GET /projects/issues?platform=github&repo=owner/name`、`POST /projects/assist`、`POST /projects/comment` 和 `POST /projects/apply-local`。最后一个接口必须传 `confirm: true`，服务才会修改本地文件。

「查找本地项目」的结果卡片支持一键切换：点击某个项目即可调用 `POST /repo/select` 把它设为当前工作项目，无需手动复制路径。

## 比赛演示建议

使用 `examples/buggy_csv` 做现场演示：Issue 指向空 CSV 崩溃，系统会显示相关函数、证据行、复现测试、候选补丁、安全扫描和两次测试结果。后续可接入真实 GitHub/Gitee Draft PR、Tree-sitter、向量数据库、Semgrep 和 Docker 沙箱。

## 评测

## 面向初学者的两个入口

开源发布助手解决“代码写完以后怎么办”：它会检查 Git、README、许可证、CI 和远程地址，解释每条命令为什么要执行，生成 GitHub/Gitee 推送步骤、README 草稿和个人网站项目卡片。系统只生成命令，不会替用户上传代码或读取凭据。

Agent 竞技场解决“我的 Agent 到底好不好”：所有 Agent 使用同一批公开任务、同一输入和同一评分规则，分别计算任务覆盖、安全性、回答结构和延迟，再生成排行榜和逐题证据。用户可以先提交固定 responses，之后再接入自己的本地 HTTP Agent。

竞技场的默认任务包含 Issue 代码定位、未知 shell 命令安全处理和开源发布计划。参赛时应把真实业务任务脱敏后加入评测集，并同时报告人工盲评、成本和 token 使用量。

命令行入口：

```powershell
python -m opensourceguard.cli onboarding `
  --repo . `
  --username yourname `
  --platform github `
  --project-name my-agent `
  --homepage https://your.site/projects/my-agent

python -m opensourceguard.cli arena
```

也可以打开网页工作台，在“新手开源发布助手”和“Agent 竞技场”两个模块中操作。

```powershell
python eval/run_eval.py
```

评测脚本比较启发式流程在样例 Issue 上的定位命中率，并输出 JSON 结果。扩展时可把真实历史 Issue 脱敏后放入 `eval/cases.json`。


## TypeSafe 项目推荐

接入依据：[TypeSafe System One 文档](https://docs.typesafe.ai/introduction)，它提供 Choice、Score、Noul 三种结构化问题类型。项目中心使用 Score 批量评估项目相关度，并把 confidence 作为人工复核提示。

项目中心支持按兴趣排序。输入“我关注的方向”和“暂时不想看”，点击“为我排序”，系统会把匹配度高的项目放在前面，并显示排序理由。

默认使用不依赖网络的本地规则，适合离线演示。要启用 TypeSafe 的结构化评分，请在启动服务前配置：

```powershell
$env:TYPESAFE_API_KEY = "你的 TypeSafe API Key"
# 可选：
$env:TYPESAFE_BASE_URL = "https://api.typesafe.ai"
$env:TYPESAFE_MODEL = "jev-latest"
```

密钥只由本地服务端读取，不会发送到浏览器、项目卡片或报告。TypeSafe 请求使用 `POST /v1/systemone`，一次批量评估多个项目；请求失败或信心不足时会自动回退本地排序。状态可通过 `GET /typesafe/status` 查看，推荐接口为 `POST /projects/recommend`。

## 发布到魔搭社区

发布助手会先扫描项目文件、疑似凭据、文件数量和大小，并生成 README 草稿。真正上传需要在页面再次确认，并且只从服务端读取以下配置：

```powershell
$env:OSG_MODELSCOPE_TOKEN = "你的 ModelScope Token"
pip install modelscope
```

页面不会接收或保存 Token。上传接口为 `POST /modelscope/publish`，必须传入 `confirm: true`；未配置 Token、SDK 或发现 `.env`、密钥、证书文件时会阻止上传。SDK 的具体上传方法会随版本变化，服务端会在缺少方法时明确返回错误。

**发布前的安全检查是可验证的，不是承诺。** 对本仓库目录执行扫描会得到：

```text
blocked_files: ['.env.local']      # 拦住含平台 Token 的文件
safe_to_upload: False              # 未确认前不允许上传
file_count: 94
token_configured: False
```

也就是说，即使配好了 Token，只要目录里还有 `.env`，工具也会拒绝上传，避免把凭据一起推到公开空间。配置 Token 的方式：

```powershell
$env:OSG_MODELSCOPE_TOKEN = "你的 ModelScope Token"
```

或复制 `config.example.env` 为 `.env.local` 填入。**当前环境未配置 Token，因此本仓库尚未真正发布到 ModelScope；配置后执行 `publish-space.bat <你的ID>/<空间名>` 即可完成首次上传。**


## 本地真实使用：双击启动

普通用户不需要记住 Python 命令。Windows 用户按下面步骤操作：

1. 安装 Python 3.10 或更高版本，并确认安装时勾选了“Add Python to PATH”。
2. 复制 `config.example.env` 为 `.env.local`，只填写确实需要的平台 Token；不填也可以使用离线模式。
3. 双击 `start.bat`。窗口会询问项目目录，直接回车使用内置演示项目，或输入自己的项目目录。
4. 脚本会自动启动本地服务并打开 `http://127.0.0.1:8787/`。关闭启动窗口即可停止服务。

也可以直接把项目目录作为参数传入：

```powershell
.\start.bat "D:\code\my-agent"
.\start.bat "D:\code\my-agent" 8788
```

macOS 或 Linux：

```bash
chmod +x start.sh
./start.sh ~/code/my-agent 8787
```

直接双击 `web/index.html` 只能查看静态界面，不能读取项目、调用 Agent、连接平台或发布到 ModelScope；真实使用请通过启动脚本打开本地 HTTP 地址。Token 始终由本地服务端读取，不会由浏览器表单接收。


## 上传 ModelScope 创空间

项目内的 `space/` 是已经准备好的 Gradio 创空间入口，包含 `app.py`、`requirements.txt` 和 Space README。配置 Token 和 SDK 后，可以直接运行：

```powershell
$env:OSG_MODELSCOPE_TOKEN = "你的 ModelScope Token"
pip install modelscope
.\publish-space.bat yourname/opensourceguard
```

脚本会先扫描 `space/`、要求输入 `YES` 二次确认，再调用官方 SDK 上传。当前环境没有 ModelScope Token，因此上传动作只能在你配置 Token 后执行；没有 Token 时脚本会安全退出。
