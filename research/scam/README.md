# Scam 离线数据与训练

四个任务共用 `scripts/scam/run_pipeline.py`。当前阶段和命令以
[统一入口说明](../../docs/SCAM_PIPELINE.md) 为准。

```bash
.venv/bin/python scripts/scam/run_pipeline.py --help
.venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot xblock-unica-recent-v1 --stage all --run mean-sage-v2 --dry-run
```

固定阶段：`sources → collect → prepare → train`，以及 `all`、`status`。
`all` 执行到训练，必须指定 `--run`；只处理数据时分别调用前三个阶段。
`chainrisk-scam` 和 `python -m research.scam` 使用相同参数；旧子命令入口已收回为内部实现。

## 当前保留结果

| 任务 | 快照 | graph-run | 模型 run |
|---|---|---|---|
| Phishing | forta-recent-v1 | 不适用 | mean-sage-v1 |
| Ponzi | xblock-unica-recent-v1 | 不适用 | mean-sage-v1 |
| Honeypot | trapdoor-api-v1 | all-recent-v1 | sage-v1 |
| Rug Pull | tokenscout-eligible-1500-v2 | recent-v1 | sage-v1 |

四套模型均已完成本地训练。新训练必须使用新 run 名称，已有模型可用 dry-run 校验。

## 实现职责

- `pipeline.py`：固定阶段、任务适配、重试及统一训练调度。
- `_commands.py`：内部数据/模型操作分派，供 pipeline 和工程测试使用。
- `phishing.py/recent.py/ponzi.py`：地址任务数据流程。
- `honeypot.py/honeypot_graphs.py/honeypot_training.py`：Honeypot 证据、图及训练准备。
- `rug_pull.py/rug_pull_graphs.py/rug_pull_training.py`：Rug Pull 来源、池、图及训练准备。
- `preparation.py/splitting.py/training.py`：通用准入、分组划分及训练。
- `storage.py/compaction.py/execution.py/failure_exclusions.py`：路径、存储、恢复及失败排除。
- `packages/`：来源、采集、标准化、图、模型和模型包的共享实现。

数据位于 `data/scam/`，交易重放依赖位于 `data/shared/`，模型位于
`artifacts/scam/`，专项诊断结果位于 `reports/`。
独立 Honeypot/Rug Pull audit 脚本和 Ponzi 来源校验脚本已删除；
必要的来源审计、元数据验证和校验和检查由流程内部执行。既有分析报告保留。

## 研究约束与维护

四个任务独立建模，使用分层、分组约束的 90/10 训练/验证划分。
标准化器只拟合训练数据，验证 AP 选择检查点，验证 Macro-F1 选择阈值。
验证集同时参与选择，没有独立测试集。Phishing 背景为未标注样本；
Ponzi/Honeypot/Rug Pull 的来源与时间局限仍按各任务契约解释。

采集样本保持冻结目标、图配方、来源证据、失败排除记录和校验值。
共享 `events.jsonl.gz` 是复现依赖，不能当普通缓存删除。
已有数据的无损压缩迁移工具 `scripts/scam/compact_storage.py` 保留为维护工具，
不属于常规训练入口。API/RPC 连通性检查脚本同样仅作诊断。

```bash
.venv/bin/python -m unittest discover -s checks -v
```

各任务的来源和历史实验说明见 `docs/PHISHING_OFFLINE_PIPELINE.md`、
`docs/PONZI_OFFLINE_PIPELINE.md`、`docs/HONEYPOT_GRAPH_PIPELINE.md` 和
`docs/RUG_PULL_TRAINING_PIPELINE.md`。统一公共阶段以新的入口说明为准。
