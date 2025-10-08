#!/bin/bash
# Automated booking script for testing monitor callbacks
#
# This script runs the interactive client and automatically books "Meeting Room A"
# to trigger monitor callbacks for testing the monitoring functionality.
#
# USAGE:
#   ./auto_book.sh [start_day] [end_day]
#
# PARAMETERS:
#   start_day   : Day of week for start (0-6, where 0=Monday, default: 0)
#   end_day     : Day of week for end (0-6, where 0=Monday, default: 0)
#
# EXAMPLES:
#   ./auto_book.sh        # Book Monday 10:00-11:00
#   ./auto_book.sh 0 0    # Book Monday 10:00-11:00
#   ./auto_book.sh 1 1    # Book Tuesday 10:00-11:00
#   ./auto_book.sh 2 2    # Book Wednesday 10:00-11:00
#
# PREREQUISITES:
#   - Server must be running at localhost:3000
#   - Monitor clients should be running to receive callbacks
#
# WHAT IT DOES:
#   1. Runs client.py with at-most-once semantics
#   2. Selects option 2 (Book Facility)
#   3. Books "Meeting Room A" for specified time slot
#   4. Exits after booking
#
# CUSTOMIZATION:
#   Edit the variables below to change default booking parameters

# ============================================================================
# CONFIGURATION
# ============================================================================
SERVER_HOST="localhost"
SERVER_PORT="3000"
SEMANTICS="at-most-once"

FACILITY_NAME="Meeting Room A"

# Default values (can be overridden by command line arguments)
DEFAULT_START_DAY="0"        # 0 = Monday
DEFAULT_START_HOUR="10"
DEFAULT_START_MIN="0"
DEFAULT_END_DAY="0"          # 0 = Monday
DEFAULT_END_HOUR="11"
DEFAULT_END_MIN="0"

# Parse command line arguments
START_DAY="${1:-$DEFAULT_START_DAY}"
END_DAY="${2:-$DEFAULT_END_DAY}"
START_HOUR="$DEFAULT_START_HOUR"
START_MIN="$DEFAULT_START_MIN"
END_HOUR="$DEFAULT_END_HOUR"
END_MIN="$DEFAULT_END_MIN"
# ============================================================================

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Day names for display
DAY_NAMES=("Monday" "Tuesday" "Wednesday" "Thursday" "Friday" "Saturday" "Sunday")

echo -e "${YELLOW}Starting automated booking...${NC}"
echo "Server: $SERVER_HOST:$SERVER_PORT"
echo "Facility: $FACILITY_NAME"
echo "Time: ${DAY_NAMES[$START_DAY]} $START_HOUR:$START_MIN - ${DAY_NAMES[$END_DAY]} $END_HOUR:$END_MIN"
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
