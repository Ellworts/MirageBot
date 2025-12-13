import "dotenv/config";
import TelegramBot from "node-telegram-bot-api";
import { isDndCall, extractDnd } from "./triggers.js";
import { randomCheckType, generateDndIntro, generateDndOutcome } from "./ai.js";

const bot = new TelegramBot(process.env.TG_TOKEN, {
  polling: true,
});

// BOT_USERNAME is fetched async because bot.username may be undefined immediately after construction
let BOT_USERNAME = null;

(async () => {
  try {
    const me = await bot.getMe();
    BOT_USERNAME = me.username;
    console.log("🤖 Bot started as @" + BOT_USERNAME);
  } catch (e) {
    console.error("Failed to get bot info:", e);
    console.log("🤖 Bot started (username unknown)");
  }
})();

bot.on("message", async (msg) => {
  try {
    // DnD flow
    if (isDndCall(msg)) {
      const { target, description } = extractDnd(msg);
      if (!description) {
        await bot.sendMessage(
          msg.chat.id,
          "Нужно описание события после /dnd. Пример: /dnd @alex украл пирожок у торговца",
          {
            reply_to_message_id: msg.message_id,
          }
        );
        return;
      }

      const intro = await generateDndIntro(target, description);
      const checkType = randomCheckType();
      const dc = Math.floor(Math.random() * 20) + 1; // 1..20

      const header = `🎭 Событие${
        target ? ` для ${target}` : ""
      }\n\n${intro}\n\n🎲 Проверка: ${checkType}\nСложность: ${dc}`;

      // Inline button state
      const token = `${Date.now()}_${Math.random().toString(36).slice(2)}`;
      // determine who is allowed to roll: mentioned user or author
      const allowedUsername = target
        ? target.replace(/^@/, "")
        : msg.from?.username || null;
      const allowedId = !target && !allowedUsername ? msg.from?.id : null;

      state.set(token, {
        chatId: msg.chat.id,
        dc,
        checkType,
        target,
        description,
        intro,
        allowedUsername,
        allowedId,
        usedBy: null,
        messageId: null,
      });

      const sent = await bot.sendMessage(msg.chat.id, header, {
        reply_to_message_id: msg.message_id,
        reply_markup: {
          inline_keyboard: [
            [{ text: "🎲 Бросить d20", callback_data: `roll:${token}` }],
          ],
        },
      });

      // Save message id for later edits
      const s = state.get(token);
      if (s) s.messageId = sent.message_id;
      return;
    }

    // Only /dnd flow is supported; ignore other messages
    return;
  } catch (e) {
    console.error(e);
  }
});

// Simple in-memory state for DnD rolls
const state = new Map();

bot.on("callback_query", async (query) => {
  try {
    const data = query.data || "";
    if (!data.startsWith("roll:")) return;
    const token = data.slice("roll:".length);
    const s = state.get(token);
    if (!s) {
      await bot.answerCallbackQuery(query.id, {
        text: "Событие устарело или не найдено.",
      });
      return;
    }

    // Enforce only the assigned user can roll
    const qUser = query.from?.username || null;
    const qId = query.from?.id || null;
    const assignedOk = s.allowedUsername
      ? qUser && qUser === s.allowedUsername
      : qId && s.allowedId && qId === s.allowedId;
    if (!assignedOk) {
      await bot.answerCallbackQuery(query.id, {
        text: s.allowedUsername
          ? `Кнопку может нажать только @${s.allowedUsername}.`
          : "Кнопку может нажать только автор события.",
      });
      return;
    }

    // Enforce single roll per event
    if (s.usedBy) {
      await bot.answerCallbackQuery(query.id, { text: "Бросок уже сделан." });
      return;
    }
    s.usedBy = qUser || qId;

    // Compute roll
    const roll = Math.floor(Math.random() * 20) + 1;
    const success = roll >= s.dc;

    await bot.answerCallbackQuery(query.id, { text: `Ты бросил: ${roll}` });

    // Generate outcome text
    const outcomeText = await generateDndOutcome({
      success,
      checkType: s.checkType,
      dc: s.dc,
      roll,
      target: s.target,
      description: s.description,
    });

    const resultBlock = `\n\n🎲 Бросок: ${roll}\nСложность: ${s.dc} — ${
      success ? "УСПЕХ" : "ПРОВАЛ"
    }\n\n${success ? "🔓" : "💥"} Продолжение истории:\n${outcomeText}`;

    const header = `🎭 Событие${s.target ? ` для ${s.target}` : ""}\n\n${
      s.intro || ""
    }\n\n🎲 Проверка: ${s.checkType}\nСложность: ${s.dc}`;
    const newText = header + resultBlock;

    // Edit original message to reveal DC and show outcome, also remove button
    await bot.editMessageText(newText, {
      chat_id: query.message.chat.id,
      message_id: s.messageId,
      reply_markup: { inline_keyboard: [] },
    });

    // Cleanup
    state.delete(token);
  } catch (e) {
    console.error("callback_query error:", e);
  }
});

console.log("🤖 Bot event handler registered");
