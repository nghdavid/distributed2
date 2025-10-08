"""
Test script for monitoring functionality - Single Client Version
Allows running one monitor client per execution for distributed testing.

This script tests the server callback mechanism where:
1. Client registers to monitor a facility
2. Server sends callbacks when bookings change
3. Client receives and displays availability updates in real-time

USAGE:
======

Basic Usage:
------------
python test_monitor.py <server_host> <server_port> [client_id]

Parameters:
    server_host  : Server IP address or hostname (e.g., localhost or 192.168.1.100)
    server_port  : Server port number (e.g., 3000)
    client_id    : Optional client identifier for display (default: 1)

Configuration (edit in file):
    FACILITY_NAME   : Facility to monitor (default: "Meeting Room A")
    MONITOR_DURATION: Monitoring duration in seconds (default: 1200)
    CLIENT_BIND_IP  : Client IP to bind to (default: '' = all interfaces)
    CLIENT_BIND_PORT: Client port to bind to (default: 0 = random port)


EXAMPLES:
=========

Internet/Cloud Testing
----------------------
Server (Cloud VM) - Public IP: 44.209.168.3:
    python server.py 3000 at-most-once 0.0

Client 1 (Your computer):
    python test_monitor.py 44.209.168.3 3000 1

Client 2 (Friend's computer):
    python test_monitor.py 44.209.168.3 3000 2

Client 3 (Another location - make bookings to trigger updates):
    python client.py 44.209.168.3 3000 at-most-once
    # Use menu option 2 to book "Meeting Room A"
    # All monitors receive updates over Internet

Note: Facility name and duration are configured in the script file (FACILITY_NAME and MONITOR_DURATION)

What happens:
    - Each computer runs one monitor client
    - When booking is made, server sends callbacks to ALL registered monitors
    - Each monitor displays the update independently
    - Demonstrates distributed callback mechanism across Internet


TESTING SCENARIOS:
==================

Scenario 1: Test callback mechanism
------------------------------------
1. Start server
2. Start monitor client (this script)
3. From another terminal/computer, use interactive client to book the facility
4. Monitor should receive and display the update
5. Make more bookings - monitor receives each update

HOW IT WORKS:
=============

1. Registration:
   - Client sends MONITOR_REGISTER request to server
   - Request includes: facility name, duration, request ID
   - Server extracts client IP:port from UDP packet
   - Server stores: (facility, client_addr, expiry_time)

2. Callback:
   - When booking/change/cancel happens, server calls _notify_monitors()
   - Server finds all monitors registered for that facility
   - Server sends MONITOR_UPDATE to each registered client address
   - Client receives update and displays availability
"""

import socket
import time
import sys
from marshalling import MessageBuilder, Unmarshaller
from protocol import MessageType


# ============================================================================
# CONFIGURATION - Edit these values to change monitoring settings
# ============================================================================
FACILITY_NAME = "Meeting Room A"  # Name of facility to monitor
MONITOR_DURATION = 1200            # Monitoring duration in seconds (20 minutes)

# Client socket binding configuration
# Set to empty string '' to bind to all interfaces (default)
# Set to specific IP like '192.168.1.100' to bind to specific interface
CLIENT_BIND_IP = ''                # Client IP to bind ('' = all interfaces, default)
CLIENT_BIND_PORT = 3001               # Client port to bind (0 = random port, default)
# ============================================================================


