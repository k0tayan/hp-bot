from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any, Dict, Iterator, List

import requests
from tqdm import tqdm


def fetch_newest_threads(
    auth_token: str,
    channel_id: str,
    *,
    limit: int = 20,
    cursor: str | None = None,
    timeout: int = 10,
) -> Dict[str, Any]:
    """
    指定したチャンネルの最新スレッド一覧を取得する。
    """
    url = "https://api.holoplus.com/v4/talent-channel/threads/newest"

    headers = {
        "user-agent": "Dart/3.9 (dart:io)",
        "accept-language": "ja",
        "host": "api.holoplus.com",
        "authorization": f"Bearer {auth_token}",
        "content-type": "text/plain; charset=utf-8",
        "app-version": "3.1.1 (904)",
    }

    params: Dict[str, str] = {"channel_id": channel_id, "limit": str(limit)}
    if cursor:
        params["cursor"] = cursor

    resp = requests.get(url, headers=headers, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def iter_all_threads(
    auth_token: str, channel_id: str, *, limit: int = 20, timeout: int = 10
) -> Iterator[Dict[str, Any]]:
    """
    カーソルを使って、指定チャンネルのスレッドを全件取得するイテレータ。
    """
    cursor: str | None = None

    while True:
        data = fetch_newest_threads(
            auth_token=auth_token,
            channel_id=channel_id,
            limit=limit,
            cursor=cursor,
            timeout=timeout,
        )
        items = data.get("items") or []

        if not items:
            break

        for item in items:
            yield item

        cursor = data.get("next_cursor")
        if not cursor:
            break


def _collect_threads_for_channel_sync(
    auth_token: str,
    channel_id: str,
    channel_name: str,
    all_threads: bool,
    *,
    limit: int = 20,
    timeout: int = 10,
) -> List[Dict[str, Any]]:
    """
    単一チャンネル分のスレッド情報を同期的に収集するヘルパー。
    """
    results: List[Dict[str, Any]] = []

    def _sanitize_thread(thread: Dict[str, Any]) -> Dict[str, Any]:
        """
        動的なデータ は差分の対象から外したいので、
        JSON には出力しないよう削除したコピーを返す。
        """
        sanitized = dict(thread)
        sanitized.pop("updated_at", None)
        sanitized.pop("reaction_total", None)
        sanitized.pop("reply_count", None)
        sanitized.pop("is_favorite", None)
        sanitized.pop("user_reacted_count", None)
        return sanitized

    if all_threads:
        for thread in iter_all_threads(
            auth_token=auth_token,
            channel_id=channel_id,
            limit=limit,
            timeout=timeout,
        ):
            thread_id = thread.get("id", "")
            if not thread_id:
                continue

            sanitized_thread = _sanitize_thread(thread)

            results.append(
                {
                    "channel_id": channel_id,
                    "channel_name": channel_name,
                    "thread_id": thread_id,
                    "thread": sanitized_thread,
                }
            )
    else:
        data = fetch_newest_threads(
            auth_token=auth_token,
            channel_id=channel_id,
            limit=limit,
            timeout=timeout,
        )
        items = data.get("items") or []

        for thread in items:
            thread_id = thread.get("id", "")
            if not thread_id:
                continue

            sanitized_thread = _sanitize_thread(thread)
            results.append(
                {
                    "channel_id": channel_id,
                    "channel_name": channel_name,
                    "thread_id": thread_id,
                    "thread": sanitized_thread,
                }
            )

    return results


async def _collect_threads_for_channel(
    auth_token: str,
    channel_id: str,
    channel_name: str,
    all_threads: bool,
) -> List[Dict[str, Any]]:
    """
    単一チャンネル分のスレッド情報を別スレッドで取得する非同期ラッパー。
    """
    return await asyncio.to_thread(
        _collect_threads_for_channel_sync,
        auth_token,
        channel_id,
        channel_name,
        all_threads,
    )


async def _main_async() -> None:
    """
    talent-channel.json を読み込み、それぞれのチャンネルの最新スレッドを取得する。
    --all オプション指定時は、カーソルを使って全件取得する。

    結果は API のスレッドレスポンス（各 item）をそのまま保持しつつ
    thread.created_at でソートし、新しいものが先頭になるように並べて
    単一の JSON ファイル (talent-channel-newest.json) に保存する。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--all",
        action="store_true",
        help="各チャンネルのスレッドをカーソルで全件取得して表示する",
    )
    args = parser.parse_args()

    auth_token = os.environ.get("HOLOPLUS_TOKEN")
    if not auth_token:
        raise SystemExit(
            "環境変数 HOLOPLUS_TOKEN に Bearer トークンを設定してください。"
        )

    with open("talent-channel.json", encoding="utf-8") as f:
        rows = json.load(f)

    # 既存の talent-channel-newest.json を読み込み、既知の thread_id を集める
    existing_thread_ids: set[str] = set()
    try:
        with open("talent-channel-newest.json", encoding="utf-8") as f:
            previous_results = json.load(f)
        for row in previous_results:
            thread_id = row.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                existing_thread_ids.add(thread_id)
    except FileNotFoundError:
        # 初回実行などでファイルがなければ、既知のスレッドはなしとみなす
        existing_thread_ids = set()
    except json.JSONDecodeError:
        # 壊れたファイルなどは無視して再生成する
        existing_thread_ids = set()

    # チャンネルごとに並列で取得
    tasks: List[asyncio.Task[List[Dict[str, Any]]]] = []
    for row in rows:
        channel_id = row.get("id", "")
        channel_name = row.get("name", "")
        if not channel_id:
            continue

        tasks.append(
            _collect_threads_for_channel(
                auth_token=auth_token,
                channel_id=channel_id,
                channel_name=channel_name,
                all_threads=bool(args.all),
            )
        )

    per_channel_results: List[List[Dict[str, Any]]] = []
    with tqdm(total=len(tasks), desc="Fetching threads") as pbar:
        for coro in asyncio.as_completed(tasks):
            channel_items = await coro
            per_channel_results.append(channel_items)
            pbar.update(1)

    results: List[Dict[str, Any]] = [
        item for channel_items in per_channel_results for item in channel_items
    ]

    # thread.created_at でソートして JSON に保存（新しいものを先頭に）
    results.sort(
        key=lambda row: (row.get("thread") or {}).get("created_at", 0),
        reverse=True,
    )

    with open("talent-channel-newest.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(
        f"Saved {len(results)} threads to talent-channel-newest.json "
        f"({'all' if args.all else 'latest per channel'})."
    )

    # 既存の JSON に含まれていない thread のみ new.json として保存
    new_results: List[Dict[str, Any]] = [
        row for row in results if row.get("thread_id") not in existing_thread_ids
    ]
    new_results.sort(
        key=lambda row: (row.get("thread") or {}).get("created_at", 0),
        reverse=True,
    )

    with open("new.json", "w", encoding="utf-8") as f:
        json.dump(new_results, f, ensure_ascii=False, indent=2)

    print(f"Saved {len(new_results)} new threads to new.json.")


def main() -> None:
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
