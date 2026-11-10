import pytest
import uuid

@pytest.mark.asyncio
async def test_link_with_tier_3(db_pool):
    """Тест: Игрок привязывается, имея роль Космического ниндзя (Тир 3)"""
    user_id = uuid.uuid4()
    discord_id = 987654321
    code = "NINJA123"
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO discord_link_requests (user_id, status, link_code, expires_at) 
            VALUES ($1, 'ready', $2, now() + interval '10 minutes')
        """, user_id, code)

        query = """
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
        """
        result = await conn.fetchval(query, code, discord_id, 3)

        assert result == user_id
        
        row = await conn.fetchrow("SELECT * FROM discord_link_requests WHERE user_id = $1", user_id)
        assert row['status'] == 'linked'
        assert row['sponsor_tier'] == 3
        assert row['sponsor_until'] is not None

@pytest.mark.asyncio
async def test_heartbeat_upgrade(db_pool):
    """Тест: Игрок был Тир 1, но получил Тир 2 (Heartbeat)"""
    discord_id = 111222333
    user_id = uuid.uuid4()
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO discord_link_requests (user_id, discord_id, status, sponsor_tier, sponsor_until) 
            VALUES ($1, $2, 'linked', 1, now() + interval '1 hour')
        """, user_id, discord_id)
        
        await conn.execute("""
            UPDATE discord_link_requests 
            SET sponsor_tier = 2, sponsor_until = now() + interval '1 hour' 
            WHERE discord_id = ANY($1::bigint[])
        """, [discord_id])
        
        row = await conn.fetchrow("SELECT sponsor_tier FROM discord_link_requests WHERE user_id = $1", user_id)
        assert row['sponsor_tier'] == 2

@pytest.mark.asyncio
async def test_role_removed(db_pool):
    """Тест: У игрока забрали роль (on_member_update)"""
    discord_id = 444555666
    user_id = uuid.uuid4()
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO discord_link_requests (user_id, discord_id, status, sponsor_tier, sponsor_until) 
            VALUES ($1, $2, 'linked', 3, now() + interval '1 hour')
        """, user_id, discord_id)
        
        await conn.execute("""
            UPDATE discord_link_requests 
            SET sponsor_tier = 0, sponsor_until = now() 
            WHERE discord_id = $1::bigint
        """, discord_id)
        
        row = await conn.fetchrow("SELECT sponsor_tier, sponsor_until FROM discord_link_requests WHERE user_id = $1", user_id)
        assert row['sponsor_tier'] == 0
        assert row['sponsor_until'] <= await conn.fetchval("SELECT now()")

@pytest.mark.asyncio
async def test_unlink_clears_everything(db_pool):
    """Тест: /unlink удаляет запись и пишет в аудит"""
    user_id = uuid.uuid4()
    discord_id = 777888999
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO discord_link_requests (user_id, discord_id, status, sponsor_tier) 
            VALUES ($1, $2, 'linked', 2)
        """, user_id, discord_id)
        
        query = """
            WITH deleted AS (
                DELETE FROM discord_link_requests 
                WHERE discord_id = $1::bigint RETURNING user_id
            )
            INSERT INTO discord_link_audit (discord_id, user_id, action)
            SELECT $1::bigint, user_id, 'unlinked' FROM deleted
            RETURNING user_id;
        """
        result = await conn.fetchval(query, discord_id)
        
        assert result == user_id
        
        assert await conn.fetchval("SELECT COUNT(*) FROM discord_link_requests WHERE user_id = $1", user_id) == 0
        
        audit = await conn.fetchrow("SELECT * FROM discord_link_audit WHERE user_id = $1", user_id)
        assert audit['action'] == 'unlinked'
