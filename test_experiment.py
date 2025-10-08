"""
Automated testing script to demonstrate the difference between
at-least-once and at-most-once semantics.

This script shows that at-least-once can lead to wrong results for
non-idempotent operations (cancel booking), while at-most-once handles
both idempotent and non-idempotent operations correctly.

USAGE EXAMPLES:
===============

RUNNING ON SAME COMPUTER (localhost):
--------------------------------------

Scenario 1: Test at-least-once semantics
-----------------------------------------
Terminal 1 (Server):
    python server.py 3000 at-least-once 0.0

Terminal 2 (Test):
    python test_experiment.py localhost 3000 at-least-once

Expected Result:
    - EXTEND operation: Both requests succeed (idempotent - safe)
    - CANCEL operation: First succeeds, second fails with "already cancelled" error
    - Demonstrates: At-least-once re-executes duplicate requests


Scenario 2: Test at-most-once semantics
----------------------------------------
Terminal 1 (Server):
    python server.py 3000 at-most-once 0.0

Terminal 2 (Test):
    python test_experiment.py localhost 3000 at-most-once

Expected Result:
    - EXTEND operation: Both requests succeed (duplicate filtered)
    - CANCEL operation: Both requests succeed (duplicate filtered, cached reply)
    - Demonstrates: At-most-once prevents duplicate execution


Scenario 3: Test with message loss (at-least-once)
---------------------------------------------------
Terminal 1 (Server):
    python server.py 3000 at-least-once 0.2    # 20% message loss

Terminal 2 (Test):
    python test_experiment.py localhost 3000 at-least-once

Expected Result:
    - May see timeouts and retries
    - Duplicate execution may occur if reply is lost
    - Non-idempotent operations can fail on retry


Scenario 4: Test with message loss (at-most-once)
--------------------------------------------------
Terminal 1 (Server):
    python server.py 3000 at-most-once 0.2    # 20% message loss

Terminal 2 (Test):
    python test_experiment.py localhost 3000 at-most-once

Expected Result:
    - May see timeouts and retries
    - Duplicate requests are filtered by server
    - Both idempotent and non-idempotent operations work correctly


RUNNING ON DIFFERENT COMPUTERS (network):
------------------------------------------

Scenario 5: Server and test client on different machines
---------------------------------------------------------
Computer 1 (Server) - IP: 192.168.1.100:
    python server.py 3000 at-most-once 0.0

Computer 2 (Test Client):
    # Use the server's IP address instead of localhost
    python test_experiment.py 192.168.1.100 3000 at-most-once

Important Notes for Network Testing:
    - Both computers must be on the same network
    - Firewall must allow UDP traffic on port 3000
    - Server binds to '' (all interfaces) automatically
    - Replace 192.168.1.100 with actual server IP address


Scenario 6: Testing across Internet (cloud/remote)
---------------------------------------------------
Server (Cloud VM - e.g., AWS EC2):
    # Use public IP or domain name
    # Example: Server public IP is 54.123.45.67

    python server.py 3000 at-most-once 0.0

Client (Your local machine):
    python test_experiment.py 54.123.45.67 3000 at-most-once

Important Notes for Internet Testing:
    - Server needs public IP address or domain name
    - Cloud security group must allow UDP port 3000 inbound
    - May experience higher latency and packet loss
    - NAT/router configuration may affect connectivity

WHAT THIS SCRIPT TESTS:
========================

Experiment 1: IDEMPOTENT Operation (EXTEND booking)
----------------------------------------------------
- Books a facility
- Sends EXTEND request with request_id=X
- Sends duplicate EXTEND request with SAME request_id=X (simulates retry)
- Checks if both responses are successful

Expected behavior:
    - At-least-once: Both succeed (operation re-executed, but idempotent)
    - At-most-once: Both succeed (second is cached reply, not re-executed)


Experiment 2: NON-IDEMPOTENT Operation (CANCEL booking)
--------------------------------------------------------
- Books a facility
- Sends CANCEL request with request_id=Y
- Sends duplicate CANCEL request with SAME request_id=Y (simulates retry)
- Checks if both responses are successful

Expected behavior:
    - At-least-once: First succeeds, second fails (operation re-executed)
    - At-most-once: Both succeed (second is cached reply, not re-executed)


KEY LEARNING:
=============
This demonstrates WHY at-most-once semantics is critical for non-idempotent
operations in unreliable networks (like UDP). Without duplicate filtering,
retries can cause operations to be executed multiple times, leading to errors.
"""

