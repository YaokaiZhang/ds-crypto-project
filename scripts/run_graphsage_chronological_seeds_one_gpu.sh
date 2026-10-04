#!/bin/bash
#SBATCH --job-name=token-graphsage-one-gpu
#SBATCH --account=project_2020551
#SBATCH --partition=gpumedium
#SBATCH --time=01:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:gh200:1
#SBATCH --output=logs/graphsage_chronological_one_gpu-%j.out

set -euo pipefail
cd /scratch/project_2020551/ds/project
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export OMP_PLACES=cores
export OMP_PROC_BIND=spread

SEEDS=(20261001 20261002 20261003)
nvidia-smi
for SEED in "${SEEDS[@]}"; do
  OUTPUT="data/graphsage_chronological_one_gpu_seed${SEED}_20261001_v1"
  echo "starting seed=${SEED} output=${OUTPUT}"
  srun --exclusive .venv/bin/python scripts/train_graphsage.py \
    --device cuda \
    --seed "${SEED}" \
    --split-name historical_chronological_secondary \
    --batch-size 512 \
    --graphs data/static_graph_chronological_20261001_v1/graphs.jsonl \
    --output "${OUTPUT}" \
    --threads "${SLURM_CPUS_PER_TASK:-1}"
  echo "finished seed=${SEED}"
done
