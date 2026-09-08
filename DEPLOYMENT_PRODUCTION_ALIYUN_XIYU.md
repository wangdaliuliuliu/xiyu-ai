# 溪语（Xiyu）生产环境部署说明：阿里云独立部署

> 给第一次接手本项目的维护者看的入口文档。本文描述当前已经上线的生产环境、目录、服务、备份、更新和故障排查方式。
>
> 文档更新时间：2026-09-07  
> Xiyu 版本：1.22.0  
> 部署原则：与同一台服务器上的 LIMI 项目完全隔离

## 1. 先看这里：线上访问入口

- 用户入口：<https://xiyu.myworlds.cn>
- 登录页：<https://xiyu.myworlds.cn/app/auth.html>
- 健康检查：<https://xiyu.myworlds.cn/api/health>
- DNS：`xiyu.myworlds.cn` 的 A 记录指向 `39.106.153.59`

不要把 `127.0.0.1:3000` 暴露给用户。3000 端口只供服务器本机的 Nginx 反向代理使用。

## 2. 服务器与隔离边界

### 服务器

- 云厂商：阿里云 ECS
- 公网 IP：`39.106.153.59`
- 系统：Ubuntu 24.04
- 规格：2 vCPU / 2 GiB RAM / 40 GiB 系统盘
- 当前状态：磁盘约使用 52%；没有 Swap

### Xiyu 的独立资源

| 资源 | 当前值 |
| --- | --- |
| 服务用户 | `xiyu` |
| 项目目录 | `/opt/xiyu-ai` |
| systemd 服务 | `xiyu-ai.service` |
| 监听地址 | `127.0.0.1:3000` |
| 数据库 | `/opt/xiyu-ai/data/bot.db` |
| 运行日志 | `journalctl -u xiyu-ai`；应用日志目录 `/opt/xiyu-ai/logs` |
| 配置文件 | `/opt/xiyu-ai/.env`（权限 600，不提交到 Git） |
| 备份目录 | `/opt/xiyu-ai/data/backups` |

### 同机但不属于 Xiyu 的服务

这些资源不能在 Xiyu 维护时改动：

- LIMI 后端：`/home/admin/LIMIbackend`，服务 `limi-backend.service`，监听 `127.0.0.1:8000`
- 现有游戏项目：`/opt/capybara-game`，PM2 进程 `limi-kid`，监听 `127.0.0.1:18001`
- 现有域名：`myworlds.cn`、`game.myworlds.cn`

Xiyu 不共享上述项目的代码目录、数据库、运行用户、端口、日志或环境变量。

## 3. Nginx 与 HTTPS

- Xiyu Nginx 配置：
  - `/etc/nginx/sites-available/xiyu-ai`
  - `/etc/nginx/sites-enabled/xiyu-ai`
- HTTPS 证书：`/etc/letsencrypt/live/xiyu.myworlds.cn/`
- 证书由 Certbot 管理并自动续期。

典型链路：

```text
浏览器
  -> https://xiyu.myworlds.cn
  -> Nginx 443
  -> 127.0.0.1:3000
  -> Xiyu Node 服务
```

修改 Nginx 后必须先检查再重载：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 4. 当前配置与数据来源

本次部署同步了本机当前 Xiyu 的数据和配置：

- 本机项目来源：`E:\FoxSpirit\xiyu-ai`
- 数据库使用 SQLite 在线备份快照迁移，迁移前完整性检查为 `ok`
- 迁移后关键数据数量与本机一致：用户 1、溪语角色 1、微信绑定 2、记忆实体 11
- API 密钥和其他敏感配置复用了本机 `.env`，但本文不记录任何密钥值

服务器运行时覆盖了以下部署相关配置：

```text
API_PORT=3000
API_HOST=127.0.0.1
DB_PATH=/opt/xiyu-ai/data/bot.db
XIYU_WORKBENCH_CONTEXT_URL=http://127.0.0.1:4175
```

其中 `API_HOST=127.0.0.1` 是为了确保 Xiyu 不直接暴露 3000 端口；工作台桥接同样通过 systemd drop-in 指向同机 `127.0.0.1:4175`，避免依赖公网 EdgeOne 是否暴露 `/api/*` 路由。这是部署安全配置，不改变业务逻辑。

## 5. 日常运维命令

以下命令在服务器上执行。登录账号需要通过阿里云控制台或已有 SSH 凭据获取；密码、API 密钥不要写进本文或命令历史。

### 查看服务

```bash
sudo systemctl status xiyu-ai --no-pager
sudo systemctl is-active xiyu-ai
sudo ss -lntp | grep ':3000'
```

### 查看实时日志

```bash
sudo journalctl -u xiyu-ai -f
```

### 重启 Xiyu

```bash
sudo systemctl restart xiyu-ai
sudo systemctl status xiyu-ai --no-pager
curl -fsS https://xiyu.myworlds.cn/api/health
```

### 查看关键状态

```bash
sudo systemctl is-active xiyu-ai limi-backend nginx xiyu-ai-backup.timer
free -h
df -h /
```

## 6. 数据库备份与恢复

### 自动备份

