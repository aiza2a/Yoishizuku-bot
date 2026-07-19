#!/usr/bin/env python3
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

root = Path(tempfile.mkdtemp(prefix='gptbot-allow-cmd-', dir='/tmp'))
os.environ['ACCESS_CONTROL_FILE'] = str(root / 'access_control.json')
sys.path.insert(0, '/home')

import config
config.ADMIN_LIST = ['90001']
config.whitelist = ['90001']
config.GROUP_LIST = []
import access_control
import bot

class FakeBot:
    def __init__(self):
        self.messages = []
    async def send_message(self, **kwargs):
        self.messages.append(kwargs)


def make_update(chat_id, chat_type='private', user_id=90001):
    message = SimpleNamespace(
        chat_id=str(chat_id), is_topic_message=False, message_thread_id=None,
        message_id=1, text='/allow', reply_to_message=None, photo=None,
        voice=None, document=None, audio=None, caption=None,
        chat=SimpleNamespace(type=chat_type), from_user=SimpleNamespace(is_bot=False),
    )
    return SimpleNamespace(
        effective_user=SimpleNamespace(id=user_id, first_name='Master', username='master'),
        effective_chat=SimpleNamespace(type=chat_type),
        message=message, edited_message=None, callback_query=None,
    )

async def run():
    fake = FakeBot()
    ctx = SimpleNamespace(args=[], bot=fake)
    await bot.allow_command(make_update('90001'), ctx)
    assert '/allow 635…' in fake.messages[-1]['text']

    ctx.args = ['6359487083']
    await bot.allow_command(make_update('90001'), ctx)
    assert access_control.is_user_allowed('6359487083')

    ctx.args = ['-1006359487083']
    await bot.allow_command(make_update('-10090001', 'supergroup'), ctx)
    assert access_control.is_group_allowed('-1006359487083')
    assert '成员' in fake.messages[-1]['text']

    reached = []
    @bot.decorators.GroupAuthorization
    @bot.decorators.Authorization
    async def group_action(update, context):
        reached.append(update.effective_user.id)
    await group_action(make_update('-1006359487083', 'supergroup', user_id=777777), ctx)
    assert reached == [777777]
    print('allow_usage_ellipsis_ok')
    print('allow_command_user_ok')
    print('allow_command_group_ok')
    print('allowed_group_any_member_ok')

try:
    asyncio.run(run())
finally:
    for path in root.glob('*'):
        path.unlink(missing_ok=True)
    root.rmdir()
