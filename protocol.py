"""
Protocol definitions and message types for the facility booking system.
"""

from enum import IntEnum

class MessageType(IntEnum):
    """Message types for request and reply messages"""
    # Request types
    QUERY_AVAILABILITY = 1
    BOOK_FACILITY = 2
    CHANGE_BOOKING = 3
    MONITOR_REGISTER = 4
    EXTEND_BOOKING = 5  # Idempotent operation
    CANCEL_BOOKING = 6  # Non-idempotent operation

    # Reply types
    QUERY_RESPONSE = 101
    BOOK_RESPONSE = 102
    CHANGE_RESPONSE = 103
    MONITOR_RESPONSE = 104
    EXTEND_RESPONSE = 105
    CANCEL_RESPONSE = 106

    # Special types
    MONITOR_UPDATE = 200
    ERROR = 255

class ErrorCode(IntEnum):
    """Error codes for error messages"""
    FACILITY_NOT_FOUND = 1
    FACILITY_UNAVAILABLE = 2
    INVALID_CONFIRMATION_ID = 3
    INVALID_TIME_RANGE = 4
    INVALID_REQUEST = 5
    BOOKING_NOT_FOUND = 6
    ALREADY_CANCELLED = 7

class DayOfWeek(IntEnum):
    """Days of the week"""
    MONDAY = 0
    TUESDAY = 1
    WEDNESDAY = 2
    THURSDAY = 3
    FRIDAY = 4
    SATURDAY = 5
    SUNDAY = 6

# Constants
MAX_MESSAGE_SIZE = 65507  # Maximum UDP packet size
TIMEOUT_SECONDS = 5
MAX_RETRIES = 3
