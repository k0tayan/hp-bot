from __future__ import annotations

import json
import os
from typing import Any, Dict, List

import requests


def fetch_talent_channels(auth_token: str, timeout: int = 10) -> Dict[str, Any]:
    """
    holoplus の talent-channel 一覧を取得する。
    """
    url = "https://api.holoplus.com/v4/talent-channel/channels"

    headers = {
        "user-agent": "Dart/3.9 (dart:io)",
        "accept-language": "ja",
        "host": "api.holoplus.com",
        "authorization": f"Bearer {auth_token}",
        "content-type": "text/plain; charset=utf-8",
        "app-version": "3.1.1 (904)",
    }

    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def save_talent_channels_to_csv(items: List[Dict[str, Any]], path: str) -> None:
    """
    talent-channel の items から id, name のみを JSON に保存する。
    id で昇順ソートする。
    """
    sorted_items = sorted(items, key=lambda item: item.get("id", ""))

    payload = [
        {
            "id": item.get("id", ""),
            "name": item.get("name", ""),
        }
        for item in sorted_items
    ]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def main() -> None:
    """
    talent-channel 一覧を取得して、id, name のみを
    id 昇順でソートした JSON (talent-channel.json) に出力する。
    """
    auth_token = os.environ.get("HOLOPLUS_TOKEN")
    if not auth_token:
        raise SystemExit(
            "環境変数 HOLOPLUS_TOKEN に Bearer トークンを設定してください。"
        )

    data = fetch_talent_channels(auth_token)
    items = data.get("items") or []
    save_talent_channels_to_csv(items, "talent-channel.json")


if __name__ == "__main__":
    main()
