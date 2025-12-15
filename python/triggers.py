import re


def is_dnd_call(text: str) -> bool:
    return text and text.strip().startswith("/dnd")


def extract_dnd(text: str):
    text = text.replace("/dnd", "", 1).strip()
    target = None

    match = re.match(r"^@(\w+)", text)
    if match:
        target = "@" + match.group(1)
        text = text[match.end():].strip()

    description = text if text else None
    return target, description
