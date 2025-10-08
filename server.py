"""
Distributed Facility Booking System - Server

This server implements a UDP-based facility booking system with support for:
1. At-least-once invocation semantics (simple request-response)
2. At-most-once invocation semantics (duplicate request filtering with history cache)

Key Features:
- Query facility availability for selected days
- Book facilities with unique confirmation IDs
- Change existing bookings by time offset
- Monitor facility availability through server callbacks
- Extend bookings (IDEMPOTENT operation)
- Cancel bookings (NON-IDEMPOTENT operation)
- Message loss simulation for testing fault tolerance
"""

import socket
import time
import random
from typing import Dict, List, Tuple, Set, Optional
from datetime import datetime, timedelta
from protocol import MessageType, ErrorCode, DayOfWeek, TIMEOUT_SECONDS
from marshalling import MessageBuilder, Unmarshaller

class TimeSlot:
    """
    Represents a time slot with day, hour, and minute.

    Time is represented within a week:
    - day: 0 (Monday) to 6 (Sunday)
    - hour: 0 to 23
    - minute: 0 to 59

    Internally converted to minutes since start of week for easy comparison.
    """
    def __init__(self, day: int, hour: int, minute: int):
        self.day = day
        self.hour = hour
        self.minute = minute

    def to_minutes(self) -> int:
        """Convert to total minutes from start of week (Monday 00:00)"""
        return self.day * 24 * 60 + self.hour * 60 + self.minute

    def __lt__(self, other):
        """Compare time slots: less than"""
        return self.to_minutes() < other.to_minutes()

    def __le__(self, other):
        """Compare time slots: less than or equal"""
        return self.to_minutes() <= other.to_minutes()

    def __eq__(self, other):
        """Compare time slots: equal"""
        return self.to_minutes() == other.to_minutes()

    def __str__(self):
        """String representation: e.g., 'Mon 10:30'"""
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        return f"{days[self.day]} {self.hour:02d}:{self.minute:02d}"


class Booking:
    """
    Represents a booking for a facility.

    Each booking has:
    - confirmation_id: Unique identifier (e.g., "CONF000001")
    - facility_name: Name of the booked facility
    - start_time: When the booking starts
    - end_time: When the booking ends
    - cancelled: Flag indicating if booking has been cancelled
    """
    def __init__(self, confirmation_id: str, facility_name: str, start_time: TimeSlot, end_time: TimeSlot):
        self.confirmation_id = confirmation_id
        self.facility_name = facility_name
        self.start_time = start_time
        self.end_time = end_time
        self.original_end_time = end_time  # Store original end time for idempotent extend operation
        self.cancelled = False  # Track if booking has been cancelled

    def overlaps(self, start: TimeSlot, end: TimeSlot) -> bool:
        """
        Check if this booking overlaps with a given time range.
        Cancelled bookings do not count as overlapping.

        Two time ranges overlap if they are NOT:
        - One ends before the other starts, OR
        - One starts after the other ends
        """
        if self.cancelled:
            return False
        return not (end <= self.start_time or start >= self.end_time)


class Facility:
    """
    Represents a facility with its bookings.

    Each facility has:
    - name: Variable-length string identifier (e.g., "Meeting Room A")
    - bookings: List of all bookings made for this facility
    """
    def __init__(self, name: str):
        self.name = name
        self.bookings: List[Booking] = []

    def is_available(self, start_time: TimeSlot, end_time: TimeSlot) -> bool:
        """
        Check if facility is available during the given time range.
        Returns False if any non-cancelled booking overlaps with the requested time.
        """
        for booking in self.bookings:
            if booking.overlaps(start_time, end_time):
                return False
        return True

    def get_availability(self, days: List[int]) -> Dict[int, List[Tuple[TimeSlot, TimeSlot]]]:
        """
        Get available time slots for specified days.

        Algorithm:
        1. For each requested day, get all non-cancelled bookings
        2. Sort bookings by start time
        3. Find gaps between bookings (available slots)
        4. Return list of (start, end) tuples for each available slot

        Returns:
            Dictionary mapping day -> list of available (start, end) time slots
        """
        availability = {}
        for day in days:
            # Get all non-cancelled bookings for this day, sorted by start time
            day_bookings = sorted([b for b in self.bookings if not b.cancelled and b.start_time.day == day],
                                  key=lambda x: x.start_time)

            slots = []
            current = TimeSlot(day, 0, 0)  # Start of day
            end_of_day = TimeSlot(day, 23, 59)

            # Find gaps between bookings
            for booking in day_bookings:
                if current < booking.start_time:
                    # There's a gap before this booking
                    slots.append((current, booking.start_time))
                # Move to end of this booking
                current = max(current, booking.end_time)

            # Add remaining time until end of day
            if current <= end_of_day:
                slots.append((current, TimeSlot(day, 24, 0)))

            # If no bookings, entire day is available
            if not day_bookings:
                slots.append((TimeSlot(day, 0, 0), TimeSlot(day, 24, 0)))

            availability[day] = slots

        return availability


