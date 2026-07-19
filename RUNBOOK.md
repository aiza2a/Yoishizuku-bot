# Yoishizuku-bot 运维手册

## 容器操作

在项目根目录执行：

```bash
docker compose pull
docker compose up -d
docker compose ps
docker logs -f Yoishizuku-bot
```

更新镜像并重建容器：

```bash
docker compose pull
docker compose up -d --remove-orphans
```

停止服务：

```bash
docker compose down
```

`down` 只删除容器和网络，不删除 `data/` 持久化数据卷目录。

## 启动核验

```bash
docker inspect Yoishizuku-bot \
  --format 'status={{.State.Status}} health={{.State.Health.Status}} restart={{.RestartCount}}'
docker logs Yoishizuku-bot --tail 50
```

正常条件：容器为 `running`、健康状态为 `healthy`、重启次数为 `0`。Guest Mode 已在 BotFather 开启时，日志会显示：

```text
Guest Mode 已开启，支持任意聊天 @bot 唤起
```

## 本地验证

```bash
sh scripts/verify.sh
```

该脚本包含 Python 语法、Compose 配置、角色/记忆/授权回归和容器内检查。当前脚本中的容器名仍使用历史名称 `GPTBOT`；在本项目部署目录执行前，需按实际容器名 `Yoishizuku-bot` 调整该检查，或将其作为源码级验证使用。

## 修改人设

编辑 `persona/modules/` 下的模块后构建最终提示词：

```bash
python3 persona/build_persona_prompt.py
```

`persona/systemprompt.md` 为生成结果。修改进入正式镜像的方式是提交到 `main`，等待 GitHub Actions 构建新镜像，再执行镜像更新命令。临时调试可以在 `docker-compose.yml` 中启用注释掉的只读文件挂载。

## 备份

必须备份 `.env` 和全部 `data/`：

```bash
mkdir -p /root/backups/yoishizuku-bot
stamp=$(date -u +%Y%m%dT%H%M%SZ)

python3 scripts/backup_memory.py \
  "/root/backups/yoishizuku-bot/memory-$stamp.sqlite3"

tar -czf "/root/backups/yoishizuku-bot/private-$stamp.tar.gz" \
  .env data/user_configs data/memory data/roles data/access
chmod 600 "/root/backups/yoishizuku-bot/private-$stamp.tar.gz"
```

备份文件包含配置与对话数据，须保存在受限目录，禁止提交或上传至公开位置。

## Guest Mode 排查

```bash
docker logs Yoishizuku-bot --tail 100 | grep -i guest
```

确认项：

1. BotFather MiniApp 已开启 **Guest Chat Mode**。
2. `getMe` 返回 `supports_guest_queries: true`。
3. 机器人镜像版本包含 Guest 更新处理器。
4. 使用 `@Yoishizuku_bot 问题` 进行测试；Guest 与 Inline Mode 是两项独立功能。

Guest 更新不是普通群消息；它使用 Telegram 的 `guest_message` 更新和 `answerGuestQuery` 回答接口，因此 bot 不在群内也可以回复。
