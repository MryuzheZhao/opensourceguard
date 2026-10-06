# 本地部署指南

OpenSourceGuard 是一个**本地优先**的工具：代码、Token 和模型调用都在你自己的机器上完成。
这份文档告诉你怎么在自己电脑上跑起来。

---

## 一、最快路径（Windows，3 步）

```powershell
# 1. 确认 Python 版本（需要 3.10 或更高）
python --version

# 2. 复制配置模板
copy config.example.env .env.local

# 3. 双击 start.bat，或在终端运行
.\start.bat
```

浏览器会自动打开 `http://127.0.0.1:8787/`，点击「使用演示账号进入」即可开始。

**macOS / Linux：**

```bash
python3 --version          # 需要 3.10+
cp config.example.env .env.local
chmod +x start.sh && ./start.sh
```

---

## 二、依赖说明

**核心功能零第三方依赖**，只用 Python 标准库。这是刻意的设计：

| 功能 | 需要安装什么 |
|---|---|
| 代码索引、安全扫描、合规审计、健康度评分 | 无，标准库即可 |
| 项目发现、Issue 总结（本地规则模式） | 无 |
| LLM 辅助分析 | 无需安装包，只要填 API Key |
| Token 加密存储（可选，推荐） | `pip install keyring` |
| 发布到魔搭创空间（可选） | `pip install modelscope` |
| 运行测试（开发用） | `pip install pytest` |

未安装 `keyring` 时，Token 会存放在用户专属目录下的受限文件中，功能不受影响。

---

## 三、配置 LLM（推荐，但非必需）

所有分析功能都支持两种模式：**有模型时用模型，没模型时自动回退本地规则**，报告里会明确标注本次用的是哪一种。

编辑 `.env.local`，填入任意一个 OpenAI 兼容服务：

### DeepSeek（国内速度快，性价比高）

```env
OSG_MODEL_BASE_URL=https://api.deepseek.com/chat/completions
OSG_MODEL_NAME=deepseek-chat
OSG_MODEL_API_KEY=你的Key
OSG_MODEL_API_STYLE=chat_completions
```

### 阿里云百炼 / 通义千问

```env
OSG_MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
OSG_MODEL_NAME=qwen-plus
OSG_MODEL_API_KEY=你的Key
```

### 魔搭 ModelScope API-Inference

```env
OSG_MODEL_BASE_URL=https://api-inference.modelscope.cn/v1/chat/completions
OSG_MODEL_NAME=Qwen/Qwen2.5-72B-Instruct
OSG_MODEL_API_KEY=你的魔搭Token
```

### 本地部署（Ollama，完全离线）

```env
OSG_MODEL_BASE_URL=http://127.0.0.1:11434/v1/chat/completions
OSG_MODEL_NAME=qwen2.5:7b
OSG_MODEL_API_KEY=ollama
```

配置完成后，在页面的「代码体检」里点 **「测试模型连接」** 验证。

> **安全提示**：`.env.local` 已被 `.gitignore` 排除，不会进入 Git 历史。
> 绝对不要把 Key 写进 `config.example.env` 或任何会被提交的文件。

---

## 四、给评委 / 体验者的演示模式

如果你想让别人直接体验完整功能（包括 LLM 分析），而不需要他们自己注册 API：

在 `.env.local` 中加入：

```env
OSG_DEMO_MODE=1
OSG_DEMO_LABEL=AIC 评委演示账号
```

开启后：

- 前端顶部显示演示模式标识和额度提示
- 体验者**无需任何配置**即可使用 LLM 辅助的全部分析能力
- **强制只读**：不会评论 Issue、不会提交 PR、不会上传任何内容
- 所有写操作仍然需要体验者自己的 Token 并二次确认

这样评委打开浏览器就能看到真实的模型推理结果，而不是"请先配置 API Key"。

> 演示模式消耗的是**你自己**的 API 额度。公开演示前建议在服务商后台设置消费上限，
> 演示结束后轮换一次 Key。

---

## 五、常用命令

图形界面之外，所有能力都有对应的命令行入口：

```bash
# 用自然语言找本机项目
python -m opensourceguard.cli find "我那个用 Python 写的爬虫"

# 代码体检
python -m opensourceguard.cli analyze --repo . --issue "空输入时崩溃"

# 项目健康度评分
python -m opensourceguard.cli health --repo . --markdown artifacts/health.md

# 依赖与许可证合规审计
python -m opensourceguard.cli compliance --repo . --fail-on-high

# Issue 定期总结
python -m opensourceguard.cli issues --repo . --platform github \
    --repo-name OWNER/REPO --markdown artifacts/issue-digest.md

# 启动 Web 界面
python -m opensourceguard.cli serve --repo . --port 8787
```

