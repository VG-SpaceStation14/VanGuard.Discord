import pytest
import pytest_asyncio
import asyncpg
import os

TEST_DB_DSN = os.getenv("TEST_DB_DSN", "postgresql://postgres:postgres@127.0.0.1:5432/test_db")

@pytest_asyncio.fixture(scope="session")
async def db_pool():
    pool = await asyncpg.create_pool(TEST_DB_DSN)
    
    with open("schema.sql", "r") as f:
        schema = f.read()
    async with pool.acquire() as conn:
        await conn.execute(schema)
        
    yield pool
    await pool.close()

@pytest_asyncio.fixture(autouse=True)
async def clean_db(db_pool):
    async with db_pool.acquire() as conn:
        await conn.execute("TRUNCATE discord_link_requests, discord_link_audit RESTART IDENTITY CASCADE;")
