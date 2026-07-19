import config
import functools
import logging

from md2tgmd.src.md2tgmd import escape
from i18n_override import strings
from utils.scripts import GetMesageInfo
from access_control import is_group_allowed, is_user_allowed


def _lang(convo_id):
    language = str(config.get_current_lang(convo_id) or '')
    if language in ('Simplified Chinese', 'zh', 'zh-cn', 'zh-hans'):
        return 'zh'
    if language in ('Traditional Chinese', 'zh-hk', 'zh-tw', 'zh-hant'):
        return 'zh-hk'
    if language in ('Japanese', 'ja'):
        return 'ja'
    return 'en'


def ban_message(update, convo_id, reason='user'):
    user = getattr(update, 'effective_user', None)
    display_name = (
        getattr(user, 'first_name', None)
        or getattr(user, 'username', None)
        or '你'
    )
    user_id = getattr(user, 'id', '')
    messages = {
        'zh': {
            'user': f'……抱歉，{display_name}。这里暂时只为被允许的人开放。\n你的编号是：`{user_id}`\n若这是误会，请把编号交给主人确认。',
            'group': '……抱歉，这个聊天目前不在允许范围内。若需要在这里使用宵雫，请先让主人把它加入名单。',
            'admin': '这个入口只给主人保留。普通聊天不受影响，其他功能请从菜单中选择。',
            'blacklist': '……抱歉，宵雫现在不能在这里回应。',
        },
        'zh-hk': {
            'user': f'……抱歉，{display_name}。這裡暫時只為獲准的人開放。\n你的編號是：`{user_id}`\n若這是誤會，請把編號交給主人確認。',
            'group': '……抱歉，這個聊天目前不在允許範圍內。若需要在這裡使用宵雫，請先讓主人把它加入名單。',
            'admin': '這個入口只為主人保留。普通聊天不受影響，其他功能請從選單中選擇。',
            'blacklist': '……抱歉，宵雫現在不能在這裡回應。',
        },
        'ja': {
            'user': f'……ごめんなさい、{display_name}。ここは今、許可された方だけが使えます。\nあなたの番号：`{user_id}`\n心当たりがなければ、この番号を主人に伝えてください。',
            'group': '……ごめんなさい。このチャットはまだ利用を許可されていません。必要なら、主人に登録をお願いしてください。',
            'admin': 'この操作は主人だけに残してあります。ほかの機能はメニューから選んでください。',
            'blacklist': '……ごめんなさい。今はここでお返事できません。',
        },
        'en': {
            'user': f'...Sorry, {display_name}. This place is only open to approved users for now.\nYour number is: `{user_id}`\nIf this seems wrong, please send the number to my master for confirmation.',
            'group': '...Sorry, this chat has not been approved yet. Please ask my master to add it before using me here.',
            'admin': 'This action is reserved for my master. The other functions are still available from the menu.',
            'blacklist': '...Sorry. I cannot answer here right now.',
        },
    }
    return escape(messages[_lang(convo_id)].get(reason, messages[_lang(convo_id)]['user']), italic=False)


def Authorization(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        update, context = args[:2]
        _, _, _, chatid, _, _, _, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context, voice=False)
        if config.BLACK_LIST and chatid in config.BLACK_LIST:
            await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text=ban_message(update, convo_id, 'blacklist'), parse_mode='MarkdownV2')
            return
        is_group_chat = str(chatid).startswith('-')
        if config.whitelist is None or (is_group_chat and is_group_allowed(chatid)):
            return await func(*args, **kwargs)
        if is_group_chat:
            return await func(*args, **kwargs)
        if config.whitelist and update.effective_user and not is_user_allowed(update.effective_user.id):
            await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text=ban_message(update, convo_id, 'user'), parse_mode='MarkdownV2')
            return
        return await func(*args, **kwargs)
    return wrapper


def GroupAuthorization(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        update, context = args[:2]
        _, _, _, chatid, _, _, _, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context, voice=False)
        if update.effective_chat is None or not str(chatid).startswith('-'):
            return await func(*args, **kwargs)
        if config.whitelist is None and config.GROUP_LIST is None:
            return await func(*args, **kwargs)
        if not is_group_allowed(chatid):
            if config.ADMIN_LIST and str(update.effective_user.id) in config.ADMIN_LIST:
                return await func(*args, **kwargs)
            await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text=ban_message(update, convo_id, 'group'), parse_mode='MarkdownV2')
            return
        return await func(*args, **kwargs)
    return wrapper


def AdminAuthorization(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        update, context = args[:2]
        _, _, _, chatid, _, _, _, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context, voice=False)
        if config.ADMIN_LIST is None or str(update.effective_user.id) in config.ADMIN_LIST:
            return await func(*args, **kwargs)
        await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text=ban_message(update, convo_id, 'admin'), parse_mode='MarkdownV2')
    return wrapper


def APICheck(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        update, context = args[:2]
        _, _, _, chatid, _, _, _, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context, voice=False)
        robot, _, api_key, api_url = config.get_robot(convo_id)
        lang = config.get_current_lang(convo_id)
        if robot is None:
            await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text=escape(strings['message_api_none'][lang]), parse_mode='MarkdownV2')
            return
        if (api_key and api_key.endswith('your_api_key')) or (api_url and api_url.endswith('your_api_url')):
            await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text=escape(strings['message_api_error'][lang]), parse_mode='MarkdownV2')
            return
        return await func(*args, **kwargs)
    return wrapper


def PrintMessage(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        update = args[0]
        logging.debug('Telegram update received; update_id=%s', getattr(update, 'update_id', None))
        return await func(*args, **kwargs)
    return wrapper
