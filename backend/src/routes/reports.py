import json
import psycopg
from fastapi import APIRouter, Depends, HTTPException
from ..db import get_conn
from ..schemas.reports import (
    ReportRequest,
    RosterCreate,
    ClaimRequest,
    ClaimRevokeRequest,
)
from ..services.roster import (
    load_attribution,
    lock_month,
    claims_snapshot,
)
from ..services.audit import record_audit
from .deps import require_roles

router = APIRouter(prefix="/reports", tags=["reports"])


def _sheet(conn, department: str, month: str):
    row = conn.execute(
        """SELECT status, totals_json, attribution_hash, published_at, approved_by
           FROM approval_sheets WHERE department=%s AND month=%s""",
        (department, month),
    ).fetchone()
    if not row:
        return None
    return {
        "status": row["status"],
        "total_approved_hours": float((row["totals_json"] or {}).get("total_approved_hours", 0)),
        "attribution_hash": row["attribution_hash"],
        "published_at": row["published_at"].isoformat() if row["published_at"] else None,
        "approved_by": row["approved_by"],
    }


def _mark_sheet_status(sheet: dict | None, live_hash: str) -> dict | None:
    """发布后归属变化时提示快照已过期，避免财务用旧快照对账。"""
    if not sheet:
        return None
    sheet["stale"] = bool(sheet["attribution_hash"]) and sheet["attribution_hash"] != live_hash
    return sheet


def _serialize_suspended(rows: list[dict]) -> list[dict]:
    return [
        {
            "record_id": r["record_id"],
            "work_date": str(r["work_date"]),
            "activity_type": r["activity_type"],
            "validated_hours": r["validated_hours"],
            "class_code": r["class_code"],
            "course_name": r["course_name"],
            "ta_id": r["ta_id"],
            "ta_name": r["ta_name"],
            "ta_email": r["ta_email"],
        }
        for r in rows
    ]


@router.get("/roster")
def list_roster(department: str = "信息工程学院",
                user=Depends(require_roles("teacher", "college_admin"))):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, department, staff_no, name, status, created_at, updated_at
               FROM finance_roster WHERE department=%s ORDER BY name, staff_no""",
            (department,),
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.post("/roster")
def create_roster(payload: RosterCreate, user=Depends(require_roles("college_admin"))):
    try:
        with get_conn() as conn:
            row = conn.execute(
                """INSERT INTO finance_roster(department, staff_no, name)
                   VALUES (%s,%s,%s)
                   ON CONFLICT(department, staff_no) DO UPDATE
                     SET name=EXCLUDED.name, status='active', updated_at=now()
                   RETURNING id, department, staff_no, name, status""",
                (payload.department, payload.staff_no.strip(), payload.name.strip()),
            ).fetchone()
    except psycopg.Error:
        raise HTTPException(status_code=409, detail="财务名册写入失败，请检查编号是否重复")
    record_audit(user["id"], "finance_roster_upserted", "finance_roster", row["id"],
                 {"department": payload.department, "staff_no": payload.staff_no})
    return dict(row)


@router.get("/ta-accounts")
def ta_accounts(department: str = "信息工程学院", month: str = "2026-11",
                user=Depends(require_roles("college_admin"))):
    """学院管理员认领时使用：列出全部助教账号及本月当前归属。"""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT u.id, u.name, u.email,
                      rc.id AS claim_id, rc.version AS claim_version,
                      rc.status AS claim_status, rc.roster_id,
                      r.staff_no, r.name AS roster_name
               FROM users u
               LEFT JOIN roster_claims rc
                 ON rc.ta_id = u.id AND rc.department = %s AND rc.month = %s
                AND rc.status = 'active'
               LEFT JOIN finance_roster r ON r.id = rc.roster_id
               WHERE u.role = 'ta'
               ORDER BY u.name, u.id""",
            (department, month),
        ).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.get("/claims")
def list_claims(department: str = "信息工程学院", month: str = "2026-11",
                user=Depends(require_roles("college_admin"))):
    with get_conn() as conn:
        return {"items": claims_snapshot(conn, department, month)}