import socket
import time
import sys
from marshalling import MessageBuilder, Unmarshaller
from protocol import MessageType, ErrorCode


class TestClient:
    """Test client for running experiments"""

    def __init__(self, server_host: str, server_port: int):
        self.server_host = server_host
        self.server_port = int(server_port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(2.0)
        self.request_id = 1

    def _send_request(self, message: bytes, retries: int = 3) -> tuple:
        """Send request with retries"""
        for attempt in range(retries):
            try:
                self.socket.sendto(message, (self.server_host, self.server_port))
                response, _ = self.socket.recvfrom(65507)
                return response, True
            except socket.timeout:
                if attempt < retries - 1:
                    continue
                return None, False
        return None, False

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

        response, success = self._send_request(builder.build())
        if not success or not response:
            return None

        unmarshaller = Unmarshaller(response)
        msg_type = unmarshaller.unpack_uint8()

        if msg_type == MessageType.BOOK_RESPONSE:
            return unmarshaller.unpack_string()
        return None

    def extend_booking_with_duplicate(self, confirmation_id: str, extension_minutes: int, send_duplicate: bool = False):
        """Extend booking (idempotent), optionally sending duplicate request"""
        builder = MessageBuilder()
        builder.add_uint8(MessageType.EXTEND_BOOKING)
        req_id = self.request_id
        builder.add_uint32(req_id)
        builder.add_string(confirmation_id)
        builder.add_uint32(extension_minutes)
        message = builder.build()

        # Send first request
        print(f"  Sending EXTEND request (request_id={req_id})...")
        response1, success1 = self._send_request(message, retries=1)

        if send_duplicate:
            # Simulate retry by sending the same request again (same request_id)
            print(f"  Sending duplicate EXTEND request (request_id={req_id})...")
            time.sleep(0.1)
            response2, success2 = self._send_request(message, retries=1)

            return [(response1, success1), (response2, success2)]

        return [(response1, success1)]

    def cancel_booking_with_duplicate(self, confirmation_id: str, send_duplicate: bool = False):
        """Cancel booking (non-idempotent), optionally sending duplicate request"""
        builder = MessageBuilder()
        builder.add_uint8(MessageType.CANCEL_BOOKING)
        req_id = self.request_id
        builder.add_uint32(req_id)
        builder.add_string(confirmation_id)
        message = builder.build()

        # Send first request
        print(f"  Sending CANCEL request (request_id={req_id})...")
        response1, success1 = self._send_request(message, retries=1)

        if send_duplicate:
            # Simulate retry by sending the same request again (same request_id)
            print(f"  Sending duplicate CANCEL request (request_id={req_id})...")
            time.sleep(0.1)
            response2, success2 = self._send_request(message, retries=1)

            return [(response1, success1), (response2, success2)]

        return [(response1, success1)]

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
        elif msg_type == MessageType.EXTEND_RESPONSE:
            success = unmarshaller.unpack_bool()
            message = unmarshaller.unpack_string()
            return "EXTEND_SUCCESS", message
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


def run_idempotent_test(semantics: str, host: str, port: int):
    """Test idempotent operation (EXTEND) with duplicates"""
    print_separator()
    print(f"EXPERIMENT 1: IDEMPOTENT OPERATION (EXTEND) - {semantics.upper()}")
    print_separator()

    client = TestClient(host, port)

    # Book a facility
    print("\n1. Booking a facility...")
    conf_id = client.book_facility("Meeting Room A", 0, 10, 0, 0, 11, 0)
    if not conf_id:
        print("  ERROR: Failed to book facility")
        client.close()
        return
    print(f"  SUCCESS: Confirmation ID = {conf_id}")

    # Extend booking with duplicate request
    print("\n2. Extending booking (with duplicate request)...")
    responses = client.extend_booking_with_duplicate(conf_id, 60, send_duplicate=True)

    print("\n3. Analyzing responses:")
    for i, (response, success) in enumerate(responses, 1):
        if success:
            msg_type, data = client.parse_response(response)
            print(f"  Response {i}: {msg_type} - {data}")
        else:
            print(f"  Response {i}: TIMEOUT/NO RESPONSE")

    client.request_id += 1
    client.close()


def run_non_idempotent_test(semantics: str, host: str, port: int):
    """Test non-idempotent operation (CANCEL) with duplicates"""
    print_separator()
    print(f"EXPERIMENT 2: NON-IDEMPOTENT OPERATION (CANCEL) - {semantics.upper()}")
    print_separator()

    client = TestClient(host, port)

    # Book a facility
    print("\n1. Booking a facility...")
    conf_id = client.book_facility("Meeting Room A", 1, 14, 0, 1, 15, 0)
    if not conf_id:
        print("  ERROR: Failed to book facility")
        client.close()
        return
    print(f"  SUCCESS: Confirmation ID = {conf_id}")

    # Cancel booking with duplicate request
    print("\n2. Cancelling booking (with duplicate request)...")
    responses = client.cancel_booking_with_duplicate(conf_id, send_duplicate=True)

    print("\n3. Analyzing responses:")
    for i, (response, success) in enumerate(responses, 1):
        if success:
            msg_type, data = client.parse_response(response)
            print(f"  Response {i}: {msg_type} - {data}")
        else:
            print(f"  Response {i}: TIMEOUT/NO RESPONSE")

    print("\n4. EXPECTED BEHAVIOR:")
    if semantics == 'at-least-once':
        print("  - First response: SUCCESS (booking cancelled)")
        print("  - Second response: ERROR (already cancelled)")
        print("  *** PROBLEM: Non-idempotent operation executed twice! ***")
    else:  # at-most-once
        print("  - First response: SUCCESS (booking cancelled)")
        print("  - Second response: SUCCESS (duplicate filtered, cached reply)")
        print("  *** CORRECT: Non-idempotent operation executed only once! ***")

    client.request_id += 1
    client.close()


def run_experiments(semantics: str, host: str, port: int):
    """Run all experiments for a given semantics"""
    print("\n\n")
    print("#" * 70)
    print(f"# TESTING WITH {semantics.upper()} SEMANTICS")
    print("#" * 70)

    time.sleep(1)
    run_idempotent_test(semantics, host, port)

    time.sleep(2)
    run_non_idempotent_test(semantics, host, port)


def print_summary():
    """Print experiment summary"""
    print("\n\n")
    print("#" * 70)
    print("# EXPERIMENT SUMMARY")
    print("#" * 70)
    print("""
IDEMPOTENT OPERATIONS (e.g., EXTEND):
- At-least-once: Works correctly (safe to execute multiple times)
- At-most-once: Works correctly (duplicate filtering prevents issues)

NON-IDEMPOTENT OPERATIONS (e.g., CANCEL):
- At-least-once: FAILS - executing twice causes errors
  * First execution succeeds
  * Second execution fails with "already cancelled" error
  * Shows that duplicate requests are not filtered

- At-most-once: SUCCEEDS - duplicate filtering ensures single execution
  * First execution succeeds
  * Second execution returns cached reply (not re-executed)
  * Server maintains request history to detect duplicates

CONCLUSION:
At-most-once semantics is necessary for non-idempotent operations to
prevent incorrect behavior due to duplicate request execution.
""")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python test_experiment.py <server_host> <server_port> <semantics>")
        print("  semantics: 'at-least-once', 'at-most-once', or 'both'")
        sys.exit(1)

    host = sys.argv[1]
    port = int(sys.argv[2])
    semantics = sys.argv[3]

    if semantics == 'both':
        print("\nNOTE: You need to run the server with at-least-once first,")
        print("      then restart with at-most-once and run this script again.")
        print()
        response = input("Which semantics is the server currently using? (at-least-once/at-most-once): ").strip()
        run_experiments(response, host, port)
    elif semantics in ['at-least-once', 'at-most-once']:
        run_experiments(semantics, host, port)
        print_summary()
    else:
        print("Error: semantics must be 'at-least-once', 'at-most-once', or 'both'")
        sys.exit(1)
