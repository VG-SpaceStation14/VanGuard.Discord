<p align="center">
  <img alt="VanGuard SS14" width="350" src="https://raw.githubusercontent.com/VG-SpaceStation14/VanGuardSS14/master/Resources/Textures/_VanGuard/Logo/logo.png" />
</p>


<div align="center">

[![Discord](https://img.shields.io/badge/Discord-Наш%20сервер-E05A33?logo=discord&logoColor=white&style=for-the-badge&labelColor=1C1C1C)](https://discord.gg/nW73CdBYkg) 
[![Сайт](https://img.shields.io/badge/Сайт-Наш%20сайт-E05A33?style=for-the-badge&labelColor=1C1C1C)](https://vanguardproject.ru/index.html)
[![Main Repo](https://img.shields.io/badge/VanGuard-SS14%20Repo-E05A33?logo=github&logoColor=white&style=for-the-badge&labelColor=1C1C1C)](https://github.com/VG-SpaceStation14/VanGuardSS14) 
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white&style=for-the-badge&labelColor=1C1C1C)](https://www.python.org/) 
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-316192?logo=postgresql&logoColor=white&style=for-the-badge&labelColor=1C1C1C)](https://www.postgresql.org/)

</div>

---

## 🤖 О проекте

**VanGuard Discord Bot** — официальный бот для Discord-сервера проекта [VanGuard](https://github.com/VG-SpaceStation14/VanGuardSS14). 

Его основная задача — **безопасная привязка аккаунтов Discord к игровым аккаунтам Space Station 14** с использованием архитектуры «тонкого клиента» (One-Time Password) и синхронизация спонсорских привилегий (тиров).

Игровой сервер (C#) не имеет прямого доступа к Discord ID игроков и не может подделать статус привязки. Вся логика, аудит и синхронизация ролей живут в этом Python-боте.

## ✨ Возможности

* **Безопасная привязка (`/link`)** — генерация одноразовых кодов (8 символов) через модальные окна Discord.
* **Отвязка аккаунта (`/unlink`)** — атомарное удаление привязки с записью в аудит.
* **Проверка статуса (`/status`)** — просмотр текущего уровня спонсора и срока действия подписки.
* **Синхронизация спонсоров** — автоматическое отслеживание ролей (Heartbeat каждые 5 минут) и мгновенная реакция на выдачу/снятие ролей (`on_member_update`).
* **Отказоустойчивость** — если бот упадёт, игровые пёрки (цвет ника, слоты) погаснут сами через 1 час благодаря проверке `sponsor_until` на стороне игры.

## 🛠 Архитектура и Стек

* **Язык:** Python 3.11+ (используется `discord.py` v2+).
* **База данных:** PostgreSQL (драйвер `asyncpg`).
* **Взаимодействие:** Бот и игровой сервер общаются исключительно через БД (таблицы `discord_link_requests` и `discord_link_audit`).
* **Безопасность:** Бот использует роль `ss14_bot` с ограниченными правами (без доступа к остальным таблицам игры).

## 🚀 Установка и запуск

**Требования:** Python 3.11+, PostgreSQL, Git.

1. Склонируйте репозиторий:
```
git clone https://github.com/VG-SpaceStation14/VanGuard.Discord.git
cd VanGuard.Discord
```

2. Создайте виртуальное окружение и установите зависимости:
```
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

3. Настройте переменные окружения (создайте файл `.env` на основе `.env.example`):
```
DISCORD_BOT_TOKEN=ваш_токен_бота
DB_DSN=postgresql://ss14_bot:пароль@127.0.0.1:5432/ss14
GUILD_ID=ID_вашего_сервера
ROLE_TIER_1=ID_роли_1
ROLE_TIER_2=ID_роли_2
ROLE_TIER_3=ID_роли_3
SYNC_COMMANDS=1
```

4. Запустите бота:
```
./venv/bin/python bot.py
```
*(Для продакшена настоятельно рекомендуется использовать systemd или Docker).*

## 🤝 Контрибьют

Мы всегда рады помощи! Если у вас есть идеи по улучшению бота, создавайте [issues](https://github.com/VG-SpaceStation14/VanGuard.Discord/issues) или открывайте Pull Requests.

**Использование ИИ.** Нейросети разрешено использовать как инструмент для написания кода. Автор пулл-реквеста полностью отвечает за результат: код должен проходить тесты и не нарушать лицензионную совместимость проекта.

## ⚖️ Лицензия

**Код — MIT.**
Исходный код в этом репозитории распространяется под лицензией [MIT](LICENSE).

**Связь с VanGuard SS14.**
Данный бот является неотъемлемой частью экосистемы [VanGuard SS14](https://github.com/VG-SpaceStation14/VanGuardSS14) и разработан для взаимодействия с его базой данных. 

---
*Разработано для проекта VanGuard. Благодарим сообщества Space Station 14.*
