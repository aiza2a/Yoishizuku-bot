#!/usr/bin/env python3
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, '/home')
import config
from utils.scripts import CutNICK, _matched_nick_prefix

config.NICK = '藍沢宵雫'
config.NICK_ALIASES = ['宵雫', '小雫', 'Shizuku']
config.NICK_NAMES = ['藍沢宵雫', '宵雫', '小雫', 'Shizuku']

private = SimpleNamespace(chat=SimpleNamespace(type='private'), reply_to_message=None)
group = SimpleNamespace(chat=SimpleNamespace(type='supergroup'), reply_to_message=None)

assert _matched_nick_prefix('藍沢宵雫 帮我查天气', config.NICK_NAMES) == '藍沢宵雫'
assert _matched_nick_prefix('宵雫，帮我查天气', config.NICK_NAMES) == '宵雫'
assert _matched_nick_prefix('小雫: 帮我查天气', config.NICK_NAMES) == '小雫'
assert _matched_nick_prefix('shizuku 帮我查天气', config.NICK_NAMES) == 'Shizuku'
assert _matched_nick_prefix('宵雫你好', config.NICK_NAMES) is None
assert _matched_nick_prefix('小雫子，测试', config.NICK_NAMES) is None

assert CutNICK('宵雫，帮我查天气', group) == '帮我查天气'
assert CutNICK('Shizuku: test', group) == 'test'
assert CutNICK('普通群消息', group) is None
assert CutNICK('普通私聊消息', private) == '普通私聊消息'
assert config.NICK == '藍沢宵雫'

print('nick_alias_primary_preserved')
print('nick_alias_full_prefix_match_ok')
print('nick_alias_false_positive_blocked')
print('nick_alias_private_chat_unchanged')
