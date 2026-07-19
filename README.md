<p align="center">
  <img src="./assets/logo-3071751.jpg" width="160" alt="藍沢宵雫">
</p>

# 藍沢宵雫 · Yoishizuku-bot

面向个人长期使用的 Telegram AI 角色机器人。项目基于 TeleChat 的 OpenAI 兼容 API 能力重构，加入藍沢宵雫人设、角色与对话档案、SQLite 长期记忆、权限控制，以及 Telegram 最新的 Draft / Guest / Rich Message 能力。

镜像：`ghcr.io/aiza2a/yoishizuku-bot:latest`
部署方式：Docker Compose
主要语言：简体中文

## 特性

- **私聊编辑流**：默认发送常规占位消息后实时编辑；设置 `DRAFT_MODE=1` 才启用 Telegram Draft 临时预览，结束后发送正式消息。
- **群聊编辑流**：群内提及、回复及普通群会话使用 `editMessageText` 流式更新。
- **Guest Chat Mode**：开启后无需邀请 bot 进群，可在任意支持的聊天中用 `@Yoishizuku_bot 问题` 临时召唤。Guest 回复通过 `answerGuestQuery` 发回原聊天，并使用内联消息编辑流更新。
- **Rich Message 可选模式**：设置 `RICH_MESSAGE=1` 后使用 Telegram Bot API 10.0 富文本消息，支持标题、表格、引用、LaTex、可折叠内容及嵌入媒体；默认保持 MarkdownV2 兼容模式。
- **角色与对话档案**：`/persona` 可管理角色和独立对话档案；不同档案隔离对话历史、记忆与成长状态。
- **持久记忆**：SQLite 保存对话摘要、长期记忆、用户档案和角色共享记忆；支持 `/memory`、`/lore`、`/canon`、`/forget`。
- **人设模块化**：`persona/modules/` 是角色设定的维护源，构建脚本会生成最终系统提示词。
- **动态授权**：管理员可用 `/allow <用户ID或群ID>` 将用户或群组写入持久化授权名单。
- **多模态与工具**：沿用上游的图片、语音、文件问答、联网搜索、网页/论文摘要、代码执行与图像生成能力，具体取决于所接入模型和配置。
- **安全容器配置**：非 root、只读根文件系统、最小能力集、资源上限和持久化数据卷。

## 使用方式

| 场景 | 操作 | 输出方式 |
|---|---|---|
| 私聊 | 直接发送文本、图片、语音或文件 | Draft 流，结束后定稿 |
| bot 已在群内 | `@Yoishizuku_bot 问题` 或回复 bot 消息 | 编辑流 |
| bot 不在聊天内 | 开启 Guest Chat Mode 后 `@Yoishizuku_bot 问题` | Guest 专用编辑流 |
| Inline Mode | 输入 `@Yoishizuku_bot 内容`，从候选卡片中选择 | 单次内联结果，不是 Guest 对话 |

Guest Mode 与 Inline Mode 是两项独立功能：Guest 让 bot 以自身身份回复；Inline 是用户从候选卡片中选择并发送内容。

## 部署

### 1. 获取项目

```bash
git clone --recurse-submodules https://github.com/aiza2a/Yoishizuku-bot.git
cd Yoishizuku-bot
cp .env.example .env
mkdir -p data/{user_configs,memory,roles,access}
```

### 2. 配置 `.env`

至少填写：

```dotenv
BOT_TOKEN=从_BotFather_取得的机器人令牌
API_KEY=OpenAI兼容接口密钥
BASE_URL=https://你的接口地址/v1/chat/completions
MODEL=你的默认模型名
ADMIN_LIST=你的Telegram数字用户ID
```

`docker-compose.yml` 从 `ghcr.io/aiza2a/yoishizuku-bot:latest` 拉取已构建镜像；代码不需要再以卷挂载方式覆盖。首次启动前请确认 `.env` 不会被提交到 Git。

### 3. 启动与查看状态

```bash
docker compose pull
docker compose up -d
docker compose ps
docker logs -f Yoishizuku-bot
```

正常启动日志会包含：

