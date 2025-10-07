"""
Marshalling and unmarshalling utilities for converting data structures to/from byte arrays.
Manual implementation without using serialization libraries.
"""

import struct
from typing import List, Tuple, Dict, Any

class Marshaller:
    """Handles marshalling of data to bytes"""

    @staticmethod
    def pack_uint8(value: int) -> bytes:
        """Pack an unsigned 8-bit integer"""
        return struct.pack('!B', value)

    @staticmethod
    def pack_uint16(value: int) -> bytes:
        """Pack an unsigned 16-bit integer"""
        return struct.pack('!H', value)

    @staticmethod
    def pack_uint32(value: int) -> bytes:
        """Pack an unsigned 32-bit integer (network byte order)"""
        return struct.pack('!I', value)

    @staticmethod
    def pack_int32(value: int) -> bytes:
        """Pack a signed 32-bit integer (network byte order)"""
        return struct.pack('!i', value)

    @staticmethod
    def pack_string(value: str) -> bytes:
        """Pack a string with length prefix"""
        encoded = value.encode('utf-8')
        length = len(encoded)
        return struct.pack('!I', length) + encoded

    @staticmethod
    def pack_bool(value: bool) -> bytes:
        """Pack a boolean value"""
        return struct.pack('!B', 1 if value else 0)

    @staticmethod
    def pack_time(day: int, hour: int, minute: int) -> bytes:
        """Pack a time tuple (day, hour, minute)"""
        return struct.pack('!BBB', day, hour, minute)

    @staticmethod
    def pack_list_of_ints(values: List[int]) -> bytes:
        """Pack a list of integers with length prefix"""
        result = struct.pack('!I', len(values))
        for val in values:
            result += struct.pack('!B', val)
        return result


class Unmarshaller:
    """Handles unmarshalling of bytes to data"""

    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def unpack_uint8(self) -> int:
        """Unpack an unsigned 8-bit integer"""
        value = struct.unpack_from('!B', self.data, self.offset)[0]
        self.offset += 1
        return value

    def unpack_uint16(self) -> int:
        """Unpack an unsigned 16-bit integer"""
        value = struct.unpack_from('!H', self.data, self.offset)[0]
        self.offset += 2
        return value

    def unpack_uint32(self) -> int:
        """Unpack an unsigned 32-bit integer (network byte order)"""
        value = struct.unpack_from('!I', self.data, self.offset)[0]
        self.offset += 4
        return value

    def unpack_int32(self) -> int:
        """Unpack a signed 32-bit integer (network byte order)"""
        value = struct.unpack_from('!i', self.data, self.offset)[0]
        self.offset += 4
        return value

    def unpack_string(self) -> str:
        """Unpack a string with length prefix"""
        length = self.unpack_uint32()
        value = self.data[self.offset:self.offset + length].decode('utf-8')
        self.offset += length
        return value

    def unpack_bool(self) -> bool:
        """Unpack a boolean value"""
        value = self.unpack_uint8()
        return value != 0

    def unpack_time(self) -> Tuple[int, int, int]:
        """Unpack a time tuple (day, hour, minute)"""
        day = self.unpack_uint8()
        hour = self.unpack_uint8()
        minute = self.unpack_uint8()
        return (day, hour, minute)

    def unpack_list_of_ints(self) -> List[int]:
        """Unpack a list of integers with length prefix"""
        length = self.unpack_uint32()
        values = []
        for _ in range(length):
            values.append(self.unpack_uint8())
        return values

    def has_data(self) -> bool:
        """Check if there's more data to unpack"""
        return self.offset < len(self.data)


class MessageBuilder:
    """Helper class to build messages incrementally"""

    def __init__(self):
        self.buffer = bytearray()

    def add_uint8(self, value: int):
        self.buffer.extend(Marshaller.pack_uint8(value))
        return self

    def add_uint16(self, value: int):
        self.buffer.extend(Marshaller.pack_uint16(value))
        return self

    def add_uint32(self, value: int):
        self.buffer.extend(Marshaller.pack_uint32(value))
        return self

    def add_int32(self, value: int):
        self.buffer.extend(Marshaller.pack_int32(value))
        return self

    def add_string(self, value: str):
        self.buffer.extend(Marshaller.pack_string(value))
        return self

    def add_bool(self, value: bool):
        self.buffer.extend(Marshaller.pack_bool(value))
        return self

    def add_time(self, day: int, hour: int, minute: int):
        self.buffer.extend(Marshaller.pack_time(day, hour, minute))
        return self

    def add_list_of_ints(self, values: List[int]):
        self.buffer.extend(Marshaller.pack_list_of_ints(values))
        return self

    def build(self) -> bytes:
        return bytes(self.buffer)
