# Yoishizuku-bot 项目结构

Yoishizuku-bot 是基于 TeleChat 的独立本地化项目。运行镜像由 GitHub Actions 构建，业务代码、人设和覆盖层直接写入镜像；运行时仅挂载持久化数据目录。

```text
.
├── app/
│   ├── bot.py                  Telegram 入口、私聊/群聊/Guest 路由、流式输出
│   ├── config.py               配置、用户偏好、模型与用户配置持久化
│   └── overrides/
│       ├── memory_store.py         SQLite 记忆、摘要、用户成长与角色共享记忆
│       ├── role_dialogue_store.py  角色与对话档案
│       ├── access_control.py       动态 /allow 名单
│       ├── decorators_override.py  鉴权与装饰器
│       ├── i18n_override.py        扩展界面文案
│       ├── bot_utils_scripts.py    消息解析、昵称别名、语音辅助
│       └── aient_*.py              AI 引擎覆盖层
├── persona/
│   ├── modules/                人设正文唯一维护源
│   ├── build_persona_prompt.py 人设构建脚本
│   ├── persona.env             人设入口及展示文本配置
│   └── *.txt                   启动消息与 bot 描述
├── scripts/                    验证、健康检查、备份、回归脚本
├── data/                       运行时持久化数据，不进入 Git
│   ├── user_configs/           用户模型与偏好
│   ├── memory/                 SQLite 长期记忆与摘要
│   ├── roles/                  角色、档案与共享记忆
│   └── access/                 动态授权名单
├── .github/workflows/          推送 main 时构建并发布 GHCR 镜像
├── Dockerfile                  基于固定上游摘要的自定义镜像定义
├── docker-compose.yml          生产运行配置与数据卷
├── .env.example                配置模板
├── README.md                   主说明文档
└── RUNBOOK.md                  日常部署、核验和备份说明
```

## Docker 中的关键路径

| 宿主机目录 | 容器路径 | 作用 |
|---|---|---|
| `./data/user_configs` | `/home/user_configs` | 用户配置 |
| `./data/memory` | `/home/memory_data` | SQLite 记忆 |
| `./data/roles` | `/home/role_data` | 角色与档案 |
| `./data/access` | `/home/access_data` | 动态授权名单 |

容器以 UID/GID `10001` 运行，根文件系统只读；新增运行时文件必须位于已挂载的数据目录或 `/tmp`。

## 镜像与代码关系

- `Dockerfile` 将 `app/`、`persona/` 和 `scripts/healthcheck.py` 写入镜像。
- `.github/workflows/docker-build.yml` 在 `main` 更新后发布 `ghcr.io/aiza2a/yoishizuku-bot:latest` 及短提交标签。
- `docker-compose.yml` 默认不再挂载源码。需要本地调试时，可启用其中已注释的只读挂载项。
