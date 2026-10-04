#!/bin/bash
#SBATCH --job-name=token-graphsage-chrono
#SBATCH --account=project_2020551
#SBATCH --partition=gpumedium
#SBATCH --time=01:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:gh200:1
#SBATCH --output=logs/graphsage_chronological_20261001_v2-%j.out

set -euo pipefail
cd /scratch/project_2020551/ds/project
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export OMP_PLACES=cores
export OMP_PROC_BIND=spread
nvidia-smi
srun .venv/bin/python scripts/train_graphsage.py \
  --device cuda \
  --batch-size 512 \
  --split-name historical_chronological_secondary \
  --graphs data/static_graph_chronological_20261001_v1/graphs.jsonl \
  --output data/graphsage_chronological_20261001_v2 \
  --threads "${SLURM_CPUS_PER_TASK:-1}"
