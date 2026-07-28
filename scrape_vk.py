from __future__ import annotations

import asyncio
import html
import json
import os
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

from playwright.async_api import BrowserContext, Page, async_playwright

WALL_ID = int(os.environ.get("VK_WALL_ID", "-60027733"))
WALL_PATH = os.environ.get("VK_WALL_PATH", "wall-60027733").strip("/")
SOURCE_URL = os.environ.get("VK_SOURCE_URL", "https://vk.ru/wall-60027733")
FEED_TITLE = os.environ.get("VK_FEED_TITLE", "doujinmusic — VK wall")
POST_LIMIT = max(20, min(int(os.environ.get("VK_POST_LIMIT", "200")), 500))
PAGE_SIZE = max(10, min(int(os.environ.get("VK_PAGE_SIZE", "20")), 50))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "_site"))
DEBUG_DIR = Path(os.environ.get("DEBUG_DIR", "debug"))

POST_RE = re.compile(rf"wall{re.escape(str(WALL_ID))}_(\d+)")
WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")

# vk.ru移行後と従来ドメインの両方を試します。
HOSTS = (
    "https://m.vk.ru",
    "https://m.vk.com",
    "https://vk.ru",
    "https://vk.com",
)


def candidate_urls(offset: int) -> list[str]:
    query = f"?offset={offset}&own=1"
    return [f"{host}/{WALL_PATH}{query}" for host in HOSTS]


def normalize_post_url(value: str) -> str | None:
    match = POST_RE.search(value)
    if not match:
        return None
    return f"https://vk.ru/wall{WALL_ID}_{match.group(1)}"


def clean_text(value: str) -> str:
    lines: list[str] = []
    previous = ""
    for raw_line in value.replace("\xa0", " ").splitlines():
        line = WHITESPACE_RE.sub(" ", raw_line).strip()
        if not line or line == previous:
            continue

        # 一般的な操作UIを本文から除きます。
        if line.casefold() in {
            "like", "share", "comment", "more", "show all",
            "нравится", "поделиться", "комментировать",
            "ещё", "показать полностью",
        }:
            continue

        lines.append(line)
        previous = line

    return "\n".join(lines).strip()


def parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    if text.isdigit():
        number = int(text)
        if number > 10_000_000_000:
            number //= 1000
        if 1_000_000_000 <= number <= 4_000_000_000:
            return datetime.fromtimestamp(number, tz=timezone.utc)

    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def make_title(post: dict[str, Any]) -> str:
    text = clean_text(post.get("text", ""))
    if text:
        first = text.splitlines()[0]
        if len(first) > 120:
            first = first[:119] + "…"
        return first

    labels: list[str] = []
    if post.get("images"):
        labels.append("photo")
    if post.get("attachments"):
        labels.append("attachment")
    suffix = ", ".join(labels) or "post"
    return f"VK {suffix} — {post['id']}"


def render_description(post: dict[str, Any]) -> str:
    parts: list[str] = []
    text = clean_text(post.get("text", ""))
    if text:
        parts.append(f"<p>{html.escape(text).replace(chr(10), '<br>')}</p>")

    for image_url in post.get("images", [])[:10]:
        escaped = html.escape(image_url, quote=True)
        parts.append(
            f'<p><a href="{escaped}"><img src="{escaped}" '
            'alt="VK photo" loading="lazy"></a></p>'
        )

    seen_links: set[str] = set()
    for attachment in post.get("attachments", []):
        url = attachment.get("url")
        if not url or url in seen_links:
            continue
        seen_links.add(url)
        label = clean_text(attachment.get("text", "")) or "Attachment"
        parts.append(
            f'<p><a href="{html.escape(url, quote=True)}">'
            f"{html.escape(label[:160])}</a></p>"
        )

    if not parts:
        parts.append("<p>Open this post on VK.</p>")

    parts.append(
        f'<p><a href="{html.escape(post["url"], quote=True)}">'
        "Open the original VK post</a></p>"
    )
    return "\n".join(parts)


def add_text(parent: ET.Element, tag: str, value: str, **attrs: str) -> ET.Element:
    node = ET.SubElement(parent, tag, attrs)
    node.text = value
    return node


