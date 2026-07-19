from utils.i18n import strings as _upstream_strings

# Copy nested dicts so overrides do not mutate upstream module state.
strings = {k: (v.copy() if isinstance(v, dict) else v) for k, v in _upstream_strings.items()}

# Ensure every entry has ja slot.
for _key, _val in list(strings.items()):
    if isinstance(_val, dict) and "ja" not in _val:
        _val["ja"] = _val.get("en") or _val.get("zh") or next(iter(_val.values()), _key)

# ---------- language labels (no emoji) ----------
strings["English"] = {
    "zh": "英文", "en": "English", "zh-hk": "英文", "ja": "英語", "ru": "英語",
}
strings["Simplified Chinese"] = {
    "zh": "简中", "en": "简中", "zh-hk": "簡中", "ja": "簡中", "ru": "簡中",
}
strings["Traditional Chinese"] = {
    "zh": "繁中", "en": "繁中", "zh-hk": "繁中", "ja": "繁中", "ru": "繁中",
}
strings["Japanese"] = {
    "zh": "日文", "en": "Japanese", "zh-hk": "日文", "ja": "日本語", "ru": "日本語",
}
if "Russian" in strings:
    strings["Russian"] = {
        "zh": "日文", "en": "Japanese", "zh-hk": "日文", "ja": "日本語", "ru": "日本語",
    }

# ---------- top buttons (no emoji) ----------
strings["button_language"] = {
    "zh": "语言", "en": "Language", "zh-hk": "語言", "ja": "言語", "ru": "言語",
}
strings["button_back"] = {
    "zh": "返回", "en": "Back", "zh-hk": "返回", "ja": "戻る", "ru": "戻る",
}
strings["button_change_model"] = {
    "zh": "模型", "en": "Models", "zh-hk": "模型", "ja": "モデル", "ru": "モデル",
}
strings["button_preferences"] = {
    "zh": "偏好", "en": "Prefs", "zh-hk": "偏好", "ja": "設定", "ru": "設定",
}
strings["button_plugins"] = {
    "zh": "插件", "en": "Plugins", "zh-hk": "插件", "ja": "プラグイン", "ru": "プラグイン",
}

# ---------- preference labels ----------
strings["PASS_HISTORY"] = {
    "zh": "历史记录", "en": "History", "zh-hk": "歷史記錄", "ja": "履歴", "ru": "履歴",
}
strings["IMAGEQA"] = {
    "zh": "图片问答", "en": "Image Q&A", "zh-hk": "圖片問答", "ja": "画像Q&A", "ru": "画像Q&A",
}
strings["LONG_TEXT"] = {
    "zh": "长文合并", "en": "Merge text", "zh-hk": "長文合併", "ja": "長文結合", "ru": "長文結合",
}
strings["LONG_TEXT_SPLIT"] = {
    "zh": "长文分隔", "en": "Split text", "zh-hk": "長文分隔", "ja": "長文分割", "ru": "長文分割",
}
strings["FILE_UPLOAD_MESS"] = {
    "zh": "上传提示", "en": "Upload tip", "zh-hk": "上傳提示", "ja": "送信通知", "ru": "送信通知",
}
strings["FOLLOW_UP"] = {
    "zh": "追问建议", "en": "Follow-up", "zh-hk": "追問建議", "ja": "次の質問", "ru": "次の質問",
}
strings["TITLE"] = {
    "zh": "模型标题", "en": "Model title", "zh-hk": "模型標題", "ja": "モデル名", "ru": "モデル名",
}
strings["REPLY"] = {
    "zh": "回复消息", "en": "Reply msg", "zh-hk": "回覆消息", "ja": "返信形式", "ru": "返信形式",
}

