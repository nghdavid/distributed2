"""
Distributed Facility Booking System - Server
Supports both at-least-once and at-most-once invocation semantics
"""

import socket
import time
import random
from typing import Dict, List, Tuple, Set, Optional
from datetime import datetime, timedelta
from protocol import MessageType, ErrorCode, DayOfWeek, TIMEOUT_SECONDS
from marshalling import MessageBuilder, Unmarshaller

class TimeSlot:
    """Represents a time slot with day, hour, and minute"""
    def __init__(self, day: int, hour: int, minute: int):
        self.day = day
        self.hour = hour
        self.minute = minute

    def to_minutes(self) -> int:
        """Convert to total minutes from start of week"""
        return self.day * 24 * 60 + self.hour * 60 + self.minute

    def __lt__(self, other):
        return self.to_minutes() < other.to_minutes()

    def __le__(self, other):
        return self.to_minutes() <= other.to_minutes()

    def __eq__(self, other):
        return self.to_minutes() == other.to_minutes()

    def __str__(self):
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        return f"{days[self.day]} {self.hour:02d}:{self.minute:02d}"


class Booking:
    """Represents a booking for a facility"""
    def __init__(self, confirmation_id: str, facility_name: str, start_time: TimeSlot, end_time: TimeSlot):
        self.confirmation_id = confirmation_id
        self.facility_name = facility_name
        self.start_time = start_time
        self.end_time = end_time
        self.cancelled = False

    def overlaps(self, start: TimeSlot, end: TimeSlot) -> bool:
        """Check if this booking overlaps with a given time range"""
        if self.cancelled:
            return False
        return not (end <= self.start_time or start >= self.end_time)


class Facility:
    """Represents a facility with bookings"""
    def __init__(self, name: str):
        self.name = name
        self.bookings: List[Booking] = []

    def is_available(self, start_time: TimeSlot, end_time: TimeSlot) -> bool:
        """Check if facility is available during the given time range"""
        for booking in self.bookings:
            if booking.overlaps(start_time, end_time):
                return False
        return True

    def get_availability(self, days: List[int]) -> Dict[int, List[Tuple[TimeSlot, TimeSlot]]]:
        """Get available time slots for specified days"""
        availability = {}
        for day in days:
            day_bookings = sorted([b for b in self.bookings if not b.cancelled and b.start_time.day == day],
                                  key=lambda x: x.start_time)

            slots = []
            current = TimeSlot(day, 0, 0)
            end_of_day = TimeSlot(day, 23, 59)

            for booking in day_bookings:
                if current < booking.start_time:
                    slots.append((current, booking.start_time))
                current = max(current, booking.end_time)

            if current <= end_of_day:
                slots.append((current, TimeSlot(day, 24, 0)))

            if not day_bookings:
                slots.append((TimeSlot(day, 0, 0), TimeSlot(day, 24, 0)))

            availability[day] = slots

        return availability


class MonitorRegistration:
    """Represents a client monitoring registration"""
    def __init__(self, facility_name: str, client_addr: Tuple[str, int], duration_seconds: int):
        self.facility_name = facility_name
        self.client_addr = client_addr
        self.expiry_time = time.time() + duration_seconds


