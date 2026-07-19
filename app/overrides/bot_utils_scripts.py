def _matched_nick_prefix(update_text, nick_names):
    text = str(update_text or '')
    folded = text.casefold()
    for name in sorted(nick_names or [], key=len, reverse=True):
        candidate = str(name).strip()
        if not candidate or not folded.startswith(candidate.casefold()):
            continue
        boundary = len(candidate)
        if len(text) == boundary or text[boundary].isspace() or text[boundary] in '，,：:。.!！?？':
            return candidate
    return None


def CutNICK(update_text, update_message):
    import config
    nick_names = getattr(config, 'NICK_NAMES', None) or ([config.NICK] if config.NICK else [])
    matched_nick = _matched_nick_prefix(update_text, nick_names)

    update_chat = update_message.chat
    update_reply_to_message = update_message.reply_to_message
    if not nick_names:
        return update_text
    if matched_nick:
        return str(update_text)[len(matched_nick):].lstrip(' \t，,：:。.!！?？')
    if update_chat.type == 'private' or (
        update_reply_to_message
        and update_reply_to_message.text
        and update_reply_to_message.from_user.is_bot
        and update_reply_to_message.sender_chat is None
    ):
        return update_text
    return None

time_out = 600
async def get_file_url(file, context):
    file_id = file.file_id
    new_file = await context.bot.get_file(file_id, read_timeout=time_out, write_timeout=time_out, connect_timeout=time_out, pool_timeout=time_out)
    file_url = new_file.file_path
    return file_url

from io import BytesIO
async def get_voice(file_id: str, context) -> str:
    file_unique_id = file_id
    filename_mp3 = f'{file_unique_id}.mp3'

    try:
        file = await context.bot.get_file(file_id)
        file_bytes = await file.download_as_bytearray()

        # 创建一个字节流对象
        audio_stream = BytesIO(file_bytes)

        # 直接使用字节流对象进行转录
        import config
        transcript = config.whisperBot.generate(audio_stream)

        return transcript

    except Exception as e:
        import logging
        logging.warning("Voice transcription failed: %s", type(e).__name__)
        return "……这段语音暂时没有听清。可以再发一次，或者直接把想说的话打出来。"
    finally:
        import os
        if os.path.exists(filename_mp3):
            os.remove(filename_mp3)

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def GetMesage(update_message, context, voice=True):
    from aient.aient.utils.scripts import Document_extract
    image_url = None
    file_url = None
    reply_to_message_text = None
    message = None
    rawtext = None
    voice_text = None
    reply_to_message_file_content = None

    chatid = str(update_message.chat_id)
    if update_message.is_topic_message:
        message_thread_id = update_message.message_thread_id
    else:
        message_thread_id = None
    if message_thread_id:
        convo_id = str(chatid) + "_" + str(message_thread_id)
    else:
        convo_id = str(chatid)

    messageid = update_message.message_id

    if update_message.text:
        message = CutNICK(update_message.text, update_message)
        rawtext = update_message.text

    if update_message.reply_to_message:
        reply_to_message_text = update_message.reply_to_message.text
        reply_to_message_file = update_message.reply_to_message.document

        if update_message.reply_to_message.photo:
            photo = update_message.reply_to_message.photo[-1]
            image_url = await get_file_url(photo, context)

        if reply_to_message_file:
            reply_to_message_file_url = await get_file_url(reply_to_message_file, context)
            reply_to_message_file_content = await Document_extract(reply_to_message_file_url, reply_to_message_file_url, None)

    if update_message.photo:
        photo = update_message.photo[-1]

        image_url = await get_file_url(photo, context)

        if update_message.caption:
            message = rawtext = CutNICK(update_message.caption, update_message)

    if voice and update_message.voice:
        voice = update_message.voice.file_id
        voice_text = await get_voice(voice, context)

        if update_message.caption:
            message = rawtext = CutNICK(update_message.caption, update_message)

    if update_message.document:
        file = update_message.document

        file_url = await get_file_url(file, context)

        if image_url == None and file_url and (file_url[-3:] == "jpg" or file_url[-3:] == "png" or file_url[-4:] == "jpeg"):
            image_url = file_url

        if update_message.caption:
            message = rawtext = CutNICK(update_message.caption, update_message)

    if update_message.audio:
        file = update_message.audio

        file_url = await get_file_url(file, context)

        if image_url == None and file_url and (file_url[-3:] == "jpg" or file_url[-3:] == "png" or file_url[-4:] == "jpeg"):
            image_url = file_url

        if update_message.caption:
            message = rawtext = CutNICK(update_message.caption, update_message)

    return message, rawtext, image_url, chatid, messageid, reply_to_message_text, message_thread_id, convo_id, file_url, reply_to_message_file_content, voice_text

async def GetMesageInfo(update, context, voice=True):
    if update.edited_message:
        message, rawtext, image_url, chatid, messageid, reply_to_message_text, message_thread_id, convo_id, file_url, reply_to_message_file_content, voice_text = await GetMesage(update.edited_message, context, voice)
        update_message = update.edited_message
    elif update.callback_query:
        message, rawtext, image_url, chatid, messageid, reply_to_message_text, message_thread_id, convo_id, file_url, reply_to_message_file_content, voice_text = await GetMesage(update.callback_query.message, context, voice)
        update_message = update.callback_query.message
    elif update.message:
        message, rawtext, image_url, chatid, messageid, reply_to_message_text, message_thread_id, convo_id, file_url, reply_to_message_file_content, voice_text = await GetMesage(update.message, context, voice)
        update_message = update.message
    else:
        return None, None, None, None, None, None, None, None, None, None, None, None
    return message, rawtext, image_url, chatid, messageid, reply_to_message_text, update_message, message_thread_id, convo_id, file_url, reply_to_message_file_content, voice_text

def safe_get(data, *keys):
    for key in keys:
        try:
            data = data[key] if isinstance(data, (dict, list)) else data.get(key)
        except (KeyError, IndexError, AttributeError, TypeError):
            return None
    return data

def is_emoji(character):
    if len(character) != 1:
        return False

    code_point = ord(character)

    # 定义表情符号的Unicode范围
    emoji_ranges = [
        (0x1F300, 0x1F5FF),  # 杂项符号和图形
        (0x1F600, 0x1F64F),  # 表情符号
        (0x1F680, 0x1F6FF),  # 交通和地图符号
        (0x2600, 0x26FF),    # 杂项符号
        (0x2700, 0x27BF),    # 装饰符号
        (0x1F900, 0x1F9FF)   # 补充符号和图形
    ]

    # 检查字符的Unicode码点是否在任何一个表情符号范围内
    return any(start <= code_point <= end for start, end in emoji_ranges)