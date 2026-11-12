# Handraw Web PostgreSQL 运维与恢复

工具入口为 `python -m ops.v2_manage`。备份和首个管理员使用 `HANDRAW_DATABASE_URL`。私有媒体位置沿用 `HANDRAW_PRIVATE_STORAGE`、`HANDRAW_UPLOADS_DIR` 和 `HANDRAW_GENERATED_DIR`，也可通过全局参数 `--uploads` 和 `--generated` 指定。安装与服务器版本兼容的 PostgreSQL 客户端工具 `pg_dump` 和 `pg_restore`。

## 备份和校验

```bash
python -m ops.v2_manage backup --output-dir /var/backups/handraw
python -m ops.v2_manage verify --backup '/var/backups/handraw/<备份目录>'
```

每次备份创建新目录，包含 `database.dump`、`uploads/`、`generated/` 和 `manifest.json`。归档和迁移清单从同一 PostgreSQL 快照读取，运行期间未提交的写入不进入备份。清单记录源工作区和目标指纹、归档 SHA-256 以及媒体清单。数据库归档和媒体属于私有数据。

校验可以离线运行。配置源数据库 URL 和源媒体路径后，校验还会匹配源工作区指纹。数据库快照与文件复制分开执行。需要数据库与本地媒体的同一时间点时，备份期间暂停媒体写入和清理。对象存储中的文件需要单独备份。

## 隔离恢复

先创建独立空数据库，并通过 `HANDRAW_RESTORE_DATABASE_URL` 配置目标。使用有权在该库创建归档对象的角色。提供 `HANDRAW_DATABASE_URL` 时，工具会按备份时的源配置匹配指纹。异地恢复可以只配置目标库。两种方式都只连接目标库。

```bash
python -m ops.v2_manage restore --backup '/var/backups/handraw/<备份目录>' \
  --restore-dir /var/lib/handraw/recovery-20261112 --dry-run
python -m ops.v2_manage restore --backup '/var/backups/handraw/<备份目录>' \
  --restore-dir /var/lib/handraw/recovery-20261112
```

工具先核对归档和媒体哈希，再把文件复制到新的私有根目录。数据库归档在单个 PostgreSQL 事务中恢复。归档执行失败时回滚新库并清理此次创建的媒体目录。工具校验恢复后的迁移记录并返回新媒体根目录。现有库和现有媒体路径继续服务。

恢复后的对象归目标连接角色所有。切换前检查应用角色权限、迁移版本和数据，并按需要应用前向迁移。切换数据库连接和媒体根目录由维护者单独执行，代码回滚保留数据库迁移。

## 首个管理员和健康检查

在初始化完成的 V3 业务库中创建首个管理员。

```bash
python -m ops.v2_manage bootstrap-admin \
  --username owner_admin --display-name 'Handraw 主理人' --email owner@example.com

python -m ops.v2_manage health --url http://127.0.0.1:3080/api/health
```

管理员密码通过交互输入两次，或使用 `--password-stdin` 从两行标准输入读取。并发执行时 PostgreSQL 事务只允许创建一个首个管理员。健康检查仅输出服务状态、HTTP 状态码、版本和数据库状态。

服务启停和连接示例见 [本地运维手册](local-operations.md)。
