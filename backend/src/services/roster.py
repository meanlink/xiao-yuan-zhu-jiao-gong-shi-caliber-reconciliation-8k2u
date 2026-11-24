"""财务名册归属。

学院月报不再按助教姓名合并，而是按财务名册人员出账：
- 每个（学院、月份）下，校内账号通过 roster_claims 认领到一条财务名册；
- 同一名册可以承接同一自然人的多个校内账号；
- 同名但不同名册人员（不同 staff_no）分别成行；
- 未认领的已批工时进入挂起清单，清完之前整份月报不能发布。

并发约定：认领的增删与月报发布都先获取 (department, month) 的事务级
advisory lock，因此发布读到的记录与归属来自同一套认领快照。
"""
from decimal import Decimal
import hashlib
import json

ATTRIBUTION_RECORDS_SQL = """
SELECT w.id AS record_id, w.work_date, w.activity_type, w.validated_hours,
       c.code AS class_code, c.course_name, c.department,
       ta.id AS ta_id, ta.name AS ta_name, ta.email AS ta_email
FROM work_records w
JOIN course_classes c ON c.id = w.class_id
JOIN users ta ON ta.id = w.ta_id
WHERE c.department = %s
  AND w.status = 'approved'
  AND w.work_date >= (%s || '-01')::date
  AND w.work_date < ((%s || '-01')::date + interval '1 month')
ORDER BY c.code, w.work_date, w.id
"""

ACTIVE_CLAIMS_SQL = """
SELECT rc.id AS claim_id, rc.ta_id, rc.roster_id, rc.version,
       r.staff_no, r.name AS roster_name, r.status AS roster_status
FROM roster_claims rc
JOIN finance_roster r ON r.id = rc.roster_id
WHERE rc.department = %s AND rc.month = %s AND rc.status = 'active'
ORDER BY rc.id
"""


def month_lock_key(department: str, month: str) -> str:
    return f"campus-ta-hours:monthly-report:{department}:{month}"


def lock_month(conn, department: str, month: str) -> None:
    """事务级锁：同一学院同一月份的认领变更与发布串行化。"""
    conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (month_lock_key(department, month),))


def _hours(value) -> Decimal:
    return Decimal(str(value or 0))


def compute_attribution(records: list[dict], claims: list[dict]) -> dict:
    """把已批工时逐条归属到名册人员；没有生效认领的记录进入挂起清单。"""
    claim_by_ta = {int(c["ta_id"]): c for c in claims}
    groups: dict[int, dict] = {}
    accounts: dict[tuple[int, int], dict] = {}
    suspended: list[dict] = []
    record_rows: list[dict] = []
    claimed_hours = Decimal("0")
    suspended_hours = Decimal("0")

    for raw in records:
        hours = _hours(raw["validated_hours"])
        claim = claim_by_ta.get(int(raw["ta_id"]))
        record_row = {
            "record_id": int(raw["record_id"]),
            "work_date": str(raw["work_date"]),
            "activity_type": raw["activity_type"],
            "validated_hours": float(hours),
            "class_code": raw["class_code"],
            "course_name": raw["course_name"],
            "ta_id": int(raw["ta_id"]),
            "ta_name": raw["ta_name"],
            "ta_email": raw["ta_email"],
            "attribution": "suspended",
            "roster_id": None,
            "staff_no": None,
            "roster_name": None,
            "claim_id": None,
            "claim_version": None,
        }
        if claim:
            roster_id = int(claim["roster_id"])
            group = groups.get(roster_id)
            if group is None:
                group = groups[roster_id] = {
                    "roster_id": roster_id,
                    "staff_no": claim["staff_no"],
                    "roster_name": claim["roster_name"],
                    "roster_status": claim["roster_status"],
                    "approved_hours": Decimal("0"),
                    "approved_record_count": 0,
                    "accounts": [],
                    "record_ids": [],
                }
            group["approved_hours"] += hours
            group["approved_record_count"] += 1
            group["record_ids"].append(int(raw["record_id"]))

            account_key = (roster_id, int(raw["ta_id"]))
            account = accounts.get(account_key)
            if account is None:
                account = accounts[account_key] = {
                    "ta_id": int(raw["ta_id"]),
                    "ta_name": raw["ta_name"],
                    "ta_email": raw["ta_email"],
                    "claim_id": int(claim["claim_id"]),
                    "claim_version": int(claim["version"]),
                    "approved_hours": Decimal("0"),
                    "approved_record_count": 0,
                }
                group["accounts"].append(account)
            account["approved_hours"] += hours
            account["approved_record_count"] += 1

            record_row.update({
                "attribution": "claimed",
                "roster_id": roster_id,
                "staff_no": claim["staff_no"],
                "roster_name": claim["roster_name"],
                "claim_id": int(claim["claim_id"]),
                "claim_version": int(claim["version"]),
            })
            claimed_hours += hours
        else:
            suspended.append(record_row)
            suspended_hours += hours
        record_rows.append(record_row)

    rows = []
    for group in groups.values():
        for account in group["accounts"]:
            account["approved_hours"] = float(account["approved_hours"])
        group["approved_hours"] = float(group["approved_hours"])
        group["accounts"].sort(key=lambda a: (a["ta_name"], a["ta_id"]))
        rows.append(group)

    # 同名助教靠 roster_id / staff_no 分开，绝不按姓名合并。
    rows.sort(key=lambda g: (g["roster_name"], g["staff_no"]))

    attribution_fingerprint = [
        [r["record_id"], r["roster_id"], r["claim_id"], r["claim_version"]]
        for r in record_rows
    ]
    attribution_hash = hashlib.sha256(
        json.dumps(attribution_fingerprint, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return {
        "rows": rows,
        "suspended": suspended,
        "records": record_rows,
        "totals": {
            "total_approved_hours": float(claimed_hours + suspended_hours),
            "claimed_hours": float(claimed_hours),
            "suspended_hours": float(suspended_hours),
            "approved_record_count": len(record_rows),
            "claimed_record_count": len(record_rows) - len(suspended),
            "suspended_record_count": len(suspended),
            "roster_count": len(rows),
            "account_count": len(accounts),
        },
        "attribution_hash": attribution_hash,
    }


def load_attribution(conn, department: str, month: str) -> dict:
    """在调用方的事务内读取记录与生效认领，保证两者来自同一快照。"""
    records = conn.execute(
        ATTRIBUTION_RECORDS_SQL, (department, month, month)
    ).fetchall()
    claims = conn.execute(ACTIVE_CLAIMS_SQL, (department, month)).fetchall()
    return compute_attribution([dict(r) for r in records], [dict(c) for c in claims])


def claims_snapshot(conn, department: str, month: str) -> list[dict]:
    rows = conn.execute(
        """SELECT rc.id, rc.ta_id, rc.roster_id, rc.version, rc.status,
                  rc.claimed_by, rc.claimed_at, rc.revoked_at,
                  u.name AS ta_name, u.email AS ta_email,
                  r.staff_no, r.name AS roster_name
           FROM roster_claims rc
           JOIN users u ON u.id = rc.ta_id
           JOIN finance_roster r ON r.id = rc.roster_id
           WHERE rc.department = %s AND rc.month = %s
           ORDER BY rc.id""",
        (department, month),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        for key in ("claimed_at", "revoked_at"):
            item[key] = item[key].isoformat() if item[key] else None
        result.append(item)
    return result
