"""Finite in-memory container checks before invoking an installed decoder."""
import struct
import zlib
from ..domain import Fault


def check_png(data):
    position, seen, ended = 8, set(), False
    while position < len(data):
        if position + 12 > len(data):
            raise Fault('MALFORMED_MEDIA')
        size = struct.unpack_from('>I', data, position)[0]
        tag = data[position + 4:position + 8]
        end = position + 12 + size
        if end > len(data) or zlib.crc32(data[position + 4:end - 4]) != struct.unpack_from('>I', data, end - 4)[0]:
            raise Fault('MALFORMED_MEDIA')
        if (not seen and (tag != b'IHDR' or size != 13)) or tag == b'acTL':
            raise Fault('UNSUPPORTED_MEDIA')
        if tag == b'IHDR' and tag in seen:
            raise Fault('MALFORMED_MEDIA')
        seen.add(tag)
        position = end
        if tag == b'IEND':
            ended = size == 0 and position == len(data)
            break
    if not ended or not {b'IHDR', b'IDAT', b'IEND'} <= seen:
        raise Fault('MALFORMED_MEDIA')


def check_mp4(data):
    position, seen = 0, set()
    while position < len(data):
        if position + 8 > len(data):
            raise Fault('MALFORMED_MEDIA')
        size, tag = struct.unpack_from('>I4s', data, position)
        header = 8
        if size == 1:
            if position + 16 > len(data):
                raise Fault('MALFORMED_MEDIA')
            size, header = struct.unpack_from('>Q', data, position + 8)[0], 16
        if size == 0:
            size = len(data) - position
        if size < header or position + size > len(data):
            raise Fault('MALFORMED_MEDIA')
        seen.add(tag)
        position += size
    if not {b'ftyp', b'moov', b'mdat'} <= seen:
        raise Fault('MALFORMED_MEDIA')