```text
Guest Mode 已开启，支持任意聊天 @bot 唤起
Application started
```

升级镜像：

```bash
docker compose pull
docker compose up -d --remove-orphans
```

持久化目录 `data/user_configs`、`data/memory`、`data/roles`、`data/access` 不会因重建容器而丢失。

## BotFather 设置

### 基础设置

1. 在 [@BotFather](https://t.me/BotFather) 创建 bot，得到 `BOT_TOKEN`。
2. 若要把 bot 拉入群组，在 BotFather 的 MiniApp 中打开 **Allow Groups**。
3. 群内仅需响应提及、回复和命令时保持 **Group Privacy** 开启；若要接收群内全部消息才关闭它。

### Guest Chat Mode

在 BotFather MiniApp 的 bot 设置中开启 **Guest Chat Mode**。开启后，用户可以在 bot 不在其中的聊天里输入：

```text
@Yoishizuku_bot 你好
```

Guest 模式的限制来自 Telegram：bot 不会取得聊天历史和成员列表，只会收到这一次召唤消息及 Telegram 附带的必要上下文；每次召唤只能在原聊天中创建一条 Guest 回复并对其编辑。

### Inline Mode（可选）

Inline 与 Guest 无关。只有需要在输入框内看到候选卡片时，才在 BotFather 开启 **Inline Mode** 并填写占位提示。当前项目的内联查询需要输入以 `.` 或 `。` 结尾才会返回候选结果。

## 关键配置

| 变量 | 默认 / 示例 | 用途 |
|---|---|---|
| `BOT_TOKEN` | 必填 | Telegram Bot Token |
| `API_KEY` | 必填 | OpenAI 兼容 API 密钥 |
| `BASE_URL` | 必填 | OpenAI 兼容 Chat Completions 地址 |
| `MODEL` | `deepseek-v4-flash-free` | 默认模型 |
| `ADMIN_LIST` | `123456789` | 管理员 Telegram 数字 ID，逗号分隔 |
| `GROUP_LIST` | `-100...` | 允许使用的群组 ID，逗号分隔 |
| `whitelist` | `123456789` | 初始用户白名单；运行中可用 `/allow` 扩展 |
| `BLACK_LIST` | 空 | 禁止访问的用户/聊天 ID |
| `CHAT_MODE` | `global` | `global` 共享配置；`multiusers` 独立用户配置 |
| `NICK` | 空 | 群内触发昵称前缀 |
| `NICK_ALIASES` | 空 | 额外触发昵称，逗号分隔 |
| `SYSTEMPROMPT` | 见人设文件 | 全局系统提示词；人设文件优先用于本地化角色设定 |
| `PERSONA_FILE` | `persona.env` | 人设入口配置文件 |
| `RICH_MESSAGE` | 未设置 | 设为 `1` 启用 Bot API 10.0 Rich Message |
| `MEMORY_DB_PATH` | `/home/memory_data/gptbot_memory.sqlite3` | SQLite 记忆库路径 |
| `MEMORY_RECENT_TURNS` | `8` | 注入近期对话轮数 |
| `MEMORY_MAX_CONTEXT_CHARS` | `7000` | 记忆注入最大字符数 |
| `MEMORY_SUMMARY_EVERY` | `8` | 每多少轮安排摘要更新 |
| `ROLE_DATA_ROOT` | `/home/role_data` | 角色与对话档案数据目录 |
| `ACCESS_CONTROL_FILE` | `/home/access_data/access_control.json` | 动态授权名单文件 |

完整的上游模型、偏好和插件变量仍可写入 `.env`；以 `app/config.py` 与 `.env.example` 为准。

## 命令

| 命令 | 作用 |
|---|---|
| `/start` | 显示欢迎信息 |
| `/info` | 查看并调整机器人信息、模型与偏好 |
| `/model` | 快速切换模型 |
| `/reset` | 重置当前对话上下文 |
| `/memory` | 查看当前对话的记忆信息 |
| `/forget` | 清理当前对话记忆 |
| `/persona` | 管理角色与对话档案 |
| `/lore` | 查看或编辑当前角色共享记忆 |
| `/canon` | `/lore` 的同义入口 |
| `/role_memory` | 兼容的角色共享记忆入口 |
| `/remember_role <内容>` | 将信息写入当前角色共享记忆 |
| `/state` | 查看当前角色/对话状态 |
| `/allow <用户ID或群ID>` | 管理员持久化授权用户或群组 |
| `/cancel` | 取消当前角色管理输入流程 |

部分命令的可见性、权限与语言会随配置变化。

## 人设、角色与记忆

### 修改人设

编辑 `persona/modules/` 中对应模块后构建：

```bash
python3 persona/build_persona_prompt.py
```

生成的 `persona/systemprompt.md` 是构建产物，不应手工维护。修改后重建镜像或临时挂载相关文件进行调试。

### 数据目录

| 路径 | 内容 | 是否应备份 |
|---|---|---|
| `data/user_configs/` | 用户模型与偏好配置 | 是 |
| `data/memory/` | SQLite 记忆、摘要和成长数据 | 是 |
| `data/roles/` | 角色、对话档案与角色记忆 | 是 |
| `data/access/` | 动态 `/allow` 授权名单 | 是 |
| `.env` | Token、API 密钥与私有配置 | 是，且不得公开 |

## Rich Message 模式

在 `.env` 写入：

```dotenv
RICH_MESSAGE=1
```

然后重建容器：

```bash
docker compose up -d --force-recreate
```

Rich Message 模式使用 Telegram Bot API 10.0 的富文本接口；关闭或移除该变量则回到 MarkdownV2。建议在目标 Telegram 客户端中先实际测试标题、表格、公式和嵌入媒体的显示效果。

## 验证与备份

本地开发环境可运行：

```bash
sh scripts/verify.sh
```

验证脚本会执行 Python 语法检查、Compose 配置检查、回归脚本及容器内检查。运行前需要 Docker Compose、已配置的 `.env` 和可拉取镜像。

备份示例：

```bash
mkdir -p /root/backups/yoishizuku-bot
stamp=$(date -u +%Y%m%dT%H%M%SZ)
python3 scripts/backup_memory.py "/root/backups/yoishizuku-bot/memory-$stamp.sqlite3"
tar -czf "/root/backups/yoishizuku-bot/source-$stamp.tar.gz" \
  --exclude='.git' --exclude='.env' --exclude='data' .
```

备份 `.env` 和 `data/` 时应使用访问受限的位置，避免上传到公开仓库或普通网盘。

## 项目结构

```text
app/
  bot.py                 Telegram 入口、普通对话、Draft、Guest 和 Rich Message 分流
  config.py              配置与用户偏好
  overrides/             记忆、鉴权、角色、i18n 和 AI 引擎覆盖层
persona/
  modules/               人设模块唯一维护源
  build_persona_prompt.py
  persona.env
scripts/                 验证、健康检查、备份与回归脚本
data/                    运行时持久化数据，不进入 Git
Dockerfile                自定义镜像构建文件
.github/workflows/        GitHub Actions 自动构建并发布 GHCR 镜像
```

更细的文件职责见 [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md)，日常运维见 [RUNBOOK.md](RUNBOOK.md)。

## 镜像构建

推送到 `main` 会触发 GitHub Actions 构建镜像并发布到：

```text
ghcr.io/aiza2a/yoishizuku-bot:latest
ghcr.io/aiza2a/yoishizuku-bot:<git短提交>
```

构建工作流位于 `.github/workflows/docker-build.yml`。Docker 镜像基于上游 `yym68686/chatgpt` 固定摘要，并将本项目的 `app/`、`persona/` 和必要脚本写入镜像。

## 来源与许可

Yoishizuku-bot 是独立仓库，不是 GitHub fork。其基础代码来自 [yym68686/ChatGPT-Telegram-Bot](https://github.com/yym68686/ChatGPT-Telegram-Bot)，并包含 `md2tgmd`、`aient` 子模块。保留上游许可证与版权声明；本项目新增部分同样遵循仓库根目录的 [LICENSE](LICENSE)。
