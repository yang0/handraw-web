# 手绘风 Web（私有）

独立门户、作品与经验分享、社区资源、积分下载、个人收藏及 Skill 同步。

本仓库扩展现有 Discourse，不包含论坛源码或生产数据。公开 Skill 和静态资源仓库保持独立。

## 日常操作

```powershell
python -m pip install -r requirements.txt
./ops/web.ps1 update
./ops/web.ps1 status
./ops/web.ps1 deploy -Commit <完整提交号>
./ops/web.ps1 rollback
```

开发、测试、数据规则和试运行说明见 `docs/`。

本地 `/web` 文件夹包含原有私人配置，始终不纳入 Git。运行中的用户数据、附件及凭据同样不进入版本库。
