#!/bin/zsh

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="/tmp/pycubsim2.log"
REQUIRED_IMPORTS="import numpy, pybullet, PIL, cv2"

PYTHON_CANDIDATES=()
if [[ "${CONDA_DEFAULT_ENV:-}" == "pycubsim2" && -n "${CONDA_PREFIX:-}" ]]; then
    PYTHON_CANDIDATES+=("$CONDA_PREFIX/bin/python")
fi
PYTHON_CANDIDATES+=(
    "$HOME/miniforge3/envs/pycubsim2/bin/python"
    "$HOME/miniconda3/envs/pycubsim2/bin/python"
    "$HOME/anaconda3/envs/pycubsim2/bin/python"
    "$HOME/mambaforge/envs/pycubsim2/bin/python"
    "/opt/homebrew/Caskroom/miniforge/base/envs/pycubsim2/bin/python"
    "/opt/homebrew/Caskroom/miniconda/base/envs/pycubsim2/bin/python"
    "/opt/miniforge3/envs/pycubsim2/bin/python"
    "/opt/miniconda3/envs/pycubsim2/bin/python"
    "/opt/anaconda3/envs/pycubsim2/bin/python"
    "/usr/local/miniforge3/envs/pycubsim2/bin/python"
    "/usr/local/miniconda3/envs/pycubsim2/bin/python"
    "/usr/local/anaconda3/envs/pycubsim2/bin/python"
)
PYTHON_BIN=""

: > "$LOG_FILE"
{
    print "PyCubSim2 source launcher"
    print "Started: $(/bin/date)"
    print "Project: $PROJECT_DIR"
} >> "$LOG_FILE"

for CANDIDATE in "${PYTHON_CANDIDATES[@]}"; do
    if [[ ! -x "$CANDIDATE" ]]; then
        print "Not found: $CANDIDATE" >> "$LOG_FILE"
        continue
    fi

    print "Checking: $CANDIDATE" >> "$LOG_FILE"
    if IMPORT_ERROR="$("$CANDIDATE" -c "$REQUIRED_IMPORTS" 2>&1)"; then
        PYTHON_BIN="$CANDIDATE"
        break
    fi

    print "Rejected: required imports failed for $CANDIDATE" >> "$LOG_FILE"
    print -r -- "$IMPORT_ERROR" >> "$LOG_FILE"
done

if [[ -z "$PYTHON_BIN" ]]; then
    {
        print "A usable pycubsim2 Conda environment was not found."
        print
        print "Required modules: numpy, pybullet, PIL, cv2"
        print "Create the environment first:"
        print
        print "  conda env create -f \"$PROJECT_DIR/environment.yml\""
        print
        print "Checked paths:"
        for CANDIDATE in "${PYTHON_CANDIDATES[@]}"; do
            print "  $CANDIDATE"
        done
        print
        print "Details were written to $LOG_FILE"
    } | tee -a "$LOG_FILE"

    if [[ -t 0 ]]; then
        read -k 1 "?Press any key to close."
        print
    fi
    exit 1
fi

print "Selected: $PYTHON_BIN" >> "$LOG_FILE"

if ! cd "$PROJECT_DIR"; then
    print "Could not open project directory: $PROJECT_DIR" | tee -a "$LOG_FILE"
    exit 1
fi

exec env PYTHONUNBUFFERED=1 "$PYTHON_BIN" "$PROJECT_DIR/run_sim.py"
