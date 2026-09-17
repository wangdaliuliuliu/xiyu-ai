.mode column
.headers on
SELECT id, state,
       ROUND((julianday('now')-julianday(created_at))*24,1) AS age_h,
       ROUND((julianday('now')-julianday(updated_at))*24,1) AS stale_h,
       substr(COALESCE(next_review_condition,''),1,50) AS cond
FROM agency_intentions
WHERE state NOT IN ('completed','expired','abandoned')
ORDER BY created_at DESC;
SELECT '--- 订单表那条 ---' AS x;
SELECT id, state, version, substr(COALESCE(next_review_condition,''),1,80) AS cond
FROM agency_intentions WHERE id='agi_mu2igy2z_78b222d0c75665';
