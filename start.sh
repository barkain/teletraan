#!/bin/bash

# Teletraan - Start Script
# Starts both backend and frontend servers

set -e

# Port configuration (can be overridden via environment variables)
BACKEND_PORT=${BACKEND_PORT:-8000}
FRONTEND_PORT=${FRONTEND_PORT:-3000}

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}       Teletraan - Starting Services${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${YELLOW}Backend Port:${NC}  $BACKEND_PORT"
echo -e "  ${YELLOW}Frontend Port:${NC} $FRONTEND_PORT"

# Function to cleanup on exit
cleanup() {
    echo -e "\n${YELLOW}Shutting down services...${NC}"
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null && echo -e "${GREEN}✓ Backend stopped${NC}"
    fi
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null && echo -e "${GREEN}✓ Frontend stopped${NC}"
    fi
    # Kill any child processes
    pkill -P $$ 2>/dev/null
    echo -e "${GREEN}Done.${NC}"
    exit 0
}

trap cleanup SIGINT SIGTERM

# Check if ports are available
check_port() {
    if lsof -Pi :$1 -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "${RED}✗ Port $1 is already in use${NC}"
        return 1
    fi
    return 0
}

echo -e "\n${YELLOW}Checking ports...${NC}"
if ! check_port $BACKEND_PORT; then
    echo -e "${YELLOW}  Kill existing process? (y/n)${NC}"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        lsof -ti:$BACKEND_PORT | xargs kill -9 2>/dev/null
        echo -e "${GREEN}  ✓ Port $BACKEND_PORT freed${NC}"
    else
        exit 1
    fi
fi

if ! check_port $FRONTEND_PORT; then
    echo -e "${YELLOW}  Kill existing process? (y/n)${NC}"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        lsof -ti:$FRONTEND_PORT | xargs kill -9 2>/dev/null
        echo -e "${GREEN}  ✓ Port $FRONTEND_PORT freed${NC}"
    else
        exit 1
    fi
fi

# Start Backend
echo -e "\n${YELLOW}Starting Backend...${NC}"
cd "$BACKEND_DIR"

# Create data directory if it doesn't exist
mkdir -p data

# Create .env if it doesn't exist
if [ ! -f .env ]; then
    cat > .env << 'ENVEOF'
DATABASE_URL=sqlite+aiosqlite:///./data/market-analyzer.db

# --- LLM Provider Configuration ---
# The app uses claude-agent-sdk for LLM access. Uncomment ONE authentication method:
#
# Option 1: Anthropic API Key (recommended for production / distributed deployments)
# ANTHROPIC_API_KEY=sk-ant-...
#
# Option 2: Amazon Bedrock (requires AWS credentials in environment)
# CLAUDE_CODE_USE_BEDROCK=1
# AWS_REGION=us-east-1
#
# Option 3: Google Vertex AI (requires GCP credentials)
# CLAUDE_CODE_USE_VERTEX=1
# VERTEX_PROJECT=my-project
# VERTEX_REGION=us-central1
#
# Option 4: Azure AI Foundry (requires Azure credentials)
# CLAUDE_CODE_USE_FOUNDRY=1
#
# Option 5: z.ai or API Proxy
# ANTHROPIC_AUTH_TOKEN=your-zai-api-key
# ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic
# API_TIMEOUT_MS=3000000
#
# Option 6: Ollama (local models)
# ANTHROPIC_AUTH_TOKEN=ollama
# ANTHROPIC_API_KEY=
# ANTHROPIC_BASE_URL=http://localhost:11434
# Note: Run with a model that has 64k+ context, e.g.: claude --model qwen3-coder
#
# Default (nothing set): Uses local Claude Code subscription auth
# WARNING: Subscription auth is for local development only.
# Anthropic TOS prohibits using claude.ai login in distributed apps.

# Optional: Override default model (default: claude-sonnet-4-20250514)
# ANTHROPIC_MODEL=claude-sonnet-4-20250514

# --- Data Source API Keys (optional) ---
# FRED_API_KEY=your-fred-key
# FINNHUB_API_KEY=your-finnhub-key

# --- Report Publishing (disabled by default for fork safety) ---
# PUBLISH_METHOD controls where reports go: github_pages | static_dir | none
# PUBLISH_METHOD=github_pages

# Option A: GitHub Pages (default method)
# GITHUB_PAGES_ENABLED=true
# GITHUB_PAGES_REPO=your-username/your-repo
# GITHUB_PAGES_BASE_URL=https://your-username.github.io/your-repo

# Option B: Static directory (for nginx, S3 sync, Netlify, etc.)
# PUBLISH_METHOD=static_dir
# PUBLISH_DIR=/var/www/reports
# PUBLISH_URL=https://reports.example.com

# Option C: Disable publishing entirely
# PUBLISH_METHOD=none
ENVEOF
    echo -e "${GREEN}  ✓ Created .env file${NC}"
fi

# Start uvicorn in background
uv run uvicorn main:app --host 0.0.0.0 --port $BACKEND_PORT --reload &
BACKEND_PID=$!
echo -e "${GREEN}  ✓ Backend starting (PID: $BACKEND_PID)${NC}"

# Wait for backend to be ready
echo -e "${YELLOW}  Waiting for backend...${NC}"
for i in {1..30}; do
    if curl -s http://localhost:$BACKEND_PORT/api/v1/health > /dev/null 2>&1; then
        echo -e "${GREEN}  ✓ Backend ready at http://localhost:$BACKEND_PORT${NC}"
        break
    fi
    sleep 1
    if [ $i -eq 30 ]; then
        echo -e "${RED}  ✗ Backend failed to start${NC}"
        cleanup
    fi
done

# Start Frontend
echo -e "\n${YELLOW}Starting Frontend...${NC}"
cd "$FRONTEND_DIR"

# Always update .env.local with current backend port (Next.js requires restart for env changes anyway)
echo "NEXT_PUBLIC_API_URL=http://localhost:$BACKEND_PORT" > .env.local
echo "NEXT_PUBLIC_WS_URL=ws://localhost:$BACKEND_PORT/api/v1/chat" >> .env.local
echo -e "${GREEN}  ✓ Updated .env.local with BACKEND_PORT=$BACKEND_PORT${NC}"

# Start Next.js in background (with custom port)
npm run dev -- -p $FRONTEND_PORT &
FRONTEND_PID=$!
echo -e "${GREEN}  ✓ Frontend starting (PID: $FRONTEND_PID)${NC}"

# Wait for frontend to be ready
echo -e "${YELLOW}  Waiting for frontend...${NC}"
for i in {1..60}; do
    if curl -s http://localhost:$FRONTEND_PORT > /dev/null 2>&1; then
        echo -e "${GREEN}  ✓ Frontend ready at http://localhost:$FRONTEND_PORT${NC}"
        break
    fi
    sleep 1
    if [ $i -eq 60 ]; then
        echo -e "${RED}  ✗ Frontend failed to start${NC}"
        cleanup
    fi
done

# Print summary
echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  ✓ All services running!${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e ""
echo -e "  ${GREEN}Frontend:${NC}  http://localhost:$FRONTEND_PORT"
echo -e "  ${GREEN}Backend:${NC}   http://localhost:$BACKEND_PORT"
echo -e "  ${GREEN}API Docs:${NC}  http://localhost:$BACKEND_PORT/docs"
echo -e ""
echo -e "  Press ${YELLOW}Ctrl+C${NC} to stop all services"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Open browser (macOS)
if command -v open &> /dev/null; then
    sleep 2
    open http://localhost:$FRONTEND_PORT
fi

# Wait for processes
wait
