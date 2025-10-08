#!/bin/bash
# Kill all server and client processes

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Killing all server and client processes...${NC}\n"

# Kill processes using port 3000
PORT_PIDS=$(lsof -ti:3000 2>/dev/null)
if [ ! -z "$PORT_PIDS" ]; then
    echo -e "${YELLOW}Killing processes on port 3000:${NC}"
    echo "$PORT_PIDS" | xargs kill -9 2>/dev/null
    echo -e "${GREEN}✓ Port 3000 processes killed${NC}"
else
    echo -e "${GREEN}✓ No processes found on port 3000${NC}"
fi

# Kill all server.py processes
SERVER_PIDS=$(pgrep -f "server.py" 2>/dev/null)
if [ ! -z "$SERVER_PIDS" ]; then
    echo -e "${YELLOW}Killing server.py processes:${NC}"
    pkill -9 -f "server.py"
    echo -e "${GREEN}✓ server.py processes killed${NC}"
else
    echo -e "${GREEN}✓ No server.py processes found${NC}"
fi

# Kill all client.py processes
CLIENT_PIDS=$(pgrep -f "client.py" 2>/dev/null)
if [ ! -z "$CLIENT_PIDS" ]; then
    echo -e "${YELLOW}Killing client.py processes:${NC}"
    pkill -9 -f "client.py"
    echo -e "${GREEN}✓ client.py processes killed${NC}"
else
    echo -e "${GREEN}✓ No client.py processes found${NC}"
fi

# Kill all test script processes
TEST_PIDS=$(pgrep -f "test_experiment.py\|test_monitor.py" 2>/dev/null)
if [ ! -z "$TEST_PIDS" ]; then
    echo -e "${YELLOW}Killing test script processes:${NC}"
    pkill -9 -f "test_experiment.py"
    pkill -9 -f "test_monitor.py"
    echo -e "${GREEN}✓ Test script processes killed${NC}"
else
    echo -e "${GREEN}✓ No test script processes found${NC}"
fi

echo -e "\n${GREEN}All processes cleaned up!${NC}"
