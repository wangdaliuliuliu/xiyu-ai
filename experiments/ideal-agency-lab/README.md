# 理想链路隔离实验 v2

正式实验入口只有 `v2/cli.py`。它不启动生产主动调度器，不使用真实 Bot 投递凭据，不写生产数据库；每个 run 都是唯一目录，所有失败证据保留。

```powershell
$run = python v2/cli.py freeze --mode FROZEN
python v2/cli.py e0 --run <run-directory>
python v2/cli.py e1 --run <run-directory>
python v2/cli.py deps --run <run-directory>
python v2/cli.py selftest --run <run-directory>
python v2/cli.py e2 --run <run-directory>
python v2/cli.py smoke --run <run-directory>
python v2/cli.py report --run <run-directory>
```

`smoke` 只有在 E0/E1/E2 全部具备资格时才允许 provider 调用；它永远不会向真实 Bot 发送消息。旧 `scripts/lab_*` 与旧 run 仅登记为历史参照，不产生 v2 正式成绩。

当前 run 的完整结论必须以 `report.md` 为准：本地逐值对账、验收器自检和确定性合同可以通过，但缺少已核验线上源身份与 OS/container 隔离时，整体只能是 `inconclusive`。
