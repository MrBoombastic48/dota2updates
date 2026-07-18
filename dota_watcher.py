#!/usr/bin/env python3
"""
Следит за официальными патчноутами Dota 2 и отправляет новые записи в Discord
через webhook.

Источник данных — тот же самый официальный эндпоинт Steam (partner events),
которым пользуется сам SteamDB для формирования страницы
https://steamdb.info/app/570/patchnotes/. Мы не скрапим HTML steamdb.info
(это запрещено их условиями использования и защищено от ботов), а берём
данные напрямую у Valve в чистом JSON — событие с event_type 12 (small
update) или 13 (major update) и тегом "patchnotes" это и есть официальные
патчноуты, а не любые посты комьюнити (распродажи, мерч и т.п.).

Состояние (id уже отправленных записей) хранится в файле state.json,
который коммитится обратно в репозиторий GitHub Actions'ом.
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

APP_ID = 570  # Dota 2
PARTNER_EVENTS_URL = "https://store.steampowered.com/events/ajaxgetadjacentpartnerevents/"
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


def fetch_news(count: int = 15) -> list:
    params = {
        "appid": APP_ID,
        "count_before": 0,
        "count_after": count,
        # event_type 12 = small update, 13 = major update — это и есть патчноуты
        "event_type_filter": "12,13",
    }
    resp = requests.get(PARTNER_EVENTS_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    events = data.get("events", [])

    items = []
    for ev in events:
        body = ev.get("announcement_body", {}) or {}
        # оставляем только настоящие патчноуты (на всякий случай, фильтр event_type
        # уже должен был это сделать, но тег надёжнее)
        tags = body.get("tags", [])
        if "patchnotes" not in tags:
            continue
        items.append(
            {
                "gid": ev.get("gid"),
                "title": ev.get("event_name") or body.get("headline") or "Обновление Dota 2",
                "contents": body.get("body", ""),
                "date": body.get("posttime", ev.get("rtime32_last_modified", time.time())),
                "url": f"https://steamcommunity.com/games/{APP_ID}/announcements/detail/{ev.get('gid')}",
            }
        )
    return items


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
        "footer": {"text": "Dota 2 Patch Notes"},
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
