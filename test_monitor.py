"""
Test script for monitoring functionality.
Demonstrates multiple clients monitoring a facility concurrently.
"""

import socket
import time
import sys
import threading
from marshalling import MessageBuilder, Unmarshaller
from protocol import MessageType


class MonitorClient:
    """Client for testing monitoring functionality"""

    def __init__(self, server_host: str, server_port: int, client_id: int):
        self.server_host = server_host
        self.server_port = int(server_port)
        self.client_id = client_id
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(1.0)
        self.request_id = 1

    def monitor_facility(self, facility_name: str, duration_seconds: int):
        """Monitor a facility"""
        print(f"[Client {self.client_id}] Registering to monitor '{facility_name}' for {duration_seconds}s")

        # Send monitor registration
        builder = MessageBuilder()
        builder.add_uint8(MessageType.MONITOR_REGISTER)
        builder.add_uint32(self.request_id)
        builder.add_string(facility_name)
        builder.add_uint32(duration_seconds)

        try:
            self.socket.sendto(builder.build(), (self.server_host, self.server_port))
            response, _ = self.socket.recvfrom(65507)

            unmarshaller = Unmarshaller(response)
            msg_type = unmarshaller.unpack_uint8()

            if msg_type == MessageType.MONITOR_RESPONSE:
                success = unmarshaller.unpack_bool()
                message = unmarshaller.unpack_string()
                print(f"[Client {self.client_id}] {message}")

                # Wait for updates
                end_time = time.time() + duration_seconds
                update_count = 0

                while time.time() < end_time:
                    try:
                        data, _ = self.socket.recvfrom(65507)
                        unmarshaller = Unmarshaller(data)
                        msg_type = unmarshaller.unpack_uint8()

                        if msg_type == MessageType.MONITOR_UPDATE:
                            update_count += 1
                            print(f"[Client {self.client_id}] Received update #{update_count}")
                            self._display_update(unmarshaller)

                    except socket.timeout:
                        continue

                print(f"[Client {self.client_id}] Monitoring ended. Received {update_count} updates.")

        except Exception as e:
            print(f"[Client {self.client_id}] Error: {e}")

        finally:
            self.socket.close()

    def _display_update(self, unmarshaller: Unmarshaller):
        """Display availability update"""
        facility_name = unmarshaller.unpack_string()
        num_days = unmarshaller.unpack_uint32()

        print(f"[Client {self.client_id}]   Facility: {facility_name}")
        print(f"[Client {self.client_id}]   Available slots:")

        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

        for _ in range(num_days):
            day = unmarshaller.unpack_uint8()
            num_slots = unmarshaller.unpack_uint32()

            if num_slots > 0:
                for _ in range(num_slots):
                    start_day, start_hour, start_min = unmarshaller.unpack_time()
                    end_day, end_hour, end_min = unmarshaller.unpack_time()
                    # Only show first slot for brevity
                    break


class BookingClient:
    """Client for making bookings during monitoring"""

    def __init__(self, server_host: str, server_port: int):
        self.server_host = server_host
        self.server_port = int(server_port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(2.0)
        self.request_id = 100

    def book_facility(self, facility_name: str, start_day: int, start_hour: int, start_min: int,
                     end_day: int, end_hour: int, end_min: int):
        """Book a facility"""
        builder = MessageBuilder()
        builder.add_uint8(MessageType.BOOK_FACILITY)
        builder.add_uint32(self.request_id)
        self.request_id += 1
        builder.add_string(facility_name)
        builder.add_time(start_day, start_hour, start_min)
        builder.add_time(end_day, end_hour, end_min)

        try:
            self.socket.sendto(builder.build(), (self.server_host, self.server_port))
            response, _ = self.socket.recvfrom(65507)

            unmarshaller = Unmarshaller(response)
            msg_type = unmarshaller.unpack_uint8()

            if msg_type == MessageType.BOOK_RESPONSE:
                conf_id = unmarshaller.unpack_string()
                print(f"[Booking Client] Booked {facility_name}: {conf_id}")
                return conf_id

        except Exception as e:
            print(f"[Booking Client] Error: {e}")

        return None

    def close(self):
        self.socket.close()


def run_monitor_test(host: str, port: int):
    """Test monitoring with multiple clients"""
    print("\n" + "="*70)
    print("MONITORING TEST: Multiple Clients Monitoring Concurrently")
    print("="*70 + "\n")

    facility_name = "Meeting Room A"
    duration = 15  # Monitor for 15 seconds

    # Start multiple monitor clients in threads
    def monitor_thread(client_id):
        client = MonitorClient(host, port, client_id)
        client.monitor_facility(facility_name, duration)

    threads = []
    for i in range(3):
        t = threading.Thread(target=monitor_thread, args=(i+1,))
        t.start()
        threads.append(t)
        time.sleep(0.5)  # Stagger starts slightly

    # Wait a bit, then make some bookings
    time.sleep(2)

    print("\n[Main] Making bookings to trigger updates...\n")
    booking_client = BookingClient(host, port)

    # Make a few bookings
    booking_client.book_facility(facility_name, 0, 9, 0, 0, 10, 0)
    time.sleep(3)

    booking_client.book_facility(facility_name, 0, 11, 0, 0, 12, 0)
    time.sleep(3)

    booking_client.book_facility(facility_name, 1, 14, 0, 1, 15, 0)

    booking_client.close()

    # Wait for all monitor threads to finish
    for t in threads:
        t.join()

    print("\n" + "="*70)
    print("Monitoring test completed!")
    print("All monitor clients should have received update notifications.")
    print("="*70 + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_monitor.py <server_host> <server_port>")
        sys.exit(1)

    host = sys.argv[1]
    port = int(sys.argv[2])

    run_monitor_test(host, port)
