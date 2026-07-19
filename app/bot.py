import re
import sys
sys.dont_write_bytecode = True
import base64
import logging
import traceback
import utils.decorators as decorators

from md2tgmd.src.md2tgmd import escape, split_code, replace_all
from aient.aient.utils.scripts import Document_extract
from aient.aient.core.utils import get_engine, get_image_message, get_text_message
import config

# ---- persona overrides (externalized) ----
from pathlib import Path as _PersonaPath
from memory_store import PersistentMemory
from access_control import allow as allow_access, ensure_initialized as ensure_access_control, is_user_allowed
from role_dialogue_store import RoleDialogueStore
import os as _persona_os

_PERSONA_DEFAULTS = {
    "START_MESSAGE": "Hi `{username}` ! I am an Assistant, a large language model trained by OpenAI. I will do my best to help answer your questions.",
    "BOT_DESCRIPTION": "I am an Assistant, a large language model trained by OpenAI. I will do my best to help answer your questions.",
    "FOLLOWUP_PROMPT": (
        "You are a professional Q&A expert. You will now be given reference information. "
        "Based on the reference information, please help me ask three most relevant questions that you most want to know from my perspective. "
        "Be concise and to the point. Do not have numbers in front of questions. Separate each question with a line break. "
        "Only output three questions in {language}, no need for any explanation. reference infomation is provided inside <infomation></infomation> XML tags."
        "Here is the reference infomation, inside <infomation></infomation> XML tags:"
        "<infomation>"
        "{info}"
        "</infomation>"
    ),
}


def _parse_env_file(path):
    data = {}
    p = _PersonaPath(path)
    if not p.exists():
        return data
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
            value = value[1:-1]
        if '\\n' in value or '\\t' in value:
            value = value.replace('\\n', '\n').replace('\\t', '\t')
        data[key] = value
    return data


def load_persona_config():
    # Priority: process env > persona.env > defaults
    file_vals = {}
    for candidate in (
        _persona_os.environ.get("PERSONA_FILE"),
        str(_PersonaPath(__file__).with_name("persona.env")),
        "/home/persona.env",
        "./persona.env",
    ):
        if not candidate:
            continue
        parsed = _parse_env_file(candidate)
        if parsed:
            file_vals = parsed
            break

    cfg = dict(_PERSONA_DEFAULTS)
    for key in ("START_MESSAGE", "BOT_DESCRIPTION", "FOLLOWUP_PROMPT", "SYSTEMPROMPT", "NICK"):
        if key in file_vals and str(file_vals[key]).strip() != "":
            cfg[key] = file_vals[key]
        env_v = _persona_os.environ.get(key)
        if env_v is not None and str(env_v).strip() != "":
            cfg[key] = env_v
    # File-based overrides for multi-line texts
    base_dir = _PersonaPath(__file__).resolve().parent
    file_map = {
        'START_MESSAGE_FILE': 'START_MESSAGE',
        'BOT_DESCRIPTION_FILE': 'BOT_DESCRIPTION',
        'FOLLOWUP_PROMPT_FILE': 'FOLLOWUP_PROMPT',
    }
    for file_key, text_key in file_map.items():
        rel = cfg.get(file_key) or file_vals.get(file_key) or _persona_os.environ.get(file_key)
        if not rel:
            continue
        fp = _PersonaPath(rel)
        if not fp.is_absolute():
            fp = base_dir / rel
        if fp.exists():
            cfg[text_key] = fp.read_text(encoding='utf-8', errors='replace').rstrip('\n')

    # Decode leftover literal escaped newlines if any
    for text_key in ('START_MESSAGE', 'BOT_DESCRIPTION', 'FOLLOWUP_PROMPT'):
        val = cfg.get(text_key)
        if isinstance(val, str) and '\\n' in val:
            cfg[text_key] = val.replace('\\n', '\n').replace('\\t', '\t')

    return cfg


PERSONA = load_persona_config()
ensure_access_control()
# ---- end persona overrides ----

from config import (
    WEB_HOOK,
    PORT,
    BOT_TOKEN,
    GET_MODELS,
    Users,
    PREFERENCES,
    LANGUAGES,
    PLUGINS,
    RESET_TIME,
    get_robot,
    reset_ENGINE,
    get_current_lang,
    update_info_message,
    update_menu_buttons,
    remove_no_text_model,
    update_initial_model,
    update_models_buttons,
    update_language_status,
    update_first_buttons_message,
    get_all_available_models,
    get_model_groups,
    CUSTOM_MODELS_LIST,
    MODEL_GROUPS,
    get_initial_model,
)

try:
    from i18n_override import strings
except Exception:
    from utils.i18n import strings
from utils.scripts import GetMesageInfo, safe_get, is_emoji, _matched_nick_prefix

from telegram.constants import ChatAction
from telegram import BotCommand, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent, Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InputMediaPhoto, InlineKeyboardButton
from telegram.ext import CommandHandler, MessageHandler, ApplicationBuilder, filters, CallbackQueryHandler, Application, InlineQueryHandler, ContextTypes, TypeHandler
from datetime import timedelta

import asyncio
time_out = 600

MEMORY_DB_PATH = _persona_os.environ.get("MEMORY_DB_PATH", "/home/memory_data/gptbot_memory.sqlite3")
MEMORY_RECENT_TURNS = int(_persona_os.environ.get("MEMORY_RECENT_TURNS", "8"))
MEMORY_MAX_CONTEXT_CHARS = int(_persona_os.environ.get("MEMORY_MAX_CONTEXT_CHARS", "7000"))
MEMORY_SUMMARY_EVERY = int(_persona_os.environ.get("MEMORY_SUMMARY_EVERY", "8"))
MEMORY = PersistentMemory(
    MEMORY_DB_PATH,
    recent_turns=MEMORY_RECENT_TURNS,
    max_context_chars=MEMORY_MAX_CONTEXT_CHARS,
)
MEMORY_SESSION_CUTOFF = {}
MEMORY_SESSION_SUMMARY = {}
ROLE_DATA_ROOT = _persona_os.environ.get("ROLE_DATA_ROOT", "/home/role_data")
ROLE_DIALOGUES = RoleDialogueStore(ROLE_DATA_ROOT)

# Rich Message 模式开关: 启用后使用 Bot API 10.0+ sendRichMessage / editMessageText(rich_message)
RICH_MODE = _persona_os.environ.get("RICH_MESSAGE", "").lower() in ("1", "true", "yes")


def role_owner_key(update, chatid, convo_id=None):
    # GetMesageInfo already includes the Telegram topic in convo_id. Keeping
    # this key stable preserves old default histories while isolating topics.
    return str(convo_id or chatid)


def active_dialogue_context(update, chatid, config_convo_id):
    owner_key, active, runtime_key = active_role_context(update, chatid, config_convo_id)
    return owner_key, active, runtime_key


def active_role_context(update, chatid, config_convo_id):
    owner_key = role_owner_key(update, chatid, config_convo_id)
    context = ROLE_DIALOGUES.active_context(owner_key)
    role = context["role"]
    dialogue = context["dialogue"]
    runtime_key = str(dialogue["runtime_key"])
    active = dict(dialogue)
    active.update({
        "role_id": role["id"],
        "role_name": role["name"],
        "role_default": role.get("default", False),
        "role_identity": role.get("identity", ""),
        "role_tone": role.get("tone", ""),
        "role_welcome": role.get("welcome", ""),
        "role_prompt": role.get("prompt", ""),
    })
    return owner_key, active, runtime_key


def active_runtime_key(update, chatid, config_convo_id):
    return active_dialogue_context(update, chatid, config_convo_id)[2]


def role_growth_identity(runtime_key, user_id, config_convo_id=None):
    if config_convo_id is not None and str(runtime_key) == str(config_convo_id):
        # Compatibility path: the migrated default dialogue keeps the old
        # user_id so existing growth profiles remain visible.
        return str(user_id or "")
    return "role:" + str(runtime_key) + ":user:" + str(user_id or "")


def reset_runtime_session(runtime_key, config_convo_id, message=None):
    if message:
        Users.set_config(config_convo_id, "systemprompt", message)
    systemprompt = Users.get_config(config_convo_id, "systemprompt")
    robot, _, api_key, _ = get_robot(config_convo_id)
    if api_key and robot:
        robot.reset(convo_id=str(runtime_key), system_prompt=systemprompt)


def mark_runtime_reset(runtime_key):
    MEMORY.mark_reset(runtime_key)
    MEMORY_SESSION_CUTOFF[runtime_key] = MEMORY.latest_turn_id(runtime_key)
    MEMORY_SESSION_SUMMARY[runtime_key] = MEMORY.get_summary(runtime_key)



logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger()

logging.getLogger("httpx").setLevel(logging.CRITICAL)
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)

class SpecificStringFilter(logging.Filter):
    def __init__(self, specific_string):
        super().__init__()
        self.specific_string = specific_string

    def filter(self, record):
        return self.specific_string not in record.getMessage()

specific_string = "httpx.RemoteProtocolError: Server disconnected without sending a response."
my_filter = SpecificStringFilter(specific_string)

update_logger = logging.getLogger("telegram.ext.Updater")
update_logger.addFilter(my_filter)
update_logger = logging.getLogger("root")
update_logger.addFilter(my_filter)

# Per-conversation runtime state. Never let one chat cancel or delay another.
from collections import defaultdict
conversation_locks = defaultdict(asyncio.Lock)
conversation_request_locks = defaultdict(asyncio.Lock)
conversation_stop_events = defaultdict(asyncio.Event)
message_cache = defaultdict(list)
time_stamps = defaultdict(list)
summary_tasks = {}

