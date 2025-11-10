-- PostgreSQL Database Schema for Underwriting AI System
-- Manages rule container deployments, banks, and policy types

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Banks/Organizations table
CREATE TABLE banks (
    bank_id VARCHAR(50) PRIMARY KEY,
    bank_name VARCHAR(255) NOT NULL,
    description TEXT,
    contact_email VARCHAR(255),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Policy types table
CREATE TABLE policy_types (
    policy_type_id VARCHAR(50) PRIMARY KEY,
    policy_name VARCHAR(255) NOT NULL,
    description TEXT,
    category VARCHAR(50), -- e.g., 'insurance', 'loan', 'credit'
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Deployed rule containers
CREATE TABLE rule_containers (
    id SERIAL PRIMARY KEY,
    container_id VARCHAR(255) UNIQUE NOT NULL,
    bank_id VARCHAR(50) REFERENCES banks(bank_id) ON DELETE CASCADE,
    policy_type_id VARCHAR(50) REFERENCES policy_types(policy_type_id) ON DELETE CASCADE,

    -- Container details
    platform VARCHAR(20) CHECK (platform IN ('docker', 'kubernetes', 'local')) NOT NULL,
    container_name VARCHAR(255),
    endpoint VARCHAR(500) NOT NULL,
    port INTEGER,

    -- Status tracking
    status VARCHAR(20) DEFAULT 'deploying' CHECK (status IN ('deploying', 'running', 'stopped', 'failed', 'unhealthy')),
    health_check_url VARCHAR(500),
    last_health_check TIMESTAMP,
    health_status VARCHAR(20) DEFAULT 'unknown' CHECK (health_status IN ('healthy', 'unhealthy', 'unknown')),
    failure_reason TEXT,

    -- Deployment metadata
    document_hash VARCHAR(64), -- SHA-256 of source policy document
    s3_policy_url VARCHAR(500), -- Original policy document
    s3_jar_url VARCHAR(500), -- Deployed JAR file
    s3_drl_url VARCHAR(500), -- Generated DRL rules
    s3_excel_url VARCHAR(500), -- Excel export of rules

    -- Versioning
    version INTEGER DEFAULT 1,
    is_active BOOLEAN DEFAULT true,

    -- Resource usage (optional)
    cpu_limit VARCHAR(20),
    memory_limit VARCHAR(20),

    -- Timestamps
    deployed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    stopped_at TIMESTAMP,

    -- Ensure only one active container per bank+policy combination
    CONSTRAINT unique_active_container UNIQUE (bank_id, policy_type_id, is_active)
        DEFERRABLE INITIALLY DEFERRED
);

-- Create partial unique index (PostgreSQL doesn't allow WHERE in constraint)
CREATE UNIQUE INDEX idx_unique_active_container
    ON rule_containers(bank_id, policy_type_id)
    WHERE is_active = true;

-- Request tracking for analytics and debugging
CREATE TABLE rule_requests (
    id SERIAL PRIMARY KEY,
    container_id INTEGER REFERENCES rule_containers(id) ON DELETE SET NULL,
    bank_id VARCHAR(50) REFERENCES banks(bank_id) ON DELETE SET NULL,
    policy_type_id VARCHAR(50) REFERENCES policy_types(policy_type_id) ON DELETE SET NULL,

    -- Request details
    request_id UUID DEFAULT uuid_generate_v4(),
    endpoint VARCHAR(255),
    http_method VARCHAR(10),

    -- Payload
    request_payload JSONB,
    response_payload JSONB,

    -- Performance
    execution_time_ms INTEGER,
    status_code INTEGER,
    status VARCHAR(20) CHECK (status IN ('success', 'error', 'timeout')),
    error_message TEXT,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Container deployment history for audit trail
CREATE TABLE container_deployment_history (
    id SERIAL PRIMARY KEY,
    container_id INTEGER REFERENCES rule_containers(id) ON DELETE CASCADE,
    bank_id VARCHAR(50),
    policy_type_id VARCHAR(50),

    -- Deployment details
    action VARCHAR(20) CHECK (action IN ('deployed', 'updated', 'stopped', 'restarted', 'failed')),
    version INTEGER,
    platform VARCHAR(20),
    endpoint VARCHAR(500),

    -- Change tracking
    document_hash VARCHAR(64),
    changes_description TEXT,
    deployed_by VARCHAR(100), -- Could be user ID or system

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX idx_containers_bank_policy ON rule_containers(bank_id, policy_type_id);
CREATE INDEX idx_containers_status ON rule_containers(status);
CREATE INDEX idx_containers_active ON rule_containers(is_active) WHERE is_active = true;
CREATE INDEX idx_containers_health ON rule_containers(health_status);
CREATE INDEX idx_containers_platform ON rule_containers(platform);
CREATE INDEX idx_containers_deployed_at ON rule_containers(deployed_at DESC);

CREATE INDEX idx_requests_container ON rule_requests(container_id);
CREATE INDEX idx_requests_bank ON rule_requests(bank_id);
CREATE INDEX idx_requests_created_at ON rule_requests(created_at DESC);
CREATE INDEX idx_requests_status ON rule_requests(status);

CREATE INDEX idx_history_container ON container_deployment_history(container_id);
CREATE INDEX idx_history_created_at ON container_deployment_history(created_at DESC);

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for automatic timestamp updates
CREATE TRIGGER update_banks_updated_at BEFORE UPDATE ON banks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_policy_types_updated_at BEFORE UPDATE ON policy_types
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_rule_containers_updated_at BEFORE UPDATE ON rule_containers
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Trigger to log deployment history
CREATE OR REPLACE FUNCTION log_container_deployment()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO container_deployment_history (
            container_id, bank_id, policy_type_id, action, version,
            platform, endpoint, document_hash
        ) VALUES (
            NEW.id, NEW.bank_id, NEW.policy_type_id, 'deployed', NEW.version,
            NEW.platform, NEW.endpoint, NEW.document_hash
        );
    ELSIF TG_OP = 'UPDATE' THEN
        IF OLD.status != NEW.status THEN
            INSERT INTO container_deployment_history (
                container_id, bank_id, policy_type_id, action, version,
                platform, endpoint, document_hash
            ) VALUES (
                NEW.id, NEW.bank_id, NEW.policy_type_id,
                CASE
                    WHEN NEW.status = 'stopped' THEN 'stopped'
                    WHEN NEW.status = 'running' AND OLD.status = 'stopped' THEN 'restarted'
                    WHEN NEW.status = 'failed' THEN 'failed'
                    ELSE 'updated'
                END,
                NEW.version, NEW.platform, NEW.endpoint, NEW.document_hash
            );
        END IF;
    END IF;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER log_container_changes AFTER INSERT OR UPDATE ON rule_containers
    FOR EACH ROW EXECUTE FUNCTION log_container_deployment();

-- No sample data inserted - tables start empty
-- Banks, policy types, and containers will be created dynamically through the API

-- Create views for common queries
CREATE OR REPLACE VIEW active_containers AS
SELECT
    rc.id,
    rc.container_id,
    rc.bank_id,
    b.bank_name,
    rc.policy_type_id,
    pt.policy_name,
    rc.platform,
    rc.endpoint,
    rc.port,
    rc.status,
    rc.health_status,
    rc.version,
    rc.deployed_at,
    rc.last_health_check
FROM rule_containers rc
JOIN banks b ON rc.bank_id = b.bank_id
JOIN policy_types pt ON rc.policy_type_id = pt.policy_type_id
WHERE rc.is_active = true
ORDER BY rc.deployed_at DESC;

CREATE OR REPLACE VIEW container_stats AS
SELECT
    rc.container_id,
    rc.bank_id,
    rc.policy_type_id,
    COUNT(rr.id) as total_requests,
    COUNT(CASE WHEN rr.status = 'success' THEN 1 END) as successful_requests,
    COUNT(CASE WHEN rr.status = 'error' THEN 1 END) as failed_requests,
    AVG(rr.execution_time_ms) as avg_execution_time_ms,
    MAX(rr.created_at) as last_request_at
FROM rule_containers rc
LEFT JOIN rule_requests rr ON rc.id = rr.container_id
WHERE rc.is_active = true
GROUP BY rc.container_id, rc.bank_id, rc.policy_type_id;

-- Grant permissions (adjust as needed)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO underwriting_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO underwriting_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO underwriting_user;
