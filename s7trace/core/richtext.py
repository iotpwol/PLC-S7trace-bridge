"""One rule for the whole program (desktop and Web): data inside a sentence - numbers with their units (19.8%, 25 ms, >= 45 ms, 99% ...),
addresses, times - is written in bold, the surrounding text is normal. Qt-free; the Web page has the same function (`boldNums` in app.js)."""
from __future__ import annotations

import html
import re

# an optional sign / comparison, the number and an optional unit; a digit inside a word (S7-300, DB1) or inside an address is left alone
_NUM = re.compile(r"(?<![\w.,:-])((?:[≥≤<>~±]\s?)?\d+(?:[.,]\d+)?(?:\s?(?:%|ms|µs|min|kb/s|B/s|kB|MB|Hz|s|B)(?![\w]))?)(?![\w]|[.,]\d)")


def bold_numbers(text: str) -> str:
    """HTML of `text` (escaped) with every number (and its unit) in <b>."""
    return _NUM.sub(lambda m: f"<b>{m.group(1)}</b>", html.escape(text, quote=False))


def bold(text: str) -> str:
    return f"<b>{html.escape(str(text), quote=False)}</b>"
