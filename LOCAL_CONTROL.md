# 本地控制与多平台登录方案

## 先说结论

ModelScope 适合分发 OpenSourceGuard、托管演示页面或提供下载入口。它不能直接访问用户电脑上的项目目录，也不应该替用户长期保管 GitHub、Gitee、GitLab 的写入凭据。

最终产品采用“云端入口 + 本地控制器”：

```text
ModelScope 创空间 / 项目页面
          │ 下载、说明、可选的云端展示
          ▼
用户电脑上的 OpenSourceGuard 控制器
          ├─ 读取本地项目和 Git
          ├─ 保存平台连接
          ├─ 调用 GitHub / Gitee / GitLab API
          └─ 执行 Agent 方案（默认只读，写操作需确认）
```

## 用户最终怎么用

1. 用户从 ModelScope 下载压缩包，或打开 ModelScope 创空间中的项目介绍页。
2. 第一次运行 `start.bat`，选择自己的项目目录。
3. 浏览器自动打开本地工作台，例如 `http://127.0.0.1:8787/`。
4. 在“平台连接”中点击“连接 GitHub / Gitee / GitLab”，浏览器完成官方授权。
5. 回到工作台后，统一查看项目、Issue、评论和 Agent 建议。
6. Agent 先生成计划；创建评论、修改文件、推送分支等动作都要再次确认。

用户不需要把 Token 粘贴到网页，也不需要把项目上传到 ModelScope 才能使用。

## OAuth 连接中心怎么实现

本地控制器为每个平台启动一次授权流程：

1. 生成随机 `state` 和 PKCE `code_verifier`。
2. 打开平台官方授权页面。
3. 使用本地回调地址接收授权码，例如 `http://127.0.0.1:<随机端口>/oauth/callback/github`。
4. 只在本地服务端用授权码换取 Token，浏览器只得到“连接成功”。
5. 删除一次性授权参数，将 Token 保存到本机安全存储。

GitHub、Gitee、GitLab 的 OAuth 应用都需要各自的 Client ID。Client Secret 不能写进网页或 ModelScope 前端。最安全的两种部署方式是：

- 桌面版：用户在本地设置中填写自己创建的 OAuth App Client ID 和 Secret。
- 有统一服务端时：由自己的后端完成 OAuth 交换，平台 Token 加密保存，并明确告知用户信任边界。

本地版优先采用第一种，避免所有用户的 Token 集中经过我们的服务器。

## 本地凭据存储

不要把平台 Token 明文写入项目目录、浏览器 LocalStorage 或普通日志。控制器应使用：

- Windows：DPAPI / Windows Credential Manager
- macOS：Keychain
- Linux：Secret Service；不可用时使用权限为 `0600` 的本地文件

每个平台只申请必要权限。读取项目和 Issue 默认只读；评论、创建分支、推送代码分别申请或确认对应权限。

## 云端页面如何连接本地控制器

不能让任意 ModelScope 网页直接调用本机 API。需要一个一次性配对流程：

1. 本地控制器生成短时有效的配对码。
2. 用户在 ModelScope 页面输入配对码，或点击“在本地打开”。
3. 本地控制器只接受配对成功后的短期 Bearer Session Token。
4. 每次写操作仍在本地弹出确认，并记录审计日志。

如果不需要云端页面，最简单可靠的版本是让所有交互都由本地控制器提供的页面完成；ModelScope 只提供下载和文档。

## 需要新增的接口

```text
GET  /connections
POST /oauth/start              {platform}
GET  /oauth/callback/{platform}
POST /connections/{platform}/disconnect
GET  /projects?platform=all
GET  /projects/issues
POST /projects/assist
POST /actions/preview
POST /actions/execute           {confirm: true}
GET  /audit-log
```

统一的连接对象只返回脱敏信息，例如平台名、账号名、权限范围和连接时间，不返回 Token：

```json
{
  "platform": "github",
  "account": "example",
  "scopes": ["read:user", "repo:status"],
  "connected": true
}
```

## 当前项目的状态

目前已经具备本地控制器、跨平台项目与 Issue 读取、Agent 方案、确认边界、`start.bat` 一键启动和 ModelScope 发布前检查。平台连接目前通过服务端环境变量完成，还不是 OAuth 登录；因此现在可以真实使用，但还不能把“点击平台登录”作为已完成能力对外宣传。

推荐的开发顺序是：

1. 先加入本地凭据存储和连接状态页。
2. 再实现 GitHub OAuth，验证完整授权、撤销和断线重连。
3. 复用同一适配器实现 Gitee、GitLab。
4. 最后增加 ModelScope 云端页面的配对入口和桌面版打包。