---

## 六、让 Issue 总结定期自动运行

工具**不会**在后台常驻守护进程——什么时候读取你的仓库，应该由你决定。
它给出的是交给系统调度器的现成命令：

**Windows（任务计划程序）：**

```powershell
schtasks /create /tn "OpenSourceGuard Issue Digest" /sc hourly /mo 24 ^
  /tr "cmd /c cd /d C:\path\to\your\project && python -m opensourceguard.cli issues --repo . --platform github --repo-name OWNER/REPO --markdown artifacts/issue-digest.md"
```

**macOS / Linux（cron）：**

```bash
crontab -e
# 加入这一行：每 24 小时生成一次报告
0 */24 * * * cd /path/to/your/project && python -m opensourceguard.cli issues --repo . --platform github --repo-name OWNER/REPO --markdown artifacts/issue-digest.md
```

或者直接在页面的「Issue 中心」点击「获取定时配置」，会生成填好路径的命令。

定时任务**只生成报告**，不会自动改代码或提交 PR。

---

## 七、常见问题

### 端口被占用

```
无法启动端口 8787：端口已占用或不可用
```

换一个端口：

```powershell
.\start.bat "C:\你的项目路径" 8788
```

### 页面能打开但按钮没反应

直接双击 `web/index.html` 只能看静态界面。**必须**通过启动脚本访问
`http://127.0.0.1:8787/`，否则前端无法调用后端。

### 报告里写着「使用本地规则分析」

说明模型未配置或调用失败。在「代码体检」页点「测试模型连接」查看具体原因：

| 提示 | 原因 |
|---|---|
| `not_configured` | `.env.local` 里的三个模型变量没填完整 |
| `http_401` | API Key 错误或已失效 |
| `http_429` | 触发限流，稍后再试 |
| `connection_failed` | 网络不通，或需要配置代理 |
| `invalid_json_result` | 模型没有返回合法 JSON，换一个支持 JSON 输出的模型 |

### 找不到本机项目

默认只扫描 `Documents`、`Desktop`、`Projects`、`Code`、`workspace` 等常见位置，
深度 7 层。如果你的项目在别处：

```env
# .env.local，多个目录用分号（Windows）或冒号（macOS/Linux）分隔
OSG_PROJECT_ROOTS=D:\我的代码;E:\github
```

### Windows 上 Token 存在哪

优先存入 Windows 凭据管理器（需要 `pip install keyring`）。
未安装时存放在 `%USERPROFILE%\.opensourceguard\connections.json`，仅当前用户可读。
Token **永远不会**返回给浏览器，也不会写进任何报告。

---

## 八、卸载

项目是纯文件形态，没有安装步骤：

1. 删除项目目录即可
2. 如果用过 `keyring`，在「Windows 凭据管理器 → 普通凭据」中删除 `opensourceguard` 开头的条目
3. 删除 `~/.opensourceguard/`（如果存在）

不会在系统其他位置写入任何文件。

---

## 三、公开部署（Docker，评委可直接访问）

本地优先意味着默认只监听回环地址；只有在容器或公网部署时才需要显式放开。

```bash
docker build -t opensourceguard .
docker run --rm -p 8787:8787 opensourceguard
```

打开 `http://<服务器地址>:8787/`，点“使用演示账号进入”即可体验完整流程。

### 安全边界（部署前必读）

- **不要给公开实例配置任何平台 Token。** 镜像里已把 `OSG_GITHUB_TOKEN`、
  `OSG_GITEE_TOKEN`、`OSG_GITLAB_TOKEN`、`OSG_MODELSCOPE_TOKEN` 全部置空。
  一旦配置，公开页面上的任何人都能通过你的 Token 读写你的仓库。
- 服务会读取容器内的 `/app/examples/buggy_csv` 作为演示仓库，**不会**读取宿主机任意路径。
- 无 Token 时工具运行在离线规则模式，功能完整（定位、补丁、复现测试、安全扫描都能跑），
  只是无法读取真实项目、无法建 PR 或上传。
- 本地使用时 `--host` 默认是 `127.0.0.1`，无需额外参数；只有容器和反向代理才需要 `0.0.0.0`。

### 健康检查

```bash
curl http://127.0.0.1:8787/health
```

镜像内置 `HEALTHCHECK`，可直接用于 Docker Swarm、Kubernetes 或负载均衡探活。
