#!/bin/bash
# Comprehensive test scenarios for distributed facility booking system

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SERVER_PORT=3000
SERVER_HOST="localhost"

# Helper functions
print_header() {
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}ℹ $1${NC}"
}

wait_for_server() {
    print_info "Waiting for server to start..."
    sleep 2
}

kill_server() {
    if [ ! -z "$SERVER_PID" ]; then
        kill $SERVER_PID 2>/dev/null || true
        # Wait briefly for graceful shutdown
        sleep 0.5
        # Force kill if still running
        kill -9 $SERVER_PID 2>/dev/null || true
        wait $SERVER_PID 2>/dev/null || true
    fi
    # Kill any python processes using the port
    lsof -ti:$SERVER_PORT | xargs kill -9 2>/dev/null || true
    # Kill any remaining server.py or test_*.py processes
    pkill -9 -f "server.py" 2>/dev/null || true
    pkill -9 -f "test_experiment.py" 2>/dev/null || true
    pkill -9 -f "test_monitor.py" 2>/dev/null || true
    pkill -9 -f "client.py" 2>/dev/null || true
    sleep 1
}

cleanup() {
    print_info "Cleaning up background processes..."
    kill_server
    # Kill all background jobs
    jobs -p | xargs kill -9 2>/dev/null || true
    # Kill any remaining Python processes related to the project
    lsof -ti:$SERVER_PORT | xargs kill -9 2>/dev/null || true
    pkill -9 -f "server.py" 2>/dev/null || true
    pkill -9 -f "test_experiment.py" 2>/dev/null || true
    pkill -9 -f "test_monitor.py" 2>/dev/null || true
    pkill -9 -f "client.py" 2>/dev/null || true
    sleep 1
}

# Trap to cleanup on exit
trap cleanup EXIT

# Test Scenario 1: At-Least-Once vs At-Most-Once with No Loss
test_semantics_no_loss() {
    print_header "Test 1: Semantics Comparison (No Message Loss)"

    # Test at-least-once
    print_info "Starting server with at-least-once semantics..."
    python server.py $SERVER_PORT at-least-once 0.0 &
    SERVER_PID=$!
    wait_for_server

    print_info "Running at-least-once experiment..."
    python test_experiment.py $SERVER_HOST $SERVER_PORT at-least-once

    kill_server

    # Test at-most-once
    print_info "Starting server with at-most-once semantics..."
    python server.py $SERVER_PORT at-most-once 0.0 &
    SERVER_PID=$!
    wait_for_server

    print_info "Running at-most-once experiment..."
    python test_experiment.py $SERVER_HOST $SERVER_PORT at-most-once

    kill_server

    print_success "Semantics comparison test completed"
}

# Test Scenario 2: Message Loss Handling
test_message_loss() {
    print_header "Test 2: Message Loss Handling"

    LOSS_RATES=(0.1 0.2 0.3 0.5)

    for LOSS in "${LOSS_RATES[@]}"; do
        print_info "Testing with ${LOSS} ($(echo "$LOSS * 100" | bc)%) message loss rate..."

        # Test with at-least-once
        print_info "  At-least-once with ${LOSS} loss..."
        python server.py $SERVER_PORT at-least-once $LOSS &
        SERVER_PID=$!
        wait_for_server

        python test_experiment.py $SERVER_HOST $SERVER_PORT at-least-once

        kill_server

        # Test with at-most-once
        print_info "  At-most-once with ${LOSS} loss..."
        python server.py $SERVER_PORT at-most-once $LOSS &
        SERVER_PID=$!
        wait_for_server

        python test_experiment.py $SERVER_HOST $SERVER_PORT at-most-once

        kill_server
    done

    print_success "Message loss testing completed"
}

# Test Scenario 3: Concurrent Monitoring
test_monitoring() {
    print_header "Test 3: Concurrent Monitoring"

    print_info "Starting server with at-most-once semantics..."
    python server.py $SERVER_PORT at-most-once 0.0 &
    SERVER_PID=$!
    wait_for_server

    print_info "Running monitoring test..."
    python test_monitor.py $SERVER_HOST $SERVER_PORT

    kill_server

    print_success "Monitoring test completed"
}

