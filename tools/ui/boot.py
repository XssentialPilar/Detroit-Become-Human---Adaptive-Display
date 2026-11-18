"""Boot cover candidate using the program's original movie transform and orientation."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path.cwd()
from abc_extend import Code, Editor
from movie import repack
from probes import attach_probes
from inspect_abc import abc_blocks

OWNER = 'comData::MENU_LEGAL_01'


def layout(editor):
    public = editor.public
    logo = editor.trait(OWNER, '_logoVideo')
    code = Code().get(0).op(0x30)
    code.get(0).op(0x66, public('stage')).put(2).get(2).branch(0x12, 'done')
    code.get(0).op(0x66, logo).put(3).get(3).branch(0x12, 'done')
    for axis, local, size in [('stageWidth', 4, 1920), ('stageHeight', 5, 1080)]:
        code.get(2).op(0x66, public(axis)).put(local)
        code.get(local).num(0).branch(0x16, 'done')
        code.get(local).num(size).op(0xa3).put(local)
    # ShowAll already applies contain. Zoom the video around its authored center
    # by cover/contain, leaving the root, legal layers and playback timing alone.
    for function in ('max', 'min'):
        code.op(0x60, editor.name('Math')).get(4).get(5).op(0x46, public(function), 2)
    code.op(0xa3).put(6)
    for size_name, position_name, size in [('width', 'x', 1920), ('height', 'y', 1080)]:
        code.num(size).get(6).op(0xa2).put(7)
        code.get(3).get(7).op(0x61, public(size_name))
        code.get(3).get(7).num(2).op(0xa3).op(0x90).op(0x61, public(position_name))
    return code.label('done').op(0x47).finish()


def build():
    source_path = ROOT / 'analysis/ui/125.bin'
    source = source_path.read_bytes()
    original_sha = hashlib.sha256(source).hexdigest()
    if original_sha != '29369225e9bed2f2042779a8a7b98beb27e18af8e773245af7800a8113214e18':
        raise ValueError('Unexpected original boot resource')
    block = next(abc_blocks(125))
    editor = Editor(block['data'])
    bodies = {body['name']: body for body in editor.abc.bodies}
    init_body = bodies[OWNER + '::QDF_OnInitialize']
    fade_body = bodies[OWNER + '::fadeIn']
    scope = init_body['scope_depth']
    # attach_probes appends only to OnInitialize in this resource. Registration
    # runs in fadeIn, which is also called by the original initialization.
    attach_probes(editor, 125)
    layout_method, layout_name = editor.add_method(OWNER, 'codexBootNativeCover', layout(editor), scope, 8)
    stage = editor.public('stage')
    register = Code().get(0).op(0x30)
    register.get(0).op(0x66, stage).branch(0x12, 'done')
    register.get(0).op(0x66, stage).op(0x2c, editor.string('resize')).get(0).op(0x66, layout_name)
    # Weak listener, so the stage cannot retain a detached legal movie.
    register.op(0x27).num(0).op(0x26).op(0x4f, editor.public('addEventListener'), 5)
    register.get(0).op(0x4f, layout_name, 0).label('done').op(0x47)
    _, register_name = editor.add_method(OWNER, 'codexBootCoverInitialize', register.finish(), scope, 1,
                                         optional_event=False)
    editor.append_before_return(fade_body['method'], Code().get(0).op(0x4f, register_name, 0).finish())
    new, parsed = editor.finish()
    result = repack(source, block, new)
    output = ROOT / 'build/boot'
    output.mkdir(exist_ok=True)
    (output / '125.bin').write_bytes(result)
    report = dict(resource=125, path=str((output / '125.bin').resolve()),
                  original_sha256=original_sha, candidate_sha256=hashlib.sha256(result).hexdigest(),
                  runtime_validated=False, installed=False, scoped_to='_logoVideo',
                  original_movie_transform_preserved=True, original_stage_mode_preserved=True)
    (output / 'manifest.json').write_text(json.dumps(report, indent=2))
    return parsed, layout_method, report