@decorators.PrintMessage
@decorators.GroupAuthorization
@decorators.Authorization
@decorators.APICheck
async def command_bot(update, context, title="", has_command=True):
    message, rawtext, image_url, chatid, messageid, reply_to_message_text, update_message, message_thread_id, convo_id, file_url, reply_to_message_file_content, voice_text = await GetMesageInfo(update, context)
    user_id = str(getattr(getattr(update, 'effective_user', None), 'id', '') or '')
    role_owner, role_dialogue, runtime_convo_id = active_role_context(update, chatid, convo_id)

    if has_command == False or len(context.args) > 0:
        if has_command:
            message = ' '.join(context.args)
        pass_history = Users.get_config(convo_id, "PASS_HISTORY")
        if message == None:
            message = voice_text
        # print("message", message)
        if message and len(message) == 1 and is_emoji(message):
            return

        nick_names = getattr(config, "NICK_NAMES", None) or ([config.NICK] if config.NICK else [])
        message_has_nick = bool(rawtext and _matched_nick_prefix(rawtext, nick_names))

        if message_has_nick and update_message.reply_to_message and update_message.reply_to_message.caption and not message:
            message = update_message.reply_to_message.caption

        if message:
            if pass_history >= 3:
                # Each dialogue has its own timer; switching later cannot reset
                # whichever dialogue happens to be active at timer expiry.
                remove_job_if_exists(runtime_convo_id, context)
                context.job_queue.run_once(
                    scheduled_function,
                    when=timedelta(seconds=RESET_TIME),
                    chat_id=chatid,
                    name=runtime_convo_id,
                    data={"config_convo_id": str(convo_id), "runtime_convo_id": runtime_convo_id},
                )

            bot_info_username = None
            try:
                bot_info = await context.bot.get_me(read_timeout=time_out, write_timeout=time_out, connect_timeout=time_out, pool_timeout=time_out)
                bot_info_username = bot_info.username
            except Exception as e:
                print("error:", e)
                bot_info_username = update_message.reply_to_message.from_user.username

            if update_message.reply_to_message \
            and update_message.from_user.is_bot == False \
            and (update_message.reply_to_message.from_user.username == bot_info_username or message_has_nick):
                if update_message.reply_to_message.from_user.is_bot and Users.get_config(convo_id, "TITLE") == True:
                    message = message + "\n" + '\n'.join(reply_to_message_text.split('\n')[1:])
                else:
                    if reply_to_message_text:
                        message = message + "\n" + reply_to_message_text
                    if reply_to_message_file_content:
                        message = message + "\n" + reply_to_message_file_content
            elif update_message.reply_to_message and update_message.reply_to_message.from_user.is_bot \
            and update_message.reply_to_message.from_user.username != bot_info_username:
                return

            robot, role, api_key, api_url = get_robot(convo_id)
            engine = Users.get_config(convo_id, "engine")

            if Users.get_config(convo_id, "LONG_TEXT"):
                import time
                async with conversation_locks[runtime_convo_id]:
                    message_cache[runtime_convo_id].append(message)
                    time_stamps[runtime_convo_id].append(time.time())
                    is_first_chunk = len(message_cache[runtime_convo_id]) == 1
                    should_collect = is_first_chunk and len(str(message_cache[runtime_convo_id][0])) > 800
                if not is_first_chunk:
                    return
                if should_collect:
                    await asyncio.sleep(2)
                async with conversation_locks[runtime_convo_id]:
                    intervals = [
                        time_stamps[runtime_convo_id][i] - time_stamps[runtime_convo_id][i - 1]
                        for i in range(1, len(time_stamps[runtime_convo_id]))
                    ]
                    if intervals:
                        logger.debug("Role dialogue chunk intervals: count=%s total=%s", len(intervals), sum(intervals))
                    message = "\n".join(message_cache.pop(runtime_convo_id, []))
                    time_stamps.pop(runtime_convo_id, None)
            # if Users.get_config(convo_id, "TYPING"):
            #     await context.bot.send_chat_action(chat_id=chatid, message_thread_id=message_thread_id, action=ChatAction.TYPING)
            if Users.get_config(convo_id, "TITLE"):
                title = f"`🤖️ {engine}`\n\n"
            if Users.get_config(convo_id, "REPLY") == False:
                messageid = None

            engine_type, _ = get_engine({"base_url": api_url}, endpoint=None, original_model=engine)
            if robot.__class__.__name__ == "chatgpt":
                engine_type = "gpt"
            if image_url:
                message_list = []
                image_message = await get_image_message(image_url, engine_type)
                text_message = await get_text_message(message, engine_type)
                message_list.append(text_message)
                message_list.append(image_message)
                message = message_list
            elif file_url:
                image_url = file_url
                message = await Document_extract(file_url, image_url, engine_type) + message

            async with conversation_request_locks[runtime_convo_id]:
                conversation_stop_events[runtime_convo_id].clear()
                await getChatGPT(
                    update_message, context, title, robot, message, chatid, messageid,
                    runtime_convo_id, message_thread_id, pass_history, api_key, api_url, engine,
                    user_id=user_id, config_convo_id=convo_id,
                )
    else:
        message = await context.bot.send_message(
            chat_id=chatid,
            message_thread_id=message_thread_id,
            text=escape(strings['message_command_text_none'][get_current_lang(convo_id)]),
            parse_mode='MarkdownV2',
            reply_to_message_id=messageid,
        )

async def delete_message(update, context, messageid = [], delay=60):
    await asyncio.sleep(delay)
    if isinstance(messageid, list):
        for mid in messageid:
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=mid)
            except Exception as e:
                pass
                # print('\033[31m')
                # print("delete_message error", e)
                # print('\033[0m')

from telegram.error import Forbidden, TelegramError, RetryAfter
async def is_bot_blocked(bot, user_id: int) -> bool:
    try:
        # 尝试向用户发送一条测试消息
        await bot.send_chat_action(chat_id=user_id, action="typing")
        return False  # 如果成功发送，说明机器人未被封禁
    except Forbidden:
        print("error:", user_id, "已封禁机器人")
        return True  # 如果收到Forbidden错误，说明机器人被封禁
    except TelegramError:
        # 处理其他可能的错误
        return False  # 如果是其他错误，我们假设机器人未被封禁


def _ui_lang_name(lang_code):
    name = str(lang_code or "")
    if name in ("Simplified Chinese", "zh", "zh-cn", "zh-hans"):
        return "zh"
    if name in ("Traditional Chinese", "zh-hk", "zh-tw", "zh-hant"):
        return "zh-hk"
    if name in ("Japanese", "ja"):
        return "ja"
    return "en"


def status_spinner(frame=0):
    frames = ["▪︎□□", "□▪︎□", "□□▪︎", "□▪︎□"]
    return frames[int(frame) % len(frames)]


def thinking_text(lang_code, frame=0):
    """Localized thinking placeholder with a lively spinner."""
    ui = _ui_lang_name(lang_code)
    if ui in ("zh", "zh-hk"):
        base = "宵雫思索中"
    elif ui == "ja":
        base = "宵雫が考えています"
    else:
        base = "Shizuku is thinking"
    return f"`{base} {status_spinner(frame)}`"


def running_text(stage_text, frame=0):
    """Running/search status with spinner, stage text kept plain."""
    stage = str(stage_text or "").strip()
    # strip trailing dots for cleaner animation
    while stage.endswith(".") or stage.endswith("…"):
        stage = stage[:-1].rstrip()
    return f"`{stage} {status_spinner(frame)}`"


async def animate_status(context, chatid, message_id, convo_id, stop_event, text_provider, interval=0.16):
    """Edit one message repeatedly to show live status animation."""
    import asyncio as _asyncio
    frame = 0
    last_text = None
    while not stop_event.is_set():
        frame += 1
        try:
            content = text_provider(frame)
            if content and content != last_text:
                if RICH_MODE:
                    await context.bot._post("editMessageText", data={
                        "chat_id": chatid,
                        "message_id": message_id,
                        "rich_message": {"markdown": escape(content)},
                        "disable_web_page_preview": True,
                    })
                else:
                    await context.bot.edit_message_text(
                        chat_id=chatid,
                        message_id=message_id,
                        text=escape(content),
                        parse_mode="MarkdownV2",
                        disable_web_page_preview=True,
                    )
                last_text = content
        except Exception:
            # Ignore edit conflicts / message-not-modified / race with final answer
            pass
        try:
            await _asyncio.sleep(interval)
        except Exception:
            break


async def animate_thinking(context, chatid, message_id, convo_id, stop_event, message_thread_id=None):
    """Backward-compatible thinking animation wrapper."""
    lang = get_current_lang(convo_id)
    await animate_status(
        context,
        chatid,
        message_id,
        convo_id,
        stop_event,
        text_provider=lambda frame: thinking_text(lang, frame),
        interval=0.16,
    )

async def refresh_persistent_summary(convo_id, model_name, api_url, api_key):
    if not api_key or not MEMORY.needs_summary(convo_id, min_turns=MEMORY_SUMMARY_EVERY):
        return
    old_summary, material, last_turn_id = MEMORY.summary_material(convo_id)
    if not material or not last_turn_id:
        return
    prompt = """你负责维护藍沢宵雫与主人的长期记忆。请将旧摘要与新对话合并为紧凑、可验证的简体中文记忆。

【严格事实规则】
- 只能记录主人明确说过的偏好、身份、事实、承诺、待办或重复习惯。
- 不得从角色设定、助手回复、语气、称呼或单次互动推断关系身份、伴侣关系、情绪、需求或未来计划。
- 不得把宵雫的回复当作主人的事实；不要记录模型猜测。
- 不确定就不记录。宁可遗漏，也不要补全或美化。
- 不要保存密码密钥、工具内部信息、一次性闲聊或露骨过程细节。

【输出格式】
只输出以下四个可省略的标题和简短条目，不要前言、评价、总结句或 Markdown 加粗：
稳定偏好：
明确事实：
重要事件与承诺：
待跟进事项：
控制在 900 个汉字以内；所有文字使用简体中文。

【旧摘要】
{old_summary}

【新增对话】
{material}""".format(
        old_summary=old_summary or "（无）",
        material=material,
    )
    try:
        result = await config.SummaryBot.ask_async(
            prompt,
            convo_id="memory_summary_" + str(convo_id),
            model=model_name,
            pass_history=0,
            api_url=api_url,
            api_key=api_key,
        )
        if result:
            MEMORY.update_summary(convo_id, str(result), last_turn_id)
    except Exception as exc:
        logger.warning(f"Persistent memory summary failed: {exc}")


def schedule_persistent_summary(convo_id, model_name, api_url, api_key):
    try:
        current = summary_tasks.get(convo_id)
        if current is not None and not current.done():
            return
        task = asyncio.create_task(refresh_persistent_summary(convo_id, model_name, api_url, api_key))
        summary_tasks[convo_id] = task

        def _clear_summary_task(done_task, key=convo_id):
            if summary_tasks.get(key) is done_task:
                summary_tasks.pop(key, None)

        task.add_done_callback(_clear_summary_task)
    except Exception as exc:
        logger.warning(f"Persistent memory scheduling failed: {exc}")


