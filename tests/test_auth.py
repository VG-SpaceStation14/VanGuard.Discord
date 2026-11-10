import pytest
import uuid

@pytest.mark.asyncio
async def test_successful_link(db_pool):
    user_id = uuid.uuid4()
    discord_id = 123456789
    code = "A1B2C3D4"
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO discord_link_requests (user_id, status, link_code, expires_at) 
            VALUES ($1, 'ready', $2, now() + interval '10 minutes')
        """, user_id, code)

        query = """
            WITH updated AS (
                UPDATE discord_link_requests
                SET status = 'linked', discord_id = $2, linked_at = now(), link_code = NULL,
                    sponsor_until = CASE WHEN $3::boolean THEN now() + interval '1 hour' END
                WHERE link_code = $1 AND status = 'ready' AND expires_at > now()
                RETURNING user_id, discord_id
            )
            INSERT INTO discord_link_audit (discord_id, user_id, action)
            SELECT discord_id, user_id, 'linked' FROM updated
            RETURNING user_id;
        """
        result = await conn.fetchval(query, code, discord_id, True)

        assert result == user_id

        audit = await conn.fetchrow("SELECT * FROM discord_link_audit")
        assert audit['action'] == 'linked'
        assert audit['discord_id'] == discord_id