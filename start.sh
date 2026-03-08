#!/usr/bin/env bash
# QQL startup script — handles platform detection automatically.
# Usage: ./start.sh [--stop]
set -euo pipefail

# Load .env so LLM_MODEL / LLM_PROVIDER / OLLAMA_MODEL are available here
[[ -f ".env" ]] && set -a && source .env && set +a

# Active model: universal LLM_MODEL override takes priority over OLLAMA_MODEL
MODEL="${LLM_MODEL:-${OLLAMA_MODEL:-llama3.1:8b}}"
COMPOSE_FILE="docker-compose.yml"
NVIDIA_OVERRIDE="docker-compose.nvidia.yml"

# ── Banner ────────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════╗"
echo "║              QQL Startup             ║"
echo "╚══════════════════════════════════════╝"
echo "  Provider : ${LLM_PROVIDER:-ollama}"
echo "  Model    : $MODEL"
echo "  Compose  : $COMPOSE_FILE"
echo ""

stop_all() {
    echo "Stopping QQL..."
    docker compose -f "$COMPOSE_FILE" down
    if [[ "$(uname -s)" == "Darwin" ]]; then
        pkill -x ollama 2>/dev/null && echo "Ollama stopped." || true
    fi
    exit 0
}

reset_eda() {
    echo "Resetting EDA cache (data_context.md + skill.md)..."
    # Use rm -rf in case Docker previously created directories instead of files
    rm -rf data_context.md skill.md
    # Always recreate as proper empty files so Docker bind-mounts work on next start
    touch data_context.md skill.md
    echo "  Files reset."
    # If the backend is up, trigger an immediate refresh; otherwise files
    # will be regenerated automatically on next startup.
    if curl -sf http://localhost:8000/health &>/dev/null; then
        echo "  Backend is running — triggering fresh EDA run..."
        curl -s -X POST http://localhost:8000/eda/refresh | python3 -c \
            "import sys,json; d=json.load(sys.stdin); print(' ', d.get('message','done'))" 2>/dev/null || true
    else
        echo "  Backend is not running — EDA will regenerate on next start."
    fi
    echo ""
    exit 0
}

[[ "${1:-}" == "--stop" ]] && stop_all
[[ "${1:-}" == "--reset-eda" ]] && reset_eda

# ── Pre-flight: ensure bind-mounted files exist as files (not directories) ────
# Docker creates a directory when the host path is missing; that breaks the mount.
for _f in data_context.md skill.md; do
    [[ -d "$_f" ]] && rm -rf "$_f"  # nuke any directory Docker may have created
    [[ -f "$_f" ]] || touch "$_f"   # create empty file if absent
done
unset _f

OS="$(uname -s)"

# ── macOS: run Ollama natively to get Metal (Apple Silicon) GPU ──────────────
if [[ "$OS" == "Darwin" ]]; then
    echo "Detected macOS — running Ollama natively for Metal GPU acceleration."
    echo ""

    # Install Ollama if not present
    if ! command -v ollama &>/dev/null; then
        echo "Ollama is not installed."
        echo ""
        echo "The script can install it automatically by running:"
        echo "  curl -fsSL https://ollama.com/install.sh | sh"
        echo ""
        read -rp "Install Ollama now? [Y/n] " _install_answer
        case "${_install_answer:-Y}" in
            [Yy]*)
                echo "Installing Ollama..."
                curl -fsSL https://ollama.com/install.sh | sh
                echo ""
                ;;
            *)
                echo ""
                echo "Skipping automatic install."
                echo "Install Ollama manually: https://ollama.com/download"
                echo "Then re-run ./start.sh"
                exit 1
                ;;
        esac
    fi

    # Start Ollama server if not already running
    if ! pgrep -x ollama &>/dev/null; then
        echo "Starting Ollama server..."
        ollama serve &>/tmp/ollama.log &
        _OLLAMA_PID=$!
        echo "  Ollama PID: $_OLLAMA_PID  (logs → /tmp/ollama.log)"
        # Wait for it to be ready
        echo -n "  Waiting for Ollama to be ready"
        for i in $(seq 1 20); do
            curl -sf http://localhost:11434/api/tags &>/dev/null && echo " ready." && break
            echo -n "."
            sleep 1
        done
    else
        echo "Ollama is already running."
    fi
    echo ""

    # Pull model if using Ollama and it's not already available
    if [[ "${LLM_PROVIDER:-ollama}" == "ollama" ]]; then
        if ! ollama list | grep -q "${MODEL%:*}"; then
            echo "Pulling model $MODEL (this may take a while on first run)..."
            ollama pull "$MODEL"
        else
            echo "  Model $MODEL is already available."
        fi
        echo ""
    fi

    # Start postgres, backend, frontend — connect backend to native Ollama
    echo "Starting services: postgres, backend, frontend..."
    OLLAMA_BASE_URL=http://host.docker.internal:11434 \
        docker compose -f "$COMPOSE_FILE" up -d postgres backend frontend

# ── Linux: check for NVIDIA GPU ──────────────────────────────────────────────
elif [[ "$OS" == "Linux" ]]; then
    if command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null; then
        echo "Detected NVIDIA GPU — starting all services with GPU acceleration..."
        docker compose -f "$COMPOSE_FILE" -f "$NVIDIA_OVERRIDE" up -d
    else
        echo "No NVIDIA GPU detected — starting all services (CPU inference)..."
        docker compose -f "$COMPOSE_FILE" up -d
    fi
    echo ""

    # Pull model into the Ollama container (skip if using a non-Ollama provider)
    if [[ "${LLM_PROVIDER:-ollama}" == "ollama" ]]; then
        echo "Waiting for Ollama container to be ready..."
        until docker exec qql_ollama ollama list &>/dev/null; do sleep 2; done
        if ! docker exec qql_ollama ollama list | grep -q "${MODEL%:*}"; then
            echo "Pulling model $MODEL into Ollama container..."
            docker exec qql_ollama ollama pull "$MODEL"
        else
            echo "  Model $MODEL is already available."
        fi
        echo ""
    fi

else
    echo "Unsupported OS: $OS" >&2
    exit 1
fi

echo "╔══════════════════════════════════════╗"
echo "║           QQL is running             ║"
echo "╚══════════════════════════════════════╝"
echo "  App    : http://localhost:8080"
echo "  API    : http://localhost:8000/health"
echo "  Model  : $MODEL  (${LLM_PROVIDER:-ollama})"
echo ""
echo "  To stop:      ./start.sh --stop
  To reset EDA: ./start.sh --reset-eda"
echo ""
