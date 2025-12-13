import OpenAI from "openai";

const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

const PERSONA = `
Ты — Мастер подземелий (Dungeon Master) в стиле Baldur’s Gate 3. 
Говоришь по-русски, ведёшь сценки с лёгким юмором, остроумными ремарками и атмосферой фэнтези-приключения.
Тон: дружелюбный, игривый, иногда саркастичный, но без токсичности. Помогай игрокам погрузиться в историю, иногда подшучивая, как харизматичный DM.

Правила подачи:
- Вступления и продолжения делай краткими (2–4 предложения), кинематографичными, будто ты описываешь сцену за игровым столом.
- Добавляй уместные отсылки к BG3, но не злоупотребляй.
- Не избегай откровенной жести, чтобы людям было смешно: шутки — забавные, атмосфера — приключенческая.
- Формат ответов — простой текст.
`;

export async function askAI(prompt, opts = {}) {
  if (!process.env.OPENAI_API_KEY) {
    throw new Error("OPENAI_API_KEY is missing in environment");
  }

  const temperature =
    typeof opts.temperature === "number" ? opts.temperature : 0.2;

  try {
    // Prefer Responses API for newer models like o4-mini
    // The Responses API expects `input` (string or array) rather than `messages`.
    const res = await client.responses.create({
      model: "gpt-4o-mini",
      input: [
        { role: "system", content: PERSONA },
        { role: "user", content: prompt },
      ],
    });

    // Extract text safely from possible response shapes
    // Newer SDKs often expose `output_text` or structured `output` array.
    if (res.output_text) return res.output_text.trim();

    if (Array.isArray(res.output)) {
      // Join all text parts
      const parts = [];
      for (const item of res.output) {
        if (!item) continue;
        if (typeof item === "string") parts.push(item);
        if (item.content) {
          // content can be array of { type, text }
          for (const c of item.content) {
            if (typeof c === "string" && c.trim()) parts.push(c);
            if (c && (c.text || c.plain_text))
              parts.push(c.text ?? c.plain_text);
          }
        }
      }
      return parts.join("\n").trim();
    }

    // Fallback: try to stringify the whole response
    return (res.body || JSON.stringify(res)).toString().slice(0, 2000);
  } catch (e) {
    // Bubble up useful error messages
    const msg = e?.message || String(e);
    console.error("askAI error:", msg);
    throw new Error("AI request failed: " + msg);
  }
}

// Randomly choose a check type
const CHECK_TYPES = [
  "Ловкость",
  "Харизма",
  "Удача",
  "Внимательность",
  "Запугивание",
  "Скрытность",
];

export function randomCheckType() {
  return CHECK_TYPES[Math.floor(Math.random() * CHECK_TYPES.length)];
}

// Generate intro narrative for a DnD-like scene
export async function generateDndIntro(target, description) {
  const who = target ? `для ${target}` : "для игрока";
  const prompt = `Сформируй короткое вступление сцены ${who} по описанию: "${description}". 
Стиль: харизматичный Мастер D&D в духе Baldur’s Gate 3 — лёгкий юмор, атмосферная подача, с небольшой ноткой токсичности. 
Дай 2–4 кинематографичных предложения простым текстом.`;

  const res = await client.responses.create({
    model: "gpt-4o-mini",
    input: [
      { role: "system", content: PERSONA },
      { role: "user", content: prompt },
    ],
  });
  return (res.output_text || "").trim();
}

// Generate outcome narrative based on success/failure
export async function generateDndOutcome({
  success,
  checkType,
  dc,
  roll,
  target,
  description,
}) {
  const resultWord = success ? "УСПЕХ" : "ПРОВАЛ";
  const prompt = `Используй описание: "${description}". 
Проверка: ${checkType}. Бросок: ${roll}. Сложность: ${dc}. Итог: ${resultWord}. 
Сделай короткое продолжение (2–4 предложения) как харизматичный DM BG3: лёгкий юмор, атмосферность, без токсичности.`;

  const res = await client.responses.create({
    model: "gpt-4o-mini",
    input: [
      { role: "system", content: PERSONA },
      { role: "user", content: prompt },
    ],
  });
  return (res.output_text || "").trim();
}
