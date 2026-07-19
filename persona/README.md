# persona 结构

- `modules/`：人设正文的唯一维护来源。
- `systemprompt.md`：生产构建产物。
- `build_persona_prompt.py`：按模块文件名字典序无损拼接。
- `start_message.txt`：`/start` 欢迎语。
- `bot_description.txt`：Telegram Bot 简介。
- `persona.env`：角色文本入口配置。

修改人设后执行：

```bash
python3 /root/data/docker_data/gptbot/persona/build_persona_prompt.py
```

构建后应比较修改前后的差异，再重启服务。
