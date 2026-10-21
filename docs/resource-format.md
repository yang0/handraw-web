# 资源包与接口

ZIP 根目录必须包含 `manifest.json`，schema_version 固定为 1：

```json
{
  "schema_version": 1,
  "resource": {
    "id": "stable-author-resource-id",
    "kind": "style",
    "name": "纸感水彩",
    "version": "1.0.0",
    "prompt_zh": "只描述媒介、线条、材质、色彩及空间机制。",
    "prompt_en": "Describe visual language independently of the subject.",
    "license": "允许个人与商业创作输出，原包再次分发需要作者授权。",
    "examples": ["主题一及使用证据", "主题二及使用证据", "主题三及使用证据"]
  }
}
```

kind 支持 `work / experience / style / layout / package`。画风与图型必须包含中英文定义；审核通过需要三个不同主题示例。上传更新会撤销当前下载审批，要求重新审核，原有用户的解锁资格保留。

## 同源 API

API 位于 `/studio/api`，使用现有 Discourse 会话、CSRF 或受支持的用户 API 凭据。写操作检查试运行资格；审核检查工作人员或指定群组及禁止自审规则。

- `GET /boot`：用户、权限、官方入口与部署版本。
- `GET /feed?kind=style&page=1&q=...`：社区发现；`GET /creators/:username`：作者主页。
- `POST /entries`：创建投稿及其讨论帖。正文与介绍公开，不接受隐藏资源定义字段。
- `POST /entries/:id/bundle`：作者上传完整 ZIP；`GET /entries/:id/download`：仅作者与有效解锁用户可下载。
- `POST /entries/:id/unlock`：传 `price` 与 `price_revision`，事务性扣费并创建永久资格，重试不重复扣费。
- `POST /entries/:id/collection`、`DELETE`：免费收藏与取消。
- `GET /library`：自己的投稿、收藏和已解锁资源，解锁项提供下载地址及 SHA256。
- `GET /wallet`、`POST /welcome`：账本与一次性新人任务。
- `POST /entries/:id/events`：有效曝光、详情访问、使用后有用／不太有用反馈。
- `GET /review`、`POST /entries/:id/review`：版主审核、报告处理与审计记录。
- `POST /entries/:id/report`、`POST /entries/:id/appeal`：问题报告及作者申诉。
- `POST /unlocks/:id/refund`、`POST /wallets/:id/freeze`：退款、收益追回与账户冻结。

完整附件没有静态公开路径。详情接口不返回 bundle_key、存储绝对路径或包内提示词。原始账目不修改，退款与收益追回追加新的账目记录。
