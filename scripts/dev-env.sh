#!/usr/bin/env bash
# Source this in Git Bash before working:  source scripts/dev-env.sh
# Points every cache, the interpreter and the virtualenv at one data directory, so that they do not land on the system drive.
DATA="data"
mkdir -p "$DATA"/{uv-cache,uv-python,hf,corpus,postgres,ollama}
export ORDERORDER_DATA_DIR="$DATA"
export UV_CACHE_DIR="$DATA/uv-cache"
export UV_PYTHON_INSTALL_DIR="$DATA/uv-python"
export UV_PROJECT_ENVIRONMENT="$DATA/venv"
export HF_HOME="$DATA/hf"
export OLLAMA_MODELS="$DATA/ollama"
echo "OrderOrder dev environment: data and caches under $DATA"
echo "Next: uv sync        (installs into $DATA/venv)"
echo "      uv run orderorder --help"