class MonitorClient:
    """Single monitor client for testing monitoring functionality"""

    def __init__(self, server_host: str, server_port: int, client_id: int):
        """
        Initialize monitor client.

        Args:
            server_host: Server IP address or hostname
            server_port: Server port number
            client_id: Client identifier for display purposes
        """
        self.server_host = server_host
        self.server_port = int(server_port)
        self.client_id = client_id

        # Create UDP socket
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Bind to specific IP and port (configured at top of file)
        # This determines which local IP:port the client uses
        # Server will send callbacks to this IP:port
        try:
            self.socket.bind((CLIENT_BIND_IP, CLIENT_BIND_PORT))
            # Get the actual address after binding (especially if port was 0)
            actual_addr = self.socket.getsockname()
            print(f"[Client {client_id}] Bound to local address: {actual_addr[0]}:{actual_addr[1]}")
        except OSError as e:
            print(f"[Client {client_id}] WARNING: Could not bind to {CLIENT_BIND_IP}:{CLIENT_BIND_PORT}")
            print(f"[Client {client_id}] Error: {e}")
            print(f"[Client {client_id}] Using default binding instead")

        self.socket.settimeout(1.0)  # 1 second timeout for receiving updates
        self.request_id = 1

    def monitor_facility(self, facility_name: str, duration_seconds: int):
        """
        Monitor a facility and receive availability updates via server callbacks.

        Process:
        1. Send registration request to server
        2. Wait for confirmation
        3. Listen for callback updates during monitoring period
        4. Display each update received
        5. Exit when monitoring period expires

        Args:
            facility_name: Name of facility to monitor
            duration_seconds: How long to monitor (in seconds)
        """
        print(f"\n{'='*70}")
        print(f"MONITOR CLIENT {self.client_id}")
        print(f"{'='*70}")
        print(f"Server: {self.server_host}:{self.server_port}")
        print(f"Facility: '{facility_name}'")
        print(f"Duration: {duration_seconds} seconds")
        print(f"{'='*70}\n")

        # Build and send monitor registration request
        print(f"[Client {self.client_id}] Registering to monitor '{facility_name}'...")
        builder = MessageBuilder()
        builder.add_uint8(MessageType.MONITOR_REGISTER)
        builder.add_uint32(self.request_id)
        builder.add_string(facility_name)
        builder.add_uint32(duration_seconds)

        try:
            # Send registration request
            self.socket.sendto(builder.build(), (self.server_host, self.server_port))

            # Wait for confirmation response
            response, _ = self.socket.recvfrom(65507)
            unmarshaller = Unmarshaller(response)
            msg_type = unmarshaller.unpack_uint8()

            if msg_type == MessageType.ERROR:
                # Handle error response
                error_code = unmarshaller.unpack_uint8()
                error_message = unmarshaller.unpack_string()
                print(f"[Client {self.client_id}] ERROR: {error_message}")
                return

            if msg_type == MessageType.MONITOR_RESPONSE:
                # Registration successful
                success = unmarshaller.unpack_bool()
                message = unmarshaller.unpack_string()
                print(f"[Client {self.client_id}] ✓ {message}")
                print(f"[Client {self.client_id}] Waiting for updates...\n")

                # Calculate end time for monitoring
                end_time = time.time() + duration_seconds
                update_count = 0

                # Listen for callbacks during monitoring period
                while time.time() < end_time:
                    try:
                        # Wait for update from server
                        data, server_addr = self.socket.recvfrom(65507)
                        unmarshaller = Unmarshaller(data)
                        msg_type = unmarshaller.unpack_uint8()

                        if msg_type == MessageType.MONITOR_UPDATE:
                            # Received availability update callback
                            update_count += 1
                            timestamp = time.strftime("%H:%M:%S")
                            print(f"\n[{timestamp}] [Client {self.client_id}] 📢 UPDATE #{update_count} RECEIVED")
                            print(f"{'─'*70}")
                            self._display_update(unmarshaller)
                            print(f"{'─'*70}\n")

                    except socket.timeout:
                        # No update received, continue waiting
                        continue

                # Monitoring period ended
                print(f"\n{'='*70}")
                print(f"[Client {self.client_id}] Monitoring period ended")
                print(f"[Client {self.client_id}] Total updates received: {update_count}")
                print(f"{'='*70}\n")

        except socket.timeout:
            print(f"[Client {self.client_id}] ERROR: Timeout waiting for server response")
            print(f"[Client {self.client_id}] Check that server is running at {self.server_host}:{self.server_port}")
        except Exception as e:
            print(f"[Client {self.client_id}] ERROR: {e}")
        finally:
            self.socket.close()

    def _display_update(self, unmarshaller: Unmarshaller):
        """
        Display availability update received from server.

        Args:
            unmarshaller: Unmarshaller containing the update data
        """
        facility_name = unmarshaller.unpack_string()
        num_days = unmarshaller.unpack_uint32()

        print(f"Facility: {facility_name}")
        print(f"Updated availability for {num_days} day(s):\n")

        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

        for _ in range(num_days):
            day = unmarshaller.unpack_uint8()
            num_slots = unmarshaller.unpack_uint32()

            print(f"  {day_names[day]}:")
            if num_slots == 0:
                print(f"    Fully booked (no available slots)")
            else:
                for slot_num in range(num_slots):
                    start_day, start_hour, start_min = unmarshaller.unpack_time()
                    end_day, end_hour, end_min = unmarshaller.unpack_time()
                    print(f"    Slot {slot_num + 1}: {start_hour:02d}:{start_min:02d} - {end_hour:02d}:{end_min:02d}")


def print_usage():
    """Print usage instructions"""
    print("\nUsage: python test_monitor.py <server_host> <server_port> [client_id]")
    print("\nParameters:")
    print("  server_host   : Server IP address or hostname (e.g., localhost, 192.168.1.100)")
    print("  server_port   : Server port number (e.g., 3000)")
    print("  client_id     : Optional client identifier for display (default: 1)")
    print("\nConfiguration (edit in file):")
    print(f"  FACILITY_NAME    : Currently set to '{FACILITY_NAME}'")
    print(f"  MONITOR_DURATION : Currently set to {MONITOR_DURATION} seconds")
    print(f"  CLIENT_BIND_IP   : Currently set to '{CLIENT_BIND_IP}' ('' = all interfaces)")
    print(f"  CLIENT_BIND_PORT : Currently set to {CLIENT_BIND_PORT} (0 = random port)")
    print("\nExamples:")
    print('  python test_monitor.py localhost 3000')
    print('  python test_monitor.py 192.168.1.100 3000 2')
    print('  python test_monitor.py 44.209.168.3 3000 1')
    print("\nClient Socket Binding:")
    print("  - By default, client uses random port (CLIENT_BIND_PORT = 0)")
    print("  - Server sends callbacks to the IP:port it sees in registration packet")
    print("  - To use specific port, set CLIENT_BIND_PORT (e.g., 5000)")
    print("  - To use specific IP, set CLIENT_BIND_IP (e.g., '192.168.1.100')")
    print("  - Useful for firewall rules or NAT port forwarding")
    print("\nTip: Run multiple instances with different client_id to test concurrent monitoring")
    print()


if __name__ == "__main__":
    # Check command line arguments
    if len(sys.argv) < 3:
        print("\nERROR: Missing required arguments")
        print_usage()
        sys.exit(1)

    # Parse arguments
    server_host = sys.argv[1]
    server_port = int(sys.argv[2])
    client_id = int(sys.argv[3]) if len(sys.argv) > 3 else 1

    # Validate arguments
    if server_port < 1 or server_port > 65535:
        print(f"\nERROR: Invalid port number {server_port}. Must be between 1 and 65535.")
        sys.exit(1)

    # Create and run monitor client with configured facility and duration
    try:
        client = MonitorClient(server_host, server_port, client_id)
        client.monitor_facility(FACILITY_NAME, MONITOR_DURATION)
    except KeyboardInterrupt:
        print(f"\n\n[Client {client_id}] Monitoring stopped by user (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nFATAL ERROR: {e}")
        sys.exit(1)
