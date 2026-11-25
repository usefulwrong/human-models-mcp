#!/usr/bin/env bash
# Source from repository root or run: bash scripts/muscle_intelligence/local.sh
HMM_ROOT=$(pwd -P)
export HMM_LAB_WORK="${HMM_LAB_WORK:-$HMM_ROOT/outputs/v09/full-muscles}"
export HMM_LAB_APP="${HMM_LAB_APP:-$HMM_LAB_WORK/app}"
export HMM_LAB_CATALOG="$HMM_ROOT/outputs/v09/composite-organs/install-clean/catalog.json"
export HMM_LAB_SITE="$HMM_LAB_APP/lab/site"
export HMM_LAB_WHOLE="$HMM_ROOT/outputs/v09/moving-human/clip-final/motion.json"
export HMM_LAB_WHOLE_RESULTS="$HMM_ROOT/outputs/v09/motion/run-01/results"
export HMM_LAB_MOTION="$HMM_ROOT/outputs/v09/followup/motion/candidate/motion.json"
export HMM_LAB_WHOLE_SHA=b44d578bb63b58cf8fdb9b686f64e6c6cb42063ffca0e8041cae5991d0a0f6ab
export HMM_LAB_WHOLE_RENDER_SHA=bdcd2aaba4f6fba252c3385d92b82f6588a473c144c93bb10ef58ad12dbc64cf
export HMM_LAB_MUSCLE_CROSSWALK="${HMM_LAB_MUSCLE_CROSSWALK:-$HMM_LAB_WORK/MUSCLE_CROSSWALK_V2.json}"
export HMM_LAB_MUSCLE_CROSSWALK_SHA="${HMM_LAB_MUSCLE_CROSSWALK_SHA:-$(cut -d' ' -f1 "$HMM_LAB_WORK/crosswalk.sha256")}"
export HMM_LAB_MUSCLE_SELECTION="${HMM_LAB_MUSCLE_SELECTION:-$HMM_LAB_APP/shared-selection.json}"
export HUMAN_MODELS_HOME="$HMM_ROOT/outputs/v09/motion/run-01"
export PYTHONPATH="$HMM_LAB_APP/lab:$HMM_ROOT/src"
export PYTHONDONTWRITEBYTECODE=1
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  set -e
  exec "${HMM_PYTHON:-$HMM_ROOT/.client-venv/bin/python}" -m lab_web --port "${HMM_PORT:-8766}"
fi
