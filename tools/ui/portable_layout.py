"""Identify a menu by its embedded program, preserving the local movie and artwork."""
import hashlib
import struct

from movie import repack


def program(source):
    wrapper = source.find(b'MENU_RES')
    if wrapper < 0 or wrapper + 16 > len(source):
        return None
    version, size = struct.unpack_from('<II', source, wrapper + 8)
    if version != 6 or size != len(source) - wrapper - 16:
        return None
    offset = source.find(b'GFX', wrapper + 16)
    if offset < wrapper + 20 or offset + 12 > len(source):
        return None
    length, = struct.unpack_from('<I', source, offset + 4)
    end = offset + length
    if length < 12 or end > len(source) or struct.unpack_from('<I', source, offset - 4)[0] != length:
        return None
    pos = offset + 12 + (5 + 4 * (source[offset + 8] >> 3) + 7) // 8
    block = None
    while pos + 2 <= end:
        header, = struct.unpack_from('<H', source, pos)
        pos += 2
        kind, size = header >> 6, header & 63
        if size == 63:
            if pos + 4 > end:
                return None
            size, = struct.unpack_from('<I', source, pos)
            pos += 4
        if pos + size > end:
            return None
        if kind == 0:
            return block if size == 0 and pos == end else None
        if kind == 82:
            name_end = source.find(b'\0', pos + 4, pos + size)
            if block is not None or name_end < 0 or header & 63 != 63:
                return None
            block = dict(swf_offset=offset, abc_offset=name_end + 1 - offset,
                         data=source[name_end + 1:pos + size])
        pos += size
    return None


def signature(source):
    block = program(source)
    return hashlib.sha256(block['data']).hexdigest() if block else None


def apply(resource, source, expected):
    from abc_extend import Editor
    from build_screen_anchors import connect_layout
    from probes import ROOTS, attach_probes

    block = program(source)
    if not block or hashlib.sha256(block['data']).hexdigest() != expected['original']:
        raise ValueError('Layout program differs from the verified input')
    data = block['data']
    if resource in ROOTS:
        editor = Editor(data)
        attach_probes(editor, resource)
        data, _ = editor.finish()
    editor = Editor(data)
    connect_layout(editor, resource)
    rewritten, _ = editor.finish()
    result = repack(source, block, rewritten)
    if signature(result) != expected['modified']:
        raise ValueError('Generated layout program failed verification')
    return result