@router.post("/claims")
def claim_account(payload: ClaimRequest, user=Depends(require_roles("college_admin"))):
    """把某个校内账号在某月归属到一名财务名册人员。"""
    with get_conn() as conn:
        lock_month(conn, payload.department, payload.month)

        ta = conn.execute(
            "SELECT id, name, email, role FROM users WHERE id=%s", (payload.ta_id,)
        ).fetchone()
        if not ta or ta["role"] != "ta":
            raise HTTPException(status_code=404, detail="助教账号不存在")

        roster = conn.execute(
            "SELECT id, name, staff_no, status FROM finance_roster WHERE id=%s AND department=%s",
            (payload.roster_id, payload.department),
        ).fetchone()
        if not roster:
            raise HTTPException(status_code=404, detail="财务名册人员不存在")
        if roster["status"] != "active":
            raise HTTPException(status_code=409, detail="该名册人员已停用，不能继续认领")

        # 名册人员归属的学院由其部门确定；不允许把 A 学院的账号认领到 B 学院名册。
        existing = conn.execute(
            """SELECT id, roster_id, version FROM roster_claims
               WHERE department=%s AND month=%s AND ta_id=%s AND status='active'""",
            (payload.department, payload.month, payload.ta_id),
        ).fetchone()
        if existing:
            if int(existing["roster_id"]) == payload.roster_id:
                # 幂等：重复提交同一归属直接返回原认领。
                return {"id": existing["id"], "status": "active", "idempotent": True,
                        "version": existing["version"]}
            conflict = conn.execute(
                """SELECT r.name AS roster_name, r.staff_no FROM finance_roster r
                   WHERE r.id=%s""", (existing["roster_id"],)
            ).fetchone()
            raise HTTPException(
                status_code=409,
                detail=(
                    f"该账号本月已认领给 {conflict['roster_name']}（{conflict['staff_no']}），"
                    "请先撤销原认领再重新归属"
                ),
            )

        row = conn.execute(
            """INSERT INTO roster_claims(department, month, ta_id, roster_id, status,
                                         version, claimed_by, claimed_at, updated_at)
               VALUES (%s,%s,%s,%s,'active',1,%s,now(),now())
               RETURNING id, version""",
            (payload.department, payload.month, payload.ta_id, payload.roster_id, user["id"]),
        ).fetchone()
    record_audit(user["id"], "roster_claim_created", "roster_claim", row["id"], {
        "department": payload.department, "month": payload.month,
        "ta_id": payload.ta_id, "roster_id": payload.roster_id,
        "staff_no": roster["staff_no"], "ta_name": ta["name"],
    })
    return {"id": row["id"], "status": "active", "version": row["version"],
            "ta_id": payload.ta_id, "roster_id": payload.roster_id,
            "roster_name": roster["name"], "staff_no": roster["staff_no"]}


@router.post("/claims/{claim_id}/revoke")
def revoke_claim(claim_id: int, payload: ClaimRevokeRequest,
                 user=Depends(require_roles("college_admin"))):
    """撤销误认领。

    以 claim_id 精确定位，重试同一撤销请求只会命中原认领：
    若原认领已撤销则直接返回 already_revoked，不会波及之后补认的归属。
    """
    with get_conn() as conn:
        lock_month(conn, payload.department, payload.month)

        claim = conn.execute(
            """SELECT id, department, month, ta_id, roster_id, status, version
               FROM roster_claims WHERE id=%s""",
            (claim_id,),
        ).fetchone()
        if not claim or claim["department"] != payload.department or claim["month"] != payload.month:
            raise HTTPException(status_code=404, detail="认领记录不存在")

        if claim["status"] == "revoked":
            return {"id": claim_id, "status": "already_revoked",
                    "version": claim["version"], "idempotent": True}

        if payload.expected_version is not None and claim["version"] != payload.expected_version:
            raise HTTPException(status_code=409, detail="认领已被更新，请刷新后再撤销")

        row = conn.execute(
            """UPDATE roster_claims
               SET status='revoked', revoked_by=%s, revoked_at=now(), updated_at=now(),
                   revoke_reason=%s, version=version+1
               WHERE id=%s AND status='active'
               RETURNING id, version""",
            (user["id"], payload.reason or "学院管理员撤销误认领", claim_id),
        ).fetchone()
        if not row:
            # 并发下已被撤销：同样按幂等处理，绝不触碰其他认领。
            current = conn.execute(
                "SELECT version FROM roster_claims WHERE id=%s", (claim_id,)
            ).fetchone()
            return {"id": claim_id, "status": "already_revoked",
                    "version": current["version"], "idempotent": True}
    record_audit(user["id"], "roster_claim_revoked", "roster_claim", claim_id, {
        "department": payload.department, "month": payload.month,
        "ta_id": claim["ta_id"], "roster_id": claim["roster_id"],
        "reason": payload.reason,
    })
    return {"id": claim_id, "status": "revoked", "version": row["version"]}


