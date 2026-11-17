from __future__ import annotations

import html
import re

ANCHOR_RE = re.compile(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")


def html_to_telegram_text(text: str) -> str:
    """Convert the shared presentation HTML to clean Telegram plain text.

    Telegram renders line breaks/emojis well. Links are kept explicitly so older clients do not lose them.
    We intentionally avoid relying on newer rich-text extensions during the Telegram rollout.
    """
    def replace_anchor(match: re.Match[str]) -> str:
        url = html.unescape(match.group(1))
        label = TAG_RE.sub("", html.unescape(match.group(2))).strip()
        if url.startswith("tel:") or url.startswith("mailto:"):
            return label
        if label == url or not label:
            return url
        return f"{label}: {url}"

    out = ANCHOR_RE.sub(replace_anchor, text)
    out = re.sub(r"</?(?:b|i|u|s|code|pre|blockquote)[^>]*>", "", out, flags=re.IGNORECASE)
    out = TAG_RE.sub("", out)
    out = html.unescape(out)
    out = out.replace("\r\n", "\n").replace("\r", "\n")
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def format_outgoing_telegram_text(text: str) -> str:
    """Lightweight human-readable Telegram formatting without splitting field lists or URLs.

    Never mutate user input, stored source texts or identifiers. Format only final
    outgoing presentation; keep intentional line breaks inside lists and forms.
    """
    result = (text or '').replace('\r\n', '\n').replace('\r', '\n')
    result = result.translate(str.maketrans({'\u2014':'-', '\u2013':'-', '\u2015':'-', '\u2212':'-'}))
    result = re.sub(r'[ \t]+\n', '\n', result)
    result = re.sub(r'\n{3,}', '\n\n', result)
    # Two adjacent *sentences* on separate lines are separate thoughts. Leave
    # key-value sections, bulleted lists, addresses, links and numbered steps alone.
    lines = result.split('\n')
    built = []
    for line in lines:
        prev = built[-1].strip() if built else ''
        curr = line.strip()
        if (prev and curr and prev[-1] in '.?!…' and
                not prev.startswith(('http://','https://','•','-','*')) and
                not curr.startswith(('http://','https://','•','-','*')) and
                not re.match(r'^(?:\d+[.)]|[А-ЯЁ][^\n]{0,23}:)', curr) and
                not re.match(r'^[^\n]{0,25}:\s*', prev)):
            built.append('')
        built.append(line)
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(built)).strip()
