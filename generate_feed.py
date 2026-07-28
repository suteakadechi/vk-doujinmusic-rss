from __future__ import annotations

import html
import json
import os
import re
import time
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

API_BASE = "https://api.vk.com/method/"
TOKEN = os.environ.get("VK_ACCESS_TOKEN", "").strip()
OWNER_ID = int(os.environ.get("VK_OWNER_ID", "-60027733"))
SOURCE_URL = os.environ.get("VK_SOURCE_URL", "https://vk.ru/doujinmusic").strip()
FEED_TITLE = os.environ.get("VK_FEED_TITLE", "doujinmusic — VK wall").strip()
API_VERSION = os.environ.get("VK_API_VERSION", "5.199").strip()
POST_LIMIT = max(1, min(int(os.environ.get("VK_POST_LIMIT", "300")), 1000))
PAGE_SIZE = 100
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "_site"))


def vk_api(method: str, **params: Any) -> dict[str, Any]:
    if not TOKEN:
        raise RuntimeError("VK_ACCESS_TOKEN is not set")

    # POSTにして、アクセストークンをURLやログへ出さないようにします。
    body = urlencode({**params, "access_token": TOKEN, "v": API_VERSION}).encode("utf-8")
    request = Request(
        API_BASE + method,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "github-pages-vk-rss/1.0",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"VK API HTTP error: {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"VK API connection error: {exc.reason}") from exc

    if "error" in payload:
        error = payload["error"]
        code = error.get("error_code", "unknown")
        message = error.get("error_msg", "unknown error")
        raise RuntimeError(f"VK API error {code}: {message}")

    return payload["response"]


def fetch_posts() -> tuple[list[dict[str, Any]], dict[int, str]]:
    posts: list[dict[str, Any]] = []
    authors: dict[int, str] = {}
    seen: set[tuple[int, int]] = set()

    for offset in range(0, POST_LIMIT, PAGE_SIZE):
        count = min(PAGE_SIZE, POST_LIMIT - offset)
        response = vk_api(
            "wall.get",
            owner_id=OWNER_ID,
            offset=offset,
            count=count,
            extended=1,
        )

        for profile in response.get("profiles", []):
            authors[int(profile["id"])] = " ".join(
                part
                for part in (profile.get("first_name"), profile.get("last_name"))
                if part
            )
        for group in response.get("groups", []):
            authors[-int(group["id"])] = group.get("name", "")

        batch = response.get("items", [])
        for post in batch:
            key = (int(post.get("owner_id", OWNER_ID)), int(post["id"]))
            if key not in seen:
                seen.add(key)
                posts.append(post)

        if len(batch) < count:
            break

        # 複数ページを取得するときに短時間へ集中させないための間隔です。
        time.sleep(0.4)

    posts.sort(
        key=lambda post: (int(post.get("date", 0)), int(post.get("id", 0))),
        reverse=True,
    )
    return posts[:POST_LIMIT], authors


def largest_photo_url(photo: dict[str, Any]) -> str | None:
    sizes = photo.get("sizes") or []
    if not sizes:
        return None

    best = max(
        sizes,
        key=lambda size: int(size.get("width", 0)) * int(size.get("height", 0)),
    )
    return best.get("url")


def post_url(post: dict[str, Any]) -> str:
    owner_id = int(post.get("owner_id", OWNER_ID))
    post_id = int(post["id"])
    return f"https://vk.ru/wall{owner_id}_{post_id}"


def attachment_html(attachment: dict[str, Any]) -> str:
    kind = attachment.get("type", "")
    data = attachment.get(kind) or {}

    if kind == "photo":
        url = largest_photo_url(data)
        if url:
            return (
                f'<p><img src="{html.escape(url, quote=True)}" '
                'alt="Photo" loading="lazy"></p>'
            )

    if kind == "video":
        owner_id = data.get("owner_id")
        video_id = data.get("id")
        title = html.escape(data.get("title") or "Video")
        if owner_id is not None and video_id is not None:
            url = f"https://vk.ru/video{owner_id}_{video_id}"
            return (
                f'<p>Video: <a href="{html.escape(url, quote=True)}">'
                f"{title}</a></p>"
            )

    if kind == "doc":
        url = data.get("url")
        title = html.escape(data.get("title") or "Document")
        if url:
            return (
                f'<p>Document: <a href="{html.escape(url, quote=True)}">'
                f"{title}</a></p>"
            )

    if kind == "link":
        url = data.get("url")
        title = html.escape(data.get("title") or url or "Link")
        description = html.escape(data.get("description") or "")
        if url:
            extra = f"<br>{description}" if description else ""
            return (
                f'<p>Link: <a href="{html.escape(url, quote=True)}">'
                f"{title}</a>{extra}</p>"
            )

    if kind == "album":
        owner_id = data.get("owner_id")
        album_id = data.get("id")
        title = html.escape(data.get("title") or "Album")
        if owner_id is not None and album_id is not None:
            url = f"https://vk.ru/album{owner_id}_{album_id}"
            return (
                f'<p>Album: <a href="{html.escape(url, quote=True)}">'
                f"{title}</a></p>"
            )

    if kind == "poll":
        question = html.escape(data.get("question") or "Poll")
        return f"<p>Poll: {question}</p>"

    if kind == "audio":
        artist = html.escape(data.get("artist") or "")
        title = html.escape(data.get("title") or "Audio")
        label = " — ".join(part for part in (artist, title) if part)
        return f"<p>Audio: {label}</p>"

    return f"<p>Attachment: {html.escape(kind or 'unknown')}</p>"


def render_post_body(post: dict[str, Any], include_repost: bool = True) -> str:
    parts: list[str] = []
    text = post.get("text") or ""

    if text:
        escaped = html.escape(text).replace("\n", "<br>")
        parts.append(f"<p>{escaped}</p>")

    for attachment in post.get("attachments") or []:
        rendered = attachment_html(attachment)
        if rendered:
            parts.append(rendered)

    if include_repost:
        for copied in post.get("copy_history") or []:
            copied_body = render_post_body(copied, include_repost=False)
            if copied_body:
                copied_link = post_url(copied)
                parts.append(
                    '<blockquote><p>Repost: '
                    f'<a href="{html.escape(copied_link, quote=True)}">'
                    "original post</a></p>"
                    f"{copied_body}</blockquote>"
                )

    if not parts:
        parts.append(
            f'<p><a href="{html.escape(post_url(post), quote=True)}">'
            "Open this post on VK</a></p>"
        )

    return "\n".join(parts)


def make_title(post: dict[str, Any]) -> str:
    text = re.sub(r"\s+", " ", post.get("text") or "").strip()
    if text:
        return text[:120] + ("…" if len(text) > 120 else "")

    kinds = [att.get("type", "media") for att in post.get("attachments") or []]
    label = ", ".join(dict.fromkeys(kind for kind in kinds if kind)) or "media"
    return f"VK post ({label})"


def add_text(
    parent: ET.Element, tag: str, value: str, **attributes: str
) -> ET.Element:
    element = ET.SubElement(parent, tag, attributes)
    element.text = value
    return element


def build_feed(
    posts: list[dict[str, Any]], authors: dict[int, str]
) -> ET.ElementTree:
    rss = ET.Element(
        "rss",
        {
            "version": "2.0",
            "xmlns:dc": "http://purl.org/dc/elements/1.1/",
        },
    )
    channel = ET.SubElement(rss, "channel")
    add_text(channel, "title", FEED_TITLE)
    add_text(channel, "link", SOURCE_URL)
    add_text(
        channel,
        "description",
        f"Posts from VK wall {OWNER_ID}, generated by GitHub Actions",
    )
    add_text(channel, "language", "ru")
    add_text(
        channel,
        "lastBuildDate",
        format_datetime(datetime.now(timezone.utc)),
    )
    add_text(channel, "generator", "github-pages-vk-rss")

    for post in posts:
        item = ET.SubElement(channel, "item")
        url = post_url(post)

        add_text(item, "title", make_title(post))
        add_text(item, "link", url)
        add_text(item, "guid", url, isPermaLink="true")

        timestamp = datetime.fromtimestamp(
            int(post.get("date", 0)),
            tz=timezone.utc,
        )
        add_text(item, "pubDate", format_datetime(timestamp))

        author_id = int(
            post.get("from_id", post.get("owner_id", OWNER_ID))
        )
        author = authors.get(author_id)
        if author:
            add_text(item, "dc:creator", author)

        # HTMLはXML内でエスケープされ、RSSリーダー側で本文として表示されます。
        add_text(item, "description", render_post_body(post))

    return ET.ElementTree(rss)


def write_status_page(post_count: int) -> None:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    page = f"""<!doctype html>
<html lang="ja">
<meta charset="utf-8">
<title>VK RSS</title>
<h1>VK RSS</h1>
<p><a href="index.xml">RSSフィードを開く</a></p>
<p>取得項目数: {post_count}</p>
<p>生成日時: {generated}</p>
<p>取得元: <a href="{html.escape(SOURCE_URL, quote=True)}">{html.escape(SOURCE_URL)}</a></p>
"""
    (OUTPUT_DIR / "index.html").write_text(page, encoding="utf-8")


def main() -> None:
    posts, authors = fetch_posts()
    if not posts:
        raise RuntimeError(
            "VK API returned no posts; refusing to publish an empty feed"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tree = build_feed(posts, authors)
    ET.indent(tree, space="  ")
    tree.write(
        OUTPUT_DIR / "index.xml",
        encoding="utf-8",
        xml_declaration=True,
    )

    (OUTPUT_DIR / ".nojekyll").write_text("", encoding="utf-8")
    write_status_page(len(posts))
    print(f"Generated {len(posts)} RSS items")


if __name__ == "__main__":
    main()
