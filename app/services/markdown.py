from __future__ import annotations

import html

import bleach
import markdown


ALLOWED_TAGS = set(bleach.sanitizer.ALLOWED_TAGS) | {
    "p",
    "pre",
    "code",
    "blockquote",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "hr",
    "img",
}

ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel", "target"],
    "code": ["class"],
    "img": ["src", "alt", "title"],
    "th": ["align"],
    "td": ["align"],
}


def render_markdown(source: str) -> str:
    raw_html = markdown.markdown(
        source,
        extensions=["fenced_code", "tables", "sane_lists"],
        output_format="html5",
    )
    clean = bleach.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=["http", "https", "mailto"],
        strip=True,
    )
    return bleach.linkify(clean, callbacks=[set_link_attrs])


def set_link_attrs(attrs: dict, new: bool = False) -> dict:
    href_key = (None, "href")
    if href_key in attrs:
        attrs[(None, "target")] = "_blank"
        attrs[(None, "rel")] = "noreferrer noopener"
    return attrs


def plain_excerpt(source: str, limit: int = 180) -> str:
    compact = " ".join(html.unescape(source).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."
