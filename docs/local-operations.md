# Handraw Web 本地 PostgreSQL + Redis 运维手册

本文档记录 Handraw Web 在 Windows 本地环境升级为 **PostgreSQL 16 + Redis** 后的完整运维、启停、监控、备份恢复与排障命令。

---

## 1. 基础设施拓扑与路径

为保证开发环境清爽且不占用系统盘，所有数据库与中间件均部署在 **D 盘**：

| 组件 | 版本 | 部署路径 | 默认端口 | 职责 |
| :--- | :--- | :--- | :--- | :--- |
| **PostgreSQL** | 16.15 (x64) | `D:\PostgreSQL\pgsql\`<br>数据：`D:\PostgreSQL\data\` | `5432` | 核心权威数据库（业务库 `handraw_v2`） |
| **Redis** | 3.0.504 (RESP2) | `D:\Program Files\Redis\` | `6379` | 跨进程原子限流、OAuth State 临时缓存 |
| **Python** | 3.13.9 | `D:\Python313\` | - | 依赖 `psycopg[binary]`, `psycopg_pool`, `redis` |
| **Handraw Web** | 2.0 | `E:\projectHome\handraw-web\` | `3080` | 单后端服务（首页/创作台/社区/后台一体） |

---

## 2. 快捷基础设施管理脚本 (`ops/infra.ps1`)

项目内置了 PowerShell 基础设施快捷管理工具：

```powershell
# 查看 PostgreSQL 与 Redis 的实时运行状态
powershell.exe -ExecutionPolicy Bypass -File .\ops\infra.ps1 status

# 一键启动 PostgreSQL 与 Redis 后台服务
powershell.exe -ExecutionPolicy Bypass -File .\ops\infra.ps1 start

# 一键安全停止 PostgreSQL 与 Redis
powershell.exe -ExecutionPolicy Bypass -File .\ops\infra.ps1 stop

# 重启基础设施
powershell.exe -ExecutionPolicy Bypass -File .\ops\infra.ps1 restart

# 直接打开 psql 终端进入 handraw_v2 数据库
powershell.exe -ExecutionPolicy Bypass -File .\ops\infra.ps1 psql

# 直接打开 redis-cli 终端
powershell.exe -ExecutionPolicy Bypass -File .\ops\infra.ps1 redis-cli
```

---

## 3. PostgreSQL 原生运维命令

### 3.1 服务启停与检查

```powershell
# 检查运行状态（含 PID 与数据目录）
& "D:\PostgreSQL\pgsql\bin\pg_ctl.exe" status -D "D:\PostgreSQL\data"

# 启动 PostgreSQL（输出重定向至日志）
& "D:\PostgreSQL\pgsql\bin\pg_ctl.exe" start -D "D:\PostgreSQL\data" -l "D:\PostgreSQL\logfile"

# 平滑停止（-m fast 等待活动连接快速提交并断开）
& "D:\PostgreSQL\pgsql\bin\pg_ctl.exe" stop -D "D:\PostgreSQL\data" -m fast

# 重启
& "D:\PostgreSQL\pgsql\bin\pg_ctl.exe" restart -D "D:\PostgreSQL\data" -m fast
```

### 3.2 命令行与查询

```powershell
# 连接业务数据库
& "D:\PostgreSQL\pgsql\bin\psql.exe" -U postgres -h 127.0.0.1 -d handraw_v2

# 执行单行查询
& "D:\PostgreSQL\pgsql\bin\psql.exe" -U postgres -h 127.0.0.1 -d handraw_v2 -c "SELECT COUNT(*) FROM users;"
```

### 3.3 逻辑备份与恢复

```powershell
# 导出整个 handraw_v2 数据库为压缩归档 (.dump)
& "D:\PostgreSQL\pgsql\bin\pg_dump.exe" -U postgres -h 127.0.0.1 -d handraw_v2 -F c -f "D:\PostgreSQL\handraw_v2_backup.dump"

# 仅导出表结构
& "D:\PostgreSQL\pgsql\bin\pg_dump.exe" -U postgres -h 127.0.0.1 -d handraw_v2 --schema-only -f "D:\PostgreSQL\schema.sql"

# 恢复数据库（-c 清除原有对象后重建）
& "D:\PostgreSQL\pgsql\bin\pg_restore.exe" -U postgres -h 127.0.0.1 -d handraw_v2 -c "D:\PostgreSQL\handraw_v2_backup.dump"
```

### 3.4 从 SQLite 快照迁移数据到 PostgreSQL

```powershell
# 设置临时环境变量（严格防止覆盖生产库）
$env:HANDRAW_PG_STAGING_URL = "postgresql://postgres@127.0.0.1:5432/handraw_v2"
$env:HANDRAW_ALLOW_PG_STAGING = "YES"

# 迁移并进行校验和一致性核对
python ops/sqlite_to_postgres.py --sqlite-snapshot .local/handraw_v2.db --execute
```

---

## 4. Redis 原生运维命令

### 4.1 服务状态与检查

```powershell
# 连通性测试（正常返回 PONG）
& "D:\Program Files\Redis\redis-cli.exe" ping

# 查看运行状态、内存占用与已连接客户端
& "D:\Program Files\Redis\redis-cli.exe" info
```

### 4.2 启停操作

```powershell
# 启动 Redis（前台或脚本隐藏窗口调用）
& "D:\Program Files\Redis\redis-server.exe" "D:\Program Files\Redis\redis.windows.conf"

# 安全持久化并关闭 Redis
& "D:\Program Files\Redis\redis-cli.exe" shutdown
```

### 4.3 缓存清理

```powershell
# 查看所有 Handraw 业务限流 Key
& "D:\Program Files\Redis\redis-cli.exe" keys "handraw:*:rate:*"

