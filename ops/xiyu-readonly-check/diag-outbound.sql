.mode column
.headers on
SELECT id, direction, kind, substr(COALESCE(content,''),1,40) AS txt, created_at
FROM wechat_messages
WHERE direction='out'
ORDER BY created_at DESC LIMIT 8;
SELECT '--- 今日排程 ---' AS x;
SELECT date_key, slot, sent, delivery_outcome, delivery_at
FROM proactive_runtime_schedules
ORDER BY date_key DESC, slot DESC LIMIT 10;
