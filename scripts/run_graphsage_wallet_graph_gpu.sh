#!/bin/bash
#SBATCH --job-name=wallet-graphsage-general
#SBATCH --account=project_2020551
#SBATCH --partition=gpumedium
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=72
#SBATCH --gres=gpu:gh200:1
#SBATCH --output=logs/graphsage_wallet_general_20261003-%j.out

set -euo pipefail

cd /scratch/project_2020551/ds/project
export OMP_NUM_THREADS="${SLURM_CPUS_PER_TASK:-1}"
export OMP_PLACES=cores
export OMP_PROC_BIND=spread

nvidia-smi

srun .venv/bin/python scripts/train_graphsage.py \
  --device cuda \
  --batch-size 512 \
  --split-name wallet_graph_general_stratified_20261003 \
  --graphs data/wallet_graph_input_20261003_2000_v4/graphs.jsonl \
  --output data/graphsage_wallet_general_stratified_20261003_v1 \
  --threads "${SLURM_CPUS_PER_TASK:-1}"
