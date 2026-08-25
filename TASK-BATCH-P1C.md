# TASK-BATCH-P1C — MCP工具 + 多模态 + 前端联调

> 前置：P1A+P1B 已完成，35/35 全绿
> 工作目录：E:\paper project
> LLM：智谱 GLM-4.7 Flash（免费），key 在 .env 中

---

## 任务1: MCP 真实工具对接

修改: `apps/server/app/mcp/client.py`, `apps/server/app/api/v1/mcp.py`, `mcp.json`

现状：MCP client 是纯 mock，没有真实调用
目标：实现真实 MCP 工具调用框架（不需要真的装 calendar-mcp/todo-mcp，但框架要完整）

1. client.py 重写：
   - 实现 `MCPServerManager` 类，管理多个 MCP server 连接
   - `call_tool(server, tool, args)` 支持超时重试（3次，指数退避）
   - `list_servers()` 返回真实状态
   - 内置 3 个工具的 mock 实现（calendar.create_event, todo.create, search.web），接口完整但返回模拟数据
   - 工具调用结果自动记录到 AgentRunLog

2. mcp.py API 完善：
   - GET /api/v1/mcp/servers — 列出所有 MCP server 状态
   - POST /api/v1/mcp/call — 调用指定工具
   - GET /api/v1/mcp/tools — 列出所有可用工具

3. mcp.json 更新：添加 search server
   ```json
   {
     "servers": {
       "calendar": {"command": "mock", "tools": ["create_event", "list_events"]},
       "todo": {"command": "mock", "tools": ["create_todo", "complete_todo"]},
       "search": {"command": "mock", "tools": ["web_search"]}
     }
   }
   ```

4. 验证：跑 test_p2.py::test_mcp

---

## 任务2: 多模态 — OCR 用智谱 + 语音输入

修改: `apps/server/app/multimodal/ocr.py`, `apps/server/app/multimodal/asr.py`, `apps/server/app/api/v1/multimodal.py`

1. ocr.py 重写：
   - 用智谱 GLM-4V-Flash（免费）做 OCR，替换 Qwen-VL
   - 保留 mock fallback（无 key 时返回模拟课表）
   - 课表识别输出结构化 JSON：{courses: [{course, teacher, time, location}]}

2. asr.py 保持现有逻辑（Whisper 接口），加 fallback：
   - 无 key 时返回更智能的 mock（根据时间推断）

3. multimodal.py API：
   - POST /api/v1/multimodal/ocr — 上传图片识别课表
   - POST /api/v1/multimodal/asr — 上传音频识别语音
   - GET /api/v1/multimodal/capabilities — 返回支持的模态

4. 验证：跑 test_p2.py::test_multimodal

---

## 任务3: 前端联调验证 + 补全

修改: `apps/frontend/src/views/` 下各文件, `apps/frontend/src/api/`

1. 确保所有 API client 有正确的 baseURL：
   - 检查 vite.config.ts 的 proxy 配置
   - 确保 axios baseURL 指向 /api/v1

2. 前端补全：
   - CalendarView：确保能显示计划任务（从 plans API 获取）
   - DashboardView：确保 stats API 调用正确
   - HealthCheck：确保 health API 调用正确
   - 新增 MCP 管理页面或在 HealthCheck 中展示 MCP 状态

3. 新增前端文件 `apps/frontend/src/api/mcp.ts`：
   ```typescript
   export async function listMCPServers() { ... }
   export async function callMCPTool(server: string, tool: string, args: any) { ... }
   ```

4. 验证：`cd apps/frontend && npx vue-tsc --noEmit` 确认无 TypeScript 错误

---

## 完成后验证（必须全部通过）

1. `cd apps/server && python -m pytest tests/ -v --tb=short` → 35/35 passed
2. `python -c "from app.main import app; print('ok')"` → ok
3. `cd apps/frontend && npx vue-tsc --noEmit` → 无错误
4. 汇报每项改动
