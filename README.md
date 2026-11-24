# 校园助教工时口径对账

`campus-ta-hours` 是面向东澜大学教务处的助教工时核算应用。它把课程班排班、签到、助教填报、教师审批和学院月报串成一条可追溯的工时口径链路。

## 真实场景

东澜大学有 6 个学院、约 180 个课程班，每月由助教在共享表格中填报工时，授课教师在邮件中确认，学院教务秘书再手工透视汇总。现有流程的痛点是排班与签到不一致时无法快速定位、不同课程的“有效工时”口径不一致、未审批记录容易被误计入月报。

上游输入是课程排班表、门禁签到和助教工时填报。系统替代排班签到核对、工时口径校验、教师审批和学院月报透视这四段工作。下游消费者是学院教务秘书、教学副院长和财务助学金核算人员。

## 主要功能

- 排班签到：按课程班展示当天排班窗口，登记签到/签退，并对跨时段或缺签记录转人工复核。
- 助教填报：助教提交活动类型、工作说明和自报工时，后端根据签到时长和课程口径计算有效工时。
- 教师审批：教师按课程班查看待审记录，审批、退回或将冲突记录转人工复核。
- 学院月报：按学院、课程班、活动类型、助教四个维度透视汇总，仅纳入已审批工时，可下载 JSON 快照。
- JWT 三角色：`ta` 助教、`teacher` 任课教师、`college_admin` 学院教务管理员。
- 审计与限流：审批、复核、月报发布均写入审计日志，API 对单用户请求进行简单窗口限流。
- 财务名册出账：学院月报按 `finance_roster` 出账，而不是按助教姓名合并。同名助教是两条名册记录，靠 `staff_no` 区分；同一自然人的多个校内账号可以认领到同一名册人员。

## 学院月报的财务名册口径

月报页（`#/report`）把「已批工时 → 财务名册人员」的归属完整展开，供财务逐笔核对。

- 管理员按「学院 + 月份」认领：`POST /reports/claims` 把某个 `ta` 账号归属到一名名册人员；同一账号在同月只能有一条生效认领，改归属需先撤销。
- 未认领的已批工时进入**挂起清单**，不计入任何出账行；只要还有挂起，`POST /reports/monthly/publish` 返回 `409` 并列出挂起明细，清完才能发布。
- 撤销误认领用 `POST /reports/claims/{claim_id}/revoke`，按 `claim_id` 精确定位，可带 `expected_version` 做乐观校验。撤销失败后重试只会命中这条原认领（返回 `already_revoked`），不会覆盖之后补认的新归属。
- 认领变更与发布都对 `(department, month)` 取事务级 advisory lock，因此整份月报始终按同一套归属出账，不会出现一半旧、一半新的快照。
- 月报响应含 `records`（逐笔已批工时的归属，含挂起）、`suspended`（挂起清单）、`totals`、`attribution_hash`；发布快照同时保存归属哈希与挂起/认领清单，便于事后比对。助教调用时自动去掉账号邮箱等明细。

## 主流程与异常分支

主流程为 `签到 → 工时填报 → 教师审核 → 学院透视月报`。

- 签到时间必须落在课程排班窗口前后 30 分钟的容差内，且签到日期必须与课程排班星期匹配。
- 签到与排班冲突时，记录状态为 `manual_review`，教师不能直接审批，必须由学院管理员复核后再进入审批。
- 未审核工时的 `validated_hours` 不计入学院月报。
- 课程班月报只能由学院管理员生成，发布前会重新按数据库中的 `approved` 记录与认领归属计算。

## 演示账号

密码统一为 `campus123`。

| 邮箱 | 角色 | 典型权限 |
|---|---|---|
| `ta@donglan.edu` | 助教 `ta` | 查看课程班、签到、创建和提交自己的工时填报 |
| `teacher@donglan.edu` | 教师 `teacher` | 查看所授课程班、审批或退回工时、处理待复核记录 |
| `admin@donglan.edu` | 学院管理员 `college_admin` | 维护排班、人工复核冲突、认领财务名册、生成和发布学院月报 |

演示数据额外包含 `ta2@donglan.edu`（与 `ta` 同一自然人的第二个校内账号）、`ta3@donglan.edu`（同名不同人）和 `ta4@donglan.edu`（未认领，制造挂起）。财务名册 `F-001`/`F-002` 是两条同名记录。

## 技术栈与服务

| 服务 | 技术 | 责任 |
|---|---|---|
| frontend | Nginx + 原生 HTML/CSS/JS | 页面、导航和 API 交互 |
| backend | Python 3.12 + FastAPI + psycopg | JWT、领域规则、工时校验、透视汇总 |
| worker | Python 3.12 | 共享卷心跳，模拟月报异步任务存活 |
| db | PostgreSQL 16 | 领域数据与审计日志 |
| redis | Redis 7 | 限流计数与缓存心跳 |

## 快速启动

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```

前端访问 `http://localhost:18254`，后端文档访问 `http://localhost:19254/docs`。

停止并清理测试数据：

```bash
docker compose down -v --remove-orphans
```

## 目录说明

- `backend/src/models` 领域表结构与数据库初始化
- `backend/migrations` 表结构迁移（`002_finance_roster.sql` 引入财务名册与月度认领）
- `backend/src/services` 工时校验、财务名册归属、审计和认证
- `backend/src/routes` 认证、课程班、工时记录、月报与认领接口
- `frontend/src/pages` 业务页面（`report.js` 为财务名册出账月报）
- `backend/scripts/seed_demo.py` 幂等演示数据

## 共享枚举出现位置

- `WorkRecordStatus` 出现在 `backend/src/constants/enums.py`、`backend/src/schemas/work_records.py`、`frontend/src/constants/enums.js`。
- `UserRole` 出现在 `backend/src/constants/enums.py`、`backend/src/schemas/auth.py`、`frontend/src/constants/enums.js`。
- `ApprovalSheetStatus` 出现在 `backend/src/constants/enums.py`、`backend/src/schemas/reports.py`、`frontend/src/constants/enums.js`。

## 复现算法

工时有效值由 `min(签到签退实际分钟 / 60, 助教填报小时, 课程班单次口径上限)` 计算，四舍五入到 0.25 小时。排班冲突条件、缺签条件和有效小时口径写在 `backend/src/services/hour_policy.py`。财务名册归属、挂起判定与快照哈希写在 `backend/src/services/roster.py`：已批工时按认领映射到 `finance_roster`，未认领进入挂起；`attribution_hash` 由每笔 `(record_id, roster_id, claim_id, claim_version)` 计算，发布快照与页面核对共用同一份哈希。

## License

Internal demo for the Solo evaluation workspace.
