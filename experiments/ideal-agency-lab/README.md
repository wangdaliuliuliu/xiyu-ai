# 理想链路隔离实验

这套实验不启动生产主动调度器，不使用真实 Bot 投递凭据，也不写生产数据库。它把西宇数据库和工作台运行态复制到 `runs/<timestamp>/snapshot`，对副本做一致性核验，再用已配置的真实对话 API 做最小多轮冒烟。

当前工作站的 Node 原生 SQLite 模块与 Node 24 不兼容，因此数据盘点、对账和冒烟的可执行入口使用 Python 标准库；证据验收器自检仍由 Node 脚本运行。

```powershell
python scripts/lab_discover.py
python scripts/lab_parity.py --run experiments/ideal-agency-lab/runs/<timestamp>
node scripts/lab_selftest.mjs --run experiments/ideal-agency-lab/runs/<timestamp>
python scripts/lab_smoke.py --run experiments/ideal-agency-lab/runs/<timestamp>
python scripts/lab_finalize.py --run experiments/ideal-agency-lab/runs/<timestamp>
```

`lab_smoke.py` 的输出只进入 `sink://ideal-lab`，并且只覆盖规范中的 I01/I03 最小冒烟。它生成的 `report.md` 若为 `inconclusive`，表示前置证据通过但固定 24 族、留出、图片、7 天连续性和人工盲评还没执行，不能当成产品通过。

