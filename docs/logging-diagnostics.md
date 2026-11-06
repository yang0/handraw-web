# Handraw 本地故障日志

默认自动启用，服务启动时将日志写入私有存储目录下的 `logs/`。使用 `start-latest.bat` 时通常是项目根目录 `.local/logs/`。

| 文件 | 内容 |
| --- | --- |
| `handraw.log` | INFO 及以上的应用运行事件；设为 DEBUG 时也包含调试事件 |
| `handraw-error.log` | ERROR、CRITICAL 与未捕获异常的完整 traceback |
| `latest-3080.out.log` / `latest-3080.err.log` | 一键启动脚本原有 stdout/stderr 重定向输出；仍予以保留 |

每个文件默认最大 10 MiB，保留 5 个历史文件（`.1`、`.2` 等），避免磁盘无限增长。

## 日志级别

| 级别 | 用途 |
| --- | --- |
| DEBUG | 临时排障：如 `/api/boot` 成功与否 |
| INFO | 启动和正常运行事件（默认） |
| WARNING | 4xx 请求、可预期的服务错误和安全告警 |
| ERROR | 未处理的 HTTP 500 和堆栈（保存到两个文件） |
| CRITICAL | 严重故障，由调用方使用 `logger.critical` 记录 |

在启动服务**之前**设置环境变量（PowerShell）：

```powershell
$env:HANDRAW_LOG_LEVEL = "DEBUG"     # 可选 DEBUG/INFO/WARNING/ERROR/CRITICAL
$env:HANDRAW_LOG_MAX_BYTES = "10485760"
$env:HANDRAW_LOG_BACKUPS = "5"
# 可选自定义目录：
# $env:HANDRAW_LOG_DIR = "D:\\HandrawLogs"
.\start-latest.bat
```

无需为了普通的 HTTP 500 开启 DEBUG；INFO 默认也会记录完整异常堆栈。DEBUG 仅在需要更细粒度定位时短暂启用。

## 复现报错并分享

1. 复现 Google 登录后页面错误，记录页面上的 `请求编号`。浏览器 Network 中对应 500 响应也包含 `X-Request-ID`。
2. 在 PowerShell 查看：
   ```powershell
   Get-Content .\.local\logs\handraw-error.log -Tail 150 -Encoding UTF8
   Get-Content .\.local\logs\handraw.log -Tail 150 -Encoding UTF8
   ```
3. 根据 `request_id=<请求编号>` 在日志中查找相同错误：
   ```powershell
   Select-String -Path .\.local\logs\handraw-error.log* -Pattern "request_id=你的请求编号"
   ```

日志**不主动记录** Cookie、请求体、HTTP Header 或 URL 查询字符串。异常信息中的常见密钥形式也会做基础脱敏，但第三方异常可能仍包含个人信息、数据库行内容或自定义秘密；发送日志之前请人工检查并遮盖 Token、邮箱、数据库连接串和真实用户数据。

后端 500 响应统一返回 `code=internal_error` 和随机 `requestId`，不再向浏览器显示 SQL 或 Python 异常原文。错误日志记录相同 ID、请求方法、路径和完整 traceback，方便对应定位。

## 验证

```powershell
python -m unittest tests.test_logging_diagnostics -v
```
