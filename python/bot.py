import os
import random
import time
import re
from dotenv import load_dotenv

load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    filters,
)

from triggers import is_dnd_call, extract_dnd
from db import (
    init_db,
    load_items,
    item_index_by_id,
    pick_random_unclaimed_item_id,
    claim_item,
    ensure_player,
    get_player_items,
    set_equipped,
    count_equipped,
)
from ai import (
    random_check_type,
    pick_narrator,
    generate_dnd_intro,
    generate_dnd_outcome,
)

BOT_TOKEN = os.getenv("TG_TOKEN")

STATE = {}
ITEMS = load_items()
ITEMS_BY_ID = item_index_by_id(ITEMS)

LOOT_CHANCE = 0.99
MAX_EQUIPPED = 3


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


def format_stats(stats: dict) -> str:
    parts = []
    for k, v in stats.items():
        sign = "+" if v >= 0 else ""
        parts.append(f"{k} {sign}{v}")
    return ", ".join(parts)


def build_inventory_text(user_id: int, username: str) -> str:
    rows = get_player_items(user_id)
    eq_count = count_equipped(user_id)
    title = f"🎒 Инвентарь @{username}\nНадето {eq_count}/{MAX_EQUIPPED}\n\n"

    if not rows:
        return title + "Пока пусто"

    lines = []
    for r in rows:
        it = ITEMS_BY_ID.get(r["item_id"])
        if not it:
            continue
        mark = "✅" if int(r["equipped"]) == 1 else "⬜"
        stats = format_stats(it.get("stats", {}))
        lines.append(f"{mark} {it['name']} ({stats})")

    return title + "\n".join(lines)


def build_inventory_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = get_player_items(user_id)
    buttons = []

    for r in rows[:8]:
        it = ITEMS_BY_ID.get(r["item_id"])
        if not it:
            continue
        equipped = int(r["equipped"]) == 1
        if equipped:
            buttons.append(
                [InlineKeyboardButton(f"Снять: {it['name']}", callback_data=f"inv:off:{it['id']}")]
            )
        else:
            buttons.append(
                [InlineKeyboardButton(f"Надеть: {it['name']}", callback_data=f"inv:on:{it['id']}")]
            )

    buttons.append([InlineKeyboardButton("Обновить", callback_data="inv:refresh")])
    return InlineKeyboardMarkup(buttons)


async def inventory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    user = msg.from_user
    ensure_player(user.id, user.username or "")
    text = build_inventory_text(user.id, user.username or "player")
    kb = build_inventory_keyboard(user.id)

    text = stylize_actions_mdv2(text)
    await msg.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN_V2)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    if not is_dnd_call(msg.text):
        return

    target, description = extract_dnd(msg.text)

    if not description:
        await msg.reply_text("Нужно описание после /dnd. Пример: /dnd @alex украл пирожок")
        return

    narrator_emoji, narrator_label, system_prompt = pick_narrator()

    intro = await generate_dnd_intro(target, description, system_prompt)
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
        "roller_id": None,
        "drop_item_id": None,
        "rendered_text": None,
        "system_prompt": system_prompt,
        "narrator_emoji": narrator_emoji,
        "narrator_label": narrator_label,
    }

    header = f"{narrator_emoji}"
    if narrator_label == "Снюсс Уиллис":
        header = f"{narrator_emoji} {narrator_label}"

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
    sent = await msg.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN_V2)

    STATE[token]["message_id"] = sent.message_id
    STATE[token]["chat_id"] = sent.chat.id


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data or ""

    if data.startswith("roll:"):
        await handle_roll(update, context)
        return

    if data.startswith("claim:"):
        await handle_claim(update, context)
        return

    if data.startswith("inv:"):
        await handle_inventory_buttons(update, context)
        return


