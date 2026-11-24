import { get, post } from '../api/client.js';
import { layout, bindLayout } from '../components/common/layout.js';
import { statusPill } from '../components/common/status.js';
import { toast } from '../hooks/useToast.js';
import { escapeHtml, tableShell } from '../components/common/table.js';
import { session } from '../stores/session.js';

export async function renderReview() {
  const isAdmin = session.user?.role === 'college_admin';
  const [records, report] = await Promise.all([
    get('/work-records'),
    get('/reports/monthly?month=2026-11&department=信息工程学院'),
  ]);
  const rows = records.items.map((r) => `<tr><td><b>${escapeHtml(r.class_code)}</b><small class="cell-sub">${escapeHtml(r.ta_name)} · ${escapeHtml(r.work_date)}</small></td><td>${escapeHtml(r.activity_type)}<small class="cell-sub">有效 ${r.validated_hours} h</small></td><td>${statusPill(r.status)}${r.conflict_type ? `<small class="cell-sub conflict">${escapeHtml(r.conflict_type)}</small>` : ''}</td><td>${r.status === 'manual_review' && isAdmin ? `<button class="outline-btn resolve" data-id="${r.id}">学院复核</button>` : r.status === 'submitted' ? `<button class="primary-mini approve" data-id="${r.id}">教师审批</button>` : '<span class="muted">已处理</span>'}</td></tr>`);
  const reportRows = report.rows.slice(0, 8).map((r) => `<tr><td><b>${escapeHtml(r.roster_name)}</b><small class="cell-sub">名册编号 ${escapeHtml(r.staff_no)}</small></td><td>${r.approved_record_count} 笔</td><td><b>${Number(r.approved_hours).toFixed(2)} h</b></td></tr>`);
  const suspended = report.totals.suspended_record_count;
  document.getElementById('app').innerHTML = layout('review', `<div class="section-bar"><div><p class="kicker">REVIEW / MONTHLY PIVOT</p><h2>教师审批与学院月报</h2><p>审批队列与月报透视共用同一条工时状态链路；月报按财务名册出账。</p></div><div class="report-total"><span>11 月已批合计</span><b>${Number(report.total_approved_hours).toFixed(2)} h</b><small class="cell-sub">挂起 ${suspended} 笔</small></div></div><div class="review-grid"><section class="panel table-panel"><div class="panel-head"><div><span class="eyebrow">REVIEW QUEUE</span><h3>待处理记录</h3></div><span class="queue-count">${records.items.filter((r) => ['submitted','manual_review'].includes(r.status)).length} 条</span></div>${tableShell(['课程班 / 助教','活动 / 有效工时','状态','动作'], rows, '审批队列为空')}</section><section class="panel table-panel report-panel"><div class="panel-head"><div><span class="eyebrow">ROSTER PIVOT / 2026-11</span><h3>信息工程学院月报</h3></div><button class="primary-mini" id="publish-report">发布快照</button></div>${tableShell(['财务名册人员','记录数','出账工时'], reportRows, '暂无已归属的已批工时')}<div class="report-foot">透视维度：财务名册人员 × 校内账号；同名助教分开出账。<a class="text-link" href="#/report">查看逐笔归属与认领 →</a></div></section></div><section class="audit-strip"><span class="eyebrow">CONTROL NOTE</span><b>${suspended ? `仍有 ${suspended} 笔已批工时未认领，月报暂不可发布。` : '未审核工时不会出现在月报合计。'}</b><span>发布时后端重新读取 approved 状态与认领归属，避免前端缓存造成误计。</span></section>`);
  bindLayout();
  document.querySelectorAll('.approve').forEach((b) => b.addEventListener('click', async () => {
    try { await post(`/work-records/${b.dataset.id}/review`, { note: '任课教师核对签到与工作说明' }); toast('已审批，记录进入月报', 'success'); renderReview(); } catch (e) { toast(e.message, 'error'); }
  }));
  document.querySelectorAll('.resolve').forEach((b) => b.addEventListener('click', async () => {
    try { await post(`/work-records/${b.dataset.id}/resolve-conflict`, { note: '学院管理员核对排班后转教师审批' }); toast('冲突已解除，等待教师审批', 'success'); renderReview(); } catch (e) { toast(e.message, 'error'); }
  }));
  document.getElementById('publish-report').addEventListener('click', async () => {
    try {
      const result = await post('/reports/monthly/publish', { month: '2026-11', department: '信息工程学院' });
      toast(`月报已发布，出账 ${Number(result.totals.claimed_hours).toFixed(2)} 小时`, 'success');
    } catch (e) {
      const detail = e.detail;
      if (detail && typeof detail === 'object') toast(`${detail.message}（挂起 ${detail.suspended_record_count} 笔）`, 'error');
      else toast(e.message, 'error');
    }
  });
}
