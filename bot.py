import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncpg
import secrets
import time
import os
import logging
from aiohttp import web

log = logging.getLogger("vgbot")

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DB_DSN = os.getenv("DB_DSN")
BOT_SECRET = os.getenv("BOT_SECRET", "CHANGE_THIS_TO_A_RANDOM_SECRET_STRING")

GUILD_ID_STR = os.getenv("GUILD_ID")
ROLE_TIER_1_STR = os.getenv("ROLE_TIER_1")
ROLE_TIER_2_STR = os.getenv("ROLE_TIER_2")
ROLE_TIER_3_STR = os.getenv("ROLE_TIER_3")

if not all([TOKEN, DB_DSN, GUILD_ID_STR, ROLE_TIER_1_STR, ROLE_TIER_2_STR, ROLE_TIER_3_STR]):
    raise SystemExit("Ошибка: Задайте DISCORD_BOT_TOKEN, DB_DSN, GUILD_ID и ROLE_TIER_1/2/3 в .env")

GUILD_ID = int(GUILD_ID_STR)
ROLE_TIER_1 = int(ROLE_TIER_1_STR)
ROLE_TIER_2 = int(ROLE_TIER_2_STR)
ROLE_TIER_3 = int(ROLE_TIER_3_STR)

ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
RATE_LIMIT = {}

def ilag(interaction: discord.Interaction) -> float:
    """Сколько секунд прошло между созданием interaction в Discord и моментом, когда мы его обработали."""
    return (discord.utils.utcnow() - interaction.created_at).total_seconds()


async def loop_lag_monitor():
    """Пишет в лог, если event loop задерживается (что-то блокирует процесс)."""
    while True:
        t = time.monotonic()
        await asyncio.sleep(1)
        drift = time.monotonic() - t - 1
        if drift > 0.3:
            log.warning("event loop задержан на %.2fс", drift)


class VGBot(commands.Bot):
    async def setup_hook(self):
        self.db_pool = await asyncpg.create_pool(DB_DSN)
        generate_codes.start()
        heartbeat_sponsors.start()
        cleanup_expired.start()
        self.lag_task = asyncio.create_task(loop_lag_monitor())

        async def handle_generate(request):
            try:
                data = await request.json()
                if data.get("secret") != BOT_SECRET:
                    return web.json_response({"error": "Unauthorized"}, status=401)
                async with self.db_pool.acquire() as conn:
                    while await claim_one(conn):
                        pass
                return web.json_response({"status": "OK"})
            except Exception as e:
                logging.exception("Ошибка в HTTP API")
                return web.json_response({"error": str(e)}, status=500)

        app = web.Application()
        app.router.add_post('/api/generate_code', handle_generate)
        self.web_runner = web.AppRunner(app)
        await self.web_runner.setup()
        site = web.TCPSite(self.web_runner, '127.0.0.1', 8080)
        await site.start()

        if os.getenv("SYNC_COMMANDS") == "1":
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"Команды синхронизированы с гильдией {GUILD_ID}.")
        else:
            print("Пропуск синхронизации команд. Используйте SYNC_COMMANDS=1 для обновления.")

    async def close(self):
        lag_task = getattr(self, "lag_task", None)
        if lag_task:
            lag_task.cancel()
        if hasattr(self, "web_runner") and self.web_runner:
            await self.web_runner.cleanup()
        pool = getattr(self, "db_pool", None)
        if pool:
            await pool.close()
        await super().close()


intents = discord.Intents.default()
intents.members = True

bot = VGBot(command_prefix=commands.when_mentioned, intents=intents)


@bot.tree.error
async def on_app_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    original = getattr(error, "original", error)
    name = interaction.command.name if interaction.command else "?"
    if isinstance(original, discord.NotFound):
        log.warning("/%s: interaction истёк (10062), дошло через %.2fс, ws latency %.2fс",
                    name, ilag(interaction), bot.latency)
        return
    log.exception("Ошибка в команде /%s", name, exc_info=error)


@bot.event
async def on_disconnect():
    log.warning("gateway disconnect, latency=%.2f", bot.latency)


@bot.event
async def on_resumed():
    log.warning("gateway resumed, latency=%.2f", bot.latency)


def get_member_tier(member: discord.Member) -> int:
    """Определяет наивысший тир спонсора у пользователя"""
    role_ids = {r.id for r in member.roles}
    if ROLE_TIER_3 in role_ids: return 3
    if ROLE_TIER_2 in role_ids: return 2
    if ROLE_TIER_1 in role_ids: return 1
    return 0


