"""
Test script for server with loss probability.

This script tests the server configured with:
- 0% request loss (all requests succeed)
- 50% reply loss (half of replies are dropped)
- Sends duplicate CANCEL requests (same request_id) to simulate retry after lost reply

USAGE:
======

Terminal 1 (Server with at-most-once):
    python server.py 3000 at-most-once 0.0 0.5
    # 0.0 = request loss, 0.5 = reply loss

Terminal 2 (Test):
    python test_loss_scenario.py localhost 3000 at-most-once

OR

Terminal 1 (Server with at-least-once):
    python server.py 3000 at-least-once 0.0 0.5

Terminal 2 (Test):
    python test_loss_scenario.py localhost 3000 at-least-once

Expected Behavior:
==================
Scenario: Book facility, then try to cancel TWICE with the SAME request_id

AT-MOST-ONCE:
- First CANCEL: Succeeds on server but reply may be lost
- Second CANCEL: Returns cached reply (duplicate detected)
- Result: Both attempts appear successful from client perspective

AT-LEAST-ONCE:
- First CANCEL: Succeeds on server but reply may be lost
- Second CANCEL: Re-executes, gets "already cancelled" error
- Result: First succeeds, second fails (demonstrates non-idempotent problem)

This demonstrates:
- How at-most-once handles duplicate requests safely
- How at-least-once fails with non-idempotent operations
"""

import socket
import time
import sys
from marshalling import MessageBuilder, Unmarshaller
from protocol import MessageType, ErrorCode


