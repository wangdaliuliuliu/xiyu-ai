import assert from 'node:assert/strict';
import { orderMonitorRowForDate, orderMonitorStatusText, eventForOrderTableMonitor } from './feishu-sync-server.mjs';

const sheet = (values) => ({ headers: ['日期', '今日销售额', '今日票数'], rows: values.map((row, index) => ({ rowNumber: index + 2, values: row })) });

const ready = orderMonitorRowForDate(sheet([['2026-09-07', '1200', '12']]), '2026-09-07');
assert.equal(ready.reason, 'ready');
const zeroIsReady = orderMonitorRowForDate(sheet([['2026-09-07', '0', '0']]), '2026-09-07');
assert.equal(zeroIsReady.reason, 'ready');
const empty = orderMonitorRowForDate(sheet([['2026-09-07', '', '']]), '2026-09-07');
assert.equal(empty.reason, 'metrics_empty');
const missing = orderMonitorRowForDate(sheet([['2026-09-06', '1200', '12']]), '2026-09-07');
assert.equal(missing.reason, 'date_not_found');

assert.match(orderMonitorStatusText({ status: 'complete', date: '2026-09-07', totalSheets: 10, readySheets: 10 }), /10\/10/);
assert.match(orderMonitorStatusText({ status: 'in_progress', date: '2026-09-07', totalSheets: 10, readySheets: 3 }), /3\/10/);
assert.match(orderMonitorStatusText({ status: 'not_started', date: '2026-09-07', totalSheets: 10, readySheets: 0 }), /尚未开始/);

const event = eventForOrderTableMonitor({
  monitor: { status: 'complete', date: '2026-09-07', totalSheets: 10, readySheets: 10, message: '订单系统汇总表已完成更新：10/10 个业务页签均有 2026-09-07 数据。', sourceRevision: 'r1', checkedAt: '2026-09-07T02:00:00.000Z' },
  projectId: 'yuanqu-vr', actorId: 'account-1'
});
assert.equal(event.taskType, 'order_table_monitor');
assert.equal(event.actorId, 'account-1');
assert.equal(event.monitor.status, 'complete');
console.log('order-monitor-smoke: PASS');
