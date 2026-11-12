# 冷启动内容管理

首批：12 个原创虚构账号、24 篇帖子、31 条回复。题材覆盖绘画、摄影、宠物、科普、包装、手工、脚本与日常交流。6 篇带站内画风参考，正文注明配图来源，不冒充主题成片。

前台使用普通账号、主页、帖子和回复样式。后台用 `cold_start_registry` 记录来源；管理入口是下列命令。不要把这批账号计入自然注册和自然内容增长。

设置 `HANDRAW_DATABASE_URL` 指向目标 PostgreSQL。现有数据库先在单个事务中应用 `backend/postgres_112_cold_start_registry.sql`。新库初始化时会应用此迁移。

```powershell
# 默认只读，检查将新增和跳过的记录
python -X utf8 ops/seed_cold_start.py

# 导入前自动备份数据库；重复执行不会重复新增
python -X utf8 ops/seed_cold_start.py --apply

# 查看首批与其他记录的数量
python -X utf8 ops/seed_cold_start.py --stats

# 批量下架这批帖子和回复，保留账号与其他用户内容
python -X utf8 ops/seed_cold_start.py --pause --apply
```

`other_users` 和 `other_topics` 表示注册表外的记录，可能包含旧演示数据，不能直接叫作真实用户或自然增长。暂停后重新运行导入不会自动恢复已下架内容。

账号只有普通用户权限，随机密码不保存，不发放积分、会话或 API 密钥。点赞、收藏、阅读初始为零，回复数来自实际记录。用户名冲突时整次导入回滚。备份默认位于私有存储的 `backups/`，也可通过 `--backup-dir` 指定。