async def getChatGPT(update_message, context, title, robot, message, chatid, messageid, convo_id, message_thread_id, pass_history=0, api_key=None, api_url=None, engine = None, user_id="", config_convo_id=None):
    config_convo_id = str(config_convo_id or convo_id)
    lastresult = title
    text = message
    result = ""
    tmpresult = ""
    modifytime = 0
    time_out = 600
    image_has_send = 0
    model_name = engine
    language = Users.get_config(config_convo_id, "language")
    system_prompt = Users.get_config(config_convo_id, "systemprompt")
    if convo_id not in MEMORY_SESSION_CUTOFF:
        MEMORY_SESSION_CUTOFF[convo_id] = MEMORY.latest_turn_id(convo_id)
        MEMORY_SESSION_SUMMARY[convo_id] = MEMORY.get_summary(convo_id)
    memory_context = MEMORY.build_context(
        convo_id,
        query=str(message or ""),
        max_turn_id=MEMORY_SESSION_CUTOFF[convo_id],
        summary_override=MEMORY_SESSION_SUMMARY[convo_id],
    )
    if memory_context:
        system_prompt = system_prompt + "\n\n" + memory_context
    owner_key = role_owner_key(update_message, chatid, config_convo_id)
    role_meta = active_role_context(update_message, chatid, config_convo_id)[1]
    role_shared_context = MEMORY.build_role_shared_context(owner_key, role_meta.get("role_id"), query=str(message or ""))
    if role_shared_context:
        system_prompt = system_prompt + "\n\n" + role_shared_context
    growth_user_id = role_growth_identity(convo_id, user_id, config_convo_id) if user_id else ""
    growth_context = MEMORY.build_user_context(growth_user_id, query=str(message or "")) if growth_user_id else ""
    if growth_context:
        system_prompt = system_prompt + "\n\n" + growth_context
    role_prompt_parts = []
    if role_meta.get("role_identity"):
        role_prompt_parts.append("当前角色身份：" + str(role_meta["role_identity"]))
    if role_meta.get("role_tone"):
        role_prompt_parts.append("当前角色语气：" + str(role_meta["role_tone"]))
    if role_meta.get("role_prompt"):
        role_prompt_parts.append("当前角色补充设定：" + str(role_meta["role_prompt"]))
    if role_prompt_parts:
        system_prompt = system_prompt + "\n\n【当前角色补充】\n" + "\n".join(role_prompt_parts)
    plugins = Users.extract_plugins_config(config_convo_id)

    Frequency_Modification = 20
    if "gpt-5" in model_name:
        Frequency_Modification = 25
    if message_thread_id or config_convo_id.startswith("-"):
        Frequency_Modification = 35
    if "gemini" in model_name:
        Frequency_Modification = 1

    # ── Rich/Plain 消息分发层（RICH_MODE 开关控制） ──
    # PTB 的 request.post 是底层 HTTP 接口，不能传 data=。
    # 统一通过 Bot._post 调用尚未被 PTB 22.5 封装的 Bot API 10.0 方法。
    async def _bot_api(method, data):
        return await context.bot._post(method, data=data)

    async def _edit_msg(text, msg_id=None, *, plain=False):
        """编辑消息：Rich Message 或 MarkdownV2。"""
        mid = msg_id or answer_messageid
        if RICH_MODE and not plain:
            await _bot_api("editMessageText", {
                "chat_id": chatid,
                "message_id": mid,
                "rich_message": {"markdown": text},
                "disable_web_page_preview": True,
            })
        else:
            pm = None if plain else "MarkdownV2"
            await context.bot.edit_message_text(
                chat_id=chatid,
                message_id=mid,
                text=text,
                parse_mode=pm,
                disable_web_page_preview=True,
                read_timeout=time_out,
                write_timeout=time_out,
                pool_timeout=time_out,
                connect_timeout=time_out,
            )

    async def _send_final(text, *, draft=False, plain=False):
        """定稿：Rich Message 或 MarkdownV2。"""
        if RICH_MODE and not plain:
            return await _bot_api("sendRichMessage", {
                "chat_id": chatid,
                "message_thread_id": message_thread_id,
                "rich_message": {"markdown": text},
                "disable_web_page_preview": True,
            })
        pm = None if plain else "MarkdownV2"
        if draft:
            return await _bot_api("sendMessage", {
                "chat_id": chatid,
                "message_thread_id": message_thread_id,
                "text": text,
                "parse_mode": pm,
                "disable_web_page_preview": True,
            })
        return await context.bot.send_message(
            chat_id=chatid,
            message_thread_id=message_thread_id,
            text=text,
            parse_mode=pm,
            disable_web_page_preview=True,
        )


    think_stop_event = None
    think_task = None
    draft_active = False
    is_private = not str(chatid).startswith('-')
    if not await is_bot_blocked(context.bot, chatid):
        if is_private:
            try:
                if RICH_MODE:
                    draft_resp = await _bot_api("sendRichMessageDraft", {
                        "chat_id": chatid,
                        "message_thread_id": message_thread_id,
                        "rich_message": {"markdown": escape(thinking_text(get_current_lang(config_convo_id), 0))},
                        "reply_to_message_id": messageid,
                    })
                else:
                    draft_resp = await _bot_api("sendMessageDraft", {
                        "chat_id": chatid,
                        "message_thread_id": message_thread_id,
                        "text": escape(thinking_text(get_current_lang(config_convo_id), 0)),
                        "parse_mode": "MarkdownV2",
                        "reply_to_message_id": messageid,
                    })
                answer_messageid = draft_resp["result"]["message_id"]
                draft_active = True
            except Exception as exc:
                logger.warning("Draft 初始化失败，回退为常规消息：%s", exc)
                draft_active = False
        if not draft_active:
            think_text = escape(thinking_text(get_current_lang(config_convo_id), 0))
            if RICH_MODE:
                sent = await _bot_api("sendMessage", {
                    "chat_id": chatid,
                    "message_thread_id": message_thread_id,
                    "text": think_text,
                    "parse_mode": "MarkdownV2",
                    "reply_to_message_id": messageid,
                })
                answer_messageid = sent["result"]["message_id"]
            else:
                answer_messageid = (await context.bot.send_message(
                    chat_id=chatid,
                    message_thread_id=message_thread_id,
                    text=think_text,
                    parse_mode="MarkdownV2",
                    reply_to_message_id=messageid,
                )).message_id
        think_stop_event = asyncio.Event()
        think_task = asyncio.create_task(
            animate_thinking(context, chatid, answer_messageid, config_convo_id, think_stop_event, message_thread_id)
        )
    else:
        return

    try:
        # print("text", text)
        async for data in robot.ask_stream_async(text, convo_id=convo_id, pass_history=pass_history, model=model_name, language=language, api_url=api_url, api_key=api_key, system_prompt=system_prompt, plugins=plugins):
        # for data in robot.ask_stream(text, convo_id=convo_id, pass_history=pass_history, model=model_name):
            if conversation_stop_events[convo_id].is_set():
                if think_stop_event is not None:
                    think_stop_event.set()
                    try:
                        if think_task is not None:
                            think_task.cancel()
                    except Exception:
                        pass
                return
            if "message_search_stage_" not in data:
                if think_stop_event is not None and not think_stop_event.is_set():
                    think_stop_event.set()
                    try:
                        think_task.cancel()
                    except Exception:
                        pass
                result = result + data
            image_match = re.search(r"!\[image\]\(data:image\/png;base64,([a-zA-Z0-9+/=]+)\)", result)
            if image_match and image_has_send == 0:
                base64_str = image_match.group(1)
                try:
                    img_url = base64.b64decode(base64_str)
                    media_group = []
                    media_group.append(InputMediaPhoto(media=img_url))
                    await context.bot.send_media_group(
                        chat_id=chatid,
                        media=media_group,
                        message_thread_id=message_thread_id,
                        reply_to_message_id=messageid,
                    )
                    result = result.replace(image_match.group(0), "")
                    image_has_send = 1
                except Exception as e:
                    logger.warning(f"Could not process base64 image: {e}")
                continue
            if result.strip().startswith("![image](data:image/") and image_has_send:
                await context.bot.delete_message(chat_id=chatid, message_id=answer_messageid)
                break
            tmpresult = result
            if re.sub(r"```", '', result.split("\n")[-1]).count("`") % 2 != 0:
                tmpresult = result + "`"
            if sum([line.strip().startswith("```") for line in result.split('\n')]) % 2 != 0:
                tmpresult = tmpresult + "\n```"
            tmpresult = title + tmpresult
            if "message_search_stage_" in data:
                # Keep a live running animation for tool/search stages.
                stage_label = strings[data][get_current_lang(config_convo_id)]
                tmpresult = running_text(stage_label, 0)
                # Restart/reuse status animation with stage text provider.
                try:
                    if think_stop_event is not None and not think_stop_event.is_set():
                        think_stop_event.set()
                        if think_task is not None:
                            think_task.cancel()
                except Exception:
                    pass
                think_stop_event = asyncio.Event()
                stage_lang = get_current_lang(config_convo_id)
                stage_base = strings[data][stage_lang]
                think_task = asyncio.create_task(
                    animate_status(
                        context,
                        chatid,
                        answer_messageid,
                        convo_id,
                        think_stop_event,
                        text_provider=lambda frame, base=stage_base: running_text(base, frame),
                        interval=0.16,
                    )
                )
            history = robot.conversation[convo_id]
            if safe_get(history, -2, "tool_calls", 0, 'function', 'name') == "generate_image" and not image_has_send and safe_get(history, -1, 'content'):
                image_result = history[-1]['content'].split('\n\n')[1]
                await context.bot.send_photo(chat_id=chatid, photo=image_result, reply_to_message_id=messageid)
                image_has_send = 1
            modifytime = modifytime + 1

            split_len = 3500
            if len(tmpresult) > split_len and Users.get_config(config_convo_id, "LONG_TEXT_SPLIT"):
                Frequency_Modification = 40

                # print("tmpresult", tmpresult)
                replace_text = replace_all(tmpresult, r"(```[\D\d\s]+?```)", split_code)
                if "@|@|@|@" in replace_text:
                    logger.debug("Long response split marker detected; chars=%s", len(replace_text))
                    split_messages = replace_text.split("@|@|@|@")
                    send_split_message = split_messages[0]
                    result = split_messages[1][:-4]
                else:
                    logger.debug("Long response split fallback; chars=%s", len(replace_text))
                    if replace_text.strip().endswith("```"):
                        replace_text = replace_text.strip()[:-4]
                    split_messages_new = []
                    split_messages = replace_text.split("```")
                    for index, item in enumerate(split_messages):
                        if index % 2 == 1:
                            item = "```" + item
                            if index != len(split_messages) - 1:
                                item = item + "```"
                            split_messages_new.append(item)
                        if index % 2 == 0:
                            item_split_new = []
                            item_split = item.split("\n\n")
                            for sub_index, sub_item in enumerate(item_split):
                                if sub_index % 2 == 1:
                                    sub_item = "\n\n" + sub_item
                                    if sub_index != len(item_split) - 1:
                                        sub_item = sub_item + "\n\n"
                                    item_split_new.append(sub_item)
                                if sub_index % 2 == 0:
                                    item_split_new.append(sub_item)
                            split_messages_new.extend(item_split_new)

                    split_index = 0
                    for index, _ in enumerate(split_messages_new):
                        if len("".join(split_messages_new[:index])) < split_len:
                            split_index += 1
                            continue
                        else:
                            break
                    # print("split_messages_new", split_messages_new)
                    send_split_message = ''.join(split_messages_new[:split_index])
                    matches = re.findall(r"(```.*?\n)", send_split_message)
                    if len(matches) % 2 != 0:
                        send_split_message = send_split_message + "```\n"
                    # print("send_split_message", send_split_message)
                    tmp = ''.join(split_messages_new[split_index:])
                    if tmp.strip().endswith("```"):
                        result = tmp[:-4]
                    else:
                        result = tmp
                    # print("result", result)
                    matches = re.findall(r"(```.*?\n)", send_split_message)
                    result_matches = re.findall(r"(```.*?\n)", result)
                    # print("matches", matches)
                    # print("result_matches", result_matches)
                    if len(result_matches) > 0 and result_matches[0].startswith("```\n") and len(result_matches) >= 2:
                        result = matches[-2] + result
                    # print("result", result)

                title = ""
                if lastresult != escape(send_split_message, italic=False):
                    try:
                        await _edit_msg(escape(send_split_message, italic=False))
                        lastresult = escape(send_split_message, italic=False)
                    except Exception as e:
                        if "parse entities" in str(e):
                            await _edit_msg(send_split_message, plain=True)
                            logger.warning("Telegram parse fallback used for split message; chars=%s", len(send_split_message))
                        else:
                            print("error:", str(e))
                draft_active = False  # split: new message is not a draft
                answer_messageid = (await context.bot.send_message(
                    chat_id=chatid,
                    message_thread_id=message_thread_id,
                    text=escape(strings['message_think'][get_current_lang(config_convo_id)]),
                    parse_mode='MarkdownV2',
                    reply_to_message_id=messageid,
                )).message_id

            now_result = escape(tmpresult, italic=False)
            if now_result and (modifytime % Frequency_Modification == 0 and lastresult != now_result) or "message_search_stage_" in data:
                try:
                    await _edit_msg(now_result)
                    lastresult = now_result
                except Exception as e:
                    continue
    except Exception as e:
        if think_stop_event is not None:
            think_stop_event.set()
            try:
                think_task.cancel()
            except Exception:
                pass
        logger.exception("Streaming response failed for convo=%s; partial_chars=%s", convo_id, len(tmpresult or ""))
        api_key = Users.get_config(config_convo_id, "api_key")
        systemprompt = Users.get_config(config_convo_id, "systemprompt")
        if api_key:
            robot.reset(convo_id=convo_id, system_prompt=systemprompt)
        if "parse entities" in str(e):
            await _edit_msg(tmpresult)
        else:
            failure_text = "……刚才的回答在送出来时出了点问题。宵雫已经停下来整理了，请再说一次。"
            tmpresult = (str(tmpresult).strip() + "\n\n" + failure_text).strip()
    logger.debug("Completed response for convo=%s; chars=%s", convo_id, len(tmpresult or ""))

    # 添加图片URL检测和发送
    if image_has_send == 0:
        image_extensions = r'(https?://[^\s<>\"()]+(?:\.(?:webp|jpg|jpeg|png|gif)|/image)[^\s<>\"()]*)'
        image_urls = re.findall(image_extensions, tmpresult, re.IGNORECASE)
        image_urls_result = [url[0] if isinstance(url, tuple) else url for url in image_urls]
        if image_urls_result:
            try:
                # Limit the number of images to 10 (Telegram limit for albums)
                image_urls_result = image_urls_result[:10]

                # We send an album with all images
                media_group = []
                for img_url in image_urls_result:
                    media_group.append(InputMediaPhoto(media=img_url))

                await context.bot.send_media_group(
                    chat_id=chatid,
                    media=media_group,
                    message_thread_id=message_thread_id,
                    reply_to_message_id=messageid,
                )
            except Exception as e:
                logger.warning(f"Failed to send image(s): {str(e)}")

    now_result = escape(tmpresult, italic=False)
    if lastresult != now_result and answer_messageid:
        if "Can't parse entities: can't find end of code entity at byte offset" in tmpresult:
            await update_message.reply_text(tmpresult)
            logger.warning("Telegram code-entity fallback used; chars=%s", len(now_result))
        elif now_result:
            try:
                if draft_active:
                    final_msg_resp = await _send_final(now_result, draft=True)
                    draft_active = False
                    try:
                        await context.bot.delete_message(chat_id=chatid, message_id=answer_messageid)
                    except Exception:
                        pass
                else:
                    await _edit_msg(now_result)
            except Exception as e:
                if "parse entities" in str(e):
                    if draft_active:
                        try:
                            await _send_final(tmpresult, draft=True, plain=True)
                            draft_active = False
                            try:
                                await context.bot.delete_message(chat_id=chatid, message_id=answer_messageid)
                            except Exception:
                                pass
                        except Exception:
                            pass
                    else:
                        await _edit_msg(tmpresult, plain=True)

    # Persist completed dialogue so it survives container/VPS restarts.
    if str(message or "").strip() and str(tmpresult or "").strip():
        try:
            MEMORY.add_turn(convo_id, str(message), str(tmpresult), user_id=growth_user_id, source_convo_id=convo_id)
            if user_id:
                MEMORY.process_interaction(growth_user_id, convo_id, str(message), str(tmpresult))
            schedule_persistent_summary(convo_id, model_name, api_url, api_key)
        except Exception as exc:
            logger.warning(f"Persistent memory write failed: {exc}")

    if Users.get_config(config_convo_id, "FOLLOW_UP") and tmpresult.strip():
        if title != "":
            info = "\n\n".join(tmpresult.split("\n\n")[1:])
        else:
            info = tmpresult
        followup_template = PERSONA.get("FOLLOWUP_PROMPT") or _PERSONA_DEFAULTS["FOLLOWUP_PROMPT"]
        prompt = followup_template.format(language=language, info=info)
        result = (await config.SummaryBot.ask_async(prompt, convo_id=convo_id, model=model_name, pass_history=0, api_url=api_url, api_key=api_key)).split('\n')
        keyboard = []
        result = [i for i in result if i.strip() and len(i) > 5]
        logger.debug("Generated follow-up suggestions; count=%s", len(result))
        for ques in result:
            keyboard.append([KeyboardButton(ques)])
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
        await update_message.reply_text(text=escape(tmpresult, italic=False), parse_mode='MarkdownV2', reply_to_message_id=messageid, reply_markup=reply_markup)
        await context.bot.delete_message(chat_id=chatid, message_id=answer_messageid)

