# 理想链路隔离实验 v2

正式实验入口只有 `v2/cli.py`。它不启动生产主动调度器，不使用真实 Bot 投递凭据，不写生产数据库；每个 run 都是唯一目录，所有失败证据保留。

```powershell
$run = python v2/cli.py freeze --mode FROZEN
python v2/cli.py preflight --run <run-directory>
python v2/cli.py e0 --run <run-directory>
python v2/cli.py e1 --run <run-directory>
python v2/cli.py deps --run <run-directory>
python v2/cli.py context --run <run-directory>
python v2/cli.py roundtrip --run <run-directory>
python v2/cli.py selftest --run <run-directory>
python v2/cli.py e2 --run <run-directory>
python v2/cli.py mutations --run <run-directory>
python v2/cli.py gate-selftest --run <run-directory>  # 合格/不合格证据两条路径；不调用 provider
python v2/cli.py provider-audit --run <run-directory>  # 只读核查 provider/部署资料
python v2/cli.py source-runtime-audit --run <run-directory> --url https://xiyu.myworlds.cn/api/health  # 只读 GET，不发送凭据
python v2/cli.py submit-evidence --run <run-directory> --evidence <evidence.json>
python v2/cli.py validate-evidence --run <run-directory>  # 校验 hash/事实并生成放行 scope
python v2/cli.py report --run <run-directory>  # 冻结版本和证据门禁均已校验后再进入 suite
python v2/cli.py run --suite smoke --run <run-directory>
python v2/cli.py run --suite fixed --run <run-directory>
python v2/cli.py run --suite reliability --run <run-directory>
python v2/cli.py run --suite integration --run <run-directory>
python v2/cli.py run --suite holdout --run <run-directory>
python v2/cli.py run --suite media --run <run-directory> --endpoint <model-endpoint> --image-endpoint <image-endpoint> --image-model <image-model>
python v2/cli.py run --suite continuity --run <run-directory> --endpoint <model-endpoint>
python v2/cli.py run --suite performance --run <run-directory> --endpoint <model-endpoint> --image-endpoint <image-endpoint> --image-model <image-model>
python v2/cli.py run --suite prompt_pairing --run <run-directory> --endpoint <model-endpoint>
python v2/cli.py report --run <run-directory>
```

证据包必须是 `ideal-agency-gate-evidence-v1` JSON：顶层含 `runId/submissionId/submittedAt/issuer/artifacts/claims`；每个 `verified` claim 都要有 `observed_at`、`verification_method`、`artifact_ids` 和对应事实字段，artifact 需提供本地文件 `path` 与 SHA-256。禁止提交 API key/token 原文；凭据证据只提交 `credential_presence=true`、`credential_scope=gateway_only`、`not_in_worker=true`。`confirmed_unavailable` 与 `not_integrated` 会被保留为阻断原因，不能被解释为已通过。

`run --suite` 是 C06 的唯一 suite 调度入口；它先展开具体分支、重复次数和分母，再检查冻结版本、E2、evidence gate 以及显式实验 gateway binding。真实调用前必须在实验进程显式提供 `IDEAL_LAB_PROVIDER_NAME/ENDPOINT/MODEL/API_KEY`；图片套件另需 `IDEAL_LAB_IMAGE_PROVIDER_NAME/ENDPOINT/MODEL/API_KEY`。`provider_config.py` 不读取生产 `.env`、SQLite 设置或生产 provider 模块，worker 只看到脱敏后的结构化 prompt。`sample_generation` 只要求已验证的源/worker/主模型/provider 凭据/费用边界，不要求人审；`full_text_matrix` 再要求第二模型；`image_execution` 再要求图像 provider；`research_execution` 再要求冻结研究归档。`human_review` 只进入 `final_subjective_conclusion`，所以不会阻止生成测试样本或自动化测试。它同时保留 R01–R12 reliability 和 I01–I12 integration 分母。R 套件可在 E2 之后以同一正式 store/loop/adapter 路径执行 deterministic control，明确标注为非语义、非 Provider 结果。continuity 通过同一轨迹内的虚拟日期事件并在中途重开 durable store 验证跨日状态；performance 通过同一正式 loop 采集 30 个样本并计算 p95；media 通过唯一 model loop 调用 `media.prepare`，由独立 image gateway 只接收 Provider 返回的本地 base64 资产并写入轨迹目录。门禁不足时只写入唯一 attempt 和阻断证据，provider/image 调用数必须为 0。旧 `smoke` 命令仅保留为单次 provider 前置兼容入口，永远不会向真实 Bot 发送消息。旧 `scripts/lab_*` 与旧 run 仅登记为历史参照，不产生 v2 正式成绩。

provider endpoint 可以由 `IDEAL_LAB_PROVIDER_ENDPOINT` / `IDEAL_LAB_IMAGE_ENDPOINT` 显式覆盖；若 provider 名在实验 catalog 中，gateway 会按已登记的 OpenAI-compatible base URL 补全 endpoint，但仍要求实验进程自己的 `IDEAL_LAB_*_API_KEY`，不会回退到生产凭据。

`context`、`roundtrip`、`mutations` 分别产出 C02/C03/C04 证据；`provider-deployment-audit.json` 只读记录“生产材料存在 / 实验接线代码已实现但未绑定 / 运行态未观察”，并记录 Docker/Podman/WSL 候选调查；`source-runtime-readonly.json` 只证明公开 health GET 的结果，不替代实例身份/账户授权，也不探测 provider API。没有健康失败证据时不把 provider 判为“确实不可用”；`evidence-submissions/` 保留每次提交，artifact 只按 hash 与结构化主体/事实核验且不可覆盖；`gate-validation.json` 是唯一放行结果。`execution-manifest.json` 展开完整分母、多事件输入和 P0/P1×背景配对，不把未执行分支伪装成通过；P1 主提示词和 P0 基线通过 `prompt-review-pack.json` 留痕，人工确认仍是最终主观结论的外部证据。当前 run 的最终结论必须以 `report.md` 为准：缺少已核验线上源身份或 OS/container 隔离时，completion 为 `incomplete`，不会启动真实 API 主组。
