# Yoishizuku-bot RUNBOOK

## 启动
```bash
docker compose up -d
```

## 验收
```bash
sh scripts/verify.sh
```

## 修改人设
编辑 `persona/modules/*.md`，然后：
```bash
python3 persona/build_persona_prompt.py
sh scripts/verify.sh
```

## 备份
```bash
mkdir -p /root/backups/yoishizuku-bot
stamp=$(date -u +%Y%m%dT%H%M%SZ)
python3 scripts/backup_memory.py "/root/backups/yoishizuku-bot/memory-$stamp.sqlite3"
tar -czf "/root/backups/yoishizuku-bot/source-$stamp.tar.gz" \
  --exclude='.env' --exclude='data' .
```