async def _role_group_admin(update, context):
    chat = getattr(update, "effective_chat", None)
    if chat is None or getattr(chat, "type", "") == "private":
        return True
    user = getattr(update, "effective_user", None)
    query = getattr(update, "callback_query", None)
    if user is None and query is not None:
        user = getattr(query, "from_user", None)
    if user is None:
        return False
    if config.ADMIN_LIST and str(user.id) in config.ADMIN_LIST:
        return True
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        return str(getattr(member, "status", "")) in ("administrator", "creator")
    except Exception:
        return False


async def _role_mutation_allowed(update, context, query=None):
    if await _role_group_admin(update, context):
        return True
    text = "只有群管理员可以切换或新建这个群组的共享对话。"
    if query is not None:
        await query.answer(text=text, show_alert=True)
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
    return False


def _role_panel_text(owner_key, active, include_archived=False):
    roles = ROLE_DIALOGUES.list_roles(owner_key, include_archived=include_archived)
    lines = [
        "当前角色：" + str(active.get("role_name", "藍沢宵雫")),
        "当前对话：" + str(active.get("name", "默认对话")),
        "",
        "角色决定她是谁，对话档案决定你们经历过什么。",
        "",
        "已有角色：",
    ]
    for role in roles:
        mark = " · 当前" if role.get("id") == active.get("role_id") else ""
        archived = " · 已归档" if role.get("archived") else ""
        lines.append("• " + str(role.get("name", role.get("id"))) + mark + archived)
    return "\n".join(lines)


def _role_panel_markup(active):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("切换角色", callback_data="ROLE_LIST"), InlineKeyboardButton("新建角色", callback_data="ROLE_NEW")],
        [InlineKeyboardButton("当前角色设置", callback_data="ROLE_SETTINGS")],
        [InlineKeyboardButton("管理当前对话", callback_data="ROLE_DIALOGUE_PANEL")],
        [InlineKeyboardButton("管理角色归档", callback_data="ROLE_ARCHIVED")],
        [InlineKeyboardButton("关闭", callback_data="ROLE_CLOSE")],
    ])


def _role_list_markup(rows, archived=False):
    buttons = []
    for row in rows:
        label = str(row.get("name", row.get("id", "角色")))[:45]
        if row.get("default"):
            label = "默认角色 · " + label
        if archived:
            label += " · 已归档"
            action = "ROLE_RESTORE:"
        else:
            action = "ROLE_SWITCH:"
        buttons.append([InlineKeyboardButton(label, callback_data=action + str(row["id"]))])
    buttons.append([InlineKeyboardButton("新建角色", callback_data="ROLE_NEW"), InlineKeyboardButton("返回", callback_data="ROLE_PANEL")])
    return InlineKeyboardMarkup(buttons)


def _role_settings_markup(active):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("重命名角色", callback_data="ROLE_RENAME_PROMPT")],
        [InlineKeyboardButton("设置身份", callback_data="ROLE_FIELD:identity")],
        [InlineKeyboardButton("设置语气", callback_data="ROLE_FIELD:tone")],
        [InlineKeyboardButton("设置欢迎语", callback_data="ROLE_FIELD:welcome")],
        [InlineKeyboardButton("设置补充设定", callback_data="ROLE_FIELD:prompt")],
        [InlineKeyboardButton("归档当前角色", callback_data="ROLE_ARCHIVE_CONFIRM")],
        [InlineKeyboardButton("删除当前角色", callback_data="ROLE_DELETE_CONFIRM")],
        [InlineKeyboardButton("返回", callback_data="ROLE_PANEL")],
    ])


def _dialogue_panel_markup(active):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("切换对话", callback_data="ROLE_DIALOGUE_LIST"), InlineKeyboardButton("新建对话", callback_data="ROLE_NEW_DIALOGUE")],
        [InlineKeyboardButton("重命名对话", callback_data="ROLE_RENAME_DIALOGUE_PROMPT")],
        [InlineKeyboardButton("管理对话归档", callback_data="ROLE_DIALOGUE_ARCHIVED")],
        [InlineKeyboardButton("归档当前对话", callback_data="ROLE_ARCHIVE_DIALOGUE_CONFIRM")],
        [InlineKeyboardButton("删除当前对话", callback_data="ROLE_DELETE_DIALOGUE_CONFIRM")],
        [InlineKeyboardButton("重置当前对话", callback_data="ROLE_RESET_CONFIRM")],
        [InlineKeyboardButton("返回", callback_data="ROLE_PANEL")],
    ])


def _dialogue_list_markup(rows, archived=False):
    buttons = []
    for row in rows:
        label = str(row.get("name", row.get("id", "对话")))[:45]
        if row.get("id") == ROLE_DIALOGUES.DEFAULT_DIALOGUE_ID:
            label = "默认对话 · " + label
        if archived:
            label += " · 已归档"
            action = "ROLE_DIALOGUE_RESTORE:"
        else:
            action = "ROLE_DIALOGUE_SWITCH:"
        buttons.append([InlineKeyboardButton(label, callback_data=action + str(row["id"]))])
    buttons.append([InlineKeyboardButton("新建对话", callback_data="ROLE_NEW_DIALOGUE"), InlineKeyboardButton("返回", callback_data="ROLE_DIALOGUE_PANEL")])
    return InlineKeyboardMarkup(buttons)


def _role_confirm_markup(confirm_callback, cancel_callback="ROLE_PANEL"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("确认", callback_data=confirm_callback)],
        [InlineKeyboardButton("取消", callback_data=cancel_callback)],
    ])


async def _show_role_panel(query, owner_key, active):
    await query.edit_message_text(text=_role_panel_text(owner_key, active), reply_markup=_role_panel_markup(active))


async def _show_role_settings(query, active):
    text = (
        "角色设置：" + str(active.get("role_name", "角色")) + "\n\n"
        "身份：" + str(active.get("role_identity") or "未设置") + "\n"
        "语气：" + str(active.get("role_tone") or "未设置") + "\n"
        "欢迎语：" + str(active.get("role_welcome") or "未设置") + "\n"
        "补充设定：" + str(active.get("role_prompt") or "未设置")
    )
    await query.edit_message_text(text=text, reply_markup=_role_settings_markup(active))


async def _show_dialogue_panel(query, active):
    await query.edit_message_text(
        text="当前角色：" + str(active.get("role_name", "角色")) + "\n当前对话：" + str(active.get("name", "默认对话")),
        reply_markup=_dialogue_panel_markup(active),
    )


async def _role_prompt_message(context, chatid, thread_id, text):
    return await context.bot.send_message(chat_id=chatid, message_thread_id=thread_id, text=text)


async def _handle_role_pending_text(update, context):
    pending = (getattr(context, "user_data", None) or {}).get("role_pending")
    if not pending:
        return False
    message = getattr(update, "effective_message", None) or getattr(update, "message", None)
    text = str(getattr(message, "text", "") or "").strip()
    chat = getattr(update, "effective_chat", None)
    if chat is None:
        return True
    if text.casefold() in ("/cancel", "取消"):
        context.user_data.pop("role_pending", None)
        await context.bot.send_message(chat_id=chat.id, text="已取消这次对话管理操作。")
        return True
    if not text:
        await context.bot.send_message(chat_id=chat.id, text="名称或设定不能为空，请重新发送，或发送 /cancel 取消。")
        return True
    _, _, _, _, _, _, _, _, incoming_convo_id, _, _, _ = await GetMesageInfo(update, context, voice=False)
    if str(chat.id) != str(pending.get("chat_id", chat.id)) or str(incoming_convo_id) != str(pending.get("convo_id", incoming_convo_id)):
        context.user_data.pop("role_pending", None)
        await context.bot.send_message(chat_id=chat.id, text="这次对话管理操作属于另一个聊天或话题，已经取消。")
        return True
    if getattr(chat, "type", "") != "private" and not await _role_group_admin(update, context):
        context.user_data.pop("role_pending", None)
        await context.bot.send_message(chat_id=chat.id, text="只有群管理员可以修改这个群组的共享角色与对话。")
        return True
    owner_key = str(pending.get("owner_key", ""))
    action = str(pending.get("action", ""))
    try:
        if action == "role_create":
            created = ROLE_DIALOGUES.create_role(owner_key, text)
            result = "已创建并切换到角色：" + str(created["name"])
        elif action == "role_rename":
            renamed = ROLE_DIALOGUES.rename_role(owner_key, pending.get("role_id"), text)
            result = "已将角色重命名为：" + str(renamed["name"]) if renamed else "这个角色已经不存在。"
        elif action == "role_field":
            updated = ROLE_DIALOGUES.update_role(owner_key, pending.get("role_id"), pending.get("field"), text)
            result = "角色设定已更新。" if updated else "这个角色已经不存在。"
        elif action == "dialogue_create":
            created = ROLE_DIALOGUES.create(owner_key, text)
            result = "已创建并切换到对话：" + str(created["name"])
        elif action == "dialogue_rename":
            renamed = ROLE_DIALOGUES.rename(owner_key, pending.get("dialogue_id"), text)
            result = "已将对话重命名为：" + str(renamed["name"]) if renamed else "这个对话已经不存在。"
        else:
            result = "这次操作已经失效。"
    except ValueError as exc:
        messages = {
            "role_limit": "自定义角色数量已达到上限。",
            "dialogue_limit": "当前活跃对话数量已达到上限。",
            "duplicate_name": "这个名称已经被使用了，请换一个名称。",
            "default_role": "默认角色不能重命名。",
        }
        result = messages.get(str(exc), "这个名称或设定无法使用，请换一个内容。")
    context.user_data.pop("role_pending", None)
    await context.bot.send_message(chat_id=chat.id, text=result)
    return True


