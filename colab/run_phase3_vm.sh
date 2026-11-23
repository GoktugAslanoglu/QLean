#!/usr/bin/env bash
# Run on the Colab VM or the authorized CUDA SSH host.
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
mode=${1:-all}
case "$mode" in
    all|compose|prepare|verify) ;;
    *) echo "Unknown Phase 3 mode: $mode" >&2; exit 2 ;;
esac

python3 -B -c 'import sys; sys.path.insert(0, "colab"); from paths import configure; configure()'
export QLEAN_ROOT=${QLEAN_ROOT:-/tmp/qlean}
export TMPDIR="$QLEAN_ROOT/tmp"
export XDG_CACHE_HOME="$QLEAN_ROOT/cache" PIP_CACHE_DIR="$QLEAN_ROOT/cache/pip"
export HF_HOME="$QLEAN_ROOT/hf" CUDA_CACHE_PATH="$QLEAN_ROOT/cache/cuda"
export TRITON_CACHE_DIR="$QLEAN_ROOT/cache/triton"
export PYTHONDONTWRITEBYTECODE=1

packages=()
command -v git >/dev/null || packages+=(git)
command -v make >/dev/null || packages+=(make)
command -v clang >/dev/null || packages+=(clang)
if ! command -v llvm-objdump >/dev/null || ! command -v llvm-nm >/dev/null; then
    packages+=(llvm)
fi
if ! command -v riscv64-linux-gnu-ld >/dev/null && ! command -v riscv64-elf-ld >/dev/null && \
   ! command -v riscv64-unknown-elf-ld >/dev/null && ! command -v ld.lld >/dev/null; then
    packages+=(binutils-riscv64-linux-gnu)
fi
if ! python3 -B -c 'import venv' >/dev/null 2>&1; then
    packages+=(python3-venv)
fi
if ((${#packages[@]})); then
    if ! command -v apt-get >/dev/null; then
        printf 'Install required host packages with the OS package manager: %s\n' "${packages[*]}" >&2
        exit 2
    fi
    admin=()
    if ((EUID != 0)); then
        admin=(sudo -n)
    fi
    "${admin[@]}" apt-get -qq update
    "${admin[@]}" apt-get -qq install -y "${packages[@]}"
fi

host_python=python3
if ! python3 -B -c 'import sys; assert sys.version_info >= (3, 11)' >/dev/null 2>&1; then
    uv=$(command -v uv || true)
    if [[ -z $uv ]]; then
        python3 -m venv "$QLEAN_ROOT/bootstrap-venv"
        "$QLEAN_ROOT/bootstrap-venv/bin/python" -m pip install uv
        uv="$QLEAN_ROOT/bootstrap-venv/bin/uv"
    fi
    export UV_CACHE_DIR="$QLEAN_ROOT/cache/uv" UV_PYTHON_INSTALL_DIR="$QLEAN_ROOT/python"
    "$uv" python install 3.12
    host_python=$("$uv" python find --managed-python 3.12)
fi
"$host_python" -m venv --system-site-packages --without-pip "$QLEAN_ROOT/venv"
python="$QLEAN_ROOT/venv/bin/python"
if ! "$python" -m pip --version >/dev/null 2>&1; then
    if "$host_python" -m pip --version >/dev/null 2>&1; then
        "$host_python" -m pip --python "$python" install pip
    else
        "$python" -m ensurepip
    fi
fi
if [[ $mode == prepare ]]; then
    if ! "$python" -B -c 'import torch' >/dev/null 2>&1; then
        "$python" -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.9.1
    fi
else
    nvidia-smi --query-gpu=name,driver_version,compute_cap,memory.total --format=csv,noheader
    if ! "$python" -B -c 'import torch, triton; assert torch.cuda.is_available()' >/dev/null 2>&1; then
        "$python" -m pip install --upgrade --index-url https://download.pytorch.org/whl/cu128 \
            torch==2.9.1 torchvision==0.24.1
    fi
fi

case "$mode" in
    all)
        "$python" -B colab/setup.py
        "$python" -B colab/compile.py
        "$python" -B colab/verify.py
        ;;
    compose)
        "$python" -B colab/setup.py
        "$python" -B colab/compile.py
        ;;
    prepare)
        "$python" -B colab/setup.py --prepare-only
        "$python" -B colab/compile.py
        ;;
    verify)
        "$python" -B colab/setup.py --runtime-only
        "$python" -B colab/verify.py
        ;;
esac