# ---------- plugins (no emoji) ----------
strings["get_search_results"] = {
    "zh": "网络搜索", "en": "Web search", "zh-hk": "網絡搜索", "ja": "ウェブ検索", "ru": "ウェブ検索",
}
strings["get_url_content"] = {
    "zh": "网址总结", "en": "URL summary", "zh-hk": "網址總結", "ja": "URL要約", "ru": "URL要約",
}
strings["get_time"] = {
    "zh": "当前时间", "en": "Time", "zh-hk": "當前時間", "ja": "現在時刻", "ru": "現在時刻",
}
strings["generate_image"] = {
    "zh": "文生图", "en": "Image gen", "zh-hk": "文生圖", "ja": "画像生成", "ru": "画像生成",
}
strings["run_python_script"] = {
    "zh": "代码执行", "en": "Code exec", "zh-hk": "代碼執行", "ja": "コード実行", "ru": "コード実行",
}
strings["download_read_arxiv_pdf"] = {
    "zh": "论文", "en": "ArXiv", "zh-hk": "論文", "ja": "論文", "ru": "論文",
}
strings["OTHERS"] = {
    "zh": "其他", "en": "Others", "zh-hk": "其他", "ja": "その他", "ru": "その他",
}

# ---------- status / thinking / banners (no emoji) ----------
# message_think keeps a static fallback; bot.py animates dots by editing the same message.
strings["message_think"] = {
    "zh": "`思考中.`",
    "en": "`Thinking.`",
    "zh-hk": "`思考中.`",
    "ja": "`考え中.`",
    "ru": "`Thinking.`",
}
strings["message_banner"] = {
    "zh": "从下面的列表中选择模型/组：",
    "en": "Choose a model/group from the list below:",
    "zh-hk": "從下面的列表中選擇模型/組：",
    "ja": "下の一覧からモデル/グループを選択：",
    "ru": "Choose a model/group from the list below:",
}
strings["message_reset"] = {
    "zh": "对话已重置",
    "en": "Chat reset",
    "zh-hk": "對話已重置",
    "ja": "会話をリセットしました",
    "ru": "Chat reset",
}
strings["message_doc"] = {
    "zh": "上传成功",
    "en": "Upload complete",
    "zh-hk": "上傳成功",
    "ja": "アップロード完了",
    "ru": "Upload complete",
}
strings["message_command_text_none"] = {
    "zh": "请在命令后输入内容",
    "en": "Please enter text after the command",
    "zh-hk": "請在命令後輸入內容",
    "ja": "コマンドの後に内容を入力してください",
    "ru": "Please enter text after the command",
}
strings["group_title"] = {
    "zh": "分组", "en": "Group", "zh-hk": "分組", "ja": "グループ", "ru": "Group",
}

# ---------- model command texts ----------
strings["model_command_usage"] = {
    "zh": "**请指定模型名称**\n`/model model_name`",
    "en": "**Specify a model name**\n`/model model_name`",
    "zh-hk": "**請指定模型名稱**\n`/model model_name`",
    "ja": "**モデル名を指定してください**\n`/model model_name`",
    "ru": "**Specify a model name**\n`/model model_name`",
}
strings["model_name_invalid"] = {
    "zh": "模型名称无效。仅支持标准字符，且不超过 100 个字符。",
    "en": "Invalid model name. Use standard characters, max 100 chars.",
    "zh-hk": "模型名稱無效。僅支持標準字符，且不超過 100 個字符。",
    "ja": "モデル名が無効です。標準文字のみ、100文字以内にしてください。",
    "ru": "Invalid model name. Use standard characters, max 100 chars.",
}
strings["model_not_available"] = {
    "zh": "模型 `{model_name}` 不可用。\n请使用 /info 中的模型列表。",
    "en": "Model `{model_name}` is unavailable.\nUse the model list in /info.",
    "zh-hk": "模型 `{model_name}` 不可用。\n請使用 /info 中的模型列表。",
    "ja": "モデル `{model_name}` は利用できません。\n/info の一覧から選んでください。",
    "ru": "Model `{model_name}` is unavailable.\nUse the model list in /info.",
}
strings["model_changed"] = {
    "zh": "模型已切换为：`{model_name}`",
    "en": "Model changed to: `{model_name}`",
    "zh-hk": "模型已切換為：`{model_name}`",
    "ja": "モデルを変更しました：`{model_name}`",
    "ru": "Model changed to: `{model_name}`",
}