def _report_payload(conn, department: str, month: str, include_details: bool = True) -> dict:
    attribution = load_attribution(conn, department, month)
    sheet = _mark_sheet_status(_sheet(conn, department, month), attribution["attribution_hash"])
    totals = attribution["totals"]
    payload = {
        "month": month,
        "department": department,
        "rows": attribution["rows"],
        "suspended": _serialize_suspended(attribution["suspended"]),
        "totals": totals,
        "total_approved_hours": totals["total_approved_hours"],
        "row_count": len(attribution["rows"]),
        "attribution_hash": attribution["attribution_hash"],
        "sheet": sheet,
        "publishable": totals["suspended_record_count"] == 0,
        "publish_blocked_reason": (
            None if totals["suspended_record_count"] == 0
            else f"仍有 {totals['suspended_record_count']} 笔已批工时未认领，清完才能发布"
        ),
    }
    if include_details:
        # 逐笔明细与认领快照含账号邮箱，只向教师与学院管理员开放。
        payload["records"] = attribution["records"]
        payload["claims"] = claims_snapshot(conn, department, month)
        return payload

    for row in payload["rows"]:
        for account in row["accounts"]:
            account.pop("ta_email", None)
    for item in payload["suspended"]:
        item.pop("ta_email", None)
    payload["records"] = [
        {k: v for k, v in r.items() if k != "ta_email"} for r in attribution["records"]
    ]
    payload["claims"] = []
    return payload


@router.get("/monthly")
def monthly_report(month: str = "2026-11", department: str = "信息工程学院",
                   user=Depends(require_roles("teacher", "college_admin", "ta"))):
    # 记录与认领取同一快照，页面核对时不会出现“记录读了新、归属读了旧”。
    with get_conn(isolation_level="REPEATABLE READ") as conn:
        return _report_payload(conn, department, month,
                               include_details=user["role"] != "ta")


@router.post("/monthly/publish")
def publish_report(payload: ReportRequest, user=Depends(require_roles("college_admin"))):
    with get_conn() as conn:
        # 与认领变更互斥：整份月报要么全用旧归属，要么全用新归属。
        lock_month(conn, payload.department, payload.month)
        report = _report_payload(conn, payload.department, payload.month)
        if not report["publishable"]:
            suspended = report["suspended"]
            raise HTTPException(
                status_code=409,
                detail={
                    "message": report["publish_blocked_reason"],
                    "suspended_record_count": report["totals"]["suspended_record_count"],
                    "suspended_hours": report["totals"]["suspended_hours"],
                    "suspended": suspended,
                },
            )

        snapshot_totals = {
            **report["totals"],
            "rows": report["rows"],
        }
        conn.execute(
            """INSERT INTO approval_sheets(department, month, status, totals_json,
                   approved_by, published_at, attribution_hash, suspended_json, claims_json)
               VALUES (%s,%s,'published',%s,%s,now(),%s,%s,%s)
               ON CONFLICT(department,month) DO UPDATE SET
                 status='published', totals_json=EXCLUDED.totals_json,
                 approved_by=EXCLUDED.approved_by, published_at=now(),
                 attribution_hash=EXCLUDED.attribution_hash,
                 suspended_json=EXCLUDED.suspended_json,
                 claims_json=EXCLUDED.claims_json""",
            (
                payload.department, payload.month,
                json.dumps(snapshot_totals, ensure_ascii=False, default=str),
                user["id"], report["attribution_hash"],
                json.dumps(report["suspended"], ensure_ascii=False, default=str),
                json.dumps(report["claims"], ensure_ascii=False, default=str),
            ),
        )
    record_audit(user["id"], "monthly_report_published", "approval_sheet", None, {
        "department": payload.department, "month": payload.month,
        "total_approved_hours": report["totals"]["total_approved_hours"],
        "claimed_hours": report["totals"]["claimed_hours"],
        "roster_count": report["totals"]["roster_count"],
        "attribution_hash": report["attribution_hash"],
    })
    return {
        "status": "published",
        "department": payload.department,
        "month": payload.month,
        "attribution_hash": report["attribution_hash"],
        **report,
    }
