import pytest
import pytest_asyncio
import uuid
import asyncpg
import secrets
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

BOT_SECRET = "test_secret_123"
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

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
    """Копия функции claim_one из bot.py для теста"""
    for _ in range(5):
        code = "".join(secrets.choice(ALPHABET) for _ in range(8))
        try:
            return await conn.fetchrow(CLAIM_SQL, code) is not None
        except asyncpg.UniqueViolationError:
            continue
    return False


@pytest_asyncio.fixture
async def api_app(db_pool):
    """Создает тестовое приложение aiohttp, имитирующее эндпоинт бота"""
    async def handle_generate(request):
        try:
            data = await request.json()
            if data.get("secret") != BOT_SECRET:
                return web.json_response({"error": "Unauthorized"}, status=401)
            
            async with db_pool.acquire() as conn:
                while await claim_one(conn):
                    pass
            return web.json_response({"status": "OK"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    app = web.Application()
    app.router.add_post('/api/generate_code', handle_generate)
    return app


@pytest.mark.asyncio
async def test_http_ping_generates_code(db_pool, api_app):
    """Тест: C# сервер успешно пингует бота и получает код в БД"""
    user_id = uuid.uuid4()
    
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO discord_link_requests (user_id, status) VALUES ($1, 'requested')",
            user_id
        )

    async with TestClient(TestServer(api_app)) as client:

        resp = await client.post('/api/generate_code', json={"secret": BOT_SECRET})
        assert resp.status == 200
        json_data = await resp.json()
        assert json_data["status"] == "OK"

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, link_code FROM discord_link_requests WHERE user_id = $1",
            user_id
        )
        assert row['status'] == 'ready'
        assert row['link_code'] is not None
        assert len(row['link_code']) == 8


@pytest.mark.asyncio
async def test_http_ping_wrong_secret(api_app):
    """Тест: C# сервер использует неверный секрет и получает 401"""
    async with TestClient(TestServer(api_app)) as client:
        resp = await client.post('/api/generate_code', json={"secret": "WRONG_SECRET"})
        assert resp.status == 401