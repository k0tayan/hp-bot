from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import requests


def load_new_threads(path: str = "new.json") -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError(f"{path} must be a JSON array")

    return data


def build_discord_payload(entry: Dict[str, Any]) -> tuple[Dict[str, Any], str | None]:
    channel_name = entry.get("channel_name", "")
    thread: Dict[str, Any] = entry.get("thread") or {}
    thread_id = entry.get("thread_id") or thread.get("id")

    translations = thread.get("translations") or {}
    ja = translations.get("ja") or {}

    title = ja.get("title") or thread.get("title") or ""
    body = ja.get("body") or thread.get("body") or ""

    header = f"[{channel_name}] {title}".strip()

    # 画像と音声の URL を収集
    image_urls = thread.get("image_urls") or []
    voice_clip = thread.get("voice_clip") or {}
    voice_url = voice_clip.get("url")

    # 本文を埋め込みの description に載せる
    desc_lines = []
    if body:
        desc_lines.append(body)

    description = "\n".join(desc_lines)

    # Embed description は最大 4096 文字だが、安全のため少し短めに切り詰める
    MAX_DESC = 3800
    if len(description) > MAX_DESC:
        description = description[: MAX_DESC - 1] + "…"

    # スレッド URL
    thread_url = (
        f"https://www.holoplus.com/app/threads/{thread_id}" if thread_id else None
    )

    # 投稿者情報（あれば）
    user = thread.get("user") or {}
    author_name = user.get("name") or channel_name
    author_icon = user.get("icon_url")

    embed: Dict[str, Any] = {
        "title": title or channel_name or "Holoplus Thread",
        "description": description or None,
    }

    if thread_url:
        embed["url"] = thread_url

    if author_name or author_icon:
        embed["author"] = {
            "name": author_name,
            **({"icon_url": author_icon} if author_icon else {}),
        }

    # 画像（あれば先頭 1 枚）
    if image_urls:
        embed["image"] = {"url": image_urls[0]}

    # content には短いヘッダだけ載せておく
    content = header if header else thread_url or ""
    if len(content) > 2000:
        content = content[:1999] + "…"

    payload: Dict[str, Any] = {"embeds": [embed]}
    if content:
        payload["content"] = content

    return payload, voice_url


def send_discord_webhook(
    webhook_url: str, payload: Dict[str, Any], voice_url: str | None
) -> None:
    # まず埋め込みのみ送信
    resp = requests.post(
        webhook_url,
        json=payload,
        timeout=10,
    )
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        # エラー内容を分かりやすくする
        raise SystemExit(f"Webhook failed: {exc} - {resp.text}") from exc

    if voice_url:
        # 次に、音声ファイルをダウンロードして添付として送信することで、
        # Discord 上で再生 UI が表示されるようにする
        audio_resp = requests.get(voice_url, timeout=60)
        try:
            audio_resp.raise_for_status()
        except requests.HTTPError as exc:
            raise SystemExit(
                f"Failed to download voice clip: {exc} - {audio_resp.text}"
            ) from exc

        # ファイル名は常に voice-clip + 拡張子 とする
        filename = "voice-clip.m4a"
        # 拡張子を URL から推測できる場合はそれを使う
        url_path = voice_url.rstrip("/").split("/")[-1]
        if "." in url_path:
            ext = "." + url_path.split(".")[-1]
            filename = f"voice-clip{ext}"

        resp2 = requests.post(
            webhook_url,
            files={"file": (filename, audio_resp.content)},
            timeout=60,
        )
        try:
            resp2.raise_for_status()
        except requests.HTTPError as exc:
            raise SystemExit(f"Webhook (voice clip) failed: {exc} - {resp2.text}") from exc


def main() -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise SystemExit(
            "環境変数 DISCORD_WEBHOOK_URL に Discord の Webhook URL を設定してください。"
        )

    entries = load_new_threads()
    if not entries:
        print("new.json に新規スレッドはありません。何も送信しません。")
        return

    for entry in entries:
        payload, voice_url = build_discord_payload(entry)
        send_discord_webhook(webhook_url, payload, voice_url)

    print(f"Sent {len(entries)} messages to Discord webhook.")


if __name__ == "__main__":
    main()
