#!/bin/bash

set -e

NUM_EXPERIMENTS=20
EXPERIMENT_DIR="summaries"
EXPERIMENT_PREFIX="experiment-run"
CMD_FILE="summaries/experiment-01-03-26/cmd.sh"

if [[ ! -f "$CMD_FILE" ]]; then
    echo "Error: Command file not found: $CMD_FILE"
    exit 1
fi

BASE_COMMAND=$(cat "$CMD_FILE" | head -1 | sed 's/summaries_2\.csv/'"$EXPERIMENT_PREFIX"'_%02d\/summaries.csv/g')

last_completed=0
for i in $(seq 1 $NUM_EXPERIMENTS); do
    exp_folder="$EXPERIMENT_DIR/${EXPERIMENT_PREFIX}-$(printf '%02d' $i)"
    
    if [[ -f "$exp_folder/done" ]]; then
        echo "Skipping experiment $i (already completed)"
        last_completed=$i
        continue
    fi
    
    echo "Running experiment $i of $NUM_EXPERIMENTS..."
    
    mkdir -p "$exp_folder"
    
    cmd=$(printf "$BASE_COMMAND" $i)
    echo "Executing: $cmd"
    eval "$cmd"
    
    touch "$exp_folder/done"
    last_completed=$i
    echo "Experiment $i completed"
done

echo "All $NUM_EXPERIMENTS experiments completed (last: $last_completed)"
