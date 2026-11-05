# 手绘风 Web（私有）

独立门户、作品与经验分享、社区资源、积分下载、个人收藏及 Skill 同步。

本仓库扩展现有 Discourse，不包含论坛源码或生产数据。公开 Skill 和静态资源仓库保持独立。

## 日常操作

```powershell
./ops/web.ps1 update
./ops/web.ps1 status
./ops/web.ps1 deploy -Commit <完整提交号>
./ops/web.ps1 rollback
```

开发、测试、数据规则和试运行说明见 `docs/`。

本地新版只启动一个后端：`python -X utf8 -m backend.server --port 3080`。首页为 `/`，创作台为 `/studio/`，社区为 `/forum/`，后台为 `/admin/`。部署后保留二级域名，各域名反向代理到同一端口并保留 Host，见[单后端运行说明](docs/single-backend.md)。

产品定位与改版范围见 [产品文档](docs/product-direction.md)。产品评审与 DeepSeek 任务分派见 [协作说明](docs/deepseek-workflow.md)；当前本地产品评审见 [2026-10-28 评审](docs/product-review-2026-10-28.md)。

本地 `/web` 文件夹包含原有私人配置，始终不纳入 Git。运行中的用户数据、附件及凭据同样不进入版本库。