def build_feed(posts: list[dict[str, Any]]) -> ET.ElementTree:
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    add_text(channel, "title", FEED_TITLE)
    add_text(channel, "link", SOURCE_URL)
    add_text(
        channel,
        "description",
        f"Public posts scraped from VK wall {WALL_ID} by GitHub Actions",
    )
    add_text(channel, "language", "ru")
    add_text(channel, "generator", "github-pages-vk-wall-scraper")
    add_text(channel, "lastBuildDate", format_datetime(datetime.now(timezone.utc)))

    for post in posts:
        item = ET.SubElement(channel, "item")
        add_text(item, "title", make_title(post))
        add_text(item, "link", post["url"])
        add_text(item, "guid", post["url"], isPermaLink="true")

        published = parse_timestamp(post.get("timestamp"))
        if published:
            add_text(item, "pubDate", format_datetime(published))

        add_text(item, "description", render_description(post))

    return ET.ElementTree(rss)


async def prepare_page(context: BrowserContext) -> Page:
    # フォントも含めて通常のブラウザに近い状態で読み込みます。
    return await context.new_page()


async def auto_scroll(page: Page) -> None:
    # 初期HTMLに投稿が少ない場合に備え、軽くスクロールします。
    for _ in range(4):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(900)


async def extract_posts(page: Page) -> list[dict[str, Any]]:
    wall_id = WALL_ID
    raw = await page.evaluate(
        """wallId => {
            const postPattern = new RegExp(`wall${wallId}_(\\\\d+)`);
            const result = new Map();

            const absolute = value => {
                try {
                    return new URL(value, location.href).href;
                } catch {
                    return '';
                }
            };

            const visibleText = element => {
                if (!element) return '';
                return (element.innerText || element.textContent || '').trim();
            };

            const chooseContainer = anchor => {
                const selectors = [
                    '[data-post-id]',
                    '[data-post]',
                    '[id^="post"]',
                    '[id*="post-"]',
                    'article',
                    '.post',
                    '.post_item',
                    '.wall_item',
                    '.WallItem',
                    '.Post',
                    '.pi',
                    '.wi'
                ];

                for (const selector of selectors) {
                    const found = anchor.closest(selector);
                    if (found) return found;
                }

                let node = anchor;
                let best = anchor.parentElement;
                for (let i = 0; i < 9 && node?.parentElement; i += 1) {
                    node = node.parentElement;
                    const text = visibleText(node);
                    if (text.length >= 20 && text.length <= 20000) {
                        best = node;
                    }
                }
                return best || anchor.parentElement || anchor;
            };

            const getBestText = container => {
                const selectors = [
                    '.wall_post_text',
                    '.pi_text',
                    '.post_content',
                    '.post_text',
                    '.wall_text',
                    '[data-testid*="post"]'
                ];
                for (const selector of selectors) {
                    const node = container.querySelector(selector);
                    const text = visibleText(node);
                    if (text) return text;
                }
                return visibleText(container);
            };

            const getTimestamp = container => {
                const time = container.querySelector('time[datetime]');
                if (time?.getAttribute('datetime')) {
                    return time.getAttribute('datetime');
                }

                for (const selector of ['[data-date]', '[data-time]', '[data-timestamp]']) {
                    const node = container.querySelector(selector);
                    if (!node) continue;
                    for (const attr of ['data-date', 'data-time', 'data-timestamp']) {
                        const value = node.getAttribute(attr);
                        if (value) return value;
                    }
                }
                return '';
            };

            for (const anchor of document.querySelectorAll('a[href]')) {
                const href = absolute(anchor.getAttribute('href'));
                const match = href.match(postPattern);
                if (!match) continue;

                const canonical = `https://vk.ru/wall${wallId}_${match[1]}`;
                if (result.has(canonical)) continue;

                const container = chooseContainer(anchor);
                const images = [];
                const imageSeen = new Set();

                for (const image of container.querySelectorAll('img')) {
                    const candidates = [
                        image.currentSrc,
                        image.getAttribute('src'),
                        image.getAttribute('data-src'),
                        image.getAttribute('data-original')
                    ];
                    for (const candidate of candidates) {
                        const url = absolute(candidate);
                        if (!url || imageSeen.has(url)) continue;
                        const lower = url.toLowerCase();
                        if (
                            lower.includes('emoji') ||
                            lower.includes('smile') ||
                            lower.includes('avatar') ||
                            lower.includes('camera_')
                        ) continue;
                        imageSeen.add(url);
                        images.push(url);
                        break;
                    }
                }

                const attachments = [];
                const attachmentSeen = new Set();
                for (const link of container.querySelectorAll('a[href]')) {
                    const url = absolute(link.getAttribute('href'));
                    if (!url || attachmentSeen.has(url)) continue;
                    if (!/(photo|video|audio|doc|album|market|away\\.php|wall-?\\d+_\\d+)/i.test(url)) {
                        continue;
                    }
                    if (url.match(postPattern)) continue;
                    attachmentSeen.add(url);
                    attachments.push({
                        url,
                        text: visibleText(link).slice(0, 300)
                    });
                }

                result.set(canonical, {
                    id: `wall${wallId}_${match[1]}`,
                    url: canonical,
                    text: getBestText(container),
                    timestamp: getTimestamp(container),
                    images,
                    attachments
                });
            }

            return [...result.values()];
        }""",
        wall_id,
    )
    return raw


