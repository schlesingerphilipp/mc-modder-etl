#!/bin/bash

set -e

NUM_EXPERIMENTS=20
EXPERIMENT_DIR="summaries"
EXPERIMENT_PREFIX="experiment-run"
EXPERIMENT_NAME=$1
SOURCE_FILE=$2

BASE_COMMAND="poetry run summarize-commits $SOURCE_FILE $EXPERIMENT_DIR/$EXPERIMENT_NAME/run-"
# check if the folder $EXPERIMENT_DIR/$EXPERIMENT_NAME exists, if not create it
if [[ ! -d "$EXPERIMENT_DIR/$EXPERIMENT_NAME" ]]; then
    mkdir -p "$EXPERIMENT_DIR/$EXPERIMENT_NAME"
else
    echo "Experiment folder $EXPERIMENT_DIR/$EXPERIMENT_NAME already exists. Resuming from last completed experiment."
fi

last_completed=0
for i in $(seq 1 $NUM_EXPERIMENTS); do
    exp_folder="$EXPERIMENT_DIR/$EXPERIMENT_NAME/${EXPERIMENT_PREFIX}-$(printf '%02d' $i)"
    
    if [[ -f "$exp_folder/done" ]]; then
        echo "Skipping experiment $i (already completed)"
        last_completed=$i
        continue
    fi
    
    echo "Running experiment $i of $NUM_EXPERIMENTS..."
    
    mkdir -p "$exp_folder"
    
    cmd=$(printf "$BASE_COMMAND$i/summaries.parquet")
    echo "Executing: $cmd"
    eval "$cmd"
    
    touch "$exp_folder/done"
    last_completed=$i
    echo "Experiment $i completed"
done

echo "All $NUM_EXPERIMENTS experiments completed (last: $last_completed)"