class LossTestClient:
    """Test client for loss scenario testing"""

    def __init__(self, server_host: str, server_port: int):
        self.server_host = server_host
        self.server_port = int(server_port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(2.0)
        self.request_id = 1

    def _send_request(self, message: bytes, retries: int = 5) -> tuple:
        """Send request with retries"""
        for attempt in range(retries):
            try:
                self.socket.sendto(message, (self.server_host, self.server_port))
                response, _ = self.socket.recvfrom(65507)
                return response, True, attempt + 1
            except socket.timeout:
                print(f"    Attempt {attempt + 1}: TIMEOUT")
                if attempt < retries - 1:
                    continue
                return None, False, attempt + 1
        return None, False, retries

    def book_facility(self, facility_name: str, start_day: int, start_hour: int, start_min: int,
                     end_day: int, end_hour: int, end_min: int):
        """Book a facility and return confirmation ID"""
        builder = MessageBuilder()
        builder.add_uint8(MessageType.BOOK_FACILITY)
        builder.add_uint32(self.request_id)
        self.request_id += 1
        builder.add_string(facility_name)
        builder.add_time(start_day, start_hour, start_min)
        builder.add_time(end_day, end_hour, end_min)

        response, success, attempts = self._send_request(builder.build())
        if not success or not response:
            return None

        unmarshaller = Unmarshaller(response)
        msg_type = unmarshaller.unpack_uint8()

        if msg_type == MessageType.BOOK_RESPONSE:
            return unmarshaller.unpack_string()
        return None

    def cancel_booking(self, confirmation_id: str, use_request_id: int = None) -> tuple:
        """
        Cancel booking (non-idempotent operation).
        Returns (response, success, attempts, request_id_used)

        If use_request_id is provided, uses that instead of incrementing.
        """
        if use_request_id is not None:
            req_id = use_request_id
        else:
            req_id = self.request_id
            self.request_id += 1

        builder = MessageBuilder()
        builder.add_uint8(MessageType.CANCEL_BOOKING)
        builder.add_uint32(req_id)
        builder.add_string(confirmation_id)
        message = builder.build()

        print(f"  Sending CANCEL request (request_id={req_id})...")
        response, success, attempts = self._send_request(message, retries=1)

        return response, success, attempts, req_id

    def parse_response(self, response: bytes):
        """Parse and return response details"""
        if not response:
            return None, None

        unmarshaller = Unmarshaller(response)
        msg_type = unmarshaller.unpack_uint8()

        if msg_type == MessageType.ERROR:
            error_code = unmarshaller.unpack_uint8()
            error_message = unmarshaller.unpack_string()
            return "ERROR", (error_code, error_message)
        elif msg_type == MessageType.CANCEL_RESPONSE:
            success = unmarshaller.unpack_bool()
            message = unmarshaller.unpack_string()
            return "CANCEL_SUCCESS", message

        return "UNKNOWN", None

    def close(self):
        """Close socket"""
        self.socket.close()


def print_separator():
    print("\n" + "="*70)


def run_loss_test(host: str, port: int, semantics: str):
    """Test non-idempotent operations with reply loss"""
    print_separator()
    print("LOSS SCENARIO TEST: DUPLICATE CANCEL REQUESTS")
    print(f"Semantics: {semantics.upper()}")
    print("Server configured: 0% request loss, 50% reply loss")
    print_separator()

    client = LossTestClient(host, port)

    # Step 1: Book a facility
    print("\n1. Booking a facility...")
    print("  Booking Meeting Room A...")
    conf_id = client.book_facility("Meeting Room A", 0, 10, 0, 0, 11, 0)
    if not conf_id:
        print("  ERROR: Failed to book facility - SHUTTING DOWN")
        client.close()
        return
    print(f"  SUCCESS: Booking ID = {conf_id}")

    # Step 2: Try to cancel TWICE with the SAME request_id (simulating retry)
    print("\n2. Attempting to cancel (will send same request twice)...")
    print("  This simulates: first CANCEL succeeds but reply is lost, client retries")
    print()

    # First CANCEL attempt
    print("First CANCEL attempt:")
    response_1, success_1, attempts_1, req_id = client.cancel_booking(conf_id)

    if success_1:
        msg_type, data = client.parse_response(response_1)
        print(f"  Status: {msg_type}")
        print(f"  Message: {data}")
    else:
        print(f"  Status: TIMEOUT (no reply received)")

    time.sleep(0.5)  # Small delay between attempts

    # Second CANCEL attempt with SAME request_id (simulating retry)
    print("\nSecond CANCEL attempt (SAME request_id - simulating retry after timeout):")
    response_2, success_2, attempts_2, _ = client.cancel_booking(conf_id, use_request_id=req_id)

    if success_2:
        msg_type, data = client.parse_response(response_2)
        print(f"  Status: {msg_type}")
        print(f"  Message: {data}")
    else:
        print(f"  Status: TIMEOUT (no reply received)")

    # Analyze results
    print("\n3. ANALYSIS:")
    print_separator()

    if semantics == 'at-most-once':
        print(f"""
Results with AT-MOST-ONCE semantics:
- First CANCEL (request_id={req_id}): {'Received reply' if success_1 else 'TIMEOUT (reply lost)'}
- Second CANCEL (request_id={req_id}): {'Received reply' if success_2 else 'TIMEOUT (reply lost)'}

Expected Behavior:
- Server detects duplicate request (same request_id)
- Returns CACHED reply (does not re-execute CANCEL)
- Both attempts should receive success response (when not lost)
- Booking is cancelled exactly ONCE

Key Insight:
At-most-once semantics uses request history to return cached replies,
preventing duplicate execution of non-idempotent operations.
        """)
    else:  # at-least-once
        print(f"""
Results with AT-LEAST-ONCE semantics:
- First CANCEL (request_id={req_id}): {'Received reply' if success_1 else 'TIMEOUT (reply lost)'}
- Second CANCEL (request_id={req_id}): {'Received reply' if success_2 else 'TIMEOUT (reply lost)'}

Expected Behavior:
- Server does NOT detect duplicates (no request history)
- Re-executes CANCEL operation on second attempt
- First execution: SUCCESS (booking cancelled)
- Second execution: ERROR "already cancelled"

Key Insight:
At-least-once semantics re-executes every request, causing errors
when non-idempotent operations are retried (even with same request_id).
        """)

    client.close()


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python test_loss_scenario.py <server_host> <server_port> <semantics>")
        print("  semantics: 'at-least-once' or 'at-most-once'")
        print("\nExamples:")
        print("  AT-MOST-ONCE (handles duplicate requests safely):")
        print("    Terminal 1: python server.py 3000 at-most-once 0.0 0.5")
        print("    Terminal 2: python test_loss_scenario.py localhost 3000 at-most-once")
        print("\n  AT-LEAST-ONCE (duplicate requests cause errors):")
        print("    Terminal 1: python server.py 3000 at-least-once 0.0 0.5")
        print("    Terminal 2: python test_loss_scenario.py localhost 3000 at-least-once")
        print("\n  (0.0 = request loss, 0.5 = 50% reply loss)")
        sys.exit(1)

    host = sys.argv[1]
    port = int(sys.argv[2])
    semantics = sys.argv[3]

    if semantics not in ['at-least-once', 'at-most-once']:
        print("Error: semantics must be 'at-least-once' or 'at-most-once'")
        sys.exit(1)

    run_loss_test(host, port, semantics)