# ---------- search stages (no emoji) ----------
strings["message_search_stage_1"] = {
    "zh": "正在搜索问题，提取关键词...",
    "en": "Searching and extracting keywords...",
    "zh-hk": "正在搜索問題，提取關鍵詞...",
    "ja": "検索キーワードを抽出中...",
    "ru": "Searching and extracting keywords...",
}
strings["message_search_stage_2"] = {
    "zh": "正在筛选相关信息源...",
    "en": "Selecting relevant sources...",
    "zh-hk": "正在篩選相關信息源...",
    "ja": "関連ソースを選別中...",
    "ru": "Selecting relevant sources...",
}
strings["message_search_stage_3"] = {
    "zh": "已找到链接，正在获取详情...",
    "en": "Fetching detailed content...",
    "zh-hk": "已找到鏈接，正在獲取詳情...",
    "ja": "詳細内容を取得中...",
    "ru": "Fetching detailed content...",
}
strings["message_search_stage_4"] = {
    "zh": "正在整理搜索结果...",
    "en": "Organizing search results...",
    "zh-hk": "正在整理搜索結果...",
    "ja": "検索結果を整理中...",
    "ru": "Organizing search results...",
}

# ---------- 宵雫风格的命令执行提示（不改信息页和命令菜单） ----------
strings["message_ban"] = {
    "zh": "……抱歉，这里暂时只为被允许的人开放。",
    "en": "...Sorry. This place is only open to approved users for now.",
    "zh-hk": "……抱歉，這裡暫時只為獲准的人開放。",
    "ja": "……ごめんなさい。ここは今、許可された方だけが使えます。",
    "ru": "...Sorry. This place is only open to approved users for now.",
}
strings["message_think"] = {
    "zh": "`宵雫思考中.`", "en": "`Shizuku is thinking.`", "zh-hk": "`宵雫思考中.`", "ja": "`宵雫が考えています.`", "ru": "`Shizuku is thinking.`",
}
strings["message_banner"] = {
    "zh": "想换一种回答方式吗？从下面选一个就好。",
    "en": "Would you like a different way of answering? Choose one below.",
    "zh-hk": "想換一種回答方式嗎？從下面選一個就好。",
    "ja": "返事の仕方を変えますか？下から選んでください。",
    "ru": "Would you like a different way of answering? Choose one below.",
}
strings["message_reset"] = {
    "zh": "这段对话已经归档了。我们从这里重新开始吧。",
    "en": "I've put away this conversation. Let's start again from here.",
    "zh-hk": "這段對話已經歸檔了。我們從這裡重新開始吧。",
    "ja": "この会話はしまっておきました。ここから始め直しましょう。",
    "ru": "I've put away this conversation. Let's start again from here.",
}
strings["message_doc"] = {
    "zh": "文件收到了。宵雫现在就看看。",
    "en": "I received the file. I'll take a look now.",
    "zh-hk": "文件收到了。宵雫現在就看看。",
    "ja": "ファイルを受け取りました。今から確認しますね。",
    "ru": "I received the file. I'll take a look now.",
}
strings["message_command_text_none"] = {
    "zh": "命令后面还没有内容。把要说的话接在后面，再交给宵雫吧。",
    "en": "There is nothing after the command yet. Add what you want me to handle and send it again.",
    "zh-hk": "命令後面還沒有內容。把要說的話接在後面，再交給宵雫吧。",
    "ja": "コマンドの後ろが空いています。頼みたい内容を続けて送ってください。",
    "ru": "There is nothing after the command yet. Add what you want me to handle and send it again.",
}
strings["model_command_usage"] = {
    "zh": "告诉宵雫要换成哪个模型就好：\n`/model 模型名称`",
    "en": "Tell me which model to use:\n`/model model_name`",
    "zh-hk": "告訴宵雫要換成哪個模型就好：\n`/model 模型名稱`",
    "ja": "使いたいモデル名を教えてください：\n`/model モデル名`",
    "ru": "Tell me which model to use:\n`/model model_name`",
}
strings["model_name_invalid"] = {
    "zh": "这个名字看起来不太对。请从信息页里的模型名单中选择。",
    "en": "That model name does not look right. Please choose one from the list on the info page.",
    "zh-hk": "這個名字看起來不太對。請從資訊頁裡的模型名單中選擇。",
    "ja": "そのモデル名は使えないようです。情報画面の一覧から選んでください。",
    "ru": "That model name does not look right. Please choose one from the list on the info page.",
}
strings["model_not_available"] = {
    "zh": "宵雫现在还用不了 `{model_name}`。从 /info 里的名单换一个吧。",
    "en": "I cannot use `{model_name}` right now. Please choose another one from /info.",
    "zh-hk": "宵雫現在還用不了 `{model_name}`。從 /info 裡的名單換一個吧。",
    "ja": "今は `{model_name}` を使えません。/info の一覧から別のものを選んでください。",
    "ru": "I cannot use `{model_name}` right now. Please choose another one from /info.",
}
strings["model_changed"] = {
    "zh": "换好了。接下来由 `{model_name}` 陪你。",
    "en": "All set. I'll use `{model_name}` from now on.",
    "zh-hk": "換好了。接下來由 `{model_name}` 陪你。",
    "ja": "変更しました。これからは `{model_name}` でお話しします。",
    "ru": "All set. I'll use `{model_name}` from now on.",
}
strings["message_api_none"] = {
    "zh": "宵雫还没有拿到可以回答你的通行凭据。请先让主人检查设置。",
    "en": "I do not have the credentials needed to answer yet. Please ask my master to check the settings.",
    "zh-hk": "宵雫還沒有拿到可以回答你的通行憑據。請先讓主人檢查設定。",
    "ja": "まだ返事に必要な設定が整っていません。主人に確認をお願いしてください。",
    "ru": "I do not have the credentials needed to answer yet. Please ask my master to check the settings.",
}
strings["message_api_error"] = {
    "zh": "连接没有成功。可能是通行凭据或地址不对，请让主人检查后再试一次。",
    "en": "The connection did not succeed. Please ask my master to check the credentials and address, then try again.",
    "zh-hk": "連接沒有成功。可能是通行憑據或地址不對，請讓主人檢查後再試一次。",
    "ja": "接続できませんでした。主人に設定を確認してもらってから、もう一度試してください。",
    "ru": "The connection did not succeed. Please ask my master to check the credentials and address, then try again.",
}
strings["message_search_stage_1"] = {
    "zh": "宵雫正在找最合适的线索...", "en": "I'm looking for the most useful clues...", "zh-hk": "宵雫正在找最合適的線索...", "ja": "役に立つ手がかりを探しています...", "ru": "I'm looking for the most useful clues...",
}
strings["message_search_stage_2"] = {
    "zh": "找到一些方向了，正在挑选可靠的内容...", "en": "I found a few leads and am choosing the reliable ones...", "zh-hk": "找到一些方向了，正在挑選可靠的內容...", "ja": "いくつか見つかりました。信頼できる内容を選んでいます...", "ru": "I found a few leads and am choosing the reliable ones...",
}
strings["message_search_stage_3"] = {
    "zh": "线索已经找到了，宵雫再仔细看看...", "en": "I found the sources. Let me read them carefully...", "zh-hk": "線索已經找到了，宵雫再仔細看看...", "ja": "情報が見つかりました。もう少し丁寧に確認します...", "ru": "I found the sources. Let me read them carefully...",
}
strings["message_search_stage_4"] = {
    "zh": "快整理好了，再等宵雫一下...", "en": "It's almost ready. Give me one more moment...", "zh-hk": "快整理好了，再等宵雫一下...", "ja": "もうすぐまとまります。あと少しだけ待ってください...", "ru": "It's almost ready. Give me one more moment...",
}