@decorators.GroupAuthorization
@decorators.Authorization
async def role_cancel_command(update, context):
    if getattr(context, "user_data", None) and context.user_data.pop("role_pending", None):
        await context.bot.send_message(chat_id=update.effective_chat.id, text="已取消这次对话管理操作。")
    else:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="当前没有等待中的对话管理操作。")


@decorators.GroupAuthorization
@decorators.Authorization
async def persona_command(update, context):
    _, _, _, chatid, _, _, _, _, convo_id, _, _, _ = await GetMesageInfo(update, context, voice=False)
    owner_key, active, _ = active_role_context(update, chatid, convo_id)
    await context.bot.send_message(chat_id=chatid, text=_role_panel_text(owner_key, active), reply_markup=_role_panel_markup(active))


async def _pending_prompt(update, context, action, prompt, **extra):
    _, _, _, chatid, _, _, _, thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context, voice=False)
    owner_key, active, _ = active_role_context(update, chatid, convo_id)
    if not await _role_mutation_allowed(update, context, None):
        return
    message = await _role_prompt_message(context, chatid, thread_id, prompt)
    context.user_data["role_pending"] = {
        "action": action,
        "owner_key": owner_key,
        "chat_id": str(chatid),
        "convo_id": str(convo_id),
        "prompt_message_id": message.message_id,
        **extra,
    }


@decorators.GroupAuthorization
@decorators.Authorization
async def role_dialogue_button(update, context):
    query = update.callback_query
    if query is None or not str(query.data or "").startswith("ROLE_"):
        return
    _, _, _, chatid, _, _, _, _, convo_id, _, _, _ = await GetMesageInfo(update, context, voice=False)
    owner_key, active, _ = active_role_context(update, chatid, convo_id)
    data = str(query.data or "")

    if data == "ROLE_CLOSE":
        await query.answer()
        await query.edit_message_text("角色面板已收起。")
        return
    if data == "ROLE_PANEL":
        await query.answer()
        await _show_role_panel(query, owner_key, active_role_context(update, chatid, convo_id)[1])
        return
    if data == "ROLE_LIST":
        rows = ROLE_DIALOGUES.list_roles(owner_key)
        await query.answer()
        await query.edit_message_text(text="请选择要使用的角色：", reply_markup=_role_list_markup(rows))
        return
    if data == "ROLE_NEW":
        await query.answer()
        await _pending_prompt(update, context, "role_create", "请发送新角色名称，最多 60 个字符；发送 /cancel 取消。")
        return
    if data.startswith("ROLE_SWITCH:"):
        if not await _role_mutation_allowed(update, context, query): return
        role_id = data.split(":", 1)[1]
        selected = ROLE_DIALOGUES.switch_role(owner_key, role_id)
        if selected is None:
            await query.answer(text="这个角色不存在或已归档。", show_alert=True)
            return
        await query.answer()
        await _show_role_panel(query, owner_key, active_role_context(update, chatid, convo_id)[1])
        return
    if data == "ROLE_SETTINGS":
        await query.answer()
        await _show_role_settings(query, active)
        return
    if data.startswith("ROLE_FIELD:"):
        field = data.split(":", 1)[1]
        labels = {"identity": "身份", "tone": "语气", "welcome": "欢迎语", "prompt": "补充设定"}
        await query.answer()
        await _pending_prompt(update, context, "role_field", "请发送新的" + labels.get(field, "角色设定") + "；发送 /cancel 取消。", role_id=active["role_id"], field=field)
        return
    if data == "ROLE_RENAME_PROMPT":
        if active.get("role_default"):
            await query.answer(text="默认角色不能重命名。", show_alert=True)
            return
        await query.answer()
        await _pending_prompt(update, context, "role_rename", "请发送新的角色名称；发送 /cancel 取消。", role_id=active["role_id"])
        return
    if data == "ROLE_ARCHIVED":
        rows = [row for row in ROLE_DIALOGUES.list_roles(owner_key, include_archived=True) if row.get("archived")]
        if not rows:
            await query.answer(text="目前没有已归档的角色。", show_alert=True)
            return
        await query.answer()
        await query.edit_message_text(text="已归档的角色：", reply_markup=_role_list_markup(rows, archived=True))
        return
    if data.startswith("ROLE_RESTORE:"):
        if not await _role_mutation_allowed(update, context, query): return
        try:
            restored = ROLE_DIALOGUES.restore_role(owner_key, data.split(":", 1)[1])
        except ValueError:
            await query.answer(text="自定义角色数量已达到上限。", show_alert=True)
            return
        if restored is None:
            await query.answer(text="这个角色不存在。", show_alert=True)
            return
        await query.answer()
        await _show_role_panel(query, owner_key, active_role_context(update, chatid, convo_id)[1])
        return
    if data == "ROLE_ARCHIVE_CONFIRM":
        if active.get("role_default"):
            await query.answer(text="默认角色不能归档。", show_alert=True)
            return
        await query.answer()
        await query.edit_message_text(text="归档后会隐藏角色，但不会删除其对话和记忆。确定吗？", reply_markup=_role_confirm_markup("ROLE_ARCHIVE"))
        return
    if data == "ROLE_ARCHIVE":
        if not await _role_mutation_allowed(update, context, query): return
        ROLE_DIALOGUES.archive_role(owner_key, active["role_id"])
        await query.answer()
        await _show_role_panel(query, owner_key, active_role_context(update, chatid, convo_id)[1])
        return
    if data == "ROLE_DELETE_CONFIRM":
        if active.get("role_default"):
            await query.answer(text="默认角色不能删除。", show_alert=True)
            return
        await query.answer()
        await query.edit_message_text(text="删除角色会清除该角色全部对话、记忆和成长状态，不能恢复。确定吗？", reply_markup=_role_confirm_markup("ROLE_DELETE"))
        return
    if data == "ROLE_DELETE":
        if not await _role_mutation_allowed(update, context, query): return
        role_id = active["role_id"]
        for runtime_key in ROLE_DIALOGUES.role_runtime_keys(owner_key, role_id):
            conversation_stop_events[runtime_key].set()
            remove_job_if_exists(runtime_key, context)
            MEMORY.forget_runtime(runtime_key)
            MEMORY_SESSION_CUTOFF.pop(runtime_key, None)
            MEMORY_SESSION_SUMMARY.pop(runtime_key, None)
        ROLE_DIALOGUES.delete_role(owner_key, role_id)
        await query.answer()
        await _show_role_panel(query, owner_key, active_role_context(update, chatid, convo_id)[1])
        return
    if data == "ROLE_DIALOGUE_PANEL":
        await query.answer()
        await _show_dialogue_panel(query, active)
        return
    if data == "ROLE_DIALOGUE_LIST":
        rows = ROLE_DIALOGUES.list_dialogues(owner_key)
        await query.answer()
        await query.edit_message_text(text="请选择要使用的对话：", reply_markup=_dialogue_list_markup(rows))
        return
    if data == "ROLE_NEW_DIALOGUE":
        await query.answer()
        await _pending_prompt(update, context, "dialogue_create", "请发送新对话名称，最多 80 个字符；发送 /cancel 取消。")
        return
    if data.startswith("ROLE_DIALOGUE_SWITCH:"):
        if not await _role_mutation_allowed(update, context, query): return
        selected = ROLE_DIALOGUES.switch(owner_key, data.split(":", 1)[1])
        if selected is None:
            await query.answer(text="这个对话不存在或已归档。", show_alert=True)
            return
        await query.answer()
        await _show_role_panel(query, owner_key, active_role_context(update, chatid, convo_id)[1])
        return
    if data == "ROLE_RENAME_DIALOGUE_PROMPT":
        await query.answer()
        await _pending_prompt(update, context, "dialogue_rename", "请发送新的对话名称；发送 /cancel 取消。", dialogue_id=active["id"])
        return
    if data == "ROLE_DIALOGUE_ARCHIVED":
        rows = [row for row in ROLE_DIALOGUES.list_dialogues(owner_key, include_archived=True) if row.get("archived")]
        if not rows:
            await query.answer(text="目前没有已归档的对话。", show_alert=True)
            return
        await query.answer()
        await query.edit_message_text(text="已归档的对话：", reply_markup=_dialogue_list_markup(rows, archived=True))
        return
    if data.startswith("ROLE_DIALOGUE_RESTORE:"):
        if not await _role_mutation_allowed(update, context, query): return
        try:
            restored = ROLE_DIALOGUES.restore(owner_key, data.split(":", 1)[1])
        except ValueError:
            await query.answer(text="当前活跃对话数量已达到上限。", show_alert=True)
            return
        if restored is None:
            await query.answer(text="这个对话不存在。", show_alert=True)
            return
        await query.answer()
        await _show_dialogue_panel(query, active_role_context(update, chatid, convo_id)[1])
        return
    if data == "ROLE_ARCHIVE_DIALOGUE_CONFIRM":
        if active["id"] == ROLE_DIALOGUES.DEFAULT_DIALOGUE_ID:
            await query.answer(text="默认对话不能归档。", show_alert=True)
            return
        await query.answer()
        await query.edit_message_text(text="归档后会隐藏对话，但不会删除历史和记忆。确定吗？", reply_markup=_role_confirm_markup("ROLE_ARCHIVE_DIALOGUE", "ROLE_DIALOGUE_PANEL"))
        return
    if data == "ROLE_ARCHIVE_DIALOGUE":
        if not await _role_mutation_allowed(update, context, query): return
        runtime_key = active["runtime_key"]
        conversation_stop_events[runtime_key].set()
        remove_job_if_exists(runtime_key, context)
        ROLE_DIALOGUES.archive(owner_key, active["id"])
        await query.answer()
        await _show_dialogue_panel(query, active_role_context(update, chatid, convo_id)[1])
        return
    if data == "ROLE_DELETE_DIALOGUE_CONFIRM":
        if active["id"] == ROLE_DIALOGUES.DEFAULT_DIALOGUE_ID:
            await query.answer(text="默认对话不能删除。", show_alert=True)
            return
        await query.answer()
        await query.edit_message_text(text="删除对话会清除其历史、记忆和成长状态，不能恢复。确定吗？", reply_markup=_role_confirm_markup("ROLE_DELETE_DIALOGUE", "ROLE_DIALOGUE_PANEL"))
        return
    if data == "ROLE_DELETE_DIALOGUE":
        if not await _role_mutation_allowed(update, context, query): return
        runtime_key = active["runtime_key"]
        conversation_stop_events[runtime_key].set()
        remove_job_if_exists(runtime_key, context)
        MEMORY.forget_runtime(runtime_key)
        MEMORY_SESSION_CUTOFF.pop(runtime_key, None)
        MEMORY_SESSION_SUMMARY.pop(runtime_key, None)
        ROLE_DIALOGUES.delete(owner_key, active["id"])
        await query.answer()
        await _show_dialogue_panel(query, active_role_context(update, chatid, convo_id)[1])
        return
    if data == "ROLE_RESET_CONFIRM":
        await query.answer()
        await query.edit_message_text(text="只会清除当前对话档案，不会影响其他对话。确定要重置吗？", reply_markup=_role_confirm_markup("ROLE_RESET", "ROLE_DIALOGUE_PANEL"))
        return
    if data == "ROLE_RESET":
        if not await _role_mutation_allowed(update, context, query): return
        runtime_key = active["runtime_key"]
        conversation_stop_events[runtime_key].set()
        remove_job_if_exists(runtime_key, context)
        reset_runtime_session(runtime_key, convo_id)
        mark_runtime_reset(runtime_key)
        await query.answer()
        await _show_dialogue_panel(query, active_role_context(update, chatid, convo_id)[1])
        return
    await query.answer(text="这个角色操作已经失效。", show_alert=True)


