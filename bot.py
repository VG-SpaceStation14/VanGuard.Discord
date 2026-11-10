import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncpg
import secrets
import time
import os
import logging

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DB_DSN = os.getenv("DB_DSN")

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

class VGBot(commands.Bot):
    async def setup_hook(self):
        self.db_pool = await asyncpg.create_pool(DB_DSN)
        generate_codes.start()
        heartbeat_sponsors.start()
        cleanup_expired.start()
        
        if os.getenv("SYNC_COMMANDS") == "1":
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"Команды синхронизированы с гильдией {GUILD_ID}.")
        else:
            print("Пропуск синхронизации команд. Используйте SYNC_COMMANDS=1 для обновления.")

    async def close(self):
        pool = getattr(self, "db_pool", None)
        if pool:
            await pool.close()
        await super().close()

intents = discord.Intents.default()
intents.members = True

bot = VGBot(command_prefix=commands.when_mentioned, intents=intents)

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
        code = self.code_input.value.strip().upper()
        discord_id = interaction.user.id
        
        now = time.time()
        user_attempts = RATE_LIMIT.get(discord_id, [])
        user_attempts = [t for t in user_attempts if now - t < 60]
        if len(user_attempts) >= 5:
            await interaction.response.send_message("❌ Слишком много попыток. Подождите минуту.", ephemeral=True)
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
                    msg = f"✅ Успешно привязано!\n⭐ Ваш уровень спонсора: **Tier {tier}** (подписка активна 1 час, обновляется автоматически)."
                else:
                    msg = "✅ Успешно привязано! (Спонсорская роль не обнаружена)"
            else:
                msg = "❌ Код неверный или истек."
                
            await interaction.response.send_message(msg, ephemeral=True)
            
        except asyncpg.UniqueViolationError:
            await interaction.response.send_message("❌ Этот Discord уже привязан к другому аккаунту SS14.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logging.exception("Ошибка в модалке LinkModal", exc_info=error)
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ Внутренняя ошибка БД, попробуйте позже.", ephemeral=True)

@bot.tree.command(name="link", description="Привязать аккаунт SS14")
@app_commands.guild_only()
async def link(interaction: discord.Interaction):
    await interaction.response.send_modal(LinkModal())

@bot.tree.command(name="unlink", description="Отвязать аккаунт SS14")
@app_commands.guild_only()
async def unlink(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    
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
    await interaction.response.defer(ephemeral=True)
    
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
            time_left = int((until.timestamp() - time.time()) / 60)
            msg = f"✅ **Discord привязан**\n"
            msg += f"⭐ Уровень спонсора: **Tier {tier}**\n"
            msg += f"⏳ Подписка активна еще: **{time_left} мин.**"
        else:
            msg = "✅ **Discord привязан**\n"
            msg += "❌ Активной спонсорской подписки нет."

        await interaction.followup.send(msg, ephemeral=True)
        
    except Exception:
        logging.exception("Ошибка в /status")
        await interaction.followup.send("❌ Ошибка БД. Попробуйте позже.", ephemeral=True)

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
    bot.run(TOKEN)
