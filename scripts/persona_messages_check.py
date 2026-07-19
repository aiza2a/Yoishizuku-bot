#!/usr/bin/env python3
import ast
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path('/home')
BOT_FILE = Path('/home/bot.py')
sys.path.insert(0, '/home')
sys.path.insert(0, str(ROOT / 'app/overrides'))
sys.path.insert(0, str(ROOT / 'app'))

import i18n_override
import utils.decorators as decorators_override

expected_menu = {
    '基本信息', '重置对话', '启动机器人', '切换模型',
    '记忆概况', '成长状态', '删除我的记忆',
}
tree = ast.parse(BOT_FILE.read_text(encoding='utf-8'))
constants = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
assert expected_menu <= constants

assert '重新开始' in i18n_override.strings['message_reset']['zh']
assert any(word in i18n_override.strings['message_reset']['zh'] for word in ('收好', '归档'))
assert '宵雫' in i18n_override.strings['message_doc']['zh']
assert '宵雫' in i18n_override.strings['message_search_stage_1']['zh']
assert i18n_override.strings['button_change_model']['zh'] == '模型'
bot_source = BOT_FILE.read_text(encoding='utf-8')
assert '刚才的回答在送出来时出了点问题' in bot_source
assert 'tmpresult = f"{tmpresult}\\n\\n`{e}`"' not in bot_source

old_get_lang = decorators_override.config.get_current_lang
decorators_override.config.get_current_lang = lambda convo_id: 'Simplified Chinese'
try:
    update = SimpleNamespace(effective_user=SimpleNamespace(first_name='Hanabi4a', username='Hanabi4a', id=6359487083))
    message = decorators_override.ban_message(update, '6359487083', 'user')
    assert 'Hi,' not in message
    assert '您没有权限访问' not in message
    assert 'Hanabi4a' in message
    assert '6359487083' in message
    assert '抱歉' in message
finally:
    decorators_override.config.get_current_lang = old_get_lang

print('persona_system_messages_ok')
print('info_and_command_panels_preserved')