@decorators.AdminAuthorization
@decorators.GroupAuthorization
@decorators.Authorization
async def button_press(update, context):
    """Handle the existing settings panel and the role panel."""
    if str(getattr(getattr(update, "callback_query", None), "data", "")).startswith("ROLE_"):
        return await role_dialogue_button(update, context)
    _, _, _, _, _, _, _, _, convo_id, _, _, _ = await GetMesageInfo(update, context)
    callback_query = update.callback_query
    info_message = update_info_message(convo_id)
    await callback_query.answer()
    data = callback_query.data
    banner = strings['message_banner'][get_current_lang(convo_id)]
    import telegram
    try:
        if data.endswith("_MODELS"):
            data = data[:-7]
            Users.set_config(convo_id, "engine", data)
            try:
                info_message = update_info_message(convo_id)
                message = await callback_query.edit_message_text(
                    text=escape(info_message + banner),
                    reply_markup=InlineKeyboardMarkup(update_models_buttons(convo_id)),
                    parse_mode='MarkdownV2'
                )
            except Exception as e:
                logger.info(e)
                pass
        elif data.endswith("_GROUP"):
            # Processing a click on a group of models
            group_name = data[:-6]
            try:
                message = await callback_query.edit_message_text(
                    text=escape(info_message + f"\n\n**{strings['group_title'][get_current_lang(convo_id)]}:** `{group_name}`"),
                    reply_markup=InlineKeyboardMarkup(update_models_buttons(convo_id, group=group_name)),
                    parse_mode='MarkdownV2'
                )
            except Exception as e:
                logger.info(e)
                pass
        elif data.startswith("MODELS"):
            message = await callback_query.edit_message_text(
                text=escape(info_message + banner),
                reply_markup=InlineKeyboardMarkup(update_models_buttons(convo_id)),
                parse_mode='MarkdownV2'
            )

        elif data.endswith("_LANGUAGES"):
            data = data[:-10]
            update_language_status(data, chat_id=convo_id)
            try:
                info_message = update_info_message(convo_id)
                message = await callback_query.edit_message_text(
                    text=escape(info_message, italic=False),
                    reply_markup=InlineKeyboardMarkup(update_menu_buttons(LANGUAGES, "_LANGUAGES", convo_id)),
                    parse_mode='MarkdownV2'
                )
            except Exception as e:
                logger.info(e)
                pass
        elif data.startswith("LANGUAGE"):
            message = await callback_query.edit_message_text(
                text=escape(info_message, italic=False),
                reply_markup=InlineKeyboardMarkup(update_menu_buttons(LANGUAGES, "_LANGUAGES", convo_id)),
                parse_mode='MarkdownV2'
            )

        if data.endswith("_PREFERENCES"):
            data = data[:-12]
            try:
                current_data = Users.get_config(convo_id, data)
                if data == "PASS_HISTORY":
                    if current_data == 0:
                        current_data = config.PASS_HISTORY or 9999
                    else:
                        current_data = 0
                    Users.set_config(convo_id, data, current_data)
                else:
                    Users.set_config(convo_id, data, not current_data)
            except Exception as e:
                logger.info(e)
            try:
                info_message = update_info_message(convo_id)
                message = await callback_query.edit_message_text(
                    text=escape(info_message, italic=False),
                    reply_markup=InlineKeyboardMarkup(update_menu_buttons(PREFERENCES, "_PREFERENCES", convo_id)),
                    parse_mode='MarkdownV2'
                )
            except Exception as e:
                logger.info(e)
                pass
        elif data.startswith("PREFERENCES"):
            message = await callback_query.edit_message_text(
                text=escape(info_message, italic=False),
                reply_markup=InlineKeyboardMarkup(update_menu_buttons(PREFERENCES, "_PREFERENCES", convo_id)),
                parse_mode='MarkdownV2'
            )

        if data.endswith("_PLUGINS"):
            data = data[:-8]
            try:
                current_data = Users.get_config(convo_id, data)
                Users.set_config(convo_id, data, not current_data)
            except Exception as e:
                logger.info(e)
            try:
                info_message = update_info_message(convo_id)
                message = await callback_query.edit_message_text(
                    text=escape(info_message, italic=False),
                    reply_markup=InlineKeyboardMarkup(update_menu_buttons(PLUGINS, "_PLUGINS", convo_id)),
                    parse_mode='MarkdownV2'
                )
            except Exception as e:
                logger.info(e)
                pass
        elif data.startswith("PLUGINS"):
            message = await callback_query.edit_message_text(
                text=escape(info_message, italic=False),
                reply_markup=InlineKeyboardMarkup(update_menu_buttons(PLUGINS, "_PLUGINS", convo_id)),
                parse_mode='MarkdownV2'
            )

        elif data.startswith("BACK"):
            message = await callback_query.edit_message_text(
                text=escape(info_message, italic=False),
                reply_markup=InlineKeyboardMarkup(update_first_buttons_message(convo_id)),
                parse_mode='MarkdownV2'
            )
    except telegram.error.BadRequest as e:
        print('\033[31m')
        traceback.print_exc()
        if "Message to edit not found" in str(e):
            print("error: telegram.error.BadRequest: Message to edit not found!")
        else:
            print(f"error: {str(e)}")
        print('\033[0m')

@decorators.GroupAuthorization
@decorators.Authorization
@decorators.APICheck
async def handle_file(update, context):
    _, _, image_url, chatid, _, _, _, message_thread_id, convo_id, file_url, _, voice_text = await GetMesageInfo(update, context)
    _, _, runtime_convo_id = active_role_context(update, chatid, convo_id)
    robot, role, api_key, api_url = get_robot(convo_id)
    engine = Users.get_config(convo_id, "engine")

    if file_url == None and image_url:
        file_url = image_url
        if Users.get_config(convo_id, "IMAGEQA") == False:
            return
    if image_url == None and file_url:
        image_url = file_url
    engine_type, _ = get_engine({"base_url": api_url}, endpoint=None, original_model=engine)
    if robot.__class__.__name__ == "chatgpt":
        engine_type = "gpt"
    message = await Document_extract(file_url, image_url, engine_type)

    robot.add_to_conversation(message, role, runtime_convo_id)

    if Users.get_config(convo_id, "FILE_UPLOAD_MESS"):
        message = await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text=escape(strings['message_doc'][get_current_lang(convo_id)]), parse_mode='MarkdownV2', disable_web_page_preview=True)
        await delete_message(update, context, [message.message_id])

@decorators.GroupAuthorization
@decorators.Authorization
@decorators.APICheck
async def inlinequery(update: Update, context) -> None:
    """Handle the inline query."""

    chatid = update.effective_user.id
    engine = Users.get_config(chatid, "engine")
    query = update.inline_query.query
    if (query.endswith('.') or query.endswith('。')) and query.strip():
        prompt = "Answer the following questions as concisely as possible:\n\n"
        _, _, _, chatid, _, _, _, _, convo_id, _, _, _ = await GetMesageInfo(update, context)
        robot, role, api_key, api_url = get_robot(convo_id)
        result = config.ChatGPTbot.ask(prompt + query, convo_id=convo_id, model=engine, api_url=api_url, api_key=api_key, pass_history=0)

        results = [
            InlineQueryResultArticle(
                id=chatid,
                title=f"{engine}",
                thumbnail_url="https://pb.yym68686.top/TTGk",
                description=f"{result}",
                input_message_content=InputTextMessageContent(escape(result, italic=False), parse_mode='MarkdownV2')),
        ]

        await update.inline_query.answer(results)

async def guest_update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 Bot API 10.0 的 Update.guest_message。

    PTB 22.5 尚未为 guest_message 建模，原始数据位于 update.api_kwargs。
    Guest 只能通过 answerGuestQuery 创建一条消息；之后以 inline_message_id 编辑该消息。
    """
    raw_guest = getattr(update, "api_kwargs", {}).get("guest_message")
    if not isinstance(raw_guest, dict):
        return

    guest_query_id = str(raw_guest.get("guest_query_id") or "")
    text = str(raw_guest.get("text") or raw_guest.get("caption") or "").strip()
    caller = raw_guest.get("guest_bot_caller_user") or raw_guest.get("from") or {}
    caller_id = str(caller.get("id") or "")
    caller_name = str(caller.get("first_name") or caller.get("username") or "Guest")
    chat = raw_guest.get("chat") or {}
    chatid = chat.get("id")
    if not guest_query_id or not text:
        logger.warning("Guest 更新缺少 query_id 或文本；keys=%s", list(raw_guest))
        return

    # Guest 不属于普通 chat/message 更新；按调用者隔离上下文。
    # 访问控制沿用私聊规则：动态 allow、环境白名单和管理员均可进入。
    dynamic_user_allowed = is_user_allowed(caller_id)
    static_user_allowed = bool(config.whitelist and caller_id in config.whitelist)
    is_admin = bool(config.ADMIN_LIST and caller_id in config.ADMIN_LIST)
    access_enabled = bool(config.whitelist or dynamic_user_allowed)
    if access_enabled and not (is_admin or dynamic_user_allowed or static_user_allowed):
        await context.bot._post("answerGuestQuery", data={
            "guest_query_id": guest_query_id,
            "result": {
                "type": "article", "id": guest_query_id[:64], "title": "访问受限",
                "input_message_content": {"message_text": "你暂时没有使用宵雫的权限。"},
            },
        })
        return

    bot_info = await context.bot.get_me()
    username = bot_info.username or ""
    mention = "@" + username.lower()
    if text.lower().startswith(mention):
        text = text[len(mention):].lstrip(" ,，:：\n")
    if not text:
        text = "你好。"

    # Guest 按调用者隔离会话；没有持久聊天归属时避免继承群组设置。
    # 读取全局默认配置，再让用户自己的动态配置正常覆盖。
    guest_convo_id = "guest:" + caller_id
    engine = Users.get_config(None, "engine")
    api_key = Users.get_config(None, "api_key")
    api_url = Users.get_config(None, "api_url")
    language = Users.get_config(None, "language")
    system_prompt = Users.get_config(None, "systemprompt")
    plugins = Users.extract_plugins_config(None)
    robot = config.ChatGPTbot
    if not api_key:
        api_key = getattr(config, "API_KEY", None)
    if not api_url:
        api_url = getattr(config, "API_URL", None)

    logger.warning("Guest 收到召唤：caller=%s chat=%s query=%s text=%r", caller_id, chatid, guest_query_id[:12], text[:80])

    # Guest 首次应答建立一个可编辑的 inline 消息；结果只会在原调用聊天中出现。
    initial = "`宵雫思索中 ▪︎□□`"
    try:
        sent = await context.bot._post("answerGuestQuery", data={
            "guest_query_id": guest_query_id,
            "result": {
                "type": "article", "id": guest_query_id[:64], "title": "宵雫",
                "input_message_content": {"message_text": initial, "parse_mode": "MarkdownV2"},
            },
        })
        inline_message_id = str((sent or {}).get("inline_message_id") or "")
    except Exception as exc:
        logger.exception("answerGuestQuery 初始应答失败：%s", exc)
        return
    if not inline_message_id:
        logger.error("answerGuestQuery 未返回 inline_message_id")
        return

    result = ""
    last_rendered = ""
    last_edit_at = 0.0
    edit_interval = 1.2

    async def _edit_guest(text, *, plain=False):
        """按 Telegram Guest 限制节流编辑，并处理 429 RetryAfter。"""
        nonlocal last_edit_at
        import time as _time
        wait = edit_interval - (_time.monotonic() - last_edit_at)
        if wait > 0:
            await asyncio.sleep(wait)
        while True:
            try:
                await context.bot.edit_message_text(
                    text=text,
                    inline_message_id=inline_message_id,
                    parse_mode=None if plain else "MarkdownV2",
                    disable_web_page_preview=True,
                )
                last_edit_at = _time.monotonic()
                return True
            except RetryAfter as exc:
                delay = float(exc.retry_after) + 0.5
                logger.warning("Guest 编辑受限，%.1f 秒后重试", delay)
                await asyncio.sleep(delay)
            except Exception as exc:
                if "message is not modified" in str(exc).lower():
                    return True
                logger.warning("Guest 编辑失败：%s", exc)
                return False

    try:
        async for chunk in robot.ask_stream_async(
            text,
            convo_id=guest_convo_id,
            pass_history=0,
            model=engine,
            language=language,
            api_url=api_url,
            api_key=api_key,
            system_prompt=system_prompt,
            plugins=plugins,
        ):
            if "message_search_stage_" in chunk:
                continue
            result += chunk
            # Guest 走 inline_message_id 编辑，限制频率以避免 Flood control。
            rendered = escape(result, italic=False)
            if rendered and rendered != last_rendered:
                if await _edit_guest(rendered):
                    last_rendered = rendered
        final = escape(result or "……这次没有收到可以回答的内容。", italic=False)
        if final != last_rendered:
            await _edit_guest(final)
    except Exception as exc:
        logger.exception("Guest 推理失败：%s", exc)
        await _edit_guest("……刚才的回答出了问题，请再试一次。", plain=True)


@decorators.GroupAuthorization
@decorators.Authorization
async def change_model(update, context):
    """Quick model change using the command"""
    _, _, _, chatid, user_message_id, _, _, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context)
    lang = get_current_lang(convo_id)

    if not context.args:
        message = await context.bot.send_message(
            chat_id=chatid,
            message_thread_id=message_thread_id,
            text=escape(strings['model_command_usage'][lang]),
            parse_mode='MarkdownV2',
            reply_to_message_id=user_message_id,
        )
        return

    # Combine all arguments into one model name
    model_name = ' '.join(context.args)

    # Check if the model name is valid (allowing all common model name characters)
    if not re.match(r'^[a-zA-Z0-9\-_\./:\\@+\s]+$', model_name) or len(model_name) > 100:
        message = await context.bot.send_message(
            chat_id=chatid,
            message_thread_id=message_thread_id,
            text=escape(strings['model_name_invalid'][lang]),
            parse_mode='MarkdownV2',
            reply_to_message_id=user_message_id,
        )
        return

    # Get all available models from initial_model and MODEL_GROUPS
    available_models = get_all_available_models()
    for group_name, models in get_model_groups().items():
        available_models.extend(models)

    logger.info("Model switch requested; model=%s available_count=%s", model_name, len(available_models))

    # Check if the requested model is in the available models list
    if model_name not in available_models:
        message = await context.bot.send_message(
            chat_id=chatid,
            message_thread_id=message_thread_id,
            text=escape(strings['model_not_available'][lang].format(model_name=model_name)),
            parse_mode='MarkdownV2',
            reply_to_message_id=user_message_id,
        )
        return

    # Saving the new model in the user's configuration
    Users.set_config(convo_id, "engine", model_name)

    # Sending a message about changing the model
    message = await context.bot.send_message(
        chat_id=chatid,
        message_thread_id=message_thread_id,
        text=escape(strings['model_changed'][lang].format(model_name=model_name), italic=False),
        parse_mode='MarkdownV2',
        reply_to_message_id=user_message_id,
    )

async def scheduled_function(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset the exact role dialogue that became idle."""
    job = context.job
    chat_id = str(job.chat_id)
    data = job.data or {}
    runtime_convo_id = str(data.get("runtime_convo_id") or job.name or chat_id)
    config_convo_id = str(data.get("config_convo_id") or chat_id)

    if config.ADMIN_LIST and chat_id in config.ADMIN_LIST:
        return

    conversation_stop_events[runtime_convo_id].set()
    reset_runtime_session(runtime_convo_id, config_convo_id)
    try:
        mark_runtime_reset(runtime_convo_id)
    except Exception as exc:
        logger.warning("Persistent role dialogue reset marker failed: %s", exc)

    remove_job_if_exists(runtime_convo_id, context)


