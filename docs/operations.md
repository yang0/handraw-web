# 操作与恢复

## 同步

本地提交并推送 `main`，服务器部署指定完整 SHA。服务器只读部署密钥不能推送。紧急修复使用维护者身份形成提交后回流主分支，禁止覆盖同步。

`ops/web.ps1 update` 拒绝脏工作区并只快进拉取；`status` 显示两端版本；`deploy -Commit SHA` 推送已提交代码并发布指定版本；`rollback` 恢复上一版本代码，不降级数据库。

运行依赖：Windows PowerShell、Git、OpenSSH；服务器沿用现有 Ruby、PostgreSQL、Redis、Nginx 和 Supervisor。

## 数据边界

`/home/yang0/handraw-data/private` 保存受保护资源；`deployment` 保存发布状态与迁移前数据库备份。目录不在 Nginx 静态根下，不加入 Git。备份目录权限 700，文件权限 600。初次接管快照位于 `/home/yang0/backups/handraw-web-20261021T004449Z`。

恢复生产数据须停止写入、验证备份并由维护者明确执行，不包含在代码回滚命令中。正常升级只新增表和索引。

## 试运行

`handraw_enabled` 控制整个扩展；默认关闭。启用后公开浏览，默认仅工作人员可发布与解锁。通过 `handraw_pilot_group_ids` 加入十至二十名创作者；通过 `handraw_reviewer_group_ids` 指定版主。`handraw_public_submissions` 在试运行验收后开启。不会自动发送邀请。

预览库为 `handraw_web_preview`，测试库为 `handraw_web_test`；分别使用 Redis 数据库 12、13。预览只监听 127.0.0.1:3010，不启动邮件或后台任务工作进程，通过 `ops/web.ps1 preview` 建立隧道。按需启动 `ops/preview-server.sh`，验收后停止，降低内存占用。

## 故障操作

- 先访问 `/latest` 判断原论坛是否可用，再检查 `/studio/api/boot`。
- 关闭 `handraw_enabled` 前先撤销 Nginx 首页映射，恢复论坛首页。
- 发布停止通常是代码未提交或核心目录相对已保存基线发生变化。先备份、审查变化，不能用 reset --hard 绕过。
- 私有资源损坏：暂停下载，处理报告并退款；不删除历史账本。
- 积分追回超过作者余额时保留负数并冻结消费，补足后由另一位版主解冻。
