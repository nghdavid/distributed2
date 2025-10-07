# Distributed Facility Booking System

A comprehensive distributed facility booking system implemented in Python using UDP sockets, supporting both **at-least-once** and **at-most-once** invocation semantics.

## Project Overview

This project implements a client-server system for booking facilities (meeting rooms, lecture theatres, etc.) with the following features:

- **Custom Protocol**: Manual marshalling/unmarshalling without using serialization libraries
- **UDP Communication**: All communication uses UDP sockets
- **Two Invocation Semantics**:
  - At-least-once (with retries)
  - At-most-once (with duplicate filtering and request history)
- **Multiple Services**: Query, book, change, monitor, extend, and cancel operations
- **Callback Mechanism**: Server callbacks for monitoring facility availability
- **Message Loss Simulation**: Built-in packet loss simulation for testing
- **Fault Tolerance**: Timeouts, retries, and duplicate request handling

## System Architecture

### Components

1. **Server (`server.py`)**: Manages facilities, bookings, and handles client requests
2. **Client (`client.py`)**: Interactive command-line interface for users
3. **Protocol (`protocol.py`)**: Message types and constants
4. **Marshalling (`marshalling.py`)**: Custom marshalling/unmarshalling utilities
5. **Test Scripts**: Automated experiments to demonstrate semantics differences

## Features

### Core Services

1. **Query Availability**: Check facility availability for selected days
2. **Book Facility**: Reserve a facility for a time period (returns confirmation ID)
3. **Change Booking**: Modify booking time by an offset (advance/postpone)
4. **Monitor Facility**: Register for availability updates via server callbacks

### Additional Operations

5. **Extend Booking** (IDEMPOTENT): Extend booking duration
   - Safe to execute multiple times
   - Always produces the same result

6. **Cancel Booking** (NON-IDEMPOTENT): Cancel an existing booking
   - Can only be executed once
   - Demonstrates importance of at-most-once semantics

## Message Format

All messages follow a custom binary protocol with network byte order:

```
Request Format:
[Message Type (1 byte)][Request ID (4 bytes)][Parameters...]

Response Format:
[Message Type (1 byte)][Response Data...]

Error Format:
[Message Type=255 (1 byte)][Error Code (1 byte)][Error Message (string)]
```

### Marshalling Rules

- **Integers**: Network byte order (big-endian) using struct.pack/unpack
- **Strings**: Length-prefixed (4-byte length + UTF-8 encoded data)
- **Time**: 3 bytes (day, hour, minute)
- **Lists**: Length-prefixed (4-byte count + elements)

## Installation & Setup

### Prerequisites

- Python 3.7 or higher
- No external dependencies required (uses only standard library)

### File Structure

```
distributed2/
├── server.py              # Server implementation
├── client.py              # Client implementation
├── protocol.py            # Protocol definitions
├── marshalling.py         # Marshalling utilities
├── test_experiment.py     # Semantics comparison experiments
├── test_monitor.py        # Monitoring functionality test
└── README.md              # This file
```

## Usage

### Starting the Server

```bash
# At-least-once semantics (no duplicate filtering)
python server.py <port> at-least-once [loss_probability]

# At-most-once semantics (with duplicate filtering)
python server.py <port> at-most-once [loss_probability]

# Examples:
python server.py 8000 at-least-once          # No message loss
python server.py 8000 at-most-once 0.2       # 20% message loss
```

**Parameters:**
- `port`: UDP port number (e.g., 8000)
- `semantics`: `at-least-once` or `at-most-once`
- `loss_probability`: Optional, 0.0 to 1.0 (default: 0.0)

### Starting the Client

```bash
python client.py <server_host> <server_port> <semantics>

# Example:
python client.py localhost 8000 at-most-once
```

### Client Interface

The client provides an interactive menu:

```
1. Query Availability    - Check when a facility is available
2. Book Facility         - Make a new booking
3. Change Booking        - Modify booking time
4. Monitor Facility      - Receive availability updates
5. Extend Booking        - Extend booking duration (idempotent)
6. Cancel Booking        - Cancel a booking (non-idempotent)
7. Exit                  - Close the client
```

### Sample Interaction