def remove_job_if_exists(name: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """如果存在，则移除指定名称的任务"""
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True

@decorators.GroupAuthorization
@decorators.Authorization
async def reset_chat(update, context):
    _, _, _, chatid, user_message_id, _, _, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context)
    _, active, runtime_convo_id = active_dialogue_context(update, chatid, convo_id)
    conversation_stop_events[runtime_convo_id].set()
    message = None
    if (len(context.args) > 0):
        message = ' '.join(context.args)
    reset_runtime_session(runtime_convo_id, convo_id, message)
    try:
        mark_runtime_reset(runtime_convo_id)
    except Exception as exc:
        logger.warning("Persistent role dialogue reset marker failed: %s", exc)
    remove_job_if_exists(runtime_convo_id, context)

    remove_keyboard = ReplyKeyboardRemove()
    message = await context.bot.send_message(
        chat_id=chatid,
        message_thread_id=message_thread_id,
        text=escape(strings['message_reset'][get_current_lang(convo_id)]),
        reply_markup=remove_keyboard,
        parse_mode='MarkdownV2',
    )
    if GET_MODELS:
        robot, role, api_key, api_url = get_robot(convo_id)
        engine = Users.get_config(convo_id, "engine")
        provider = {
            "provider": "openai",
            "base_url": api_url,
            "api": api_key,
            "model": [engine],
            "tools": True,
            "image": True
        }
        config.initial_model = remove_no_text_model(await update_initial_model(provider))
    await delete_message(update, context, [message.message_id, user_message_id])


def _format_memory_stats(stats):
    profile = stats.get("profile") or {}
    relation = stats.get("relationship") or {}
    state = stats.get("state") or {}
    profile_parts = []
    if profile.get("stable_preferences"):
        profile_parts.append("稳定偏好：" + profile["stable_preferences"].replace("\n", "；"))
    if profile.get("response_style"):
        profile_parts.append("表达偏好：" + profile["response_style"].replace("\n", "；"))
    return {
        "turns": stats.get("turns", 0),
        "events": stats.get("events", 0),
        "profile": "\n".join(profile_parts) if profile_parts else "宵雫还没有整理出稳定偏好。再相处一阵，她会慢慢记住的。",
        "stage": relation.get("stage", "初熟"),
        "mood": state.get("mood", "平静"),
        "updated": profile.get("last_seen_local") or state.get("updated_at") or "无",
        "dialogue_name": stats.get("dialogue_name", "默认对话"),
    }


def _current_role_memory_stats(update, chatid, convo_id, user_id):
    owner_key, active, runtime_convo_id = active_dialogue_context(update, chatid, convo_id)
    dialogue_stats = MEMORY.stats(runtime_convo_id)
    growth = MEMORY.user_stats(role_growth_identity(runtime_convo_id, user_id, convo_id)) if user_id else {}
    return {
        "turns": dialogue_stats.get("turns", 0),
        "events": growth.get("events", 0),
        "profile": growth.get("profile", {}),
        "relationship": growth.get("relationship", {}),
        "state": growth.get("state", {}),
        "dialogue_name": active.get("name", "默认对话"),
    }


@decorators.GroupAuthorization
@decorators.Authorization
async def role_memory_command(update, context):
    _, _, _, chatid, _, _, _, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context, voice=False)
    owner_key, active, runtime_convo_id = active_role_context(update, chatid, convo_id)
    role_id = active.get("role_id")
    if not context.args:
        rows = MEMORY.list_role_shared_memories(owner_key, role_id)
        if not rows:
            text = "这个角色目前还没有共同记忆。可用：/role_memory add <内容>"
        else:
            lines = ["这个角色当前共同记忆："]
            for row in rows[:10]:
                lines.append(f"- {row['id']}: {row['content']}")
            lines.append("")
            lines.append("新增：/role_memory add <内容>")
            lines.append("删除：/role_memory del <ID>")
            text = "\n".join(lines)
        await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text=text)
        return
    action = str(context.args[0]).lower()
    if action == "add":
        payload = " ".join(context.args[1:]).strip()
        if not payload:
            await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text="请在 add 后面直接写要记给当前角色的内容。")
            return
        memory_id, created = MEMORY.add_role_shared_memory(owner_key, role_id, payload, source_convo_id=runtime_convo_id)
        word = "已新增" if created else "已更新"
        await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text=f"{word}角色共同记忆 #{memory_id}。")
        return
    if action == "del":
        if len(context.args) < 2 or not str(context.args[1]).isdigit():
            await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text="请使用：/role_memory del <ID>")
            return
        ok = MEMORY.delete_role_shared_memory(owner_key, role_id, int(context.args[1]))
        await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text="已删除。" if ok else "没有找到这个角色共同记忆 ID。")
        return
    await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text="可用：/role_memory、/role_memory add <内容>、/role_memory del <ID>")


@decorators.GroupAuthorization
@decorators.Authorization
async def remember_role_command(update, context):
    _, _, _, chatid, _, _, _, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context, voice=False)
    if not context.args:
        await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text="请直接写要提升为当前角色共同记忆的内容，例如：/remember_role 主人喜欢少糖。")
        return
    owner_key, active, runtime_convo_id = active_role_context(update, chatid, convo_id)
    role_id = active.get("role_id")
    payload = " ".join(context.args).strip()
    memory_id, created = MEMORY.add_role_shared_memory(owner_key, role_id, payload, source_convo_id=runtime_convo_id)
    word = "已记给当前角色" if created else "这条角色共同记忆已存在，已刷新时间"
    await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text=f"{word}。ID: {memory_id}")


async def lore_command(update, context):
    return await role_memory_command(update, context)


async def canon_command(update, context):
    return await remember_role_command(update, context)


@decorators.GroupAuthorization
@decorators.Authorization
async def memory_info(update, context):
    _, _, _, chatid, _, _, _, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context)
    if getattr(getattr(update, 'effective_chat', None), 'type', '') != 'private':
        await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text="这些是只属于你的记忆。到私聊里来，宵雫再悄悄告诉你。")
        return
    user_id = str(getattr(getattr(update, 'effective_user', None), 'id', '') or '')
    data = _format_memory_stats(_current_role_memory_stats(update, chatid, convo_id, user_id))
    text = (
        f"宵雫记得的事情（{data['dialogue_name']}）\n"
        f"已经收好的对话：{data['turns']} 条\n"
        f"记得比较清楚的事情：{data['events']} 条\n"
        f"{data['profile']}"
    )
    await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text=text)


@decorators.GroupAuthorization
@decorators.Authorization
async def state_info(update, context):
    _, _, _, chatid, _, _, _, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context)
    if getattr(getattr(update, 'effective_chat', None), 'type', '') != 'private':
        await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text="这些变化也只属于你。到私聊里，宵雫再给你看。")
        return
    user_id = str(getattr(getattr(update, 'effective_user', None), 'id', '') or '')
    data = _format_memory_stats(_current_role_memory_stats(update, chatid, convo_id, user_id))
    text = (
        f"宵雫现在的样子（{data['dialogue_name']}）\n"
        f"我们走到的阶段：{data['stage']}\n"
        f"她现在的心情：{data['mood']}\n"
        f"上次认真记下变化：{data['updated']}"
    )
    await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text=text)


@decorators.AdminAuthorization
async def allow_command(update, context):
    _, _, _, chatid, _, _, _, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context, voice=False)
    if len(context.args) != 1:
        await context.bot.send_message(
            chat_id=chatid,
            message_thread_id=message_thread_id,
            text="宵雫需要一个完整的编号。正数是用户，负数是群组。请这样发送：/allow 635…",
        )
        return
    identifier = str(context.args[0]).strip()
    if not re.fullmatch(r"-?[1-9][0-9]{4,19}", identifier):
        await context.bot.send_message(
            chat_id=chatid,
            message_thread_id=message_thread_id,
            text="这个编号看起来不完整。正数是用户，负数是群组。请这样发送：/allow 635…",
        )
        return
    try:
        kind, added = allow_access(identifier)
    except OSError:
        logger.exception("Failed to persist access-control entry")
        await context.bot.send_message(
            chat_id=chatid,
            message_thread_id=message_thread_id,
            text="……名单暂时没有保存成功。宵雫没有把它记进去，请稍后再试一次。",
        )
        return
    if kind == "group":
        if added:
            text = f"已经记下了。群组 `{identifier}` 里的成员，现在都可以使用宵雫。"
        else:
            text = f"群组 `{identifier}` 已经在允许名单里，不需要再添加一次。"
    else:
        if added:
            text = f"已经记下了。编号为 `{identifier}` 的用户，现在可以来找宵雫了。"
        else:
            text = f"编号为 `{identifier}` 的用户已经在允许名单里，不需要再添加一次。"
    await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text=text, parse_mode="Markdown")


