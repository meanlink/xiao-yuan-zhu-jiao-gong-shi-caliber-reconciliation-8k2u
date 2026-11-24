from src.db import get_conn, init_db
from src.services.auth_service import ensure_users
from src.security import hash_password

init_db()
ensure_users()

# 演示用额外账号：同名助教、同一人的第二个校内账号、以及未认领账号。
DEMO_TAS = [
    ("ta2@donglan.edu", "林若溪"),   # 与 ta 同一自然人，第二个校内账号
    ("ta3@donglan.edu", "林若溪"),   # 同名不同人，需靠财务名册编号区分
    ("ta4@donglan.edu", "陈知远"),   # 未认领，已批工时会在月报中挂起
]

with get_conn() as conn:
    teacher = conn.execute("SELECT id FROM users WHERE email='teacher@donglan.edu'").fetchone()["id"]
    for email, name in DEMO_TAS:
        conn.execute(
            """INSERT INTO users(email,name,role,password_hash) VALUES (%s,%s,'ta',%s)
               ON CONFLICT(email) DO UPDATE SET name=EXCLUDED.name""",
            (email, name, hash_password("campus123")),
        )
    user_ids = {
        r["email"]: r["id"]
        for r in conn.execute("SELECT id,email FROM users").fetchall()
    }
    ta, ta2, ta3, ta4 = (
        user_ids["ta@donglan.edu"], user_ids["ta2@donglan.edu"],
        user_ids["ta3@donglan.edu"], user_ids["ta4@donglan.edu"],
    )

    conn.execute("""INSERT INTO course_classes(code,course_name,department,term,weekday,start_time,end_time,room,expected_hours,teacher_id)
        VALUES ('CS201-A','数据结构与算法','信息工程学院','2026-秋',1,'09:00','11:00','知行楼 A201',2.0,%s)
        ON CONFLICT(code) DO UPDATE SET teacher_id=EXCLUDED.teacher_id""", (teacher,))
    conn.execute("""INSERT INTO course_classes(code,course_name,department,term,weekday,start_time,end_time,room,expected_hours,teacher_id)
        VALUES ('DS110-B','数据分析导论','信息工程学院','2026-秋',3,'14:00','16:00','知行楼 B305',2.0,%s)
        ON CONFLICT(code) DO UPDATE SET teacher_id=EXCLUDED.teacher_id""", (teacher,))
    conn.execute("""INSERT INTO course_classes(code,course_name,department,term,weekday,start_time,end_time,room,expected_hours,teacher_id)
        VALUES ('EDU305-C','教育测量基础','教育学院','2026-秋',4,'10:00','12:00','博学楼 204',2.0,%s)
        ON CONFLICT(code) DO UPDATE SET teacher_id=EXCLUDED.teacher_id""", (teacher,))
    classes = {r["code"]: r["id"] for r in conn.execute("SELECT id,code FROM course_classes").fetchall()}

    # Stable natural keys keep reruns idempotent while preserving review states.
    seed_rows = [
        (classes["CS201-A"], ta, "2026-11-02", "2026-11-02T09:05:00+00:00", "2026-11-02T10:55:00+00:00", "答疑", "课前习题答疑与课堂签到协助", 1.75, 1.75, "approved", None),
        (classes["DS110-B"], ta, "2026-11-04", "2026-11-04T14:08:00+00:00", "2026-11-04T15:42:00+00:00", "实验辅导", "清洗实验数据并辅导小组作业", 1.5, 1.5, "submitted", None),
        (classes["EDU305-C"], ta, "2026-11-05", "2026-11-05T09:10:00+00:00", "2026-11-05T12:08:00+00:00", "资料整理", "教育测量案例资料整理", 2.5, 0, "manual_review", "checkout_outside_schedule"),
        # 同一自然人的第二个校内账号，认领到同一名册人员。
        (classes["DS110-B"], ta2, "2026-11-11", "2026-11-11T14:03:00+00:00", "2026-11-11T15:50:00+00:00", "实验辅导", "实验课分组辅导与答疑", 1.5, 1.5, "approved", None),
        # 同名不同人，认领到另一条名册记录。
        (classes["CS201-A"], ta3, "2026-11-16", "2026-11-16T09:02:00+00:00", "2026-11-16T10:58:00+00:00", "答疑", "课前习题答疑", 1.75, 1.75, "approved", None),
        # 未认领的已批工时，发布前必须清完。
        (classes["DS110-B"], ta4, "2026-11-18", "2026-11-18T14:05:00+00:00", "2026-11-18T15:50:00+00:00", "资料整理", "教育测量题库整理", 1.75, 1.75, "approved", None),
    ]
    for row in seed_rows:
        conn.execute("""INSERT INTO work_records(class_id,ta_id,work_date,check_in,check_out,activity_type,work_description,reported_hours,validated_hours,status,conflict_type)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(class_id,ta_id,work_date,activity_type) DO NOTHING""", row)

    # 财务名册：同名人员是两条独立记录。
    roster_rows = [
        ("信息工程学院", "F-001", "林若溪"),
        ("信息工程学院", "F-002", "林若溪"),
    ]
    for department, staff_no, name in roster_rows:
        conn.execute(
            """INSERT INTO finance_roster(department,staff_no,name) VALUES (%s,%s,%s)
               ON CONFLICT(department,staff_no) DO UPDATE SET name=EXCLUDED.name, status='active'""",
            (department, staff_no, name),
        )
    roster = {
        r["staff_no"]: r["id"]
        for r in conn.execute("SELECT id,staff_no FROM finance_roster WHERE department='信息工程学院'").fetchall()
    }

    claims = [
        ("信息工程学院", "2026-11", ta, roster["F-001"]),
        ("信息工程学院", "2026-11", ta2, roster["F-001"]),
        ("信息工程学院", "2026-11", ta3, roster["F-002"]),
    ]
    for department, month, ta_id, roster_id in claims:
        exists = conn.execute(
            """SELECT id FROM roster_claims WHERE department=%s AND month=%s
               AND ta_id=%s AND status='active'""",
            (department, month, ta_id),
        ).fetchone()
        if not exists:
            conn.execute(
                """INSERT INTO roster_claims(department,month,ta_id,roster_id,status,version,claimed_at,updated_at)
                   VALUES (%s,%s,%s,%s,'active',1,now(),now())""",
                (department, month, ta_id, roster_id),
            )

print("seed_demo complete: 3 classes, 6 work records, 6 users, 2 roster people, 3 claims")
