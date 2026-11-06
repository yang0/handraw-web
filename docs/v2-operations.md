# Handraw Web 2.0 运维与恢复

本文对应新版 Python 服务的运维操作约束。如果使用本地 PostgreSQL 16 + Redis 架构运行，完整的原生与脚本化运维命令参见 [本地 PostgreSQL + Redis 运维手册](local-operations.md)。

## 1. 路径与边界

工具入口是 `ops/v2_manage.py`。默认读取当前 workspace 的 `.local/handraw_v2.db`、`.local/uploads` 和 `.local/demo_generated`；线上建议显式指定私有存储路径：

```bash
python3 ops/v2_manage.py \
  --root /srv/handraw-web \
  --db /var/lib/handraw/private/handraw_v2.db \
  --uploads /var/lib/handraw/private/uploads \
  --generated /var/lib/handraw/private/generated \
  health --url http://127.0.0.1:3080/api/health
```

私有数据库、上传文件、生图文件和 `image-service.json` 不加入 Git。备份目录同样按敏感数据处理：目录权限建议 `700`，文件权限建议 `600`。

## 2. 在线一致备份

`backup` 使用 SQLite Online Backup API，不直接复制正在写入的 `.db-wal` 文件；因此应用可以在线运行，得到的是一个一致的 SQLite 快照。工具还会复制 `uploads` 与 `generated`，并生成 `manifest.json`：

```bash
python3 ops/v2_manage.py \
  --root /srv/handraw-web \
  --db /var/lib/handraw/private/handraw_v2.db \
  --uploads /var/lib/handraw/private/uploads \
  --generated /var/lib/handraw/private/generated \
  backup --output-dir /var/backups/handraw-v2
```

每次执行都会新建不可覆盖的时间戳目录，包含：

- `database.sqlite3`：一致快照，并经过 `integrity_check` 与 `foreign_key_check`；
- `uploads/`、`generated/`：私有媒体及 SHA-256、大小、相对路径清单；
- `manifest.json`：workspace 指纹、目标路径指纹、schema migration 版本、数据库和媒体 checksum。

manifest 不写入环境变量、API key、密码、Cookie 或其他凭据。备份数据库本身仍包含账号数据和密码哈希，不能按公开文件处理。

验证备份：

```bash
python3 ops/v2_manage.py --root /srv/handraw-web \
  --db /var/lib/handraw/private/handraw_v2.db \
  --uploads /var/lib/handraw/private/uploads \
  --generated /var/lib/handraw/private/generated \
  verify --backup /var/backups/handraw-v2/handraw-v2-<timestamp>
```

验证会在任何恢复动作前检查 manifest、SQLite 完整性、所有私有媒体 checksum 以及当前 workspace/目标路径指纹。

## 3. 恢复前置条件与恢复

恢复是显式维护动作。工具不会替你停止 systemd、worker、网关或其他写入进程；没有 `--stop-write` 会直接拒绝：

```bash
# 先由维护者停止应用及所有会写 SQLite/uploads/generated 的进程。
sudo systemctl stop handraw-v2.service

python3 ops/v2_manage.py \
  --root /srv/handraw-web \
  --db /var/lib/handraw/private/handraw_v2.db \
  --uploads /var/lib/handraw/private/uploads \
  --generated /var/lib/handraw/private/generated \
  restore \
  --backup /var/backups/handraw-v2/handraw-v2-<timestamp> \
  --stop-write --dry-run

python3 ops/v2_manage.py \
  --root /srv/handraw-web \
  --db /var/lib/handraw/private/handraw_v2.db \
  --uploads /var/lib/handraw/private/uploads \
  --generated /var/lib/handraw/private/generated \
  restore \
  --backup /var/backups/handraw-v2/handraw-v2-<timestamp> \
  --stop-write

sudo systemctl start handraw-v2.service
```

恢复流程：

1. 先做完整预检，workspace 或数据库/uploads/generated 目标不一致就拒绝；
2. 对当前状态再做一个 `handraw-v2-pre-restore-*` 备份；
3. 检查备份 schema 版本；如果当前数据库版本更高，拒绝数据库降级；
4. 原子替换数据库及私有媒体目录；
5. 恢复后再次检查 checksum/integrity，失败则回滚到本次恢复前的路径；
6. 成功后清理暂存旧路径，但恢复前备份仍保留。

代码回滚不包含数据库回滚。即使恢复旧代码，也不能把数据库 migration 降回旧版本；需要先使用兼容旧代码的数据库策略，或制定单独的前向迁移方案。

## 4. 健康状态

新版服务暴露最小的 `/api/health`。工具只保留 `ok`、HTTP status、version 和 `db` 四个字段，不打印响应中可能出现的其他内容：

```bash
python3 ops/v2_manage.py health --url http://127.0.0.1:3080/api/health
```

systemd 示例固定绑定 `127.0.0.1`，由 Nginx 或其他受控反向代理转发。不要把 `HANDRAW_HOST` 改成公网通配地址，除非已经有单独的边界策略和审核记录。

## 5. 首个真实 admin

空的生产 SQLite 可以用 CLI 创建首个真实 admin；它不会加载演示 seed、不会写欢迎积分、不会设置默认密码，也不会把密码打印到终端：

```bash
umask 077
python3 ops/v2_manage.py \
  --root /srv/handraw-web \
  --db /var/lib/handraw/private/handraw_v2.db \
  bootstrap-admin \
  --username owner_admin \
  --display-name 'Handraw 主理人' \
  --email owner@example.com
```

工具会交互式要求输入两次密码。密码至少 12 位，同时包含字母和数字；也可以用 `--password-stdin` 传入两行密码，但应确保 shell 历史和进程日志不会保存输入。已有 active admin 时会拒绝重复 bootstrap。`HANDRAW_DEMO_MODE=1` 时也会拒绝，避免把真实管理员写进演示库。

## 6. systemd 示例

`ops/handraw-v2.service.example` 是示例，不会自动安装。它明确指定 `/srv/handraw-web/.venv/bin/python`、`/etc/handraw/handraw-v2.env`、loopback 监听和 `/var/lib/handraw/private` 可写目录。部署前由维护者创建对应用户、目录、venv 和环境文件，并单独管理 image-service 凭据。

示例检查：

```bash
sudo install -o root -g root -m 0644 ops/handraw-v2.service.example /etc/systemd/system/handraw-v2.service
sudo systemctl daemon-reload
sudo systemctl enable --now handraw-v2.service
sudo systemctl status handraw-v2.service
```

以上命令只是安装示例单元的操作说明；本次代码任务没有运行这些命令，也没有实际部署服务器。

## 7. 自动备份计划（未配置）

当前仓库没有自动备份 timer、cron 或远端对象存储凭据，不能把“工具可执行”描述成“已经自动备份”。如果维护者确认保留策略、磁盘和异地复制后，可安排类似计划任务：

```cron
# 示例：每天 03:15 UTC 执行；需要维护者自行配置、限权和轮换策略。
15 3 * * * /srv/handraw-web/.venv/bin/python /srv/handraw-web/ops/v2_manage.py --root /srv/handraw-web --db /var/lib/handraw/private/handraw_v2.db --uploads /var/lib/handraw/private/uploads --generated /var/lib/handraw/private/generated backup --output-dir /var/backups/handraw-v2 >> /var/log/handraw-v2-backup.log 2>&1
```

配置后仍要定期执行 `verify`，并做一次隔离 workspace 的试恢复；仅有备份文件而没有恢复演练，不算完成灾备闭环。
