#!/bin/bash
#SBATCH --job-name=wallet-capacity-sweep
#SBATCH --account=project_2020551
#SBATCH --partition=gpumedium
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=9
#SBATCH --cpus-per-task=8
#SBATCH --gres=gpu:gh200:1
#SBATCH --output=/scratch/project_2020551/ds/project/logs/graphsage_wallet_capacity_sweep-%j.out

set -euo pipefail

cd /scratch/project_2020551/ds/project
export OMP_NUM_THREADS=8
export OMP_PLACES=cores
export OMP_PROC_BIND=spread
# The whole job intentionally owns one GPU; all nine processes share this
# allocation while Slurm keeps their CPU cores exclusive.
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"

GRAPH=data/wallet_graph_input_20261003_2000_v4/graphs.jsonl
SPLIT=wallet_graph_general_stratified_20261003

launch() {
    local name="$1"
    local seed="$2"
    local hidden_dim="$3"
    local layers="$4"
    local output="data/graphsage_wallet_capacity_${name}_seed${seed}_v1"
    echo "starting name=${name} seed=${seed} output=${output}"
    srun --exclusive --ntasks=1 --cpus-per-task=8 \
        .venv/bin/python scripts/train_graphsage.py \
        --device cuda \
        --seed "${seed}" \
        --hidden-dim "${hidden_dim}" \
        --layers "${layers}" \
        --batch-size 512 \
        --split-name "${SPLIT}" \
        --graphs "${GRAPH}" \
        --output "${output}" \
        --threads 8 \
        > "logs/graphsage_wallet_capacity_${name}_seed${seed}-${SLURM_JOB_ID}.out" 2>&1 &
}

for seed in 20261001 20261002 20261003; do
    launch hidden64 "${seed}" 64 2
    launch hidden128 "${seed}" 128 2
    launch 3layer_hidden64 "${seed}" 64 3
done

status=0
for pid in $(jobs -pr); do
    if ! wait "${pid}"; then
        status=1
    fi
done

if [[ "${status}" -ne 0 ]]; then
    echo "capacity sweep failed"
    exit "${status}"
fi
echo "capacity sweep completed"