async def handle_roll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    token = query.data.replace("roll:", "")
    state = STATE.get(token)

    if not state:
        await query.answer("Событие устарело")
        return

    user = query.from_user

    if state["allowed_username"]:
        if user.username != state["allowed_username"]:
            await query.answer("Это не твой бросок")
            return
    elif state["allowed_id"] != user.id:
        await query.answer("Это не твой бросок")
        return

    if state["used"]:
        await query.answer("Бросок уже сделан")
        return

    state["used"] = True
    state["roller_id"] = user.id

    roll = random.randint(1, 20)
    success = roll >= state["dc"]

    loot_hint = None
    kb_rows = []
    drop_text = ""

    if random.random() < LOOT_CHANCE:
        item_id = pick_random_unclaimed_item_id()
        if item_id:
            state["drop_item_id"] = item_id
            it = ITEMS_BY_ID[item_id]
            stats = format_stats(it.get("stats", {}))
            loot_hint = f"{it['name']} ({stats}). {it.get('desc','')}"
            drop_text = f"\n\n🎁 {it['name']}\n{stats}"
            kb_rows.append([InlineKeyboardButton("🎁 Забрать", callback_data=f"claim:{token}")])

    outcome = await generate_dnd_outcome(
        success=success,
        check_type=state["check_type"],
        dc=state["dc"],
        roll=roll,
        target=state["target"],
        description=state["description"],
        system_prompt=state["system_prompt"],
        loot_hint=loot_hint,
    )

    result = (
        f"\n\n🎲 Бросок: {roll}\n"
        f"Сложность: {state['dc']} — {'УСПЕХ' if success else 'ПРОВАЛ'}\n\n"
        f"{'🔓' if success else '💥'} Продолжение:\n{outcome}"
        f"{drop_text}"
    )

    header = f"{state['narrator_emoji']}"
    if state["narrator_label"] == "Снюсс Уиллис":
        header = f"{state['narrator_emoji']} {state['narrator_label']}"

    new_text = (
        f"🎭 Событие {header} {state['target'] or ''}\n\n"
        f"{state['intro']}\n\n"
        f"🎲 Проверка: {state['check_type']}\n"
        f"Сложность: {state['dc']}"
        f"{result}"
    )

    state["rendered_text"] = new_text

    reply_markup = InlineKeyboardMarkup(kb_rows) if kb_rows else InlineKeyboardMarkup([])

    new_text_fmt = stylize_actions_mdv2(new_text)
    await context.bot.edit_message_text(
        chat_id=state["chat_id"],
        message_id=state["message_id"],
        text=new_text_fmt,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    if not state.get("drop_item_id"):
        del STATE[token]


async def handle_claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    token = query.data.replace("claim:", "")
    state = STATE.get(token)
    if not state:
        await query.answer("Событие устарело")
        return

    user = query.from_user

    if state.get("roller_id") != user.id:
        await query.answer("Забрать может только тот кто бросал")
        return

    item_id = state.get("drop_item_id")
    if not item_id:
        await query.answer("Тут уже нечего забирать")
        return

    ok = claim_item(user.id, user.username or "", item_id)

    if not ok:
        await query.answer("Предмет уже забрали")
        note = "\n\n⚠️ Предмет уже забрали"
    else:
        await query.answer("Забрал")
        note = "\n\n✅ Предмет забран"

    base = state.get("rendered_text") or ""
    final_text = base + note

    final_text_fmt = stylize_actions_mdv2(final_text)
    await context.bot.edit_message_text(
        chat_id=state["chat_id"],
        message_id=state["message_id"],
        text=final_text_fmt,
        reply_markup=InlineKeyboardMarkup([]),
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    del STATE[token]


async def handle_inventory_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    ensure_player(user.id, user.username or "")

    data = query.data

    if data == "inv:refresh":
        text = build_inventory_text(user.id, user.username or "player")
        kb = build_inventory_keyboard(user.id)
        text = stylize_actions_mdv2(text)
        await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN_V2)
        return

    parts = data.split(":")
    if len(parts) != 3:
        await query.answer("Ошибка")
        return

    mode = parts[1]
    item_id = parts[2]

    if item_id not in ITEMS_BY_ID:
        await query.answer("Нет такого предмета")
        return

    if mode == "on":
        ok, msg = set_equipped(user.id, item_id, True, MAX_EQUIPPED)
        await query.answer(msg)
    elif mode == "off":
        ok, msg = set_equipped(user.id, item_id, False, MAX_EQUIPPED)
        await query.answer(msg)
    else:
        await query.answer("Ошибка")
        return

    text = build_inventory_text(user.id, user.username or "player")
    kb = build_inventory_keyboard(user.id)
    text = stylize_actions_mdv2(text)
    await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN_V2)


def main():
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("inventory", inventory_cmd))
    app.add_handler(MessageHandler(filters.TEXT, on_message))
    app.add_handler(CallbackQueryHandler(on_callback))

    print("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