```
Enter choice (1-7): 1
Enter facility name: Meeting Room A
Enter days (0=Mon, 1=Tue, ..., 6=Sun, comma-separated): 0,1,2

Querying availability for 'Meeting Room A' on days [0, 1, 2]...

Availability for 'Meeting Room A':

  Monday:
    00:00 - 24:00

  Tuesday:
    00:00 - 24:00

  Wednesday:
    00:00 - 24:00
```

## Experiments

### Running Automated Tests

#### Experiment 1: Semantics Comparison

This experiment demonstrates the critical difference between invocation semantics:

```bash
# Test with at-least-once semantics
python server.py 8000 at-least-once 0.0
python test_experiment.py localhost 8000 at-least-once

# Test with at-most-once semantics
python server.py 8000 at-most-once 0.0
python test_experiment.py localhost 8000 at-most-once
```

**What it tests:**
- IDEMPOTENT operation (EXTEND): Both semantics work correctly
- NON-IDEMPOTENT operation (CANCEL):
  - At-least-once: FAILS (second execution causes error)
  - At-most-once: SUCCEEDS (duplicate filtered, cached reply returned)

#### Experiment 2: Monitoring Test

Tests multiple clients monitoring concurrently:

```bash
python server.py 8000 at-most-once
python test_monitor.py localhost 8000
```

**What it tests:**
- Multiple clients can monitor the same facility
- All registered clients receive callbacks when bookings change
- Monitor registrations expire after specified duration

#### Experiment 3: Message Loss Testing

Tests fault tolerance with simulated packet loss:

```bash
# Start server with 30% message loss
python server.py 8000 at-least-once 0.3

# Use client normally - observe retries
python client.py localhost 8000 at-least-once
```

**What it tests:**
- Client retries on timeout
- At-least-once: May execute operations multiple times
- At-most-once: Duplicate requests are filtered even with retries

## Implementation Details

### At-Least-Once Semantics

**Mechanism:**
- Client sends request and waits for reply
- On timeout, client retransmits the request (up to MAX_RETRIES)
- Server processes every request received (no duplicate filtering)

**Characteristics:**
- Simple implementation
- Works well for idempotent operations
- Risk: Non-idempotent operations may execute multiple times

### At-Most-Once Semantics

**Mechanism:**
- Each request has a unique ID (client_addr + request_id)
- Server maintains a request history cache
- On receiving a request:
  - If request_id is in history: return cached reply (no re-execution)
  - If request_id is new: execute operation, cache reply, return reply
- Old history entries are cleaned periodically (5 minutes)

**Characteristics:**
- Prevents duplicate execution
- Safe for non-idempotent operations
- Higher overhead (memory for history cache)

### Time Representation

Time is represented as tuples:
- **Day**: 0 (Monday) to 6 (Sunday)
- **Hour**: 0 to 23
- **Minute**: 0 to 59

Internally converted to minutes since start of week for comparison.

### Facility Management

- Server initializes with sample facilities: "Meeting Room A", "Lecture Theatre 1", "Conference Hall", "Seminar Room B"
- Bookings are stored per facility
- Availability is computed dynamically by checking for overlapping bookings
- Cancelled bookings are marked but not removed (for history)

### Monitoring Mechanism

1. Client sends MONITOR_REGISTER request with facility name and duration
2. Server records client address and expiry time
3. Server sends initial MONITOR_RESPONSE
4. When bookings change, server sends MONITOR_UPDATE to all registered clients
5. Registrations automatically expire after duration
6. Client blocks during monitoring (single-threaded design as per requirements)

## Design Decisions

### Additional Operations

**1. Extend Booking (IDEMPOTENT)**
- Extends the end time of a booking
- Always extends from the original booking time
- Executing multiple times produces the same result
- Safe with at-least-once semantics

**2. Cancel Booking (NON-IDEMPOTENT)**
- Cancels a booking (sets cancelled flag)
- Can only be done once
- Second attempt returns error (already cancelled)
- Requires at-most-once semantics for correctness

### Protocol Design Choices

1. **Fixed-size headers**: Message type (1 byte) and request ID (4 bytes) for all requests
2. **Length-prefixed strings**: Supports variable-length facility names
3. **Explicit type markers**: Each field has clear type and size
4. **Network byte order**: Using struct.pack/unpack with '!' format

### Fault Tolerance

