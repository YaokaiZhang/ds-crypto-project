#!/bin/bash
#SBATCH --job-name=wallet-edge-architectures
#SBATCH --account=project_2020551
#SBATCH --partition=gpumedium
#SBATCH --time=04:00:00
#SBATCH --nodes=1
# One batch task owns the node's CPU set; child processes are CPU-pinned below.
# Keeping one Slurm task avoids creating nine child steps that each inherit the
# whole GPU allocation and are consequently serialized by Slurm.
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=72
#SBATCH --gres=gpu:gh200:1
#SBATCH --output=/scratch/project_2020551/ds/project/logs/graphsage_wallet_edge_architectures-%j.out

set -euo pipefail

cd /scratch/project_2020551/ds/project
export OMP_NUM_THREADS=8
export OMP_PLACES=cores
export OMP_PROC_BIND=spread
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"

GRAPH=data/wallet_graph_input_20261003_2000_v4/graphs.jsonl
SPLIT=wallet_graph_general_stratified_20261003
SEEDS=(20261001 20261002 20261003)
ARCHITECTURES=(edge_sage edge_gcn edge_gat)
OUTPUT_VERSION="${OUTPUT_VERSION:-v2}"
CPUS_PER_CHILD=8
CHILD_COUNT=9

# Slurm may assign a non-zero CPU range to the batch task. Expand the actual
# allowed set so taskset receives valid CPU IDs instead of assuming 0-based IDs.
cpu_allowed_list=$(awk '/^Cpus_allowed_list:/ {print $2}' /proc/self/status)
CPU_IDS=()
IFS=',' read -ra cpu_groups <<< "${cpu_allowed_list}"
for cpu_group in "${cpu_groups[@]}"; do
    if [[ "${cpu_group}" == *-* ]]; then
        cpu_start=${cpu_group%-*}
        cpu_end=${cpu_group#*-}
        for ((cpu=cpu_start; cpu<=cpu_end; cpu++)); do
            CPU_IDS+=("${cpu}")
        done
    else
        CPU_IDS+=("${cpu_group}")
    fi
done
if (( ${#CPU_IDS[@]} < CPUS_PER_CHILD * CHILD_COUNT )); then
    echo "expected at least $((CPUS_PER_CHILD * CHILD_COUNT)) allowed CPUs, got ${#CPU_IDS[@]} (${cpu_allowed_list})"
    exit 1
fi

gpu_memory_mib=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -n 1 | tr -d ' ')
if [[ -z "${gpu_memory_mib}" || "${gpu_memory_mib}" -lt 60000 ]]; then
    echo "refusing shared GAT launch: expected at least 60000 MiB, got ${gpu_memory_mib:-unknown}"
    exit 1
fi
nvidia-smi --query-gpu=name,memory.total --format=csv

gpu_monitor_log="logs/graphsage_wallet_edge_gpu_dmon-${SLURM_JOB_ID}.out"
nvidia-smi dmon -s pucm -d 10 > "${gpu_monitor_log}" 2>&1 &
gpu_monitor_pid=$!
cleanup() {
    kill "${gpu_monitor_pid}" 2>/dev/null || true
}
trap cleanup EXIT
WAVE_PIDS=()

launch() {
    local architecture="$1"
    local seed="$2"
    local hidden_dim="$3"
    local layers="$4"
    local cpu_slot="$5"
    local cpu_set=""
    local cpu_index
    for ((offset=0; offset<CPUS_PER_CHILD; offset++)); do
        cpu_index=$((cpu_slot * CPUS_PER_CHILD + offset))
        if (( offset > 0 )); then
            cpu_set+=","
        fi
        cpu_set+="${CPU_IDS[$cpu_index]}"
    done
    local name="${architecture}_hidden${hidden_dim}_layers${layers}"
    local output="data/graphsage_wallet_edge_${name}_seed${seed}_${OUTPUT_VERSION}"
    echo "starting architecture=${architecture} hidden=${hidden_dim} layers=${layers} seed=${seed} cpus=${cpu_set} output=${output}"
    taskset --cpu-list "${cpu_set}" \
        .venv/bin/python scripts/train_graphsage.py \
        --architecture "${architecture}" \
        --device cuda \
        --seed "${seed}" \
        --hidden-dim "${hidden_dim}" \
        --layers "${layers}" \
        --batch-size 512 \
        --split-name "${SPLIT}" \
        --graphs "${GRAPH}" \
        --output "${output}" \
        --threads 8 \
        --cache-graphs \
        > "logs/graphsage_wallet_edge_${name}_seed${seed}-${SLURM_JOB_ID}.out" 2>&1 &
    WAVE_PIDS+=("$!")
}

run_wave() {
    local hidden_dim="$1"
    local layers="$2"
    local status=0
    local cpu_slot=0
    WAVE_PIDS=()
    for architecture in "${ARCHITECTURES[@]}"; do
        for seed in "${SEEDS[@]}"; do
            launch "${architecture}" "${seed}" "${hidden_dim}" "${layers}" "${cpu_slot}"
            cpu_slot=$((cpu_slot + 1))
        done
    done
    for pid in "${WAVE_PIDS[@]}"; do
        if ! wait "${pid}"; then
            status=1
        fi
    done
    if [[ "${status}" -ne 0 ]]; then
        echo "edge architecture wave failed: hidden=${hidden_dim} layers=${layers}"
        exit "${status}"
    fi
    echo "edge architecture wave completed: hidden=${hidden_dim} layers=${layers}"
}

run_wave 32 2
run_wave 64 2
run_wave 128 2
run_wave 64 3
echo "edge architecture sweep completed"
