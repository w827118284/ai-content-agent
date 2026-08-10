# AI Content Agent Frontend

React + TypeScript + Vite 前端，用于操作 FastAPI / LangGraph 内容工作流。

工作台左侧历史任务栏加载轻量项目索引；点击任务后使用原 `thread_id` 从 LangGraph checkpoint 恢复完整状态，并可继续选题、Reject 或 Approve。历史列表失败不会阻塞当前工作流操作。

## 开发

```powershell
npm install
npm run dev
```

默认访问 `http://localhost:5173`，API 地址通过 `VITE_API_BASE_URL` 配置。

## 验证

```powershell
npm test
npm run build
```
