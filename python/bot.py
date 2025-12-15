import os
import random
import time
import re
from dotenv import load_dotenv

load_dotenv()

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from ai import (
    random_check_type,
    generate_dnd_intro,
    generate_dnd_outcome,
    pick_persona,
)
from triggers import is_dnd_call, extract_dnd

BOT_TOKEN = os.getenv("TG_TOKEN")

STATE = {}


def narrator_title(persona_emoji: str, persona_label: str) -> str:
    
    if persona_label == "Снюсс Уиллис":
        return f"{persona_emoji} {persona_label}"
    return f"{persona_emoji}"


def stylize_actions_mdv2(text: str) -> str:
    
    placeholders: list[str] = []

    def repl(m: re.Match) -> str:
        placeholders.append(m.group(1))
        return f"@@ACT{len(placeholders) - 1}@@"

    temp = re.sub(r"\*(.+?)\*", repl, text)

    temp = escape_markdown(temp, version=2)

    for i, action in enumerate(placeholders):
        safe_action = escape_markdown(action, version=2)
        temp = temp.replace(f"@@ACT{i}@@", f"`*{safe_action}*`")

    return temp


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    if not is_dnd_call(msg.text):
        return

    target, description = extract_dnd(msg.text)

    if not description:
        await msg.reply_text(
            "Нужно описание после /dnd.\nПример: /dnd @alex украл пирожок"
        )
        return

    persona_emoji, persona_label, persona_text = pick_persona()

    intro = await generate_dnd_intro(target, description, persona_text)
    check_type = random_check_type()
    dc = random.randint(1, 20)

    token = f"{int(time.time())}_{random.randint(1000,9999)}"

    allowed_username = target.replace("@", "") if target else msg.from_user.username
    allowed_id = msg.from_user.id if not target else None

    STATE[token] = {
        "dc": dc,
        "check_type": check_type,
        "target": target,
        "description": description,
        "intro": intro,
        "allowed_username": allowed_username,
        "allowed_id": allowed_id,
        "used": False,
        "persona": persona_text,
        "persona_emoji": persona_emoji,
        "persona_label": persona_label,
    }

    header = narrator_title(persona_emoji, persona_label)

    text = (
        f"🎭 Событие {header} {target or ''}\n\n"
        f"{intro}\n\n"
        f"🎲 Проверка: {check_type}\n"
        f"Сложность: {dc}"
    )

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🎲 Бросить d20", callback_data=f"roll:{token}")]]
    )

    text = stylize_actions_mdv2(text)
    sent = await msg.reply_text(
        text,
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    STATE[token]["message_id"] = sent.message_id
    STATE[token]["chat_id"] = sent.chat.id


async def on_roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("roll:"):
        return

    token = query.data.replace("roll:", "")
    state = STATE.get(token)

    if not state:
        await query.answer("Событие устарело.")
        return

    user = query.from_user

    if state["allowed_username"]:
        if user.username != state["allowed_username"]:
            await query.answer("Это не твой бросок.")
            return
    elif state["allowed_id"] != user.id:
        await query.answer("Это не твой бросок.")
        return

    if state["used"]:
        await query.answer("Бросок уже сделан.")
        return

    state["used"] = True

    roll = random.randint(1, 20)
    success = roll >= state["dc"]

    outcome = await generate_dnd_outcome(
        success=success,
        check_type=state["check_type"],
        dc=state["dc"],
        roll=roll,
        target=state["target"],
        description=state["description"],
        persona=state["persona"],
    )

    result = (
        f"\n\n🎲 Бросок: {roll}\n"
        f"Сложность: {state['dc']} — {'УСПЕХ' if success else 'ПРОВАЛ'}\n\n"
        f"{'🔓' if success else '💥'} Продолжение:\n{outcome}"
    )

    header = narrator_title(state["persona_emoji"], state["persona_label"])

    new_text = (
        f"🎭 Событие {header} {state['target'] or ''}\n\n"
        f"{state['intro']}\n\n"
        f"🎲 Проверка: {state['check_type']}\n"
        f"Сложность: {state['dc']}"
        f"{result}"
    )

    # ✅ Format and edit as MarkdownV2
    new_text = stylize_actions_mdv2(new_text)
    await context.bot.edit_message_text(
        chat_id=state["chat_id"],
        message_id=state["message_id"],
        text=new_text,
        reply_markup=InlineKeyboardMarkup([]),
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    del STATE[token]


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, on_message))
    app.add_handler(CallbackQueryHandler(on_roll))

    print("🤖 Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
