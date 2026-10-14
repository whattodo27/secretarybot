# 🤖 Личный секретарь — Telegram-бот

Бот, который понимает обычную речь на 7 языках, сохраняет напоминания и присылает
их точно вовремя, в часовом поясе пользователя.

Пользователь пишет «напомни завтра в 10 позвонить маме» — бот сам понимает, **что**
и **когда**, и в назначенный момент пишет: «⏰ Напоминание: позвонить маме».
Никаких команд и календарей — обычный язык.

## Возможности

| # | Что | Как это работает |
|---|-----|------------------|
| 1 | Понимает обычную речь | LLM парсит сообщение в структуру `{текст, время, повтор, язык}` |
| 2 | Уведомления вовремя | фоновый цикл раз в `POLL_INTERVAL_SEC` проверяет БД на «наступившие» |
| 3 | Список напоминаний | разделён на **🔜 Ближайшие** и **🗓 Позже** (окно `UPCOMING_WINDOW_H`) |
| 4 | Изменить / удалить | кнопки под каждым напоминанием; удаление — с подтверждением |
| 5 | Часовые пояса | `zoneinfo`/IANA; список популярных городов + ввод текстом |
| 6 | 7 языков | en (по умолчанию), ru, es, de, fr, pt, tr — авто-определение + ручной выбор |
| 7 | Данные не теряются | всё в SQLite (`data/bot.db`), файл монтируется как volume |

## Архитектура и стек

- **Python 3.12 + aiogram 3** — async, нативный FSM для вложенных меню.
- **SQLite** через `SQLAlchemy[asyncio] + aiosqlite` — один файл, ноль OPS.
- **LLM через OpenAI-совместимый API** — любой провайдер (OpenRouter, DeepSeek,
  OpenAI, gpt4all и т.д.), настраивается через `LLM_BASE_URL` / `LLM_MODEL`.
- **Планировщик = polling-цикл** по БД. Не `APScheduler`/Redis: после рестарта
  напоминания просто перечитываются из БД, ничего не теряется.
- **Всё время хранится в UTC**, показывается в локальном времени пользователя.

### Структура

```
bot/
  config.py      — настройки из .env
  db.py          — модели + доступ к SQLite (User, Reminder)
  i18n.py        — 7 языков, строки + форматирование дат
  timezones.py   — IANA-зоны, популярные города, resolve текстом
  llm.py         — клиент LLM + парсинг намерения/языка/времени
  keyboards.py   — все inline-клавиатуры
  scheduler.py   — фоновый цикл отправки уведомлений
  main.py        — маршрутизатор и все обработчики (FSM)
Dockerfile / docker-compose.yml
```

## Локальный запуск

```bash
cp .env.example .env
# отредактируйте .env: впишите BOT_TOKEN (от @BotFather) и LLM_API_KEY

python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m bot.main
```

## Запуск в Docker (рекомендуется для VPS 24/7)

```bash
cp .env.example .env   # заполните токены

docker compose up -d --build
docker compose logs -f bot
```

`restart: unless-stopped` держит бота живым, а `./data` (volume с SQLite) переживает
перезапуски и пересборку образа.

Чтобы обновить код на сервере: `git pull && docker compose up -d --build` — данные
в volume не тронутся.

## Без Docker (systemd на VPS)

```bash
sudo tee /etc/systemd/system/secretary-bot.service > /dev/null <<'EOF'
[Unit]
Description=Secretary Telegram bot
After=network.target

[Service]
WorkingDirectory=/opt/secretary-bot
ExecStart=/opt/secretary-bot/.venv/bin/python -m bot.main
EnvironmentFile=/opt/secretary-bot/.env
Restart=always

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now secretary-bot
```

## Переменные окружения (.env)

| Переменная | Назначение | По умолчанию |
|------------|-----------|--------------|
| `BOT_TOKEN` | токен бота от @BotFather | — |
| `LLM_BASE_URL` | база OpenAI-совместимого API | `https://openrouter.ai/api/v1` |
| `LLM_API_KEY` | ключ LLM | — |
| `LLM_MODEL` | модель | `deepseek/deepseek-chat` |
| `DATA_DIR` / `DB_FILE` | путь к SQLite | `data` / `bot.db` |
| `POLL_INTERVAL_SEC` | период проверки напоминаний | `15` |
| `UPCOMING_WINDOW_H` | окно «ближайшие» | `24` |

## Как это устроено (ключевые детали)

- **Парсинг речи.** Системный промпт просит модель вернуть единственный JSON:
  `{intent, language, reply, text, when, recurrence, reminder_ref}`. `when` — местное
  время пользователя в ISO, бот сам переводит его в UTC.
- **Определение языка.** Модель возвращает ISO-код языка сообщения. В режиме
  «auto» бот сразу отвечает на нём и запоминает; в ручном режиме — отвечает на
  нём и **предлагает кнопкой переключить интерфейс** (см. п.6 ТЗ).
- **Уведомления.** У поля `last_notified` + `status`/`recurrence` — повторяющиеся
  напоминания (`daily`/`weekly`/`monthly`) после отправки сдвигаются вперёд, а
  не удаляются.
- **Повтор:** «каждый день в 10» → `recurrence=daily`; точное «каждый понедельник»
  можно докрутить в подсказке промпта, сейчас поддерживаются daily/weekly/monthly.

## Тест

```bash
.venv/bin/python smoke_test.py   # проверяет i18n, tz, БД, импорты — без токенов/сети
```