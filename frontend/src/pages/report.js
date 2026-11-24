import { get, post } from '../api/client.js';
import { layout, bindLayout } from '../components/common/layout.js';
import { toast } from '../hooks/useToast.js';
import { escapeHtml, tableShell } from '../components/common/table.js';
import { session } from '../stores/session.js';

const DEPARTMENT = '信息工程学院';
const MONTH = '2026-11';

export async function renderReport() {
  const isAdmin = session.user?.role === 'college_admin';
  const query = `?month=${encodeURIComponent(MONTH)}&department=${encodeURIComponent(DEPARTMENT)}`;
  const [report, roster, accounts] = await Promise.all([
    get(`/reports/monthly${query}`),
    isAdmin ? get(`/reports/roster?department=${encodeURIComponent(DEPARTMENT)}`) : Promise.resolve({ items: [] }),
    isAdmin ? get(`/reports/ta-accounts${query}`) : Promise.resolve({ items: [] }),
  ]);
  const t = report.totals;

  const rosterRows = report.rows.map((r) => `<tr>
    <td><b>${escapeHtml(r.roster_name)}</b><small class="cell-sub">名册编号 ${escapeHtml(r.staff_no)}</small></td>
    <td>${r.accounts.map((a) => `<div class="account-line"><b>${escapeHtml(a.ta_name)}</b><small class="cell-sub">${escapeHtml(a.ta_email || '—')} · ${a.approved_record_count} 笔 / ${Number(a.approved_hours).toFixed(2)} h</small></div>`).join('')}</td>
    <td>${r.approved_record_count} 笔</td>
    <td><b>${Number(r.approved_hours).toFixed(2)} h</b></td>
  </tr>`);

  const suspendedRows = report.suspended.map((r) => `<tr>
    <td><b>${escapeHtml(r.class_code)}</b><small class="cell-sub">${escapeHtml(r.course_name)} · ${escapeHtml(r.work_date)}</small></td>
    <td>${escapeHtml(r.activity_type)}</td>
    <td>${escapeHtml(r.ta_name)}<small class="cell-sub">${escapeHtml(r.ta_email || '—')}</small></td>
    <td><b>${Number(r.validated_hours).toFixed(2)} h</b></td>
    <td><span class="pill pill-manual_review">待认领·挂起</span></td>
  </tr>`);

  const recordRows = report.records.map((r) => {
    const claimed = r.attribution === 'claimed';
    return `<tr>
      <td><b>${escapeHtml(r.class_code)}</b><small class="cell-sub">${escapeHtml(r.work_date)} · ${escapeHtml(r.activity_type)}</small></td>
      <td>${escapeHtml(r.ta_name)}<small class="cell-sub">${escapeHtml(r.ta_email || '—')}</small></td>
      <td>${claimed ? `<b>${escapeHtml(r.roster_name)}</b><small class="cell-sub">名册编号 ${escapeHtml(r.staff_no)}</small>` : '<span class="pill pill-manual_review">未认领 · 挂起</span>'}</td>
      <td><b>${Number(r.validated_hours).toFixed(2)} h</b></td>
    </tr>`;
  });

  const claimRows = accounts.items.map((a) => `<tr>
    <td><b>${escapeHtml(a.name)}</b><small class="cell-sub">${escapeHtml(a.email)}</small></td>
    <td>${a.claim_id ? `<b>${escapeHtml(a.roster_name)}</b><small class="cell-sub">名册编号 ${escapeHtml(a.staff_no)}</small>` : '<span class="muted">未认领</span>'}</td>
    <td>${a.claim_id
      ? `<button class="outline-btn revoke-claim" data-claim="${a.claim_id}" data-version="${a.claim_version}">撤销认领</button>`
      : `<select class="claim-select" data-ta="${a.id}"><option value="">选择名册人员</option>${roster.items.filter((x) => x.status === 'active').map((x) => `<option value="${x.id}">${escapeHtml(x.name)} · ${escapeHtml(x.staff_no)}</option>`).join('')}</select><button class="primary-mini claim-btn" data-ta="${a.id}">认领</button>`}</td>
  </tr>`);

  const blocked = !report.publishable;
  const sheetNote = report.sheet
    ? `<span class="cell-sub">上次发布 ${escapeHtml(report.sheet.published_at || '')} · 归属校验 ${escapeHtml((report.sheet.attribution_hash || '').slice(0, 12))}…${report.sheet.stale ? ' · <b class="conflict">快照已过期，请重新发布</b>' : ''}</span>`
    : '<span class="cell-sub">尚未发布</span>';

  document.getElementById('app').innerHTML = layout('report', `
    <div class="section-bar">
      <div><p class="kicker">FINANCE ROSTER / MONTHLY REPORT</p><h2>按财务名册出账的学院月报</h2><p>同名助教分开计算；同一人的多个校内账号可认领到同一名册人员。未认领的已批工时挂起，清完才能发布。</p></div>
      <div class="report-total"><span>${escapeHtml(MONTH)} 已批合计</span><b>${Number(t.total_approved_hours).toFixed(2)} h</b><small class="cell-sub">已归属 ${Number(t.claimed_hours).toFixed(2)} h · 挂起 ${Number(t.suspended_hours).toFixed(2)} h</small></div>
    </div>

    <div class="metric-grid">
      <div class="metric accent"><span>月报出账（已归属）</span><b>${Number(t.claimed_hours).toFixed(2)}</b><small>${t.claimed_record_count} 笔 · ${t.roster_count} 名名册人员</small></div>
      <div class="metric ${blocked ? 'warning' : ''}"><span>挂起工时</span><b>${Number(t.suspended_hours).toFixed(2)}</b><small>${t.suspended_record_count} 笔未认领</small></div>
      <div class="metric"><span>校内账号</span><b>${t.account_count}</b><small>已认领账号数</small></div>
      <div class="metric"><span>发布状态</span><b>${report.sheet?.status === 'published' ? '已发布' : '待发布'}</b><small>${blocked ? '挂起未清，暂不可发布' : '可发布'}</small></div>
    </div>

    <section class="panel table-panel">
      <div class="panel-head"><div><span class="eyebrow">ROSTER ATTRIBUTION</span><h3>名册出账透视</h3></div><span class="queue-count">按名册编号区分同名人员</span></div>
      ${tableShell(['财务名册人员', '归属的校内账号', '记录数', '出账工时'], rosterRows, '还没有已归属的已批工时')}
      <div class="report-foot">同一名册人员承接同一自然人的多个账号；同名助教靠名册编号分开出账，不按姓名合并。</div>
    </section>

    <div class="split-grid report-split">
      <section class="panel table-panel">
        <div class="panel-head"><div><span class="eyebrow">SUSPENDED QUEUE</span><h3>挂起工时（未认领）</h3></div><span class="queue-count">${t.suspended_record_count} 笔</span></div>
        ${tableShell(['课程班 / 日期', '活动类型', '助教', '工时', '状态'], suspendedRows, '没有挂起工时，可以发布')}
        <div class="report-foot">已审批但未认领到财务名册的工时不会计入任何出账行，也不允许发布。</div>
      </section>
      ${isAdmin ? `<section class="panel table-panel">
        <div class="panel-head"><div><span class="eyebrow">CLAIM MANAGEMENT</span><h3>账号认领</h3></div><span class="queue-count">${t.suspended_record_count ? '有待认领账号' : '全部已认领'}</span></div>
        <form class="roster-form" id="roster-form">
          <input name="name" placeholder="财务名册姓名" required maxlength="80" />
          <input name="staff_no" placeholder="名册编号（区分同名）" required maxlength="40" />
          <button class="primary-mini" type="submit">新增名册人员</button>
        </form>
        ${tableShell(['校内账号', '当前归属', '操作'], claimRows, '没有助教账号')}
        <div class="report-foot">撤销误认领只作用于该条认领；撤销失败后重试不会覆盖后来补认的新归属。</div>
      </section>` : ''}
    </div>

    <section class="panel table-panel">
      <div class="panel-head"><div><span class="eyebrow">RECORD-LEVEL AUDIT</span><h3>逐笔工时归属核对</h3></div><span class="queue-count">${report.records.length} 笔已批工时</span></div>
      ${tableShell(['课程班 / 日期', '助教账号', '归给财务名册', '有效工时'], recordRows, '本月没有已批工时')}
      <div class="report-foot">共 ${report.records.length} 笔已批工时，全部逐笔列出归属；挂起记录同样可见。归属哈希 ${escapeHtml(report.attribution_hash.slice(0, 16))}…</div>
    </section>

    <section class="audit-strip">
      <span class="eyebrow">PUBLISH CONTROL</span>
      <b>${blocked ? `仍有 ${t.suspended_record_count} 笔已批工时未认领，月报已锁定。` : '挂起已清空，可以发布。'}</b>
      <span>发布与认领互斥，整份月报按同一套归属出账。</span>
      ${isAdmin ? `<button class="primary-btn publish-btn" id="publish-report" ${blocked ? 'disabled' : ''}>${blocked ? '挂起未清，暂不可发布' : '发布月报快照'} <span>→</span></button>` : ''}
      ${sheetNote}
    </section>
  `);
  bindLayout();

  if (!isAdmin) return;

  document.getElementById('roster-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    try {
      await post('/reports/roster', {
        department: DEPARTMENT,
        staff_no: String(form.get('staff_no')).trim(),
        name: String(form.get('name')).trim(),
      });
      toast('名册人员已新增', 'success');
      renderReport();
    } catch (err) { toast(err.message, 'error'); }
  });

  document.querySelectorAll('.claim-btn').forEach((btn) => btn.addEventListener('click', async () => {
    const select = document.querySelector(`.claim-select[data-ta="${btn.dataset.ta}"]`);
    if (!select || !select.value) { toast('请先选择财务名册人员', 'error'); return; }
    try {
      await post('/reports/claims', { department: DEPARTMENT, month: MONTH, ta_id: Number(btn.dataset.ta), roster_id: Number(select.value) });
      toast('认领已保存，月报归属已更新', 'success');
      renderReport();
    } catch (e) { toast(e.message, 'error'); }
  }));

  document.querySelectorAll('.revoke-claim').forEach((btn) => btn.addEventListener('click', async () => {
    try {
      const result = await post(`/reports/claims/${btn.dataset.claim}/revoke`, {
        department: DEPARTMENT, month: MONTH,
        expected_version: Number(btn.dataset.version),
        reason: '学院管理员撤销误认领',
      });
      toast(result.status === 'already_revoked' ? '该认领已撤销，无需重复操作' : '认领已撤销', 'info');
      renderReport();
    } catch (e) {
      // 撤销失败：刷新后重试，重试只命中原认领，不会覆盖后来补认的归属。
      toast(`${e.message}，请刷新后重试`, 'error');
      renderReport();
    }
  }));

  document.getElementById('publish-report')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const result = await post('/reports/monthly/publish', { month: MONTH, department: DEPARTMENT });
      toast(`月报已发布，出账 ${Number(result.totals.claimed_hours).toFixed(2)} 小时`, 'success');
      renderReport();
    } catch (e) {
      const detail = e.detail;
      if (detail && typeof detail === 'object') {
        toast(`${detail.message}（挂起 ${detail.suspended_record_count} 笔 / ${Number(detail.suspended_hours).toFixed(2)} h）`, 'error');
      } else {
        toast(e.message, 'error');
      }
      renderReport();
    }
  });
}
