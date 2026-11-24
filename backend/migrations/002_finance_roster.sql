-- 财务名册与月度认领：学院月报按财务名册人员出账，而不是按助教姓名合并。
CREATE TABLE IF NOT EXISTS finance_roster (
  id SERIAL PRIMARY KEY,
  department TEXT NOT NULL,
  staff_no TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (department, staff_no)
);

-- 同名人员是两条名册记录，靠 staff_no 区分；姓名不做唯一约束。
CREATE INDEX IF NOT EXISTS finance_roster_department_idx
  ON finance_roster(department, status, name);

CREATE TABLE IF NOT EXISTS roster_claims (
  id SERIAL PRIMARY KEY,
  department TEXT NOT NULL,
  month TEXT NOT NULL CHECK (month ~ '^[0-9]{4}-[0-9]{2}$'),
  ta_id INTEGER NOT NULL REFERENCES users(id),
  roster_id INTEGER NOT NULL REFERENCES finance_roster(id),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
  version INTEGER NOT NULL DEFAULT 1,
  claimed_by INTEGER REFERENCES users(id),
  claimed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_by INTEGER REFERENCES users(id),
  revoked_at TIMESTAMPTZ,
  revoke_reason TEXT
);

-- 一个校内账号在同一学院、同一月份只能有一个生效认领；
-- 同一名册人员可以承接同一人的多个校内账号，因此不对 roster_id 做唯一约束。
CREATE UNIQUE INDEX IF NOT EXISTS roster_claim_active_account_uniq
  ON roster_claims(department, month, ta_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS roster_claim_month_idx
  ON roster_claims(department, month, status);

-- 发布快照额外保存归属哈希、挂起清单与认领快照，便于财务事后核对。
ALTER TABLE approval_sheets ADD COLUMN IF NOT EXISTS attribution_hash TEXT;
ALTER TABLE approval_sheets ADD COLUMN IF NOT EXISTS suspended_json JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE approval_sheets ADD COLUMN IF NOT EXISTS claims_json JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS work_records_approved_month_idx
  ON work_records(work_date) WHERE status = 'approved';
