#!/usr/bin/env python3
"""
Следит за новостями/обновлениями Dota 2 через Steam News API
и отправляет новые записи в Discord через webhook.

Состояние (id последней отправленной новости) хранится в файле state.json,
который коммитится обратно в репозиторий GitHub Actions'ом.
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

APP_ID = 570  # Dota 2
STEAM_NEWS_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v0002/"
STATE_FILE = Path(__file__).parent / "state.json"

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"last_gid": None, "sent_gids": []}


def save_state(state: dict) -> None:
    # держим последние 50 id, чтобы файл не рос бесконечно
    state["sent_gids"] = state["sent_gids"][-50:]
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_news(count: int = 10) -> list:
    params = {
        "appid": APP_ID,
        "count": count,
        "maxlength": 500,  # обрежем текст, полный текст всё равно смотреть по ссылке
        "format": "json",
    }
    resp = requests.get(STEAM_NEWS_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    return data.get("appnews", {}).get("newsitems", [])


def clean_contents(text: str) -> str:
    # в Steam-новостях бывают BBCode-теги [b], [url] и т.п. — грубо вычищаем
    import re

    text = re.sub(r"\[img\].*?\[/img\]", "", text, flags=re.DOTALL)
    text = re.sub(r"\[.*?\]", "", text)
    text = text.strip()
    if len(text) > 350:
        text = text[:350].rsplit(" ", 1)[0] + "…"
    return text


def send_to_discord(item: dict) -> None:
    embed = {
        "title": item.get("title", "Обновление Dota 2")[:256],
        "url": item.get("url"),
        "description": clean_contents(item.get("contents", "")),
        "color": 0xB01717,  # тёмно-красный, в духе Dota
        "timestamp": time.strftime(
            "%Y-%m-%dT%H:%M:%S", time.gmtime(item.get("date", time.time()))
        ),
        "footer": {"text": item.get("feedlabel", "Steam News")},
    }
    payload = {
        "username": "Dota 2 Updates",
        "embeds": [embed],
    }
    resp = requests.post(WEBHOOK_URL, json=payload, timeout=20)
    if resp.status_code >= 300:
        print(f"Ошибка отправки в Discord: {resp.status_code} {resp.text}", file=sys.stderr)
        resp.raise_for_status()


def main() -> None:
    if not WEBHOOK_URL:
        print("Не задана переменная окружения DISCORD_WEBHOOK_URL", file=sys.stderr)
        sys.exit(1)

    state = load_state()
    sent_gids = set(state.get("sent_gids", []))

    news_items = fetch_news()
    if not news_items:
        print("Новостей не найдено.")
        return

    # старые -> новые, чтобы порядок сообщений в Discord был хронологичный
    news_items.sort(key=lambda x: x.get("date", 0))

    new_items = [item for item in news_items if str(item.get("gid")) not in sent_gids]

    if not new_items:
        print("Новых записей нет.")
        return

    for item in new_items:
        print(f"Отправляю: {item.get('title')}")
        send_to_discord(item)
        sent_gids.add(str(item.get("gid")))
        time.sleep(1)  # небольшая пауза, чтобы не словить rate limit

    state["sent_gids"] = list(sent_gids)
    state["last_gid"] = new_items[-1].get("gid")
    save_state(state)
    print(f"Готово, отправлено новых записей: {len(new_items)}")


if __name__ == "__main__":
    main()
