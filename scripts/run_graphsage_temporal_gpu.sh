#!/bin/bash
#SBATCH --job-name=wallet-graphsage-temporal
#SBATCH --account=project_2020551
#SBATCH --partition=gpumedium
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=72
#SBATCH --gres=gpu:gh200:1
#SBATCH --output=/scratch/project_2020551/ds/project/logs/graphsage_wallet_temporal-%j.out

set -euo pipefail

cd /scratch/project_2020551/ds/project
export OMP_NUM_THREADS=8
export OMP_PLACES=cores
export OMP_PROC_BIND=spread

nvidia-smi

GRAPH=data/wallet_graph_input_20261003_2000_v4/graphs.jsonl
OVERRIDE=data/model_split_temporal_wallet_graph_20261005_v1/splits.parquet
SPLIT=wallet_graph_temporal_20261005_v1
SEEDS=(20261001 20261002 20261003)

run_model() {
    local architecture="$1"
    local hidden_dim="$2"
    local seed="$3"
    local output="data/graphsage_wallet_temporal_${architecture}_hidden${hidden_dim}_layers2_seed${seed}_v1"
    echo "starting architecture=${architecture} hidden=${hidden_dim} seed=${seed} output=${output}"
    srun --exclusive --cpu-bind=cores .venv/bin/python scripts/train_graphsage.py \
        --architecture "${architecture}" \
        --device cuda \
        --seed "${seed}" \
        --hidden-dim "${hidden_dim}" \
        --layers 2 \
        --batch-size 512 \
        --split-name "${SPLIT}" \
        --graphs "${GRAPH}" \
        --partition-override "${OVERRIDE}" \
        --output "${output}" \
        --threads 8 \
        --cache-graphs
}

for seed in "${SEEDS[@]}"; do
    run_model edge_gcn 128 "${seed}"
done
for seed in "${SEEDS[@]}"; do
    run_model topology_sage 64 "${seed}"
done

echo "temporal graph training completed"
