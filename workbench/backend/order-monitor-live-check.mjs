import { checkOrderTableMonitor } from './feishu-sync-server.mjs';

const date = process.argv[2] || undefined;
const actorId = process.argv[3] || '1';
const result = await checkOrderTableMonitor({ date, actorId, projectId: 'yuanqu-vr' });
console.log(JSON.stringify({ date: result.date, actorId: result.actorId, status: result.status, totalSheets: result.totalSheets, readySheets: result.readySheets, dateRows: result.dateRows, missingSheets: result.missingSheets, incompleteSheets: result.incompleteSheets, error: result.error || '' }));
