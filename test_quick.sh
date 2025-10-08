#!/bin/bash
# Quick smoke test - runs basic scenarios quickly

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}Quick Smoke Test - Distributed Booking System${NC}\n"

cleanup() {
    # Kill all background jobs
    jobs -p | xargs kill -9 2>/dev/null || true
    # Kill processes using port 3000
    lsof -ti:3000 | xargs kill -9 2>/dev/null || true
    # Kill all related Python processes
    pkill -9 -f "server.py" 2>/dev/null || true
    pkill -9 -f "test_experiment.py" 2>/dev/null || true
    pkill -9 -f "test_monitor.py" 2>/dev/null || true
    pkill -9 -f "client.py" 2>/dev/null || true
    sleep 1
}
trap cleanup EXIT

kill_all_python() {
    # Kill processes using port 3000
    lsof -ti:3000 | xargs kill -9 2>/dev/null || true
    # Kill all related Python processes
    pkill -9 -f "server.py" 2>/dev/null || true
    pkill -9 -f "test_experiment.py" 2>/dev/null || true
    pkill -9 -f "test_monitor.py" 2>/dev/null || true
    pkill -9 -f "client.py" 2>/dev/null || true
    sleep 1
}

# Test 1: Basic at-least-once
echo -e "${YELLOW}[1/4] Testing at-least-once (no loss)...${NC}"
python server.py 3000 at-least-once 0.0 &
sleep 2
python test_experiment.py localhost 3000 at-least-once
kill_all_python
echo -e "${GREEN}✓ Passed${NC}\n"

# Test 2: Basic at-most-once
echo -e "${YELLOW}[2/4] Testing at-most-once (no loss)...${NC}"
python server.py 3000 at-most-once 0.0 &
sleep 2
python test_experiment.py localhost 3000 at-most-once
kill_all_python
echo -e "${GREEN}✓ Passed${NC}\n"

# Test 3: With message loss
echo -e "${YELLOW}[3/4] Testing at-most-once with 20% loss...${NC}"
python server.py 3000 at-most-once 0.2 &
sleep 2
python test_experiment.py localhost 3000 at-most-once
kill_all_python
echo -e "${GREEN}✓ Passed${NC}\n"

# Test 4: Monitoring
echo -e "${YELLOW}[4/4] Testing monitoring...${NC}"
python server.py 3000 at-most-once 0.0 &
sleep 2
python test_monitor.py localhost 3000
kill_all_python
echo -e "${GREEN}✓ Passed${NC}\n"

echo -e "${GREEN}All quick tests passed!${NC}"
