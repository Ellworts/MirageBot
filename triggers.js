// /ask and bot-reply triggers removed — only /dnd remains

// Detect /dnd commands like: /dnd @username описание события
export function isDndCall(msg) {
  if (!msg.text) return false;
  return msg.text.trim().startsWith("/dnd");
}

// Extract target username and description from /dnd command
// Returns { target: string|null, description: string|null }
export function extractDnd(msg) {
  const text = (msg.text || "").trim();
  if (!text.startsWith("/dnd")) return { target: null, description: null };

  const withoutCmd = text.replace("/dnd", "").trim();
  // Try to find a @mention at the start
  const mentionMatch = withoutCmd.match(/^@([A-Za-z0-9_]+)/);
  let target = null;
  let description = withoutCmd;

  if (mentionMatch) {
    target = "@" + mentionMatch[1];
    description = withoutCmd.slice(mentionMatch[0].length).trim();
  }

  if (!description) description = null;
  return { target, description };
}