1. **Timeouts**: 5-second timeout for client requests
2. **Retries**: Up to 3 attempts for at-least-once
3. **Request IDs**: Unique identifiers for duplicate detection
4. **History cache**: 5-minute retention for at-most-once
5. **Graceful degradation**: Errors are reported clearly to clients

## Testing & Validation

### Test Scenarios

1. ✅ Query availability for single/multiple days
2. ✅ Book facility successfully
3. ✅ Book overlapping time (should fail)
4. ✅ Change booking to available time
5. ✅ Change booking to unavailable time (should fail)
6. ✅ Monitor facility with multiple clients
7. ✅ Extend booking (idempotent)
8. ✅ Cancel booking (non-idempotent)
9. ✅ Duplicate requests with at-least-once (re-executed)
10. ✅ Duplicate requests with at-most-once (filtered)
11. ✅ Message loss with retries
12. ✅ Monitor expiration

### Expected Results

**At-Least-Once with Message Loss:**
- Client retries automatically
- Idempotent operations work correctly
- Non-idempotent operations may execute multiple times (ERROR on retry)

**At-Most-Once with Message Loss:**
- Client retries automatically
- All operations work correctly
- Duplicate requests return cached reply (no re-execution)

## Limitations & Assumptions

1. **Single-threaded server**: Processes one request at a time (as per requirements)
2. **In-memory storage**: No persistent storage (data lost on server restart)
3. **Single-threaded client**: Blocks during monitoring (as per requirements)
4. **Time granularity**: Minute-level precision (sufficient for facility booking)
5. **Fixed week**: Availability only tracked for 7 days (can be extended)
6. **No authentication**: All clients trusted (can be added)
7. **No booking ownership**: Any client can change/cancel any booking (can be added)

## Key Learning Points

### 1. Invocation Semantics Matter

At-least-once semantics are simple but unsafe for non-idempotent operations. The experiments clearly demonstrate that duplicate execution causes errors when operations have side effects.

### 2. Request History is Essential

At-most-once semantics require maintaining request history to filter duplicates. This is a classic space-time tradeoff: we use memory to ensure correctness.

### 3. Manual Marshalling is Non-Trivial

Implementing marshalling without libraries requires careful attention to:
- Byte ordering (network vs. host)
- String length encoding
- Variable-length data structures
- Type safety

### 4. UDP Requires Application-Level Reliability

Unlike TCP, UDP provides no guarantees. Applications must implement:
- Timeouts and retries
- Request/reply matching
- Duplicate detection
- In-order delivery (if needed)

## Troubleshooting

### Common Issues

**1. "Address already in use"**
```bash
# Wait a moment or use a different port
python server.py 8001 at-most-once
```

**2. Client timeout**
- Check server is running
- Verify host and port are correct
- Check firewall settings

**3. "Unknown message type"**
- Ensure client and server are using same code version
- Check network byte order in marshalling

## Future Enhancements

1. **Persistent storage**: Save bookings to disk/database
2. **Authentication**: User login and access control
3. **Booking ownership**: Track which user made each booking
4. **Multi-day bookings**: Support bookings spanning multiple weeks
5. **Search functionality**: Find available facilities by criteria
6. **Email notifications**: Alert users about booking changes
7. **Web interface**: Replace CLI with web UI
8. **TCP option**: Alternative transport for comparison
9. **Encryption**: Secure communication between client and server
10. **Load balancing**: Multiple servers with coordinator

## References

- Coulouris et al., "Distributed Systems: Concepts and Design"
- UDP socket programming in Python
- Network byte order and marshalling
- RPC invocation semantics

## Author & License

This project was developed as part of a distributed systems course assignment.

**License**: Educational use only

---

## Quick Start Example

### Terminal 1 (Server)
```bash
python server.py 8000 at-most-once 0.0
```

### Terminal 2 (Client)
```bash
python client.py localhost 8000 at-most-once

# Then in the menu:
# 1. Query availability: facility="Meeting Room A", days=0,1
# 2. Book facility: Mon 10:00 to 11:00
# 3. Receive confirmation ID
# 5. Extend booking by 30 minutes
# 6. Cancel booking
```

### Terminal 3 (Experiments)
```bash
python test_experiment.py localhost 8000 at-most-once
python test_monitor.py localhost 8000
```

---

**Enjoy exploring distributed systems concepts!** 🚀
