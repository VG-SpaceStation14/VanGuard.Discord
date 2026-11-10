CREATE TABLE IF NOT EXISTS discord_link_requests (
    user_id UUID PRIMARY KEY,
    link_code VARCHAR(8) UNIQUE,
    discord_id BIGINT UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'requested', 
    sponsor_tier SMALLINT DEFAULT 0,
    sponsor_until TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    requested_at TIMESTAMPTZ DEFAULT now(),
    linked_at TIMESTAMPTZ,
    CONSTRAINT chk_status CHECK (status IN ('requested', 'ready', 'linked')),
    CONSTRAINT chk_linked_has_discord CHECK (status <> 'linked' OR discord_id IS NOT NULL),
    CONSTRAINT chk_discord_only_when_linked CHECK (status = 'linked' OR discord_id IS NULL),
    CONSTRAINT chk_ready_has_code CHECK (status <> 'ready' OR (link_code IS NOT NULL AND expires_at IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_discord_link_requested
ON discord_link_requests(requested_at) WHERE status = 'requested';

CREATE TABLE IF NOT EXISTS discord_link_audit (
    id SERIAL PRIMARY KEY,
    discord_id BIGINT,
    user_id UUID,
    action VARCHAR(20) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT chk_action CHECK (action IN ('linked', 'unlinked'))
);

CREATE INDEX IF NOT EXISTS idx_audit_user ON discord_link_audit(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_discord ON discord_link_audit(discord_id);