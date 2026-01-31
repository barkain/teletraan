#!/bin/bash

# Market Analyzer - Start Script
# Starts both backend and frontend servers

set -e

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
echo -e "${BLUE}       Market Analyzer - Starting Services${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

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
if ! check_port 8000; then
    echo -e "${YELLOW}  Kill existing process? (y/n)${NC}"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        lsof -ti:8000 | xargs kill -9 2>/dev/null
        echo -e "${GREEN}  ✓ Port 8000 freed${NC}"
    else
        exit 1
    fi
fi

if ! check_port 3000; then
    echo -e "${YELLOW}  Kill existing process? (y/n)${NC}"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        lsof -ti:3000 | xargs kill -9 2>/dev/null
        echo -e "${GREEN}  ✓ Port 3000 freed${NC}"
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
    echo "DATABASE_URL=sqlite+aiosqlite:///./data/market-analyzer.db" > .env
    echo -e "${GREEN}  ✓ Created .env file${NC}"
fi

# Start uvicorn in background
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!
echo -e "${GREEN}  ✓ Backend starting (PID: $BACKEND_PID)${NC}"

# Wait for backend to be ready
echo -e "${YELLOW}  Waiting for backend...${NC}"
for i in {1..30}; do
    if curl -s http://localhost:8000/api/v1/health > /dev/null 2>&1; then
        echo -e "${GREEN}  ✓ Backend ready at http://localhost:8000${NC}"
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

# Create .env.local if it doesn't exist
if [ ! -f .env.local ]; then
    echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
    echo "NEXT_PUBLIC_WS_URL=ws://localhost:8000/api/v1/chat" >> .env.local
    echo -e "${GREEN}  ✓ Created .env.local file${NC}"
fi

# Start Next.js in background
npm run dev &
FRONTEND_PID=$!
echo -e "${GREEN}  ✓ Frontend starting (PID: $FRONTEND_PID)${NC}"

# Wait for frontend to be ready
echo -e "${YELLOW}  Waiting for frontend...${NC}"
for i in {1..60}; do
    if curl -s http://localhost:3000 > /dev/null 2>&1; then
        echo -e "${GREEN}  ✓ Frontend ready at http://localhost:3000${NC}"
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
echo -e "  ${GREEN}Frontend:${NC}  http://localhost:3000"
echo -e "  ${GREEN}Backend:${NC}   http://localhost:8000"
echo -e "  ${GREEN}API Docs:${NC}  http://localhost:8000/docs"
echo -e ""
echo -e "  Press ${YELLOW}Ctrl+C${NC} to stop all services"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Open browser (macOS)
if command -v open &> /dev/null; then
    sleep 2
    open http://localhost:3000
fi

# Wait for processes
wait
