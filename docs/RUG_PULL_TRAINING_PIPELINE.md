# Rug Pull 离线处理与训练

当前公共阶段以 [统一入口说明](SCAM_PIPELINE.md) 为准：`sources / collect / prepare / train / all / status`。`all` 包含训练并要求 `--run`；本文较早的内部阶段与历史实验记录不改变既有结果。

2026-10-23：采集结束后清理临时 external Key 的进程配置及独立 quota 文件。
原账号、local_secrets.py 和默认 quota 保持原样。数据处理不需要 API。

同日 `sage-v1` 已完成训练：最优轮 7，早停轮 32，验证 AP=0.953006、
Accuracy=0.893891。训练曲线、过拟合、数据分布与误判分析见
[完整报告](../reports/rug_pull/tokenscout-eligible-1500-v2/recent-v1/sage-v1-audit/FINDINGS_zh.md)。

## 处理结果

快照：`tokenscout-eligible-1500-v2`，图运行：`recent-v1`。

- 冻结采集目标：3,112；成功构图并进入训练准备：3,107。
- 正例 1,499，负例 1,608。另 5 个标准化失败保留证据并排除，不补选。
- 训练集：2,796（正例 1,349，负例 1,447）。
- 验证集：311（正例 150，负例 161）。
- 同一 Token 或所选池关联的样本保持同一分区；无独立测试集。
- 沿用已冻结的 token-v2-recent-1.0 图配方和现有模型、训练规则。

处理入口：

```zsh
.venv/bin/python scripts/scam/run_pipeline.py \
  --task rug_pull --snapshot tokenscout-eligible-1500-v2 \
  --stage collect --graph-run recent-v1 --progress on
.venv/bin/python scripts/scam/run_pipeline.py \
  --task rug_pull --snapshot tokenscout-eligible-1500-v2 \
  --stage prepare --graph-run recent-v1
```

输出目录：
`data/scam/rug_pull/tokenscout-eligible-1500-v2/graph_runs/recent-v1/prepared/`。
包含 graphs.jsonl、targets.jsonl、supervision.jsonl、splits.jsonl、
training_config.json 和 dataset_manifest.json。输入、输出和排除记录均固定校验和；
重复执行验证已有结果，输入改变或产物损坏则停止。

TokenScout 的原始来源标签保持不变。训练准备通过显式
`tokenscout-rug-pull-source-adopted-1` 策略生成本实验监督，保留来源备注，
不把这些备注当作图特征。事件时间、标签有效期与可知时间保持未知；
默认 rug_incidents 导入和标签协调仍要求事件与控制者证据。

## 执行训练

以下为本次使用的训练命令。当前 sage-v1 已完成；新实验应使用新的 --run 名称，
避免覆盖既有模型。

```zsh
.venv/bin/python scripts/scam/run_pipeline.py \
  --task rug_pull --snapshot tokenscout-eligible-1500-v2 \
  --stage train --graph-run recent-v1 --run sage-v1 --progress on
```

与 Honeypot 使用相同的训练调度入口：先验证准备数据和校验和，再读取冻结的
training_config.json、graphs.jsonl、supervision.jsonl、splits.jsonl，调用现有
内部共享训练器。结果保存到
`artifacts/scam/rug_pull/tokenscout-eligible-1500-v2/sage-v1/`，并保存 run_manifest.json。
train 阶段与 all 中的最后一步执行拟合；--dry-run 只校验，可用 --epochs、--patience、
--min-delta 覆盖对应训练参数。all 现在顺序完成来源、采集构图、训练准备和训练。

沿用现有 directed_edge_sage、weighted BCE、batch_size=32、最多 200 epoch、
patience=25、min_delta=0.0001；默认 CPU。验证 AP 控制最优权重和提前停止。
同一验证集用于模型/阈值选择，输出是历史来源样本的验证结果。
输出训练总结、验证结果和 bundle；已存在的非空模型目录不会覆盖。
