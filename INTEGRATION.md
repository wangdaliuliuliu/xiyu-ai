# 溪语 × 经营工作台

本仓库是当前完整项目的联动代码仓库：

- 根目录：溪语（Xiyu）微信 AI 陪伴与主动协同服务。
- `workbench/`：VR 大空间经营策略工作台，包含前端页面、工作台后端、经营知识契约和联动协议。

两边仍然是两个独立进程，职责和数据边界不混在一起：

1. 溪语负责微信接入、对话、记忆和主动消息。
2. 工作台负责经营事实、周报、知识资产和执行闭环。
3. 溪语通过 `XIYU_WORKBENCH_CONTEXT_URL` 调用工作台的窄知识桥；工作台不可用时，溪语主聊天应保持可用。
4. 工作相关信息先经过范围和类型过滤，候选信息不会直接变成正式经营事实或经验。

## 本地启动

在两个终端分别启动：

```powershell
# 工作台
cd workbench
node backend/feishu-sync-server.mjs

# 溪语（另一个终端）
node index.mjs
```

默认地址：

- 工作台：`http://127.0.0.1:4174/`
- 溪语：`http://127.0.0.1:3000/`

溪语本地配置示例：

```dotenv
XIYU_WORKBENCH_CONTEXT_URL=http://127.0.0.1:4174
```

## 配置边界

真实的模型 Key、飞书 App Secret、电子表格 token、微信凭据、SQLite 数据库、运行态 JSON、日志、上传图片和测试截图均只保留在本地或部署服务器，不进入 GitHub。工作台的后端变量示例见 `workbench/backend/.env.example`；飞书目标表结构示例见 `workbench/data/feishu-target.example.json`。

线上部署仍按两个服务分别部署；这个仓库统一保存源码和协议，不代表把两个生产服务合并成一个进程或一次部署。
