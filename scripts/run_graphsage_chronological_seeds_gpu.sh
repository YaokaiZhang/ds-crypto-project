#!/bin/bash
#SBATCH --job-name=token-graphsage-seeds
#SBATCH --account=project_2020551
#SBATCH --partition=gpumedium
#SBATCH --time=01:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:gh200:1
#SBATCH --array=0-1%2
#SBATCH --output=logs/graphsage_chronological_seeds-%A_%a.out

set -euo pipefail
cd /scratch/project_2020551/ds/project
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export OMP_PLACES=cores
export OMP_PROC_BIND=spread

SEEDS=(20261002 20261003)
SEED="${SEEDS[${SLURM_ARRAY_TASK_ID}]}"
OUTPUT="data/graphsage_chronological_seed${SEED}_20261001_v1"

echo "seed=${SEED} output=${OUTPUT}"
nvidia-smi
srun .venv/bin/python scripts/train_graphsage.py \
  --device cuda \
  --seed "${SEED}" \
  --split-name historical_chronological_secondary \
  --batch-size 512 \
  --graphs data/static_graph_chronological_20261001_v1/graphs.jsonl \
  --output "${OUTPUT}" \
  --threads "${SLURM_CPUS_PER_TASK:-1}"