# 清理指定限流 Key
& "D:\Program Files\Redis\redis-cli.exe" del "<key>"
```

---

## 5. Handraw Web 单后端运维

### 5.1 环境变量配置 (`.env.local`)

确保 `.env.local` 包含以下配置项：

```env
HANDRAW_PORT=3080
HANDRAW_HOST=127.0.0.1
HANDRAW_BASE_URL=http://localhost:3080

# PostgreSQL 16
HANDRAW_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/handraw_v2
HANDRAW_PG_RUNTIME_ACK=STAGING_ONLY

# Redis (RESP2 协议必须带上 ?protocol=2)
HANDRAW_REDIS_URL=redis://127.0.0.1:6379/0?protocol=2
HANDRAW_REDIS_REQUIRED=1
```

### 5.2 启动与管理

```powershell
# 前台直接启动
python -X utf8 -m backend.server --port 3080

# 或者使用 Windows 服务交互菜单
.\service.bat

# 或者使用 PowerShell 静默后台启动
powershell.exe -ExecutionPolicy Bypass -File .\ops\local-service.ps1 -Action start -Port 3080
```

### 5.3 健康检查与冒烟验证

```powershell
# 1. 基础健康检查
Invoke-RestMethod -Uri "http://127.0.0.1:3080/api/health"
# 预期返回: ok=True, version="2.0.0", db=True

# 2. 系统元数据与当前会话引导
Invoke-RestMethod -Uri "http://127.0.0.1:3080/api/boot"

# 3. 第三方 OAuth 登录状态（Google 与 GitHub）
Invoke-RestMethod -Uri "http://127.0.0.1:3080/api/auth/providers"

# 4. 作品广场公开 Feed（校验从 PostgreSQL 读取作品列表）
Invoke-RestMethod -Uri "http://127.0.0.1:3080/api/works/feed"
```

### 5.4 运行全量存储与高并发集成测试

```powershell
$env:HANDRAW_REDIS_URL = "redis://127.0.0.1:6379/0?protocol=2"
$env:HANDRAW_REDIS_REQUIRED = "1"
$env:HANDRAW_PG_STAGING_URL = "postgresql://postgres@127.0.0.1:5432/postgres"
$env:HANDRAW_PG_PARITY_TEST = "YES"

# 运行 10 项存储、跨线程原子限流与 PG 并发扣费测试
python -m unittest tests/test_production_storage.py -v

# 运行 OAuth 流程测试
python -m unittest tests/test_p2_growth_oauth.py -v
```

### 5.5 Web 日志与请求排障

日常排障优先查看 `.local/logs/web-3080.log`。它包含时间、等级、API 路径、HTTP 状态、请求编号和处理耗时（发送响应头时）；5xx 在存在异常时附带堆栈。健康检查和正常静态资源请求不逐条记录。

```powershell
# 实时查看应用日志，Ctrl+C 只退出查看
Get-Content .local\logs\web-3080.log -Tail 100 -Wait

# 按浏览器响应头 X-Request-ID 或错误 JSON 的 requestId 定位请求
Select-String -Path .local\logs\web-3080.log* -SimpleMatch '<请求编号>'
```

应用日志追加写入，重启保留；单文件达到 10 MiB 后轮转为 `.log.1` 至 `.log.5`。不同端口使用独立文件，例如演示服务为 `web-3097.log`。同端口多进程部署应改用进程外日志收集，不能共享 Python 的轮转文件。

`service-3080.out.log` 仍是启动输出，`service-3080.err.log` 是警告、错误及进程标准错误；使用 `start-latest.bat` 则前缀为 `latest-3080`。这些启动器重定向文件会在重新启动时覆盖，且单次运行没有大小上限，因此历史排障优先使用应用轮转日志。

GET、POST、PUT、DELETE、OPTIONS 共用异常入口；5xx 还在响应出口统一记录，覆盖主动返回的 502/503。浏览器收到未知异常时只显示通用错误及请求编号，详细错误留在服务端。默认请求日志继续关闭，以免原始请求行泄露 OAuth 查询参数；新增请求摘要不记录查询字符串、Cookie、Authorization 或请求体。格式化器额外遮蔽 URL 查询参数、连接串密码及常见 token，但无法识别任意业务文本中的秘密。

目前 `/api/health` 的 `db: true` 是固定返回值，只能证明 HTTP 进程可访问，不能代替数据库、Redis 或业务初始化检查。完整评估与后续建议见 [日志系统评估](logging-review-20261106.md)。

---

## 6. 常见问题与排障

### 6.1 Redis 抛出 `unknown command 'HELLO'`
- **原因**：Python `redis` 客户端 5.x 默认使用 RESP3 协议发送 `HELLO` 握手命令，而 Redis 3.0.x 仅支持 RESP2。
- **解决**：在连接字符串中显式指定协议版本：`redis://127.0.0.1:6379/0?protocol=2`。

### 6.2 PostgreSQL 报 `PostgreSQL 模式不允许 --db`
- **原因**：在开启 `HANDRAW_DATABASE_URL` 时，系统严禁传入 `--db` 或 `--reset-db` 参数以防误伤或回退至 SQLite。
- **解决**：启动时省略 `--db` 参数，统一由环境变量驱动。

### 6.3 端口占用快速查杀
```powershell
# 查找占用 3080 / 5432 / 6379 的进程
Get-NetTCPConnection -LocalPort 3080, 5432, 6379 -State Listen | Select-Object LocalPort, OwningProcess

# 根据 PID 关闭进程
Stop-Process -Id <PID> -Force
```
