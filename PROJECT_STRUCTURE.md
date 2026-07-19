# Yoishizuku-bot 项目结构

基于 yym68686/ChatGPT-Telegram-Bot (TeleChat) 的 Telegram AI Bot。

## 根目录
- `.env.example`：配置模板。
- `docker-compose.yml`：非 root、只读根文件系统和资源限制配置。
- `app/`：自定义代码，通过 Docker volume 注入覆盖上游文件。
- `persona/`：人设模块系统。
- `scripts/`：验证与备份工具。
- `data/`：运行时数据（不进入 Git）。

## app/
- `bot.py`：Telegram 入口、命令处理、会话隔离。
- `config.py`：配置 schema 与用户设置。
- `overrides/`：对上游容器的覆盖层。

## persona/
- `modules/`：人设正文唯一维护源。
- `build_persona_prompt.py`：模块拼接脚本。
- `persona.env`：角色文本入口配置。

## scripts/
- `verify.sh`：完整验收。
- `daily_backup.sh`：每日备份。
- `healthcheck.py`：Docker 健康检查。
