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

# Returns 0 if something is already listening on the given local TCP port.
port_in_use() {
    local port=$1
    if command -v nc &>/dev/null; then
        nc -z localhost "$port" &>/dev/null 2>&1
    else
        (echo >/dev/tcp/localhost/"$port") 2>/dev/null
    fi
}

# ── Pre-flight: configuration checks ─────────────────────────────────────────
preflight_check() {
    local -a errors=()

    echo "Checking configuration..."
    echo ""

    # .env presence
    if [[ ! -f ".env" ]]; then
        echo "  ✗ .env not found"
        errors+=(".env is missing — copy example.env → .env and fill in the required values.")
    else
        echo "  ✓ .env found"
    fi

    # QQL_READONLY_PASSWORD — without this the DB user is silently never created
    if [[ -z "${QQL_READONLY_PASSWORD:-}" ]]; then
        echo "  ✗ QQL_READONLY_PASSWORD is not set"
        errors+=("QQL_READONLY_PASSWORD is not set. The qql_readonly DB user won't be created and the backend cannot connect. Set it in .env (see example.env).")
    else
        echo "  ✓ QQL_READONLY_PASSWORD is set"
    fi

    # LLM provider credentials
    case "${LLM_PROVIDER:-ollama}" in
        openai)
            if [[ -z "${OPENAI_API_KEY:-}" ]]; then
                echo "  ✗ LLM_PROVIDER=openai but OPENAI_API_KEY is not set"
                errors+=("OPENAI_API_KEY is required when LLM_PROVIDER=openai. Set it in .env.")
            else
                echo "  ✓ OpenAI API key found"
            fi
            ;;
        bedrock)
            if [[ -z "${AWS_ACCESS_KEY_ID:-}" ]] && [[ ! -f "$HOME/.aws/credentials" ]]; then
                echo "  ⚠  LLM_PROVIDER=bedrock: no AWS credentials found (will rely on IAM role)"
            else
                echo "  ✓ AWS credentials found"
            fi
            ;;
        vertex)
            if [[ -z "${GCP_PROJECT:-}" ]]; then
                echo "  ✗ LLM_PROVIDER=vertex but GCP_PROJECT is not set"
                errors+=("GCP_PROJECT is required when LLM_PROVIDER=vertex. Set it in .env.")
            else
                echo "  ✓ GCP project: ${GCP_PROJECT}"
            fi
            ;;
        ollama|*)
            echo "  ✓ LLM provider: ${LLM_PROVIDER:-ollama}"
            ;;
    esac

    # Docker
    if ! command -v docker &>/dev/null; then
        echo "  ✗ docker not found"
        errors+=("Docker is not installed. See https://docs.docker.com/get-docker/")
    elif ! docker info &>/dev/null 2>&1; then
        echo "  ✗ Docker daemon is not running"
        errors+=("Docker daemon is not running. Start Docker Desktop or run: sudo systemctl start docker")
    elif ! docker compose version &>/dev/null 2>&1; then
        echo "  ✗ 'docker compose' (v2) not available"
        errors+=("'docker compose' v2 is required. Update Docker to a version that bundles Compose v2.")
    else
        echo "  ✓ Docker is running"
    fi

    # Port availability
    local _pf_os; _pf_os="$(uname -s)"
    local -a _ports=( 5435        8000           8080       )
    local -a _pnames=( "PostgreSQL" "Backend API" "Frontend" )
    # On Linux Ollama runs in Docker and needs 11434.
    # On macOS the native Ollama section handles "already running" gracefully — skip here.
    if [[ "$_pf_os" == "Linux" ]]; then
        _ports+=( 11434 ); _pnames+=( "Ollama" )
    fi
    for _pi in "${!_ports[@]}"; do
        if port_in_use "${_ports[$_pi]}"; then
            echo "  ✗ Port ${_ports[$_pi]} is already in use (${_pnames[$_pi]})"
            errors+=("Port ${_ports[$_pi]} is in use — find what's using it: lsof -i :${_ports[$_pi]}")
        else
            echo "  ✓ Port ${_ports[$_pi]} is free   (${_pnames[$_pi]})"
        fi
    done

    echo ""

    if [[ ${#errors[@]} -gt 0 ]]; then
        local n=${#errors[@]}
        echo "  $n error$([ "$n" -gt 1 ] && echo "s") found — fix $([ "$n" -gt 1 ] && echo "them" || echo "it") before re-running ./start.sh"
        echo ""
        for _e in "${errors[@]}"; do
            echo "  → $_e"
        done
        echo ""
        exit 1
    fi
}
preflight_check

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