class MonitorRegistration:
    """
    Represents a client monitoring registration for facility availability callbacks.

    When a client registers to monitor a facility:
    - Server records the client's address and port
    - Server sends updates whenever the facility's availability changes
    - Registration expires after the specified duration
    """
    def __init__(self, facility_name: str, client_addr: Tuple[str, int], duration_seconds: int):
        self.facility_name = facility_name  # Which facility to monitor
        self.client_addr = client_addr  # Where to send callbacks (IP, port)
        self.expiry_time = time.time() + duration_seconds  # When registration expires


class FacilityBookingServer:
    """
    Main server class for facility booking system.

    Architecture:
    - Uses UDP sockets for client-server communication
    - Single-threaded request processing (as per requirements)
    - Supports two invocation semantics:
      1. At-least-once: Simple request-response, no duplicate filtering
      2. At-most-once: Maintains request history to prevent duplicate execution

    Data Structures:
    - facilities: Maps facility name -> Facility object
    - bookings: Maps confirmation ID -> Booking object
    - monitors: List of active monitor registrations
    - request_history: Cache of (client, request_id) -> (reply, timestamp) for at-most-once
    """

    def __init__(self, port: int, semantics: str, loss_probability: float = 0.0):
        """
        Initialize the server.

        Args:
            port: UDP port to listen on
            semantics: 'at-least-once' or 'at-most-once'
            loss_probability: Probability (0.0-1.0) to simulate message loss
        """
        self.port = port
        self.semantics = semantics  # Determines duplicate request handling
        self.loss_probability = loss_probability  # For testing fault tolerance
        self.facilities: Dict[str, Facility] = {}  # All facilities
        self.bookings: Dict[str, Booking] = {}  # All bookings by confirmation ID
        self.next_confirmation_id = 1  # Counter for unique confirmation IDs
        self.monitors: List[MonitorRegistration] = []  # Active monitor registrations

        # For at-most-once semantics: cache of request -> reply mappings
        # Key: (client_address_string, request_id)
        # Value: (cached_reply_bytes, timestamp)
        self.request_history: Dict[Tuple[str, int], Tuple[bytes, float]] = {}

        # Create UDP socket and bind to port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('', port))

        # Initialize some sample facilities for testing
        self._initialize_facilities()

    def _initialize_facilities(self):
        """Initialize sample facilities for demonstration purposes."""
        facility_names = ["Meeting Room A", "Lecture Theatre 1", "Conference Hall", "Seminar Room B"]
        for name in facility_names:
            self.facilities[name] = Facility(name)

    def _generate_confirmation_id(self) -> str:
        """
        Generate unique confirmation ID for bookings.
        Format: CONF000001, CONF000002, etc.
        """
        conf_id = f"CONF{self.next_confirmation_id:06d}"
        self.next_confirmation_id += 1
        return conf_id

    def _should_simulate_loss(self) -> bool:
        """
        Simulate message loss for testing fault tolerance.
        Returns True with probability equal to loss_probability.
        """
        return random.random() < self.loss_probability

    def _clean_expired_monitors(self):
        """
        Remove expired monitor registrations.
        Called before sending updates to avoid sending to expired registrations.
        """
        current_time = time.time()
        self.monitors = [m for m in self.monitors if m.expiry_time > current_time]

    def _notify_monitors(self, facility_name: str):
        """
        Send availability updates to all registered monitors for a facility.

        This implements the callback mechanism:
        1. Clean expired registrations
        2. Get current availability for the facility
        3. Send update to each registered client

        Called whenever a booking is made, changed, extended, or cancelled.
        """
        self._clean_expired_monitors()

        facility = self.facilities.get(facility_name)
        if not facility:
            return

        # Get availability for all days of the week
        all_days = list(range(7))
        availability = facility.get_availability(all_days)

        # Send update to each registered monitor
        for monitor in self.monitors:
            if monitor.facility_name == facility_name:
                response = self._build_availability_response(facility_name, availability, is_update=True)
                try:
                    # Send callback to client
                    self.socket.sendto(response, monitor.client_addr)
                    print(f"Sent monitor update to {monitor.client_addr}")
                except Exception as e:
                    print(f"Error sending monitor update: {e}")

    def _build_availability_response(self, facility_name: str, availability: Dict, is_update: bool = False) -> bytes:
        """Build availability response message"""
        msg_type = MessageType.MONITOR_UPDATE if is_update else MessageType.QUERY_RESPONSE
        builder = MessageBuilder()
        builder.add_uint8(msg_type)
        builder.add_string(facility_name)
        builder.add_uint32(len(availability))

        for day, slots in availability.items():
            builder.add_uint8(day)
            builder.add_uint32(len(slots))
            for start, end in slots:
                builder.add_time(start.day, start.hour, start.minute)
                builder.add_time(end.day, end.hour, end.minute)

        return builder.build()

    def _handle_query_availability(self, unmarshaller: Unmarshaller) -> bytes:
        """Handle query availability request"""
        facility_name = unmarshaller.unpack_string()
        days = unmarshaller.unpack_list_of_ints()

        print(f"Query: facility='{facility_name}', days={days}")

        if facility_name not in self.facilities:
            return self._build_error_response(ErrorCode.FACILITY_NOT_FOUND,
                                              f"Facility '{facility_name}' not found")

        facility = self.facilities[facility_name]
        availability = facility.get_availability(days)

        return self._build_availability_response(facility_name, availability)

    def _handle_book_facility(self, unmarshaller: Unmarshaller) -> bytes:
        """Handle book facility request"""
        facility_name = unmarshaller.unpack_string()
        start_day, start_hour, start_minute = unmarshaller.unpack_time()
        end_day, end_hour, end_minute = unmarshaller.unpack_time()

        start_time = TimeSlot(start_day, start_hour, start_minute)
        end_time = TimeSlot(end_day, end_hour, end_minute)

        print(f"Book: facility='{facility_name}', from {start_time} to {end_time}")

        if facility_name not in self.facilities:
            return self._build_error_response(ErrorCode.FACILITY_NOT_FOUND,
                                              f"Facility '{facility_name}' not found")

        if start_time >= end_time:
            return self._build_error_response(ErrorCode.INVALID_TIME_RANGE,
                                              "Start time must be before end time")

        facility = self.facilities[facility_name]
        if not facility.is_available(start_time, end_time):
            return self._build_error_response(ErrorCode.FACILITY_UNAVAILABLE,
                                              f"Facility is not available during requested period")

        confirmation_id = self._generate_confirmation_id()
        booking = Booking(confirmation_id, facility_name, start_time, end_time)
        facility.bookings.append(booking)
        self.bookings[confirmation_id] = booking

        # Notify monitors
        self._notify_monitors(facility_name)

        builder = MessageBuilder()
        builder.add_uint8(MessageType.BOOK_RESPONSE)
        builder.add_string(confirmation_id)
        return builder.build()

    def _handle_change_booking(self, unmarshaller: Unmarshaller) -> bytes:
        """Handle change booking request"""
        confirmation_id = unmarshaller.unpack_string()
        offset_minutes = unmarshaller.unpack_int32()

        print(f"Change: confirmation_id='{confirmation_id}', offset={offset_minutes} minutes")

        if confirmation_id not in self.bookings:
            return self._build_error_response(ErrorCode.INVALID_CONFIRMATION_ID,
                                              f"Invalid confirmation ID")

        booking = self.bookings[confirmation_id]

        if booking.cancelled:
            return self._build_error_response(ErrorCode.BOOKING_NOT_FOUND,
                                              "Booking has been cancelled")

        # Calculate new time range
        start_minutes = booking.start_time.to_minutes() + offset_minutes
        end_minutes = booking.end_time.to_minutes() + offset_minutes

        if start_minutes < 0 or end_minutes > 7 * 24 * 60:
            return self._build_error_response(ErrorCode.INVALID_TIME_RANGE,
                                              "New time range is outside the week")

        new_start = TimeSlot(start_minutes // (24 * 60), (start_minutes // 60) % 24, start_minutes % 60)
        new_end = TimeSlot(end_minutes // (24 * 60), (end_minutes // 60) % 24, end_minutes % 60)

        facility = self.facilities[booking.facility_name]

        # Check availability (excluding current booking)
        for other_booking in facility.bookings:
            if other_booking.confirmation_id != confirmation_id and other_booking.overlaps(new_start, new_end):
                return self._build_error_response(ErrorCode.FACILITY_UNAVAILABLE,
                                                  "Facility is not available during new requested period")

        # Update booking
        booking.start_time = new_start
        booking.end_time = new_end

        # Notify monitors
        self._notify_monitors(booking.facility_name)

        builder = MessageBuilder()
        builder.add_uint8(MessageType.CHANGE_RESPONSE)
        builder.add_bool(True)
        return builder.build()

    def _handle_monitor_register(self, unmarshaller: Unmarshaller, client_addr: Tuple[str, int]) -> bytes:
        """Handle monitor registration request"""
        facility_name = unmarshaller.unpack_string()
        duration_seconds = unmarshaller.unpack_uint32()

        print(f"Monitor: facility='{facility_name}', duration={duration_seconds}s, client={client_addr}")

        if facility_name not in self.facilities:
            return self._build_error_response(ErrorCode.FACILITY_NOT_FOUND,
                                              f"Facility '{facility_name}' not found")

        # Register monitor
        registration = MonitorRegistration(facility_name, client_addr, duration_seconds)
        self.monitors.append(registration)

        # Send initial availability
        facility = self.facilities[facility_name]
        all_days = list(range(7))
        availability = facility.get_availability(all_days)

        builder = MessageBuilder()
        builder.add_uint8(MessageType.MONITOR_RESPONSE)
        builder.add_bool(True)
        builder.add_string(f"Monitoring '{facility_name}' for {duration_seconds} seconds")
        return builder.build()

    def _handle_extend_booking(self, unmarshaller: Unmarshaller) -> bytes:
        """
        Handle extend booking request (IDEMPOTENT OPERATION).

        This operation extends the end time of an existing booking.

        Why it's TRULY IDEMPOTENT:
        - Always extends from the ORIGINAL end time (stored at booking creation)
        - Executing multiple times with the same extension produces the SAME result
        - First execution: original_end + extension = new_end
        - Second execution: original_end + extension = same new_end (no change)
        - Third execution: original_end + extension = same new_end (no change)

        This demonstrates true idempotency: f(x) = f(f(x)) = f(f(f(x))) = ...
        The result is the same regardless of how many times you execute it.
        """
        confirmation_id = unmarshaller.unpack_string()
        extension_minutes = unmarshaller.unpack_uint32()

        print(f"Extend: confirmation_id='{confirmation_id}', extension={extension_minutes} minutes")

        if confirmation_id not in self.bookings:
            return self._build_error_response(ErrorCode.INVALID_CONFIRMATION_ID,
                                              f"Invalid confirmation ID")

        booking = self.bookings[confirmation_id]

        if booking.cancelled:
            return self._build_error_response(ErrorCode.BOOKING_NOT_FOUND,
                                              "Booking has been cancelled")

        # Calculate new end time by extending from ORIGINAL end time (IDEMPOTENT!)
        # This ensures the same extension value always produces the same result
        new_end_minutes = booking.original_end_time.to_minutes() + extension_minutes

        # Validate new end time doesn't exceed week boundary
        if new_end_minutes > 7 * 24 * 60:
            return self._build_error_response(ErrorCode.INVALID_TIME_RANGE,
                                              "Extended time exceeds the week")

        new_end = TimeSlot(new_end_minutes // (24 * 60), (new_end_minutes // 60) % 24, new_end_minutes % 60)

        # Check if this is actually changing the booking (avoid unnecessary updates)
        if booking.end_time == new_end:
            # Already extended to this time - return success without re-notifying
            print(f"Booking already extended to {new_end} (idempotent - no change)")
            builder = MessageBuilder()
            builder.add_uint8(MessageType.EXTEND_RESPONSE)
            builder.add_bool(True)
            builder.add_string(f"Booking extended to {new_end}")
            return builder.build()

        facility = self.facilities[booking.facility_name]

        # Check if extension period is available (don't conflict with other bookings)
        # Check from current end to new end
        check_start = min(booking.end_time, new_end)
        check_end = max(booking.end_time, new_end)

        for other_booking in facility.bookings:
            if other_booking.confirmation_id != confirmation_id:
                if other_booking.overlaps(check_start, check_end):
                    return self._build_error_response(ErrorCode.FACILITY_UNAVAILABLE,
                                                      "Cannot extend: facility unavailable during extension period")

        # Update the booking's end time
        old_end = booking.end_time
        booking.end_time = new_end
        print(f"Extended booking from {old_end} to {new_end}")

        # Notify all monitors that facility availability has changed
        self._notify_monitors(booking.facility_name)

        builder = MessageBuilder()
        builder.add_uint8(MessageType.EXTEND_RESPONSE)
        builder.add_bool(True)
        builder.add_string(f"Booking extended to {new_end}")
        return builder.build()

    def _handle_cancel_booking(self, unmarshaller: Unmarshaller) -> bytes:
        """
        Handle cancel booking request (NON-IDEMPOTENT OPERATION).

        This operation cancels an existing booking by setting its cancelled flag.

        Why it's NON-IDEMPOTENT:
        - Can only be executed successfully ONCE
        - First execution: Sets cancelled=True, returns success
        - Second execution: Already cancelled, returns error
        - Different results for same input = NON-IDEMPOTENT

        This demonstrates why at-most-once semantics is important:
        - With at-least-once: Duplicate requests cause errors
        - With at-most-once: Duplicate requests return cached success reply
        """
        confirmation_id = unmarshaller.unpack_string()

        print(f"Cancel: confirmation_id='{confirmation_id}'")

        if confirmation_id not in self.bookings:
            return self._build_error_response(ErrorCode.INVALID_CONFIRMATION_ID,
                                              f"Invalid confirmation ID")

        booking = self.bookings[confirmation_id]

        # Check if already cancelled - this makes it NON-IDEMPOTENT
        if booking.cancelled:
            return self._build_error_response(ErrorCode.ALREADY_CANCELLED,
                                              "Booking has already been cancelled")

        # Set the cancelled flag (can only be done once successfully)
        booking.cancelled = True

        # Notify all monitors that facility availability has changed
        self._notify_monitors(booking.facility_name)

        builder = MessageBuilder()
        builder.add_uint8(MessageType.CANCEL_RESPONSE)
        builder.add_bool(True)
        builder.add_string("Booking cancelled successfully")
        return builder.build()

    def _build_error_response(self, error_code: ErrorCode, message: str) -> bytes:
        """Build error response message"""
        builder = MessageBuilder()
        builder.add_uint8(MessageType.ERROR)
        builder.add_uint8(error_code)
        builder.add_string(message)
        return builder.build()

    def _process_request(self, data: bytes, client_addr: Tuple[str, int]) -> bytes:
        """
        Process a client request and return the appropriate response.

        Request Processing Flow:
        1. Unmarshal the request to get message type and request ID
        2. For at-most-once: Check if this is a duplicate request
           - If yes: Return cached reply (don't re-execute)
           - If no: Continue to step 3
        3. Execute the appropriate service handler
        4. For at-most-once: Cache the reply for future duplicate detection
        5. Return the response to send back to client

        This is the KEY difference between invocation semantics:
        - At-least-once: Every request is executed (no duplicate checking)
        - At-most-once: Duplicate requests return cached reply (not re-executed)
        """
        unmarshaller = Unmarshaller(data)
        msg_type = unmarshaller.unpack_uint8()
        request_id = unmarshaller.unpack_uint32()

        print(f"\nReceived request: type={msg_type}, request_id={request_id}, from={client_addr}")

        # AT-MOST-ONCE SEMANTICS: Check for duplicate requests
        if self.semantics == 'at-most-once':
            cache_key = (f"{client_addr[0]}:{client_addr[1]}", request_id)
            if cache_key in self.request_history:
                # This is a duplicate request - return cached reply without re-executing
                cached_reply, timestamp = self.request_history[cache_key]
                print(f"Returning cached reply for duplicate request {request_id}")
                return cached_reply

        # Execute the appropriate service handler based on message type
        try:
            if msg_type == MessageType.QUERY_AVAILABILITY:
                response = self._handle_query_availability(unmarshaller)
            elif msg_type == MessageType.BOOK_FACILITY:
                response = self._handle_book_facility(unmarshaller)
            elif msg_type == MessageType.CHANGE_BOOKING:
                response = self._handle_change_booking(unmarshaller)
            elif msg_type == MessageType.MONITOR_REGISTER:
                response = self._handle_monitor_register(unmarshaller, client_addr)
            elif msg_type == MessageType.EXTEND_BOOKING:
                response = self._handle_extend_booking(unmarshaller)
            elif msg_type == MessageType.CANCEL_BOOKING:
                response = self._handle_cancel_booking(unmarshaller)
            else:
                response = self._build_error_response(ErrorCode.INVALID_REQUEST,
                                                      f"Unknown request type: {msg_type}")
        except Exception as e:
            print(f"Error processing request: {e}")
            response = self._build_error_response(ErrorCode.INVALID_REQUEST, str(e))

        # AT-MOST-ONCE SEMANTICS: Cache the response for duplicate detection
        if self.semantics == 'at-most-once':
            cache_key = (f"{client_addr[0]}:{client_addr[1]}", request_id)
            self.request_history[cache_key] = (response, time.time())

            # Garbage collection: Remove entries older than 5 minutes
            # This prevents unbounded memory growth while maintaining recent history
            current_time = time.time()
            keys_to_delete = [k for k, v in self.request_history.items() if current_time - v[1] > 300]
            for k in keys_to_delete:
                del self.request_history[k]

        return response

    def run(self):
        """
        Main server loop - receives and processes client requests.

        Loop Structure:
        1. Wait for incoming UDP datagram
        2. Optionally simulate message loss (for testing)
        3. Process the request
        4. Optionally simulate reply loss (for testing)
        5. Send response back to client
        6. Repeat

        Message Loss Simulation:
        - Can drop incoming requests (client will retry)
        - Can drop outgoing replies (client will retry)
        - Tests fault tolerance of both semantics
        """
        print(f"Facility Booking Server started on port {self.port}")
        print(f"Invocation semantics: {self.semantics}")
        print(f"Message loss probability: {self.loss_probability}")
        print(f"Available facilities: {', '.join(self.facilities.keys())}")
        print("Waiting for requests...\n")

        while True:
            try:
                # Receive request from client (UDP datagram)
                # Max UDP datagram size: 65507 bytes
                data, client_addr = self.socket.recvfrom(65507)

                # Simulate message loss for testing fault tolerance
                if self._should_simulate_loss():
                    print(f"Simulated loss of request from {client_addr}")
                    continue  # Drop this request

                # Process the request and generate response
                response = self._process_request(data, client_addr)

                # Simulate reply loss for testing fault tolerance
                if self._should_simulate_loss():
                    print(f"Simulated loss of reply to {client_addr}")
                    continue  # Drop this reply

                # Send response back to client
                self.socket.sendto(response, client_addr)
                print(f"Sent response to {client_addr}\n")

            except KeyboardInterrupt:
                print("\nServer shutting down...")
                break
            except Exception as e:
                print(f"Error in server loop: {e}")

        self.socket.close()


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python server.py <port> <semantics> [loss_probability]")
        print("  semantics: 'at-least-once' or 'at-most-once'")
        print("  loss_probability: optional, between 0.0 and 1.0 (default: 0.0)")
        sys.exit(1)

    port = int(sys.argv[1])
    semantics = sys.argv[2]
    loss_probability = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0

    if semantics not in ['at-least-once', 'at-most-once']:
        print("Error: semantics must be 'at-least-once' or 'at-most-once'")
        sys.exit(1)

    server = FacilityBookingServer(port, semantics, loss_probability)
    server.run()
