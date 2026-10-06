from __future__ import annotations

import gradio as gr


TITLE = "OpenSourceGuard · 开源项目本地控制中心"
INTRO = "统一查看项目与 Issue，先让 Agent 给出可审核方案，再由你确认是否执行。"
LOCAL_GUIDE = """## 本地真实使用

ModelScope 创空间不能直接读取你电脑上的项目目录，也不应代替你保管平台 Token。

1. 下载 OpenSourceGuard 源码。
2. Windows 双击 `start.bat`；macOS/Linux 运行 `./start.sh`。
3. 浏览器打开本地工作台后，连接 GitHub、Gitee 或 GitLab。
4. 在本地统一管理项目、Issue、Agent 方案和发布流程。

本地控制器会默认只读。评论、修改代码、创建分支和推送都需要再次确认。
"""


def explain(platform: str, action: str) -> str:
    platform = platform or "GitHub"
    action = action or "查看项目和 Issue"
    return (
        f"### {platform} · {action}\n\n"
        "请在本地工作台完成登录。授权码和 Token 只在 localhost 服务中处理，"
        "不会保存到浏览器，也不会上传到这个创空间。"
    )


with gr.Blocks(title=TITLE, theme=gr.themes.Soft()) as demo:
    gr.Markdown(f"# 🛡️ {TITLE}\n\n{INTRO}")
    gr.Markdown(LOCAL_GUIDE)
    with gr.Row():
        platform = gr.Dropdown(["GitHub", "Gitee", "GitLab"], value="GitHub", label="平台")
        action = gr.Dropdown(["查看项目和 Issue", "让 Agent 分析 Issue", "准备发布到 ModelScope"],
                             value="查看项目和 Issue", label="想做什么")
    output = gr.Markdown()
    gr.Button("查看安全说明").click(explain, [platform, action], output)
    gr.Markdown("[下载源码并在本地启动](https://www.modelscope.cn/) · 本创空间不接收平台密码或 Token")


if __name__ == "__main__":
    demo.launch()