class FacilityBookingServer:
    """Main server class for facility booking system"""

    def __init__(self, port: int, semantics: str, loss_probability: float = 0.0):
        self.port = port
        self.semantics = semantics  # 'at-least-once' or 'at-most-once'
        self.loss_probability = loss_probability
        self.facilities: Dict[str, Facility] = {}
        self.bookings: Dict[str, Booking] = {}
        self.next_confirmation_id = 1
        self.monitors: List[MonitorRegistration] = []

        # For at-most-once semantics
        self.request_history: Dict[Tuple[str, int], Tuple[bytes, float]] = {}  # (client_addr, request_id) -> (reply, timestamp)

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(('', port))

        # Initialize some sample facilities
        self._initialize_facilities()

    def _initialize_facilities(self):
        """Initialize sample facilities"""
        facility_names = ["Meeting Room A", "Lecture Theatre 1", "Conference Hall", "Seminar Room B"]
        for name in facility_names:
            self.facilities[name] = Facility(name)

    def _generate_confirmation_id(self) -> str:
        """Generate unique confirmation ID"""
        conf_id = f"CONF{self.next_confirmation_id:06d}"
        self.next_confirmation_id += 1
        return conf_id

    def _should_simulate_loss(self) -> bool:
        """Simulate message loss based on configured probability"""
        return random.random() < self.loss_probability

    def _clean_expired_monitors(self):
        """Remove expired monitor registrations"""
        current_time = time.time()
        self.monitors = [m for m in self.monitors if m.expiry_time > current_time]

    def _notify_monitors(self, facility_name: str):
        """Send availability updates to registered monitors"""
        self._clean_expired_monitors()

        facility = self.facilities.get(facility_name)
        if not facility:
            return

        all_days = list(range(7))
        availability = facility.get_availability(all_days)

        for monitor in self.monitors:
            if monitor.facility_name == facility_name:
                response = self._build_availability_response(facility_name, availability, is_update=True)
                try:
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
        """Handle extend booking request (IDEMPOTENT)"""
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

        # Calculate new end time (IDEMPOTENT: always extends from original booking)
        new_end_minutes = booking.end_time.to_minutes() + extension_minutes

        if new_end_minutes > 7 * 24 * 60:
            return self._build_error_response(ErrorCode.INVALID_TIME_RANGE,
                                              "Extended time exceeds the week")

        new_end = TimeSlot(new_end_minutes // (24 * 60), (new_end_minutes // 60) % 24, new_end_minutes % 60)

        facility = self.facilities[booking.facility_name]

        # Check availability for extension
        for other_booking in facility.bookings:
            if other_booking.confirmation_id != confirmation_id:
                if other_booking.overlaps(booking.end_time, new_end):
                    return self._build_error_response(ErrorCode.FACILITY_UNAVAILABLE,
                                                      "Cannot extend: facility unavailable during extension period")

        # Update booking
        old_end = booking.end_time
        booking.end_time = new_end

        # Notify monitors
        self._notify_monitors(booking.facility_name)

        builder = MessageBuilder()
        builder.add_uint8(MessageType.EXTEND_RESPONSE)
        builder.add_bool(True)
        builder.add_string(f"Booking extended to {new_end}")
        return builder.build()

    def _handle_cancel_booking(self, unmarshaller: Unmarshaller) -> bytes:
        """Handle cancel booking request (NON-IDEMPOTENT)"""
        confirmation_id = unmarshaller.unpack_string()

        print(f"Cancel: confirmation_id='{confirmation_id}'")

        if confirmation_id not in self.bookings:
            return self._build_error_response(ErrorCode.INVALID_CONFIRMATION_ID,
                                              f"Invalid confirmation ID")

        booking = self.bookings[confirmation_id]

        if booking.cancelled:
            return self._build_error_response(ErrorCode.ALREADY_CANCELLED,
                                              "Booking has already been cancelled")

        # Cancel booking (NON-IDEMPOTENT: can only be done once)
        booking.cancelled = True

        # Notify monitors
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
        """Process a request and return response"""
        unmarshaller = Unmarshaller(data)
        msg_type = unmarshaller.unpack_uint8()
        request_id = unmarshaller.unpack_uint32()

        print(f"\nReceived request: type={msg_type}, request_id={request_id}, from={client_addr}")

        # For at-most-once semantics, check if we've seen this request before
        if self.semantics == 'at-most-once':
            cache_key = (f"{client_addr[0]}:{client_addr[1]}", request_id)
            if cache_key in self.request_history:
                cached_reply, timestamp = self.request_history[cache_key]
                print(f"Returning cached reply for duplicate request {request_id}")
                return cached_reply

        # Process request based on type
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

        # For at-most-once semantics, cache the response
        if self.semantics == 'at-most-once':
            cache_key = (f"{client_addr[0]}:{client_addr[1]}", request_id)
            self.request_history[cache_key] = (response, time.time())

            # Clean old entries (older than 5 minutes)
            current_time = time.time()
            keys_to_delete = [k for k, v in self.request_history.items() if current_time - v[1] > 300]
            for k in keys_to_delete:
                del self.request_history[k]

        return response

    def run(self):
        """Main server loop"""
        print(f"Facility Booking Server started on port {self.port}")
        print(f"Invocation semantics: {self.semantics}")
        print(f"Message loss probability: {self.loss_probability}")
        print(f"Available facilities: {', '.join(self.facilities.keys())}")
        print("Waiting for requests...\n")

        while True:
            try:
                data, client_addr = self.socket.recvfrom(65507)

                # Simulate message loss for requests
                if self._should_simulate_loss():
                    print(f"Simulated loss of request from {client_addr}")
                    continue

                response = self._process_request(data, client_addr)

                # Simulate message loss for replies
                if self._should_simulate_loss():
                    print(f"Simulated loss of reply to {client_addr}")
                    continue

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
