# 冷启动内容管理

首批：12 个原创虚构账号、24 篇帖子、31 条回复。题材覆盖绘画、摄影、宠物、科普、包装、手工、脚本与日常交流。6 篇带站内画风参考，正文注明配图来源，不冒充主题成片。

前台使用普通账号、主页、帖子和回复样式。后台用 `cold_start_registry` 记录来源；管理入口是下列命令。不要把这批账号计入自然注册和自然内容增长。

```powershell
# 默认只读，检查将新增和跳过的记录
python -X utf8 ops/seed_cold_start.py --db .local/handraw_v2.db

# 导入前自动备份数据库；重复执行不会重复新增
python -X utf8 ops/seed_cold_start.py --db .local/handraw_v2.db --apply

# 查看首批与其他记录的数量
python -X utf8 ops/seed_cold_start.py --db .local/handraw_v2.db --stats

# 批量下架这批帖子和回复，保留账号与其他用户内容
python -X utf8 ops/seed_cold_start.py --db .local/handraw_v2.db --pause --apply
```

`other_users` 和 `other_topics` 表示注册表外的记录，可能包含旧演示数据，不能直接叫作真实用户或自然增长。暂停后重新运行导入不会自动恢复已下架内容。

账号只有普通用户权限，随机密码不保存，不发放积分、会话或 API 密钥。点赞、收藏、阅读初始为零，回复数来自实际记录。用户名冲突时停止，不接管已有账号。备份位于目标数据库旁的 `backups/`。

本次已导入默认本地数据库 `.local/handraw_v2.db` 和独立预览库 `.local/product-refresh/final-preview/handraw.db`。原 3080 服务的数据库连接未变更；预览使用 3240–3243 端口。生产未导入。
