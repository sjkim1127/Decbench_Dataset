"""Small strict ELF64-LE pilot validator, not a general function extractor."""
import struct
from pathlib import Path
import zlib


def sections(path: Path) -> dict:
    data = path.read_bytes()
    if data[:6] != b'\x7fELF\x02\x01':
        raise ValueError('Pilot requires ELF64 little endian')
    kind, machine = struct.unpack_from('<HH', data, 16)
    if (kind, machine) != (3, 62):
        raise ValueError('Pilot requires x86-64 ET_DYN')
    offset = struct.unpack_from('<Q', data, 40)[0]
    entry_size, count, names_index = struct.unpack_from('<HHH', data, 58)
    if entry_size != 64 or not count or names_index >= count:
        raise ValueError('Unsupported ELF section layout')
    entries = [struct.unpack_from('<IIQQQQIIQQ', data, offset + i * entry_size) for i in range(count)]
    names = entries[names_index]
    table = data[names[4]:names[4] + names[5]]
    result = {}
    for name_offset, section_type, flags, address, start, size, *_ in entries:
        name = table[name_offset:].split(b'\0', 1)[0].decode('ascii')
        content = data[start:start + size] if section_type != 8 else None
        if content is not None and len(content) != size:
            raise ValueError('Truncated ELF section')
        result[name] = {'type': section_type, 'flags': flags, 'address': address, 'size': size, 'data': content}
    return result


def validate_debug_pair(directory: Path) -> dict:
    original = sections(directory / 'binary.unstripped.so')
    stripped = sections(directory / 'binary.stripped.so')
    debug = sections(directory / 'binary.debug')
    if not original.get('.debug_info', {}).get('size') or not debug.get('.debug_info', {}).get('size'):
        raise ValueError('Missing DWARF information')
    if '.debug_info' in stripped:
        raise ValueError('Stripped artifact still contains debug_info')
    for name, section in original.items():
        if section['flags'] & 2:  # SHF_ALLOC: code and runtime data must survive stripping.
            if stripped.get(name) != section:
                raise ValueError(f'Allocated section changed during stripping: {name}')
    link = stripped['.gnu_debuglink']['data']
    filename = link.split(b'\0', 1)[0]
    crc_offset = (len(filename) + 1 + 3) & ~3
    crc = struct.unpack_from('<I', link, crc_offset)[0]
    if filename != b'binary.debug' or crc != zlib.crc32((directory / 'binary.debug').read_bytes()):
        raise ValueError('GNU debuglink filename/CRC mismatch')
    return {'format': 'elf', 'arch': 'x86_64', 'bits': 64, 'endianness': 'little',
            'allocated_sections_preserved': True, 'dwarf_present': True, 'debuglink_crc_valid': True}
