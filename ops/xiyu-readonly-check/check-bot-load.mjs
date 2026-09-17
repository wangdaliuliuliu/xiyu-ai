// 验证 bot.mjs 能正常加载（含新增的 getAgencyIntention 导入）
import('/tmp/xiyu-verify-all/src/bot.mjs')
  .then(() => { console.log('bot.mjs 可加载 OK'); process.exit(0); })
  .catch((e) => { console.log('加载失败: ' + e.message); process.exit(1); });
