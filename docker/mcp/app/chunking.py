from __future__ import annotations

import hashlib
import re
from html import unescape

from bs4 import BeautifulSoup

TOKEN_TARGET = 500
TOKEN_OVERLAP = 50
SECTION_HEADING_TAGS = ("h1", "h2")
TITLE_CLASS_RE = re.compile(r"(?:^|[\s:])title(?::|-)?[12](?:$|[\s:])", re.I)


def body_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    text = soup.get_text("\n")
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _words(text: str) -> list[str]:
    return re.findall(r"\S+", text)


def _window_chunks(text: str) -> list[str]:
    words = _words(text)
    if not words:
        return []
    if len(words) <= TOKEN_TARGET:
        return [text]
    chunks: list[str] = []
    step = max(TOKEN_TARGET - TOKEN_OVERLAP, 1)
    for start in range(0, len(words), step):
        piece = words[start : start + TOKEN_TARGET]
        if not piece:
            break
        chunks.append(" ".join(piece))
        if start + TOKEN_TARGET >= len(words):
            break
    return chunks


def _is_section_heading(tag) -> bool:
    if tag.name in SECTION_HEADING_TAGS:
        return True
    classes = " ".join(tag.get("class") or [])
    return bool(TITLE_CLASS_RE.search(classes))


def _split_html_sections(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    headings = [tag for tag in soup.find_all(True) if _is_section_heading(tag)]
    if len(headings) < 2:
        return []

    sections: list[str] = []
    for heading in headings:
        parts = [str(heading)]
        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) and _is_section_heading(sibling):
                break
            parts.append(str(sibling))
        text = html_to_text("".join(parts))
        if text:
            sections.append(text)
    return sections


def chunk_body(doc_id: str, layer: str, body_text: str) -> list[tuple[str, int, str]]:
    sections = _split_html_sections(body_text)
    pieces: list[str] = []
    if sections:
        for section in sections:
            pieces.extend(_window_chunks(section) or [section])
    else:
        pieces = _window_chunks(html_to_text(body_text) or body_text)

    result: list[tuple[str, int, str]] = []
    for index, text in enumerate(pieces, start=1):
        if not text.strip():
            continue
        chunk_id = f"{doc_id}:{layer}:{index}"
        result.append((chunk_id, index, text.strip()))
    return result
