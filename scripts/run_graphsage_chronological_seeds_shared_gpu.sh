#!/bin/bash
#SBATCH --job-name=token-graphsage-shared
#SBATCH --account=project_2020551
#SBATCH --partition=gpumedium
#SBATCH --time=01:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:gh200:1
#SBATCH --output=logs/graphsage_chronological_shared_gpu-%j.out

set -euo pipefail
cd /scratch/project_2020551/ds/project

SEEDS=(20261001 20261002 20261003)
THREADS_PER_RUN=5
export OMP_NUM_THREADS="${THREADS_PER_RUN}"
export MKL_NUM_THREADS="${THREADS_PER_RUN}"
export OMP_PLACES=cores
export OMP_PROC_BIND=spread

nvidia-smi
PIDS=()
for SEED in "${SEEDS[@]}"; do
  OUTPUT="data/graphsage_chronological_shared_gpu_seed${SEED}_20261001_v1"
  LOG="logs/graphsage_chronological_shared_gpu-${SLURM_JOB_ID}-seed${SEED}.out"
  echo "starting seed=${SEED} output=${OUTPUT} log=${LOG}"
  .venv/bin/python scripts/train_graphsage.py \
    --device cuda \
    --seed "${SEED}" \
    --split-name historical_chronological_secondary \
    --batch-size 512 \
    --graphs data/static_graph_chronological_20261001_v1/graphs.jsonl \
    --output "${OUTPUT}" \
    --threads "${THREADS_PER_RUN}" \
    >"${LOG}" 2>&1 &
  PIDS+=("$!")
done

STATUS=0
for PID in "${PIDS[@]}"; do
  if wait "${PID}"; then
    echo "completed pid=${PID}"
  else
    echo "failed pid=${PID}" >&2
    STATUS=1
  fi
done
exit "${STATUS}"