class LinkModal(discord.ui.Modal, title='Привязка аккаунта SS14'):
    code_input = discord.ui.TextInput(
        label='Введите код из игры',
        placeholder='Например: A3B4C5D6',
        min_length=8,
        max_length=8
    )

    async def on_submit(self, interaction: discord.Interaction):
        log.info("LinkModal.on_submit: дошло через %.2fс, ws latency %.2fс", ilag(interaction), bot.latency)

        # Сразу подтверждаем, чтобы запрос к БД не упёрся в лимит 3 секунды
        try:
            await interaction.response.defer(ephemeral=True)
        except discord.NotFound:
            log.warning("LinkModal: interaction истёк до defer, дошло через %.2fс", ilag(interaction))
            return

        code = self.code_input.value.strip().upper()
        discord_id = interaction.user.id

        now = time.time()
        user_attempts = RATE_LIMIT.get(discord_id, [])
        user_attempts = [t for t in user_attempts if now - t < 60]
        if len(user_attempts) >= 5:
            await interaction.followup.send("❌ Слишком много попыток. Подождите минуту.", ephemeral=True)
            return
        user_attempts.append(now)
        RATE_LIMIT[discord_id] = user_attempts

        tier = get_member_tier(interaction.user)

        try:
            async with bot.db_pool.acquire() as conn:
                result = await conn.fetchval("""
                    WITH updated AS (
                        UPDATE discord_link_requests
                        SET status = 'linked',
                            discord_id = $2::bigint,
                            linked_at = now(),
                            link_code = NULL,
                            sponsor_tier = CASE WHEN $3::smallint > 0 THEN $3::smallint ELSE 0 END,
                            sponsor_until = CASE WHEN $3::smallint > 0 THEN now() + interval '1 hour' END
                        WHERE link_code = $1 AND status = 'ready' AND expires_at > now()
                        RETURNING user_id, discord_id
                    )
                    INSERT INTO discord_link_audit (discord_id, user_id, action)
                    SELECT discord_id, user_id, 'linked' FROM updated
                    RETURNING user_id;
                """, code, discord_id, tier)

            if result is not None:
                if tier > 0:
                    msg = f"✅ Успешно привязано!\n⭐ Ваш уровень спонсора: **Tier {tier}**"
                else:
                    msg = "✅ Успешно привязано! (Спонсорская роль не обнаружена)"
            else:
                msg = "❌ Код неверный или истек."

            await interaction.followup.send(msg, ephemeral=True)

        except asyncpg.UniqueViolationError:
            await interaction.followup.send("❌ Этот Discord уже привязан к другому аккаунту SS14.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logging.exception("Ошибка в модалке LinkModal", exc_info=error)
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message("❌ Внутренняя ошибка БД, попробуйте позже.", ephemeral=True)
            else:
                await interaction.followup.send("❌ Внутренняя ошибка БД, попробуйте позже.", ephemeral=True)
        except Exception:
            pass


@bot.tree.command(name="link", description="Привязать аккаунт SS14")
@app_commands.guild_only()
async def link(interaction: discord.Interaction):
    log.info("/link: дошло через %.2fс, ws latency %.2fс", ilag(interaction), bot.latency)
    await interaction.response.send_modal(LinkModal())


@bot.tree.command(name="unlink", description="Отвязать аккаунт SS14")
@app_commands.guild_only()
async def unlink(interaction: discord.Interaction):
    log.info("/unlink: дошло через %.2fс, ws latency %.2fс", ilag(interaction), bot.latency)
    try:
        await interaction.response.defer(ephemeral=True)
    except discord.NotFound:
        log.warning("/unlink: interaction истёк до defer, дошло через %.2fс, ws latency %.2fс",
                    ilag(interaction), bot.latency)
        return
    except Exception as e:
        log.error("Network error in /unlink defer: %s", e)
        return

    try:
        async with bot.db_pool.acquire() as conn:
            query = """
                WITH deleted AS (
                    DELETE FROM discord_link_requests
                    WHERE discord_id = $1::bigint RETURNING user_id
                )
                INSERT INTO discord_link_audit (discord_id, user_id, action)
                SELECT $1::bigint, user_id, 'unlinked' FROM deleted
                RETURNING user_id;
            """
            deleted = await conn.fetchval(query, interaction.user.id)

        if deleted is not None:
            await interaction.followup.send("✅ Аккаунт отвязан.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Ваш Discord не привязан.", ephemeral=True)
    except Exception:
        logging.exception("Ошибка в /unlink")
        try:
            await interaction.followup.send("❌ Ошибка БД. Попробуйте позже.", ephemeral=True)
        except Exception:
            pass


@bot.tree.command(name="status", description="Проверить статус привязки и спонсора")
@app_commands.guild_only()
async def status(interaction: discord.Interaction):
    log.info("/status: дошло через %.2fс, ws latency %.2fс", ilag(interaction), bot.latency)
    try:
        await interaction.response.defer(ephemeral=True)
    except discord.NotFound:
        log.warning("/status: interaction истёк до defer, дошло через %.2fс, ws latency %.2fс",
                    ilag(interaction), bot.latency)
        return
    except Exception as e:
        log.error("Network error in /status defer: %s", e)
        return

    try:
        async with bot.db_pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT status, sponsor_tier, sponsor_until
                FROM discord_link_requests
                WHERE discord_id = $1::bigint
            """, interaction.user.id)

        if not row or row['status'] != 'linked':
            await interaction.followup.send("❌ Ваш Discord не привязан к аккаунту SS14. Используйте `/link`.", ephemeral=True)
            return

        tier = row['sponsor_tier']
        until = row['sponsor_until']

        is_active = until is not None and until.timestamp() > time.time()

        if is_active and tier > 0:
            msg = "✅ **Discord привязан**\n"
            msg += f"⭐ Уровень спонсора: **Tier {tier}**\n"
            msg += "⏳ Статус подписки: **Активна**"
        else:
            msg = "✅ **Discord привязан**\n"
            msg += "❌ Активной спонсорской подписки нет."

        await interaction.followup.send(msg, ephemeral=True)

    except Exception:
        logging.exception("Ошибка в /status")
        try:
            await interaction.followup.send("❌ Ошибка БД. Попробуйте позже.", ephemeral=True)
        except Exception:
            pass


CLAIM_SQL = """
    UPDATE discord_link_requests
    SET status = 'ready', link_code = $1, expires_at = now() + interval '10 minutes'
    WHERE user_id = (
        SELECT user_id FROM discord_link_requests
        WHERE status = 'requested'
        ORDER BY requested_at ASC
        FOR UPDATE SKIP LOCKED LIMIT 1
    )
    RETURNING user_id;
"""


async def claim_one(conn) -> bool:
    for _ in range(5):
        code = "".join(secrets.choice(ALPHABET) for _ in range(8))
        try:
            return await conn.fetchrow(CLAIM_SQL, code) is not None
        except asyncpg.UniqueViolationError:
            continue
    return False


@tasks.loop(seconds=2.0)
async def generate_codes():
    try:
        async with bot.db_pool.acquire() as conn:
            while await claim_one(conn):
                pass
    except Exception:
        logging.exception("Ошибка в generate_codes")


@tasks.loop(minutes=5)
async def heartbeat_sponsors():
    try:
        guild = bot.get_guild(GUILD_ID)
        if not guild: return

        role1 = guild.get_role(ROLE_TIER_1)
        role2 = guild.get_role(ROLE_TIER_2)
        role3 = guild.get_role(ROLE_TIER_3)

        t3_ids = {m.id for m in role3.members} if role3 else set()
        t2_ids = {m.id for m in role2.members if m.id not in t3_ids} if role2 else set()
        t1_ids = {m.id for m in role1.members if m.id not in t3_ids and m.id not in t2_ids} if role1 else set()

        async with bot.db_pool.acquire() as conn:
            async with conn.transaction():
                if t3_ids:
                    await conn.execute("UPDATE discord_link_requests SET sponsor_tier = 3, sponsor_until = now() + interval '1 hour' WHERE discord_id = ANY($1::bigint[])", list(t3_ids))
                if t2_ids:
                    await conn.execute("UPDATE discord_link_requests SET sponsor_tier = 2, sponsor_until = now() + interval '1 hour' WHERE discord_id = ANY($1::bigint[])", list(t2_ids))
                if t1_ids:
                    await conn.execute("UPDATE discord_link_requests SET sponsor_tier = 1, sponsor_until = now() + interval '1 hour' WHERE discord_id = ANY($1::bigint[])", list(t1_ids))
    except Exception:
        logging.exception("Ошибка в heartbeat_sponsors")


@heartbeat_sponsors.before_loop
async def before_heartbeat():
    await bot.wait_until_ready()


@tasks.loop(hours=24)
async def cleanup_expired():
    try:
        async with bot.db_pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM discord_link_requests
                WHERE status = 'ready' AND expires_at < now()
            """)
    except Exception:
        logging.exception("Ошибка в cleanup_expired")


@bot.event
async def on_ready():
    print(f"Бот {bot.user} успешно подключен к Discord!")
    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Game(name="VanGuard SS14")
    )


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.roles == after.roles: return

    tier = get_member_tier(after)

    try:
        async with bot.db_pool.acquire() as conn:
            if tier > 0:
                await conn.execute("""
                    UPDATE discord_link_requests
                    SET sponsor_tier = $1::smallint, sponsor_until = now() + interval '1 hour'
                    WHERE discord_id = $2::bigint
                """, tier, after.id)
            else:
                await conn.execute("""
                    UPDATE discord_link_requests
                    SET sponsor_tier = 0, sponsor_until = now()
                    WHERE discord_id = $1::bigint
                """, after.id)
    except Exception:
        logging.exception("Ошибка в on_member_update")


@bot.event
async def on_member_remove(member: discord.Member):
    try:
        async with bot.db_pool.acquire() as conn:
            await conn.execute("""
                UPDATE discord_link_requests
                SET sponsor_tier = 0, sponsor_until = now()
                WHERE discord_id = $1::bigint
            """, member.id)
    except Exception:
        logging.exception("Ошибка в on_member_remove")


if __name__ == "__main__":
    bot.run(TOKEN, log_level=logging.INFO)