# Test Scenario 4: High Message Loss (Stress Test)
test_high_loss() {
    print_header "Test 4: High Message Loss Stress Test"

    print_info "Testing with 70% message loss (extreme scenario)..."

    python server.py $SERVER_PORT at-most-once 0.7 &
    SERVER_PID=$!
    wait_for_server

    print_info "Running experiment with high loss rate..."
    python test_experiment.py $SERVER_HOST $SERVER_PORT at-most-once || print_error "Test failed as expected with high loss"

    kill_server

    print_success "High loss stress test completed"
}

# Test Scenario 5: Idempotent vs Non-Idempotent Operations
test_idempotency() {
    print_header "Test 5: Idempotent vs Non-Idempotent Operations"

    print_info "This test demonstrates the critical difference between:"
    print_info "  - EXTEND (idempotent): Safe to execute multiple times"
    print_info "  - CANCEL (non-idempotent): Only safe with at-most-once"

    # At-least-once should fail for non-idempotent
    print_info "Testing at-least-once (should fail for CANCEL)..."
    python server.py $SERVER_PORT at-least-once 0.0 &
    SERVER_PID=$!
    wait_for_server

    python test_experiment.py $SERVER_HOST $SERVER_PORT at-least-once

    kill_server

    # At-most-once should succeed for both
    print_info "Testing at-most-once (should succeed for both)..."
    python server.py $SERVER_PORT at-most-once 0.0 &
    SERVER_PID=$!
    wait_for_server

    python test_experiment.py $SERVER_HOST $SERVER_PORT at-most-once

    kill_server

    print_success "Idempotency test completed"
}

# Test Scenario 6: All Operations (Quick Test)
test_all_operations() {
    print_header "Test 6: All Operations Quick Test"

    print_info "Starting server..."
    python server.py $SERVER_PORT at-most-once 0.0 &
    SERVER_PID=$!
    wait_for_server

    print_info "Testing all operations..."
    python test_experiment.py $SERVER_HOST $SERVER_PORT at-most-once
    python test_monitor.py $SERVER_HOST $SERVER_PORT

    kill_server

    print_success "All operations test completed"
}

# Main menu
show_menu() {
    echo -e "\n${GREEN}Distributed Facility Booking System - Test Suite${NC}\n"
    echo "1. Semantics Comparison (No Loss)"
    echo "2. Message Loss Handling (Multiple Loss Rates)"
    echo "3. Concurrent Monitoring Test"
    echo "4. High Message Loss Stress Test"
    echo "5. Idempotent vs Non-Idempotent Operations"
    echo "6. All Operations Quick Test"
    echo "7. Run All Tests"
    echo "0. Exit"
    echo ""
}

# Main execution
main() {
    if [ "$1" ]; then
        # Run specific test from command line
        case $1 in
            1) test_semantics_no_loss ;;
            2) test_message_loss ;;
            3) test_monitoring ;;
            4) test_high_loss ;;
            5) test_idempotency ;;
            6) test_all_operations ;;
            7)
                test_semantics_no_loss
                test_message_loss
                test_monitoring
                test_high_loss
                test_idempotency
                ;;
            *) echo "Invalid test number"; exit 1 ;;
        esac
    else
        # Interactive menu
        while true; do
            show_menu
            read -p "Enter choice (0-7): " choice

            case $choice in
                0)
                    print_info "Exiting..."
                    exit 0
                    ;;
                1) test_semantics_no_loss ;;
                2) test_message_loss ;;
                3) test_monitoring ;;
                4) test_high_loss ;;
                5) test_idempotency ;;
                6) test_all_operations ;;
                7)
                    test_semantics_no_loss
                    test_message_loss
                    test_monitoring
                    test_high_loss
                    test_idempotency
                    print_header "ALL TESTS COMPLETED"
                    ;;
                *)
                    print_error "Invalid choice. Please try again."
                    ;;
            esac
        done
    fi
}

# Run main function
main "$@"
