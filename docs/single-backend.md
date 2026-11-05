# 单后端运行

目前只启动一个 Python 进程和一个 HTTP 监听端口。首页、创作台、社区和管理后台共用 API、数据库及生成任务管理。

Windows 双击项目根目录的 `service.bat`，选择启动、关闭、重启或查看状态。服务在后台运行，退出菜单不会关闭服务；日志在 `.local/logs/`。脚本会核对端口进程与本项目数据库，只关闭属于本项目的服务。

也可使用 `service.bat start`、`service.bat stop`、`service.bat restart`、`service.bat status`。

```powershell
python -X utf8 -m backend.server --port 3080
```

本地入口：

| 页面 | 地址 |
| --- | --- |
| 首页 | http://127.0.0.1:3080/ |
| 创作台 | http://127.0.0.1:3080/studio/ |
| 社区 | http://127.0.0.1:3080/forum/ |
| 后台 | http://127.0.0.1:3080/admin/ |

`/studio.html`、`/forum.html`、`/admin.html` 保留兼容。3081–3083 不再启动监听器。更换本地端口时，通过 `HANDRAW_ALLOWED_ORIGINS` 明确设置允许的浏览器来源。

## 部署后的二级域名

| 域名 | 后端入口 |
| --- | --- |
| handraw-style.com | 同一服务，首页 |
| studio.handraw-style.com | 同一服务，创作台 |
| forum.handraw-style.com | 同一服务，社区 |
| admin.handraw-style.com | 同一服务，后台 |

反向代理全部指向 `127.0.0.1:3080`。后端读取原始 Host 来选择前端入口；API 的权限仍由登录身份决定。

Nginx 的相关配置片段如下。将 location 用于各域名已有的 HTTPS server 块，沿用其证书配置：

```nginx
# http 块
upstream handraw_backend {
    server 127.0.0.1:3080;
}

# 各域名的 server 块中
location / {
    proxy_pass http://handraw_backend;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
}
```

默认绑定回环地址，由反向代理接入公网。域名导航、原有登录 Cookie 和后台 API 鉴权保留。生产默认允许的来源仍为现有网站域名；新增域名需要明确配置 `HANDRAW_ALLOWED_ORIGINS`。

本次只调整本地应用，未修改生产 Nginx、DNS、证书或 Discourse。生产发布继续遵循备份、精确提交与数据库只增不减的规则。

## 2026-10-29 本地验证

- 实际仅监听 3080；原 3081–3083 及旧预览服务已停止，默认本地数据库保留并备份。
- 四个本地页面和 API 返回正常；本机携带四个生产域名的 Host 请求，可从同一端口得到对应前端。
- 47 项后端测试、7 组前端检查通过，覆盖单次创建监听器、路径与域名分发、登录会话、后台拒绝匿名和普通用户访问、同源导航及既有业务。
- 浏览器验证 `/studio/` → `/forum/` 导航，所有主导航均指向 3080。截图：`.local/product-refresh/acceptance/single-backend-community.jpg`。
