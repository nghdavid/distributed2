#!/bin/bash
# Automated booking script for testing monitor callbacks
#
# This script runs the interactive client and automatically books "Meeting Room A"
# to trigger monitor callbacks for testing the monitoring functionality.
#
# USAGE:
#   ./auto_book.sh
#
# PREREQUISITES:
#   - Server must be running at 44.209.168.3:3000
#   - Monitor clients should be running to receive callbacks
#
# WHAT IT DOES:
#   1. Runs client.py with at-most-once semantics
#   2. Selects option 2 (Book Facility)
#   3. Books "Meeting Room A" for a 1-hour slot
#   4. Exits after booking
#
# CUSTOMIZATION:
#   Edit the variables below to change booking parameters

# ============================================================================
# CONFIGURATION
# ============================================================================
SERVER_HOST="44.209.168.3"
SERVER_PORT="3000"
SEMANTICS="at-most-once"

FACILITY_NAME="Meeting Room A"
START_DAY="0"        # 0 = Monday
START_HOUR="10"
START_MIN="0"
END_DAY="0"          # 0 = Monday
END_HOUR="11"
END_MIN="0"
# ============================================================================

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Starting automated booking...${NC}"
echo "Server: $SERVER_HOST:$SERVER_PORT"
echo "Facility: $FACILITY_NAME"
echo "Time: Day $START_DAY, $START_HOUR:$START_MIN - $END_HOUR:$END_MIN"
echo ""

# Use heredoc to pipe commands to client.py
# Menu option 2 = Book Facility
# Menu option 7 = Exit
python3 client.py "$SERVER_HOST" "$SERVER_PORT" "$SEMANTICS" <<EOF
2
$FACILITY_NAME
$START_DAY
$START_HOUR
$START_MIN
$END_DAY
$END_HOUR
$END_MIN
7
EOF

echo ""
echo -e "${GREEN}Booking request completed!${NC}"
echo "Check monitor clients for callback updates."
