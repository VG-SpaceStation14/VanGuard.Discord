import time

RATE_LIMIT = {}

def check_rate_limit(discord_id):
    now = time.time()
    user_attempts = RATE_LIMIT.get(discord_id, [])
    user_attempts = [t for t in user_attempts if now - t < 60]
    
    if len(user_attempts) >= 5:
        return False
        
    user_attempts.append(now)
    RATE_LIMIT[discord_id] = user_attempts
    return True

def test_rate_limit_blocks_after_five():
    discord_id = 999888777
    RATE_LIMIT.clear()
    
    for _ in range(5):
        assert check_rate_limit(discord_id) is True
        
    assert check_rate_limit(discord_id) is False

def test_rate_limit_resets_after_minute(monkeypatch):
    discord_id = 111222333
    RATE_LIMIT.clear()
    
    for _ in range(5):
        check_rate_limit(discord_id)
        
    original_time = time.time
    monkeypatch.setattr(time, "time", lambda: original_time() + 61)
    
    assert check_rate_limit(discord_id) is True
