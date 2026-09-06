#!/usr/bin/env bash
# Source this in Git Bash before working:  source scripts/dev-env.sh
# Points every cache, the interpreter and the virtualenv at one data directory, so that several
# gigabytes of corpus, model weights and build caches do not land on the system drive.
# Set ORDERORDER_DATA_DIR to choose where that is; it defaults to ./data inside the repo.
DATA="${ORDERORDER_DATA_DIR:-$PWD/data}"
mkdir -p "$DATA"/{uv-cache,uv-python,hf,corpus,postgres,ollama}
export ORDERORDER_DATA_DIR="$DATA"
export UV_CACHE_DIR="$DATA/uv-cache"
export UV_PYTHON_INSTALL_DIR="$DATA/uv-python"
export UV_PROJECT_ENVIRONMENT="$DATA/venv"
export HF_HOME="$DATA/hf"
# Windows will not make symlinks without developer mode or an elevated shell, and the model cache
# uses them by default; without this a model download dies on a privilege error partway through.
export HF_HUB_DISABLE_SYMLINKS=1
export HF_HUB_DISABLE_SYMLINKS_WARNING=1
export OLLAMA_MODELS="$DATA/ollama"
# The virtualenv holds one editable install, and `uv sync` writes into it the absolute path of
# whichever checkout ran it last. A second checkout of this repository -- a git worktree, a clone
# beside it -- then gets an `orderorder` on the PATH that runs the *first* checkout's code, and it
# fails in the way that costs the most time: the command exists, and the subcommand just added to it
# does not. `pyproject.toml` pins this for pytest; this is the same fix for the CLI.
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO/src"
# Windows Python cannot read a /c/... path, and Git Bash is where this is usually sourced.
command -v cygpath >/dev/null 2>&1 && SRC="$(cygpath -w "$SRC")"
export PYTHONPATH="$SRC"
echo "OrderOrder dev environment: data and caches under $DATA"
echo "                            source read from $SRC"
echo "Next: uv sync        (installs into $DATA/venv)"
echo "      uv run orderorder --help"
