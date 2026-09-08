import { refreshEnterpriseEvents } from './feishu-sync-server.mjs';

const date = process.argv[2] || undefined;
const actorId = process.argv[3] || '1';
const result = await refreshEnterpriseEvents({
  date,
  actorId,
  projectId: 'yuanqu-vr',
  purposes: ['order_table_monitor'],
  discoverGaps: false,
});
console.log(JSON.stringify({
  date: result.date,
  projectId: result.projectId,
  actorId,
  created: (result.created || []).map(item => ({ id: item.id, taskType: item.taskType, actorId: item.actorId, status: item.status, statement: item.statement })),
  totalPending: result.totalPending,
}));
