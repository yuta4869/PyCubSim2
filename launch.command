#!/bin/zsh

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ -x "/opt/miniconda3/envs/pycubsim2/bin/python" ]]; then
    PYTHON="/opt/miniconda3/envs/pycubsim2/bin/python"
elif [[ -x "/opt/miniconda3/envs/pycub-homeostatic/bin/python" ]]; then
    PYTHON="/opt/miniconda3/envs/pycub-homeostatic/bin/python"
else
    PYTHON="$(command -v python3)"
fi

cd "$PROJECT_DIR" || exit 1
exec "$PYTHON" run_sim.py