async def save_debug(page: Page, label: str, details: dict[str, Any]) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "-", label).strip("-") or "page"

    try:
        (DEBUG_DIR / f"{safe_label}.html").write_text(
            await page.content(), encoding="utf-8"
        )
    except Exception:
        pass

    try:
        await page.screenshot(
            path=str(DEBUG_DIR / f"{safe_label}.png"),
            full_page=True,
        )
    except Exception:
        pass

    (DEBUG_DIR / f"{safe_label}.json").write_text(
        json.dumps(details, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def scrape() -> tuple[list[dict[str, Any]], str]:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    collected: dict[str, dict[str, Any]] = {}
    successful_source = ""

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            locale="ru-RU",
            timezone_id="Europe/Moscow",
            viewport={"width": 1365, "height": 1800},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
            },
        )

        page = await prepare_page(context)

        for offset in range(0, POST_LIMIT + PAGE_SIZE, PAGE_SIZE):
            page_posts: list[dict[str, Any]] = []
            attempts: list[dict[str, Any]] = []

            for url in candidate_urls(offset):
                try:
                    response = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=60_000,
                    )
                    await page.wait_for_timeout(3_000)

                    if "challenge.html" in page.url:
                        await page.wait_for_timeout(10_000)

                    await auto_scroll(page)
                    page_posts = await extract_posts(page)

                    attempts.append(
                        {
                            "requested": url,
                            "final_url": page.url,
                            "status": response.status if response else None,
                            "title": await page.title(),
                            "posts": len(page_posts),
                        }
                    )

                    if page_posts:
                        successful_source = page.url
                        break
                except Exception as exc:
                    attempts.append(
                        {
                            "requested": url,
                            "final_url": page.url,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )

            if not page_posts:
                await save_debug(
                    page,
                    f"offset-{offset}",
                    {"offset": offset, "attempts": attempts},
                )
                if offset == 0:
                    raise RuntimeError(
                        "VKの先頭ページから投稿を抽出できませんでした。"
                        "debugアーティファクトを確認してください。"
                    )
                break

            new_count = 0
            for post in page_posts:
                normalized = normalize_post_url(post.get("url", ""))
                if not normalized:
                    continue
                post["url"] = normalized
                post["id"] = normalized.rsplit("/", 1)[-1]
                if normalized not in collected:
                    collected[normalized] = post
                    new_count += 1

            if new_count == 0 and offset > 0:
                break

            if len(collected) >= POST_LIMIT:
                break

        await browser.close()

    def post_number(post: dict[str, Any]) -> int:
        match = POST_RE.search(post["url"])
        return int(match.group(1)) if match else 0

    posts = sorted(collected.values(), key=post_number, reverse=True)
    return posts[:POST_LIMIT], successful_source


def write_output(posts: list[dict[str, Any]], source: str) -> None:
    if len(posts) < 10:
        raise RuntimeError(
            f"抽出できた投稿が少なすぎます: {len(posts)}件。"
            "ブロックページをRSSとして公開しないため停止します。"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tree = build_feed(posts)
    ET.indent(tree, space="  ")
    tree.write(
        OUTPUT_DIR / "index.xml",
        encoding="utf-8",
        xml_declaration=True,
    )

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    status = f"""<!doctype html>
<html lang="ja">
<meta charset="utf-8">
<title>VK RSS</title>
<h1>VK RSS</h1>
<p><a href="index.xml">RSSフィードを開く</a></p>
<p>取得投稿数: {len(posts)}</p>
<p>生成日時: {generated}</p>
<p>取得元ページ: {html.escape(source)}</p>
<p>対象ウォール: <a href="{html.escape(SOURCE_URL, quote=True)}">{html.escape(SOURCE_URL)}</a></p>
"""
    (OUTPUT_DIR / "index.html").write_text(status, encoding="utf-8")
    (OUTPUT_DIR / ".nojekyll").write_text("", encoding="utf-8")


async def main() -> None:
    posts, source = await scrape()
    write_output(posts, source)
    print(f"Generated {len(posts)} RSS items from {source}")


if __name__ == "__main__":
    asyncio.run(main())
