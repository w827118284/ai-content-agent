# AI Content Agent Frontend

React + TypeScript + Vite 前端，用于操作带 JWT 登录与用户归属保护的 FastAPI / LangGraph 内容工作流。

工作台左侧历史任务栏加载轻量项目索引；点击任务后使用原 `thread_id` 从 LangGraph checkpoint 恢复完整状态，并可继续选题、Reject 或 Approve。历史列表失败不会阻塞当前工作流操作。

应用启动时从 localStorage 读取 `content_agent_access_token`，通过 `/api/v1/auth/me` 验证后才挂载工作台。所有 workflow/history 请求由统一 API client 添加 Bearer header；认证接口或受保护接口返回 401 时会清理登录态。退出登录同时清除 token 与当前 `thread_id`，但不会删除服务端用户、项目或 checkpoint。

## 开发

```powershell
npm install
npm run dev
```

默认访问 `http://localhost:5173`，API 地址通过 `VITE_API_BASE_URL` 配置。本地开发推荐使用 `http://127.0.0.1:8000/api/v1`；Docker production build 使用同源 `/api/v1`。client 仍兼容只配置 origin 的旧值，并确保不会重复拼接 `/api/v1`。

当前本地学习版将 Access Token 保存到 localStorage。生产环境若对 XSS 风险有更高要求，应评估 `HttpOnly + Secure + SameSite` Cookie，并同步设计 CSRF 与 CORS 策略。本阶段仍使用 Authorization header，不启用 cookie credentials；Markdown 渲染也未启用 raw HTML。

## 验证

```powershell
npm test
npm run build
```
