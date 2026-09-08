import { upsertEnterpriseProactivePolicy } from '../src/db.mjs';

const accountId = Number(process.argv[2] || 1);
const companionId = Number(process.argv[3] || 1);
const policy = upsertEnterpriseProactivePolicy(accountId, companionId, { order_monitor_enabled: true, order_monitor_time: '10:00' });
console.log(JSON.stringify({ account_id: policy.account_id, companion_id: policy.companion_id, order_monitor_enabled: policy.order_monitor_enabled, order_monitor_time: policy.order_monitor_time }));