- 定时器：`xiyu-ai-backup.timer`
- 执行时间：每天 04:10（Asia/Shanghai）
- 服务：`xiyu-ai-backup.service`
- 备份目录：`/opt/xiyu-ai/data/backups`
- 默认保留：7 天
- 备份使用 SQLite 在线备份并执行 `PRAGMA integrity_check`

检查定时器和备份：

```bash
sudo systemctl list-timers xiyu-ai-backup.timer
sudo find /opt/xiyu-ai/data/backups -maxdepth 1 -type f -printf '%f %s bytes\\n'
```

手动执行一次备份：

```bash
sudo systemctl start xiyu-ai-backup.service
sudo journalctl -u xiyu-ai-backup.service -n 20 --no-pager
```

### 恢复数据库

恢复前必须先停 Xiyu，避免 WAL 写入冲突。恢复脚本会保留恢复前的旧库：

```bash
sudo systemctl stop xiyu-ai
cd /opt/xiyu-ai
sudo -u xiyu bash scripts/restore-db.sh --list
sudo -u xiyu bash scripts/restore-db.sh --latest
sudo systemctl start xiyu-ai
curl -fsS https://xiyu.myworlds.cn/api/health
```

恢复前先确认要使用的备份文件，不要覆盖同机 LIMI 数据库。

## 7. 更新 Xiyu 的推荐顺序

更新前先备份数据库，并保留当前可运行目录。不要直接删除 `/opt/xiyu-ai`，也不要把新的 `.env` 提交到 Git。

```bash
# 1. 先备份
sudo systemctl start xiyu-ai-backup.service

# 2. 上传或同步新的代码到临时目录，确认内容完整后再替换项目文件
#    保留 /opt/xiyu-ai/.env、/opt/xiyu-ai/data、/opt/xiyu-ai/public/avatars

# 3. 安装依赖（不要用 root 执行 npm install）
sudo -u xiyu -H bash -lc 'cd /opt/xiyu-ai && npm ci --omit=dev'

# 4. 重启并验证
sudo systemctl restart xiyu-ai
sudo systemctl status xiyu-ai --no-pager
curl -fsS https://xiyu.myworlds.cn/api/health
```

如果更新涉及 `src/api.mjs`、主动触发、记忆、企业上下文或消息投递，先阅读：

- `AGENTS.md`
- `docs/xiyu-architecture-maintenance-map.md`

不得为了一个小场景新增第二套调度器、记忆库、企业路由或消息发送链路。

## 8. 故障排查

### 页面打不开或 502

```bash
sudo systemctl status xiyu-ai --no-pager
sudo journalctl -u xiyu-ai -n 100 --no-pager
sudo nginx -t
sudo ss -lntp | grep -E ':(3000|443|80)'
```

### 健康检查失败

```bash
curl -i http://127.0.0.1:3000/api/health
sudo journalctl -u xiyu-ai -n 100 --no-pager
```

如果本机健康检查正常、域名访问异常，优先检查 Nginx 和 DNS，不要先改 Xiyu 数据库。

### 资源不足

当前服务器只有 2 GiB 内存且没有 Swap。Xiyu 当前常驻内存约 100 MB，但图像处理、模型请求或并发增加时可能上升。出现 OOM 前应先观察：

```bash
free -h
sudo journalctl -k -n 100 --no-pager | grep -i -E 'oom|killed process'
```

不要为了临时解决资源问题重启或修改 LIMI 服务。应先评估增加 Swap 或升级服务器规格。

## 9. 本次部署验收结果

- `https://xiyu.myworlds.cn/`：HTTP 200
- `/app/auth.html`：HTTP 200
- `/api/health`：HTTP 200
- Xiyu systemd 服务：active + enabled
- Xiyu 备份定时器：active + enabled
- Limi 原站：HTTP 200
- Limi 的 8000 端口和现有项目的 18001 端口：未改变
- Xiyu 数据库：迁移前后关键数量一致

## 10. 明确禁止事项

- 不要把密码、API Key、微信凭据写入 Git、README 或聊天记录。
- 不要把 Xiyu 的数据库放到 `/home/admin/LIMIbackend` 或其他 LIMI 目录。
- 不要复用 LIMI 的 systemd 服务、PM2 进程或端口。

## 订单系统汇总表监控与溪语收件人

订单表监控复用既有经营主动协同链路，不单独起一个发送器。溪语后台的“经营主动协同”卡片中，打开“订单系统汇总表更新提醒”并设置检查时间（默认 10:00）即可。

收件人不是全局固定的：策略按 `account_id + companion_id` 保存，溪语调度器只为当前活动绑定的账号准备事件；事件也必须带同一个 `actorId` 才能被读取。未来新增人员时，需要为其自己的 Web 账号绑定溪语并单独保存策略；“全部门店”只表示数据范围，不表示把消息广播给所有人。

来源表检查端点为工作台后端的 `/api/feishu/order-monitor/check`，经营事件端点为 `/api/intelligence/events/refresh`。如果线上工作台尚未部署这两个端点，溪语会保持原有聊天行为并记录连接失败，不会把“无法读取”伪装成“未开始更新”。
- 不要直接对 `/opt/xiyu-ai/data/bot.db` 使用 `cp` 覆盖正在运行的数据库；使用备份脚本。
- 不要在没有备份的情况下升级依赖或替换整套目录。
