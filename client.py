"""
Distributed Facility Booking System - Client

This client provides an interactive command-line interface for users to access
the facility booking services provided by the server.

Key Features:
- UDP-based communication with automatic retries on timeout
- Support for both at-least-once and at-most-once semantics
- Interactive menu-driven interface
- All six required services:
  1. Query facility availability
  2. Book facility
  3. Change booking
  4. Monitor facility (with server callbacks)
  5. Extend booking (IDEMPOTENT)
  6. Cancel booking (NON-IDEMPOTENT)

Architecture:
- Single-threaded (as per requirements)
- Blocking during monitor period (user cannot input new requests while monitoring)
- Automatic retry logic with configurable timeout and max retries
"""

import socket
import time
import sys
from typing import Optional, Tuple
from protocol import MessageType, ErrorCode, DayOfWeek, TIMEOUT_SECONDS, MAX_RETRIES
from marshalling import MessageBuilder, Unmarshaller


class FacilityBookingClient:
    """
    Client for facility booking system.

    Handles:
    - Building and sending requests to server
    - Receiving and parsing responses
    - Retry logic for fault tolerance
    - User interface and input validation
    """

    def __init__(self, server_host: str, server_port: int, semantics: str):
        """
        Initialize the client.

        Args:
            server_host: Server IP address or hostname
            server_port: Server UDP port number
            semantics: 'at-least-once' or 'at-most-once'
        """
        self.server_host = server_host
        self.server_port = int(server_port)
        self.semantics = semantics  # Stored for display purposes
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(TIMEOUT_SECONDS)  # Set timeout for recvfrom
        self.next_request_id = 1  # Counter for unique request IDs

    def _get_request_id(self) -> int:
        """
        Get next request ID for this client.
        Each request has a unique ID used by server for duplicate detection.
        """
        request_id = self.next_request_id
        self.next_request_id += 1
        return request_id

    def _send_request(self, message: bytes, expect_updates: bool = False) -> Optional[bytes]:
        """
        Send request to server and wait for response with retry logic.

        Retry Mechanism:
        1. Send request to server
        2. Wait for response (with timeout)
        3. If timeout occurs:
           - Retry up to MAX_RETRIES times
           - Retransmit the SAME request (same request_id)
        4. Return response or None if all retries fail

        This implements the client-side of both invocation semantics:
        - At-least-once: Each retry may cause re-execution (if server lost request)
        - At-most-once: Server filters duplicates, safe to retry

        Args:
            message: The marshalled request bytes to send
            expect_updates: True for monitor requests (special handling)

        Returns:
            Response bytes from server, or None if all retries failed
        """
        retries = 0

        while retries < MAX_RETRIES:
            try:
                # Send request to server
                self.socket.sendto(message, (self.server_host, self.server_port))

                if expect_updates:
                    # For monitor requests, don't retry, just wait for initial response
                    # Updates will be sent by server via callbacks
                    response, _ = self.socket.recvfrom(65507)
                    return response

                # Wait for response (will timeout after TIMEOUT_SECONDS)
                response, _ = self.socket.recvfrom(65507)
                return response

            except socket.timeout:
                # No response received - retry
                retries += 1
                if retries < MAX_RETRIES:
                    print(f"Timeout, retrying... (attempt {retries + 1}/{MAX_RETRIES})")
                else:
                    print("Maximum retries reached, request failed")
                    return None

        return None

    def _parse_error_response(self, unmarshaller: Unmarshaller):
        """Parse and display error response"""
        error_code = unmarshaller.unpack_uint8()
        error_message = unmarshaller.unpack_string()
        print(f"\nError [{error_code}]: {error_message}")

    def query_availability(self, facility_name: str, days: list):
        """Query facility availability"""
        print(f"\nQuerying availability for '{facility_name}' on days {days}...")

        builder = MessageBuilder()
        builder.add_uint8(MessageType.QUERY_AVAILABILITY)
        builder.add_uint32(self._get_request_id())
        builder.add_string(facility_name)
        builder.add_list_of_ints(days)

        response = self._send_request(builder.build())
        if not response:
            return

        unmarshaller = Unmarshaller(response)
        msg_type = unmarshaller.unpack_uint8()

        if msg_type == MessageType.ERROR:
            self._parse_error_response(unmarshaller)
            return

        if msg_type == MessageType.QUERY_RESPONSE:
            facility_name = unmarshaller.unpack_string()
            num_days = unmarshaller.unpack_uint32()

            print(f"\nAvailability for '{facility_name}':")
            day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

            for _ in range(num_days):
                day = unmarshaller.unpack_uint8()
                num_slots = unmarshaller.unpack_uint32()

                print(f"\n  {day_names[day]}:")
                if num_slots == 0:
                    print("    No available slots")
                else:
                    for _ in range(num_slots):
                        start_day, start_hour, start_min = unmarshaller.unpack_time()
                        end_day, end_hour, end_min = unmarshaller.unpack_time()
                        print(f"    {start_hour:02d}:{start_min:02d} - {end_hour:02d}:{end_min:02d}")

    def book_facility(self, facility_name: str, start_day: int, start_hour: int, start_min: int,
                     end_day: int, end_hour: int, end_min: int):
        """Book a facility"""
        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        print(f"\nBooking '{facility_name}' from {day_names[start_day]} {start_hour:02d}:{start_min:02d} "
              f"to {day_names[end_day]} {end_hour:02d}:{end_min:02d}...")

        builder = MessageBuilder()
        builder.add_uint8(MessageType.BOOK_FACILITY)
        builder.add_uint32(self._get_request_id())
        builder.add_string(facility_name)
        builder.add_time(start_day, start_hour, start_min)
        builder.add_time(end_day, end_hour, end_min)

        response = self._send_request(builder.build())
        if not response:
            return

        unmarshaller = Unmarshaller(response)
        msg_type = unmarshaller.unpack_uint8()

        if msg_type == MessageType.ERROR:
            self._parse_error_response(unmarshaller)
            return

        if msg_type == MessageType.BOOK_RESPONSE:
            confirmation_id = unmarshaller.unpack_string()
            print(f"\nBooking successful!")
            print(f"Confirmation ID: {confirmation_id}")

    def change_booking(self, confirmation_id: str, offset_minutes: int):
        """Change a booking by offset"""
        direction = "advance" if offset_minutes < 0 else "postpone"
        print(f"\nChanging booking {confirmation_id} to {direction} by {abs(offset_minutes)} minutes...")

        builder = MessageBuilder()
        builder.add_uint8(MessageType.CHANGE_BOOKING)
        builder.add_uint32(self._get_request_id())
        builder.add_string(confirmation_id)
        builder.add_int32(offset_minutes)

        response = self._send_request(builder.build())
        if not response:
            return

        unmarshaller = Unmarshaller(response)
        msg_type = unmarshaller.unpack_uint8()

        if msg_type == MessageType.ERROR:
            self._parse_error_response(unmarshaller)
            return

        if msg_type == MessageType.CHANGE_RESPONSE:
            success = unmarshaller.unpack_bool()
            if success:
                print(f"\nBooking changed successfully!")

    def monitor_facility(self, facility_name: str, duration_seconds: int):
        """
        Monitor facility availability through server callbacks.

        Monitoring Process:
        1. Send registration request to server with facility name and duration
        2. Receive initial confirmation from server
        3. Block and wait for server callbacks (MONITOR_UPDATE messages)
        4. Display each update as it arrives
        5. After duration expires, stop monitoring

        Important:
        - Client is BLOCKED during monitoring period (as per requirements)
        - User cannot input new requests while monitoring
        - Server sends callbacks whenever the facility's availability changes
        - Multiple clients can monitor the same facility concurrently
        """
        print(f"\nRegistering to monitor '{facility_name}' for {duration_seconds} seconds...")

        # Build registration request
        builder = MessageBuilder()
        builder.add_uint8(MessageType.MONITOR_REGISTER)
        builder.add_uint32(self._get_request_id())
        builder.add_string(facility_name)
        builder.add_uint32(duration_seconds)

        # Send request and wait for initial confirmation
        response = self._send_request(builder.build(), expect_updates=True)
        if not response:
            return

        unmarshaller = Unmarshaller(response)
        msg_type = unmarshaller.unpack_uint8()

        if msg_type == MessageType.ERROR:
            self._parse_error_response(unmarshaller)
            return

        if msg_type == MessageType.MONITOR_RESPONSE:
            success = unmarshaller.unpack_bool()
            message = unmarshaller.unpack_string()
            print(f"\n{message}")
            print("Waiting for updates... (press Ctrl+C to stop)\n")

        # Wait for callbacks from server during the monitoring period
        end_time = time.time() + duration_seconds
        self.socket.settimeout(1.0)  # Short timeout to check if period has ended

        try:
            while time.time() < end_time:
                try:
                    # Wait for callback from server
                    data, _ = self.socket.recvfrom(65507)
                    unmarshaller = Unmarshaller(data)
                    msg_type = unmarshaller.unpack_uint8()

                    if msg_type == MessageType.MONITOR_UPDATE:
                        # Server sent an availability update
                        self._display_availability_update(unmarshaller)

                except socket.timeout:
                    # No update received, continue waiting
                    continue

        except KeyboardInterrupt:
            print("\nMonitoring stopped by user")

        finally:
            self.socket.settimeout(TIMEOUT_SECONDS)  # Restore normal timeout
            print("\nMonitoring period ended")

    def _display_availability_update(self, unmarshaller: Unmarshaller):
        """Display availability update from server"""
        facility_name = unmarshaller.unpack_string()
        num_days = unmarshaller.unpack_uint32()

        print(f"\n{'='*60}")
        print(f"UPDATE: Availability changed for '{facility_name}'")
        print(f"{'='*60}")

        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

        for _ in range(num_days):
            day = unmarshaller.unpack_uint8()
            num_slots = unmarshaller.unpack_uint32()

            print(f"\n  {day_names[day]}:")
            if num_slots == 0:
                print("    Fully booked")
            else:
                for _ in range(num_slots):
                    start_day, start_hour, start_min = unmarshaller.unpack_time()
                    end_day, end_hour, end_min = unmarshaller.unpack_time()
                    print(f"    {start_hour:02d}:{start_min:02d} - {end_hour:02d}:{end_min:02d}")

        print(f"{'='*60}\n")

    def extend_booking(self, confirmation_id: str, extension_minutes: int):
        """
        Extend a booking (IDEMPOTENT operation).

        This service extends the end time of an existing booking.
        Marked as IDEMPOTENT - safe to execute multiple times with at-least-once semantics.
        """
        print(f"\nExtending booking {confirmation_id} by {extension_minutes} minutes...")

        # Build extend request
        builder = MessageBuilder()
        builder.add_uint8(MessageType.EXTEND_BOOKING)
        builder.add_uint32(self._get_request_id())
        builder.add_string(confirmation_id)
        builder.add_uint32(extension_minutes)

        # Send request with automatic retry
        response = self._send_request(builder.build())
        if not response:
            return

        # Parse and display response
        unmarshaller = Unmarshaller(response)
        msg_type = unmarshaller.unpack_uint8()

        if msg_type == MessageType.ERROR:
            self._parse_error_response(unmarshaller)
            return

        if msg_type == MessageType.EXTEND_RESPONSE:
            success = unmarshaller.unpack_bool()
            message = unmarshaller.unpack_string()
            if success:
                print(f"\n{message}")

    def cancel_booking(self, confirmation_id: str):
        """
        Cancel a booking (NON-IDEMPOTENT operation).

        This service cancels an existing booking.
        Marked as NON-IDEMPOTENT - executing twice causes different results:
        - First execution: Success
        - Second execution: Error (already cancelled)

        This demonstrates why at-most-once semantics is necessary for
        non-idempotent operations in unreliable networks.
        """
        print(f"\nCancelling booking {confirmation_id}...")

        # Build cancel request
        builder = MessageBuilder()
        builder.add_uint8(MessageType.CANCEL_BOOKING)
        builder.add_uint32(self._get_request_id())
        builder.add_string(confirmation_id)

        # Send request with automatic retry
        response = self._send_request(builder.build())
        if not response:
            return

        # Parse and display response
        unmarshaller = Unmarshaller(response)
        msg_type = unmarshaller.unpack_uint8()

        if msg_type == MessageType.ERROR:
            self._parse_error_response(unmarshaller)
            return

        if msg_type == MessageType.CANCEL_RESPONSE:
            success = unmarshaller.unpack_bool()
            message = unmarshaller.unpack_string()
            if success:
                print(f"\n{message}")

    def show_menu(self):
        """Display menu options"""
        print("\n" + "="*60)
        print("Facility Booking System Client")
        print(f"Semantics: {self.semantics}")
        print("="*60)
        print("\n1. Query Availability")
        print("2. Book Facility")
        print("3. Change Booking")
        print("4. Monitor Facility")
        print("5. Extend Booking (Idempotent)")
        print("6. Cancel Booking (Non-Idempotent)")
        print("7. Exit")
        print()

    def run(self):
        """Main client loop"""
        while True:
            self.show_menu()
            choice = input("Enter choice (1-7): ").strip()

            if choice == '1':
                facility_name = input("Enter facility name: ").strip()
                days_input = input("Enter days (0=Mon, 1=Tue, ..., 6=Sun, comma-separated): ").strip()
                try:
                    days = [int(d.strip()) for d in days_input.split(',')]
                    self.query_availability(facility_name, days)
                except ValueError:
                    print("Invalid day format")

            elif choice == '2':
                facility_name = input("Enter facility name: ").strip()
                try:
                    start_day = int(input("Start day (0=Mon, 1=Tue, ..., 6=Sun): ").strip())
                    start_hour = int(input("Start hour (0-23): ").strip())
                    start_min = int(input("Start minute (0-59): ").strip())
                    end_day = int(input("End day (0=Mon, 1=Tue, ..., 6=Sun): ").strip())
                    end_hour = int(input("End hour (0-23): ").strip())
                    end_min = int(input("End minute (0-59): ").strip())
                    self.book_facility(facility_name, start_day, start_hour, start_min,
                                     end_day, end_hour, end_min)
                except ValueError:
                    print("Invalid input format")

            elif choice == '3':
                confirmation_id = input("Enter confirmation ID: ").strip()
                try:
                    offset = int(input("Enter offset in minutes (negative to advance, positive to postpone): ").strip())
                    self.change_booking(confirmation_id, offset)
                except ValueError:
                    print("Invalid offset format")

            elif choice == '4':
                facility_name = input("Enter facility name: ").strip()
                try:
                    duration = int(input("Enter monitoring duration in seconds: ").strip())
                    self.monitor_facility(facility_name, duration)
                except ValueError:
                    print("Invalid duration format")

            elif choice == '5':
                confirmation_id = input("Enter confirmation ID: ").strip()
                try:
                    extension = int(input("Enter extension in minutes: ").strip())
                    self.extend_booking(confirmation_id, extension)
                except ValueError:
                    print("Invalid extension format")

            elif choice == '6':
                confirmation_id = input("Enter confirmation ID: ").strip()
                self.cancel_booking(confirmation_id)

            elif choice == '7':
                print("\nExiting client...")
                break

            else:
                print("\nInvalid choice, please try again")

        self.socket.close()


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python client.py <server_host> <server_port> <semantics>")
        print("  semantics: 'at-least-once' or 'at-most-once'")
        sys.exit(1)

    server_host = sys.argv[1]
    server_port = int(sys.argv[2])
    semantics = sys.argv[3]

    if semantics not in ['at-least-once', 'at-most-once']:
        print("Error: semantics must be 'at-least-once' or 'at-most-once'")
        sys.exit(1)

    client = FacilityBookingClient(server_host, server_port, semantics)
    client.run()