@decorators.GroupAuthorization
@decorators.Authorization
async def forget_memory(update, context):
    _, _, _, chatid, _, _, update_message, message_thread_id, convo_id, _, _, _ = await GetMesageInfo(update, context)
    if getattr(getattr(update, 'effective_chat', None), 'type', '') != 'private':
        await context.bot.send_message(chat_id=chatid, message_thread_id=message_thread_id, text="这件事只能在私聊里做。到那里，再把 /forget confirm 交给宵雫。")
        return
    if not context.args or context.args[0].lower() != 'confirm':
        await context.bot.send_message(
            chat_id=chatid,
            text="这会让宵雫忘掉与你有关的长期记忆、相处变化和这段私聊。若你真的决定好了，请发送：/forget confirm",
        )
        return
    user_id = str(getattr(getattr(update, 'effective_user', None), 'id', '') or '')
    _, active, runtime_convo_id = active_dialogue_context(update, chatid, convo_id)
    growth_user_id = role_growth_identity(runtime_convo_id, user_id, convo_id)
    MEMORY.forget_user(growth_user_id, runtime_convo_id)
    MEMORY_SESSION_CUTOFF.pop(runtime_convo_id, None)
    MEMORY_SESSION_SUMMARY.pop(runtime_convo_id, None)
    reset_runtime_session(runtime_convo_id, convo_id)
    remove_job_if_exists(runtime_convo_id, context)
    await context.bot.send_message(chat_id=chatid, text=f"……已经忘掉了。属于你的‘{active.get('name', '默认对话')}’档案、长期记忆和相处变化，都不会再被宵雫提起。")


@decorators.AdminAuthorization
@decorators.GroupAuthorization
@decorators.Authorization
async def info(update, context):
    _, _, _, chatid, user_message_id, _, _, message_thread_id, convo_id, _, _, voice_text = await GetMesageInfo(update, context)
    info_message = update_info_message(convo_id)
    message = await context.bot.send_message(
        chat_id=chatid,
        message_thread_id=message_thread_id,
        text=escape(info_message, italic=False),
        reply_markup=InlineKeyboardMarkup(update_first_buttons_message(convo_id)),
        parse_mode='MarkdownV2',
        disable_web_page_preview=True,
        read_timeout=600,
    )
    await delete_message(update, context, [message.message_id, user_message_id])

@decorators.PrintMessage
@decorators.GroupAuthorization
@decorators.Authorization
async def start(update, context): # 当用户输入/start时，返回文本
    _, _, _, _, _, _, _, _, convo_id, _, _, _ = await GetMesageInfo(update, context)
    user = update.effective_user
    if user.language_code == "zh-hans":
        update_language_status("Simplified Chinese", chat_id=convo_id)
    elif user.language_code == "zh-hant":
        update_language_status("Traditional Chinese", chat_id=convo_id)
    elif user.language_code and user.language_code.startswith("ja"):
        update_language_status("Japanese", chat_id=convo_id)
    else:
        update_language_status("English", chat_id=convo_id)
    start_template = PERSONA.get("START_MESSAGE") or _PERSONA_DEFAULTS["START_MESSAGE"]
    try:
        message = start_template.format(username=user.username)
    except Exception:
        message = _PERSONA_DEFAULTS["START_MESSAGE"].format(username=user.username)
    if not message.endswith("\n"):
        message += "\n"
    if len(context.args) == 2 and context.args[1].startswith("sk-"):
        api_url = context.args[0]
        api_key = context.args[1]
        Users.set_config(convo_id, "api_key", api_key)
        Users.set_config(convo_id, "api_url", api_url)
        # if GET_MODELS:
        #     update_initial_model()

    if len(context.args) == 1 and context.args[0].startswith("sk-"):
        api_key = context.args[0]
        Users.set_config(convo_id, "api_key", api_key)
        Users.set_config(convo_id, "api_url", "https://api.openai.com/v1/chat/completions")
        # if GET_MODELS:
        #     update_initial_model()

    # message = (
    #     ">Block quotation started\n"
    #     ">Block quotation continued\n"
    #     ">Block quotation continued\n"
    #     ">Block quotation continued\n"
    #     ">The last line of the block quotation\n"
    #     "**>The expandable block quotation started right after the previous block quotation\n"
    #     ">It is separated from the previous block quotation by an empty bold entity\n"
    #     ">Expandable block quotation continued\n"
    #     ">Hidden by default part of the expandable block quotation started\n"
    #     ">Expandable block quotation continued\n"
    #     ">The last line of the expandable block quotation with the expandability mark||\n"
    # )
    # await update.message.reply_text(message, parse_mode='MarkdownV2', disable_web_page_preview=True)
    await update.message.reply_text(escape(message, italic=False), parse_mode='MarkdownV2', disable_web_page_preview=True)

async def error(update, context):
    traceback_string = traceback.format_exception(None, context.error, context.error.__traceback__)
    if "telegram.error.TimedOut: Timed out" in traceback_string:
        logger.warning('error: telegram.error.TimedOut: Timed out')
        return
    if "Message to be replied not found" in traceback_string:
        logger.warning('error: telegram.error.BadRequest: Message to be replied not found')
        return
    logger.warning('Update "%s" caused error "%s"', update, context.error)
    logger.warning('Error traceback: %s', ''.join(traceback_string))

@decorators.GroupAuthorization
@decorators.Authorization
async def unknown(update, context): # 当用户输入未知命令时，返回文本
    return
    # await context.bot.send_message(chat_id=update.effective_chat.id, text="Sorry, I didn't understand that command.")

async def post_init(application: Application) -> None:
    if GET_MODELS:
        await get_initial_model()
    try:
        # PTB 22.x 的 User 类未映射 supports_guest_queries，直调 Bot API
        import httpx, os as _post_os
        token = _post_os.environ.get("BOT_TOKEN", "")
        async with httpx.AsyncClient() as c:
            r = await c.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
            guest_mode = r.json().get("result", {}).get("supports_guest_queries", False)
        if not guest_mode:
            logger.warning("⚠️ Guest Mode 未在 BotFather 开启。@bot 唤起功能不可用。请用 BotFather MiniApp 开启。")
        else:
            logger.warning("✅ Guest Mode 已开启，支持任意聊天 @bot 唤起")
    except Exception:
        import traceback
        logger.error("(Guest) 检测异常:\n%s", traceback.format_exc()[:500])
        logger.warning("(Guest) ⚠️ 请检查 .env 中 BOT_TOKEN 是否正确")

    commands_en = [
        BotCommand("info", "Basic information"),
        BotCommand("reset", "Reset chat"),
        BotCommand("start", "Start the bot"),
        BotCommand("model", "Switch model"),
        BotCommand("memory", "Memory overview"),
        BotCommand("state", "Growth state"),
        BotCommand("forget", "Delete my memory"),
        BotCommand("persona", "Manage roles and dialogues"),
        BotCommand("lore", "Manage role canon"),
        BotCommand("canon", "Promote role canon"),
        BotCommand("allow", "Manage access list"),
    ]
    commands_zh = [
        BotCommand("info", "基本信息"),
        BotCommand("reset", "重置对话"),
        BotCommand("start", "启动机器人"),
        BotCommand("model", "切换模型"),
        BotCommand("memory", "记忆概况"),
        BotCommand("state", "成长状态"),
        BotCommand("forget", "删除我的记忆"),
        BotCommand("persona", "角色与对话管理"),
        BotCommand("lore", "管理角色正史记忆"),
        BotCommand("canon", "写入角色正史记忆"),
        BotCommand("allow", "管理访问名单"),
    ]
    commands_ja = [
        BotCommand("info", "基本情報"),
        BotCommand("reset", "会話リセット"),
        BotCommand("start", "起動"),
        BotCommand("model", "モデル切替"),
        BotCommand("memory", "記憶の概要"),
        BotCommand("state", "成長状態"),
        BotCommand("forget", "記憶を削除"),
        BotCommand("persona", "角色與對話管理"),
        BotCommand("lore", "管理角色正史記憶"),
        BotCommand("canon", "寫入角色正史記憶"),
        BotCommand("allow", "管理訪問名單"),
    ]

    # Default + language-specific command menus
    # Default commands in Chinese; language-specific menus for en/zh/ja.
    # Note: Telegram rejects some codes like zh-hans/zh-hant here.
    await application.bot.set_my_commands(commands_zh)
    await application.bot.set_my_commands(commands_en, language_code="en")
    await application.bot.set_my_commands(commands_zh, language_code="zh")
    await application.bot.set_my_commands(commands_ja, language_code="ja")

    description = PERSONA.get("BOT_DESCRIPTION") or _PERSONA_DEFAULTS["BOT_DESCRIPTION"]
    await application.bot.set_my_description(description)

if __name__ == '__main__':
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(16)
        .connection_pool_size(32)
        .get_updates_connection_pool_size(8)
        .read_timeout(time_out)
        .write_timeout(time_out)
        .connect_timeout(time_out)
        .pool_timeout(time_out)
        .get_updates_read_timeout(30)
        .get_updates_write_timeout(time_out)
        .get_updates_connect_timeout(time_out)
        .get_updates_pool_timeout(time_out)
                # .rate_limiter removed -- was causing 1000s+ delays
        .post_init(post_init)
        .build()
    )

    application.add_handler(CommandHandler("info", info))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset_chat))
    application.add_handler(CommandHandler("model", change_model))
    application.add_handler(CommandHandler("memory", memory_info))
    application.add_handler(CommandHandler("lore", lore_command))
    application.add_handler(CommandHandler("canon", canon_command))
    application.add_handler(CommandHandler("role_memory", role_memory_command))
    application.add_handler(CommandHandler("remember_role", remember_role_command))
    application.add_handler(CommandHandler("state", state_info))
    application.add_handler(CommandHandler("forget", forget_memory))
    application.add_handler(CommandHandler("persona", persona_command))
    application.add_handler(CommandHandler("cancel", role_cancel_command))
    application.add_handler(CommandHandler("allow", allow_command))
    application.add_handler(InlineQueryHandler(inlinequery))
    application.add_handler(CallbackQueryHandler(role_dialogue_button, pattern=r"^ROLE_"))
    application.add_handler(CallbackQueryHandler(button_press))

    # PTB 22.5 不认识 Update.guest_message；TypeHandler 捕获所有 Update，
    # handler 内仅处理 api_kwargs 中实际存在的 guest_message。
    application.add_handler(TypeHandler(Update, guest_update_handler, block=False), group=-1)

    # 普通消息统一路由。Guest 更新由上方 TypeHandler 处理，
    # 不会匹配 MessageHandler（PTB 22.5 的 update.message 为 None）。
    async def role_text_router(update, context):
        if await _handle_role_pending_text(update, context):
            return
        await command_bot(update, context, has_command=False)

    application.add_handler(MessageHandler((filters.TEXT | filters.VOICE) & ~filters.COMMAND, role_text_router, block = False))
    application.add_handler(MessageHandler(
        filters.CAPTION &
        (
            (filters.PHOTO & ~filters.COMMAND) |
            (
                filters.Document.PDF |
                filters.Document.TXT |
                filters.Document.DOC |
                filters.Document.FileExtension("jpg") |
                filters.Document.FileExtension("jpeg") |
                filters.Document.FileExtension("png") |
                filters.Document.FileExtension("md") |
                filters.Document.FileExtension("py") |
                filters.Document.FileExtension("yml")
            )
        ), lambda update, context: command_bot(update, context, has_command=False)))
    application.add_handler(MessageHandler(
        ~filters.CAPTION &
        (
            (filters.PHOTO & ~filters.COMMAND) |
            (
                filters.Document.PDF |
                filters.Document.TXT |
                filters.Document.DOC |
                filters.Document.FileExtension("jpg") |
                filters.Document.FileExtension("jpeg") |
                filters.Document.FileExtension("png") |
                filters.Document.FileExtension("md") |
                filters.Document.FileExtension("py") |
                filters.Document.FileExtension("yml") |
                filters.AUDIO |
                filters.Document.FileExtension("wav")
            )
        ), handle_file))
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
    application.add_error_handler(error)

    if WEB_HOOK:
        print("WEB_HOOK:", WEB_HOOK)
        application.run_webhook("0.0.0.0", PORT, webhook_url=WEB_HOOK)
    else:
        application.run_polling(timeout=time_out)
