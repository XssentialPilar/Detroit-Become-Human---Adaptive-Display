"""Build per-component layouts in the game's original, centered movie coordinates."""
import hashlib
import json
from pathlib import Path
import sys

WORK = Path.cwd()
from abc_extend import Code, Editor
from boot import build as build_boot
from movie import BASE, extract
from movie import repack
from probes import MAIN_PAGES, MENU, MENU_PAGE, ROOTS, attach_probes
from inspect_abc import abc_blocks

OWNERS = {**ROOTS, 111: 'comData::GLOBAL_LOADING_01', 191: 'comData::GLOBAL_SCENE_LOCATION',
          193: 'comData::GLOBAL_GAUGE_BENDING', 202: 'comData::BFD_LOCATION_TIME',
          203: 'comData::GLOBAL_LOADING_BARPMU',
          214: 'comData::GLOBAL_BENDING_NOTOTO'}
DATE = (191, 202)
STATE = (193, 214)
STATUS_CAPTION = 'comData.global_gauge_bending::AdjectiveInsert'
STATUS_PLATE = 'comLib.QD_LIB_COMPONENTS::TriangleBG'
STATUS_TREND = 'comData.global_gauge_bending::BendingState'
OPTIONS_MAIN = 'comData.menu_options_01.pages::MenuMainOptions'
LIST = 'comLib.QD_LIB_COMPONENTS.MENU::ListMenuComponents'


def slot(editor, owner, suffix):
    names = editor.abc.trait_spans[owner][3]
    found = [name for name in names if editor.abc.name(name).split('::')[-1] == suffix]
    if len(found) != 1:
        raise ValueError((owner, suffix, found))
    return found[0]


class Layout:
    # Local 1 is reserved for a possible event. Locals 2/3 contain the full
    # visible width/height in authored units after the stock centered projection.
    def __init__(self, editor, resource):
        self.e = editor
        self.id = resource
        self.owner = OWNERS[resource]
        self.c = Code().get(0).op(0x30)

    def field(self, local, *keys):
        self.c.get(local)
        for key in keys:
            self.c.op(0x66, self.e.public(key) if isinstance(key, str) else key)
        return self.c

    def root(self, name):
        return self.field(0, slot(self.e, BASE if self.id == 217 else self.owner, name))

    def assign(self, local, key, value):
        self.c.get(local)
        value()
        self.c.op(0x61, self.e.public(key) if isinstance(key, str) else key)

    def math(self, name, *args):
        self.c.op(0x60, self.e.name('Math'))
        for arg in args:
            arg()
        return self.c.op(0x46, self.e.public(name), len(args))

    def viewport(self):
        c = self.c
        self.field(0, 'stage').put(4).get(4).branch(0x12, 'done')
        for size, local in [('stageWidth', 2), ('stageHeight', 3)]:
            self.field(4, size).put(local).get(local).num(0).branch(0x16, 'done')
        self.math('min', lambda: c.get(2).num(1920).op(0xa3),
                  lambda: c.get(3).num(1080).op(0xa3)).put(4)
        for local in (2, 3):
            c.get(local).get(4).op(0xa3).put(local)
        # Half the additional space on each side of the reference movie.
        for local, size, pad in [(2, 1920, 5), (3, 1080, 6)]:
            c.get(local).num(size).op(0xa1).num(2).op(0xa3).put(pad)

    def publish(self, name, local):
        self.assign(0, self.e.add_slot(self.owner, 'codexProbe' + name), lambda: self.c.get(local))

    def overlays(self):
        c = self.c
        self.assign(0, self.e.add_slot(self.owner, 'codexLayoutResourceId'), lambda: c.num(self.id))
        if self.id == 203:
            self.field(0, 'codexProgressGroup').put(7).get(7).branch(0x12, 'done')
            self.publish('Group', 7)
            self.root('_percentLabel').put(9)
            self.publish('Label', 9)
            self.root('_loader').put(9)
            self.publish('Progress', 9)
            self.hud_scale()
            self.assign(7, 'x', lambda: c.get(5).op(0x90))
            self.assign(7, 'y', lambda: c.num(1080).get(6).op(0xa0).num(1080).get(8).op(0xa2).op(0xa1))
            return
        if self.id == 111:
            self.root('_loader').put(7).get(7).branch(0x12, 'done')
            self.publish('Ring', 7)
            self.hud_scale()
            self.assign(7, 'x', lambda: c.num(1920).get(5).op(0xa0).num(128).get(8).op(0xa2).op(0xa1))
            self.assign(7, 'y', lambda: c.num(84).get(8).op(0xa2).get(6).op(0xa1))
            return
        self.root('_container').put(7).get(7).branch(0x12, 'done')
        self.root('_bg').put(9)
        if self.id in STATE:
            self.status_overlay()
            return
        self.root({191: '_dateText', 202: '_locationText'}[self.id]).put(10)
        c.get(9).branch(0x12, 'done').get(10).branch(0x12, 'done')
        self.publish('Group', 7)
        self.publish('Plate', 9)
        self.publish('Label', 10)
        # The plate and its localized labels are siblings underneath this
        # group. Scale them uniformly, with room for both ends of long text.
        self.field(10).op(0x46, self.e.public('getTextWidth'), 0).put(12)
        self.math('max', lambda: c.num(600), lambda: c.get(12).num(450).op(0xa0)).put(13)
        self.hud_scale(width_cap=13)
        self.assign(7, 'x', lambda: c.get(5).op(0x90))
        def bottom():
            c.num(1080).get(6).op(0xa0).num(128)
            self.root('safeY').op(0xa0).get(8).op(0xa2).op(0xa1)
        self.assign(7, 'y', bottom)

    def status_overlay(self):
        c, e = self.c, self.e
        self.root('_adjectiveLabel').put(10)
        self.root('_nameLabel').put(11)
        self.root('_tendancy').put(12)
        for local in (9, 10, 11, 12):
            c.get(local).branch(0x12, 'done')
        c.get(10).op(0x4f, e.public('codexPlaceStatusLetters'), 0)
        # Bounds in the common parent. The name is flashed only in Connor
        # state NONE (-1). In infected states its hidden text can be >1000px.
        self.field(10, 'x').put(14).get(14).put(15)
        self.field(10, 'hasAdjective').branch(0x12, 'name')
        self.field(10, 'codexInkLeft').get(14).op(0xa0).put(14)
        self.field(10, 'codexInkRight').get(15).op(0xa0).put(15)
        c.label('name')
        self.field(10, 'codexCaption').put(16)
        self.root('_connorState').num(0).branch(0x18, 'indicator')
        self.math('min', lambda: c.get(14), lambda: self.field(11, 'x').get(11)
                  .op(0x46, e.public('getTextWidth'), 0).op(0xa1)).put(14)
        self.math('max', lambda: c.get(15), lambda: self.field(11, 'x')).put(15)
        c.get(11).put(16)
        c.label('indicator')
        self.root('_state').put(19)
        self.assign(0, e.add_slot(self.owner, 'codexStatusChange'), lambda: c.get(19))
        self.field(12, 'codexChevron').put(17)
        self.publish('Chevron', 17)
        # The arrow starts at local x=8, with a 32-unit half span and a
        # 3-unit stroke. Reserve its own column past the animated letters.
        self.assign(12, 'x', lambda: self.field(11, 'x').num(40).op(0xa0))
        for state in (0, 1, 4, 5):
            c.get(19).num(state).branch(0x13, 'arrow_column')
        c.branch(0x10, 'measured_indicator').label('arrow_column')
        self.assign(12, 'x', lambda: self.math('max', lambda: self.field(12, 'x'),
                    lambda: c.get(15).num(42).op(0xa0)))
        c.label('measured_indicator')
        # The unlock/lock label uses a separately localized width. Other
        # states only use the chevron at x+8, with a 32-unit half span.
        self.math('max', lambda: c.get(15), lambda: self.field(12, 'x').num(40).op(0xa0)).put(15)
        self.root('_state').num(2).branch(0x13, 'lock')
        self.root('_state').num(3).branch(0x14, 'plate')
        c.label('lock')
        self.math('min', lambda: c.get(14), lambda: self.field(12, 'x').num(4).op(0xa1)
                  .get(12).op(0x46, e.public('getBGWidth'), 0).op(0xa1)).put(14)
        c.label('plate')
        c.get(9).op(0x46, e.public('getTriangleWidth'), 0).num(2).op(0xa3).put(17)
        # One pitch on each sloping edge leaves a common horizontal interior
        # all the way from the top to the bottom of the plate.
        self.math('min', lambda: c.num(1470), lambda: c.get(14).get(17).op(0xa1).num(12).op(0xa1)).put(14)
        self.math('max', lambda: c.num(1470).get(17).num(5).op(0xa2).op(0xa0),
                  lambda: c.get(15).get(17).op(0xa0).num(12).op(0xa0)).put(15)
        self.assign(9, 'x', lambda: c.get(14))
        c.get(9).get(15).get(14).op(0xa1).get(17).num(5).op(0xa2).op(0xa1)
        c.op(0x4f, e.public('codexExtendStatusCenter'), 1)
        self.math('max', lambda: c.num(1920), lambda: c.get(15).num(16).op(0xa0)).put(18)
        c.get(18).get(14).op(0xa1).num(16).op(0xa0).put(13)
        self.hud_scale(width_cap=13)
        self.assign(7, 'x', lambda: c.num(1920).get(5).op(0xa0).get(18).get(8).op(0xa2).op(0xa1))
        self.assign(7, 'y', lambda: self.root('safeY').get(8).op(0xa2).get(6).op(0xa1))
        self.publish('Group', 7)
        self.publish('Plate', 9)
        self.publish('Label', 16)

    def hud_scale(self, width_cap=None):
        c = self.c
        # Relative to native contain, use the short screen edge for HUD size.
        self.math('min', lambda: c.get(2), lambda: c.get(3)).num(1080).op(0xa3).put(8)
        if width_cap:
            self.math('min', lambda: c.get(8), lambda: c.get(2).get(width_cap).op(0xa3)).put(8)
        for axis in ('scaleX', 'scaleY'):
            self.assign(7, axis, lambda: c.get(8))

    def panel(self):
        c = self.c
        self.root('_bg').put(7).get(7).branch(0x12, 'footer')
        c.get(7).op(0x46, self.e.public('get2DBG'), 0).put(7).get(7).branch(0x12, 'footer')
        self.publish('Plate', 7)
        # This sprite contains only a uniform translucent rectangle authored
        # around (0,0). Its original alpha, color, center and parent survive.
        for axis, dim, original in [('scaleX', 2, 1920), ('scaleY', 3, 1080)]:
            self.assign(7, axis, lambda: c.get(dim).num(original).op(0xa3))
        c.label('footer')
        self.field(0, slot(self.e, MENU, '_buttons')).put(7).get(7).branch(0x12, 'row')
        # Offset its coordinate system; configuration and active prompts
        # continue to be positioned together by ScreenButton2D itself.
        self.assign(7, 'x', lambda: c.get(5))
        self.assign(7, 'y', lambda: c.get(6))
        c.label('row')

    def buttons(self, callback_slot):
        c = self.c
        page_class = OPTIONS_MAIN if self.id == 217 else MAIN_PAGES[self.id]
        self.root('_mainPage' if self.id == 63 else '_main').put(7)
        c.get(7).branch(0x12, 'done')
        self.field(7, slot(self.e, page_class, '_container')).put(8)
        self.field(7, slot(self.e, page_class, '_list')).put(9)
        for local in (8, 9):
            c.get(local).branch(0x12, 'done')
        self.assign(9, callback_slot, lambda: self.field(0, 'codexScreenLayout'))
        c.get(9).op(0x46, self.e.public('getComponents'), 0).put(9)
        self.field(9, 'length').put(10).get(10).num(0).branch(0x16, 'done')
        indexer = next(i for i, (kind, _) in enumerate(self.e.abc.names) if kind == 0x1b)
        if self.id == 217:
            # Only publish the cards on the landing page. The existing probes
            # independently track the focused scroll page in the video submenu.
            card_slots = [self.e.add_slot(self.owner, f'codexProbeButton{n+1}') for n in range(5)]
            for key in card_slots:
                self.assign(0, key, lambda: c.op(0x20))
            self.field(0, 'codexProbePage').get(7).branch(0x14, 'cards_named')
            self.assign(0, 'codexProbeControls', lambda: c.get(8))
            for n, key in enumerate(card_slots):
                c.get(10).num(n).branch(0x16, 'cards_named')
                self.assign(0, key, lambda: c.get(9).num(n).op(0x66, indexer))
            c.label('cards_named')
        capacity = 4 if self.id == 64 else 5
        c.get(10).num(capacity).branch(0x17, 'done')
        c.num(1).put(12)
        # The same literal vector indices as the successfully observed probes.
        # Emit forward-only paths for these small, fixed authored inventories.
        for n in range(capacity):
            c.get(10).num(n).branch(0x16, 'measured')
            c.get(9).num(n).op(0x66, indexer).put(13)
            self.math('max', lambda: c.get(12), lambda: self.field(13, 'width')).put(12)
        c.label('measured')
        gap = 30 if self.id == 217 else 50
        # Keep the authored one-row reading order at 16:10 and 4:3. Use
        # larger buttons and wrap the same list on narrow/portrait screens.
        c.num(1).put(14).get(3).num(1600).branch(0x16, 'columns')
        self.math('min', lambda: c.num(2), lambda: c.get(3).num(1080).op(0xa3)).put(14)
        c.label('columns')
        self.math('min', lambda: c.get(14), lambda: c.get(2).num(144).op(0xa1).get(12).op(0xa3)).put(14)
        self.math('floor', lambda: c.get(2).num(144).op(0xa1).get(14).op(0xa3).num(gap).op(0xa0)
                  .get(12).num(gap).op(0xa0).op(0xa3)).put(15)
        self.math('min', lambda: c.get(10), lambda: c.get(15)).put(15)
        self.math('max', lambda: c.num(1), lambda: c.get(15)).put(15)
        self.math('ceil', lambda: c.get(10).get(15).op(0xa3)).put(16)
        # Convert the row center into its actual parent's author coordinates.
        # Parent Y is 826 in Main, 640 in Pause and 540 in Options.
        parent_y = {63: 826, 64: 640, 217: 540}[self.id]
        # Original centers are 851, 745 and 745. Subtitles get the bottom band.
        rel_y = 311 if self.id == 63 else 205
        c.num(540).get(3).num(rel_y).op(0xa2).num(1080).op(0xa3).op(0xa0)
        c.get(16).num(1).op(0xa1).num(80).op(0xa2).num(25).op(0xa0).get(14).op(0xa2).op(0xa1).put(17)
        # Include the focused frame, the optional caption on the last card,
        # and a bottom band for character speech or the controller prompts.
        c.get(16).num(1).op(0xa1).num(160).op(0xa2).num(130).op(0xa0).get(14).op(0xa2).put(18)
        self.math('min', lambda: c.get(17), lambda: c.num(1080).get(6).op(0xa0)
                  .num(144).op(0xa1).get(18).op(0xa1)).put(17)
        if self.id == 63:
            # Stock speech in the menu occupies the lower part of the centered
            # reference movie. Do not put a wrapped row across that band.
            c.get(17).num(1040).get(14).num(20).op(0xa2).op(0xa0).branch(0x18, 'speech_clear')
            self.math('min', lambda: c.get(17), lambda: c.num(958).get(18).op(0xa1)).put(17)
            c.label('speech_clear')
        self.assign(8, 'x', lambda: c.get(15).get(12).num(gap).op(0xa0).op(0xa2)
                    .num(gap).op(0xa1).get(14).op(0xa2).num(2).op(0xa3).op(0x90))
        self.assign(8, 'y', lambda: c.get(17).num(parent_y).op(0xa1))
        for axis in ('scaleX', 'scaleY'):
            self.assign(8, axis, lambda: c.get(14))
        if self.id in (64, 217):
            if self.id == 64:
                self.root('_title').put(13)
            else:
                self.field(7, slot(self.e, MENU_PAGE, '_title')).put(13)
            c.get(13).branch(0x12, 'no_title')
            # Use the column group as the left guide. Keep the heading's
            # existing depth, font and animation, even on sparse last rows.
            self.assign(13, 'x', lambda: self.field(8, 'x').num(22).op(0xa1))
            self.assign(13, 'y', lambda: c.get(3).num(300).op(0xa2).num(1080).op(0xa3).op(0x90))
            c.label('no_title')
        for n in range(capacity):
            c.get(10).num(n).branch(0x16, 'placed')
            c.get(9).num(n).op(0x66, indexer).put(13)
            self.math('floor', lambda: c.num(n).get(15).op(0xa3)).put(18)
            self.math('min', lambda: c.get(15), lambda: c.get(10).get(18).get(15).op(0xa2).op(0xa1)).put(19)
            def left():
                # Keep the first child's native (0,0) on full rows. A partial
                # last row is centered inside the list instead of the screen.
                c.num(n).get(15).op(0xa4).get(15).get(19).op(0xa1).num(2).op(0xa3).op(0xa0)
                c.get(12).num(gap).op(0xa0).op(0xa2)
                c.get(12)
                self.field(13, 'width').op(0xa1).num(2).op(0xa3).op(0xa0)
            self.assign(13, 'x', left)
            self.assign(13, 'y', lambda: c.get(18).num(160).op(0xa2))
        c.label('placed')
        if self.id == 63:
            self.field(7, slot(self.e, page_class, '_exit')).put(13).get(13).branch(0x12, 'done')
            def exit_x():
                c.num(960).get(5).op(0xa0)
                self.field(8, 'x').op(0xa1).get(14).op(0xa3).num(410).op(0xa1)
            self.assign(13, 'x', exit_x)
            self.assign(13, 'y', lambda: c.num(226).get(6).op(0xa1).get(17).op(0xa1).get(14).op(0xa3))


def status_chevrons(e, resource, bodies):
    layout = Layout(e, resource)
    c = layout.c
    arrow = slot(e, STATUS_TREND, '_jacques')
    change = slot(e, STATUS_TREND, '_state')
    probe = e.add_slot(STATUS_TREND, 'codexChevron')
    constructor = bodies[STATUS_TREND + '::<init>']
    e.append_before_return(constructor['method'], Code().get(0).get(0).op(0x66, arrow).op(0x61, probe).finish())
    layout.field(0, arrow).put(1)
    layout.field(1, 'graphics').put(2)
    layout.field(0, change).put(3)
    c.get(2).op(0x4f, e.public('clear'), 0)
    c.get(2).num(3).op(0x2d, e.abc.ints.index(0xffffff)).num(1).op(0x27)
    c.op(0x2c, e.string('normal')).op(0x2c, e.string('none')).op(0x4f, e.public('lineStyle'), 6)
    # Reuse the live colored sprite and the original 64x32 stroke. Its
    # signed Y scale conveys the direction. A second stroke conveys intensity.
    for y in (0, 16):
        if y:
            c.get(3).num(4).branch(0x15, 'ready')
        c.get(2).num(0).num(32).op(0xa1).num(y+32).op(0x4f, e.public('moveTo'), 2)
        c.get(2).num(0).num(y).op(0x4f, e.public('lineTo'), 2)
        c.get(2).num(32).num(y+32).op(0x4f, e.public('lineTo'), 2)
    c.label('ready')
    layout.assign(1, 'y', lambda: c.num(0))
    layout.assign(1, 'alpha', lambda: c.num(1))
    layout.assign(1, 'visible', lambda: c.op(0x26))
    _, prepare = e.add_method(STATUS_TREND, 'codexPrepareChevron', c.op(0x47).finish(),
                              constructor['scope_depth'], 4, optional_event=False)

    # The four final tweens fade the arrow before the card is dismissed.
    # Preserve the motion, mask, easing and the native lock and sound events.
    animation, = (b for n, b in bodies.items() if n.startswith(STATUS_TREND+'::') and n.endswith('::chevronAnimation'))
    from inspect_abc import opcode_table
    ins = e.abc.disassemble(animation, opcode_table())
    code = bytearray(animation['code'])
    endings = [b['offset'] for a,b in zip(ins, ins[1:]) if a['note'] == "'alpha'" and
               b['instruction'] == 'pushbyte' and b['args'] == [0]]
    if len(endings) != 4 or code[:2] != b'\xd0\x30' or animation['exceptions']:
        raise ValueError('Unexpected chevron animation in resource '+str(resource))
    for off in endings:
        code[off+1] = 1
    start = Code().get(2).num(0).branch(0x14, 'animated').get(0).op(0x4f, prepare, 0).label('animated')
    e.replace_body(animation['method'], code[:2] + start.finish() + code[2:])

    # Native hide() only fades the single chevrons. Strong arrows formerly
    # finished their own fade; explicitly release both sprites on dismissal.
    hide = bodies[STATUS_TREND + '::hide']
    c = Code().get(0).op(0x66, change).num(4).branch(0x13, 'strong')
    c.get(0).op(0x66, change).num(5).branch(0x14, 'done').label('strong')
    for sprite in (arrow, slot(e, STATUS_TREND, '_yves')):
        c.get(0).op(0x66, sprite).op(0x27).op(0x61, e.public('visible'))
        c.get(0).op(0x66, sprite).num(0).op(0x61, e.public('alpha'))
    e.append_before_return(hide['method'], c.label('done').finish())


def status_components(e, resource, bodies):
    status_chevrons(e, resource, bodies)
    # GhostLetters.width is the authored string advance. It is stable while
    # the individual letters blink. Recenter these rows on the localized ink.
    layout = Layout(e, resource)
    c = layout.c
    layout.field(0, slot(e, STATUS_CAPTION, '_adjLabel')).put(1)
    layout.assign(0, e.add_slot(STATUS_CAPTION, 'codexCaption'), lambda: c.get(1))
    layout.field(1, 'x').put(2)
    c.get(1).op(0x46, e.public('getTextWidth'), 0).get(2).op(0xa0).put(3)
    c.get(2).get(3).op(0xa0).num(2).op(0xa3).put(4)
    layout.field(0, slot(e, STATUS_CAPTION, '_connorState')).put(7)
    c.get(7).num(0).branch(0x15, 'bounds')
    for child, quarters in [('_topGhost', 2), ('_botGhost1', 3), ('_botGhost2', 1), ('_topDeviant', 2)]:
        if child == '_topDeviant':
            c.get(7).num(1).branch(0x14, 'bounds')
        layout.field(0, slot(e, STATUS_CAPTION, child)).put(5)
        layout.field(5, 'width').put(6)
        layout.assign(5, 'x', lambda: c.get(4).get(6).num(quarters).op(0xa2).num(4).op(0xa3).op(0xa1))
        layout.math('min', lambda: c.get(2), lambda: layout.field(5, 'x')).put(2)
        layout.math('max', lambda: c.get(3), lambda: layout.field(5, 'x').get(6).op(0xa0)).put(3)
    c.label('bounds')
    for local, name in [(2, 'codexInkLeft'), (3, 'codexInkRight')]:
        layout.assign(0, e.add_slot(STATUS_CAPTION, name), lambda: c.get(local))
    scope = bodies[STATUS_CAPTION + '::setAdjective']['scope_depth']
    e.add_method(STATUS_CAPTION, 'codexPlaceStatusLetters', c.op(0x47).finish(), scope, 8, optional_event=False)

    # Keep the four animated sprites and their original alpha table. Extend
    # only the shared middle seam. The two end caps retain their diagonals.
    layout = Layout(e, resource)
    c = layout.c
    last = e.add_slot(STATUS_PLATE, 'codexCenterExtension')
    layout.field(0, last).get(1).branch(0x13, 'done')
    layout.field(0, slot(e, STATUS_PLATE, '_triangles')).put(2)
    layout.field(2, 'length').num(4).branch(0x14, 'done')
    layout.field(0, slot(e, STATUS_PLATE, '_triangleWidth')).num(2).op(0xa3).put(3)
    layout.field(0, slot(e, STATUS_PLATE, '_triangleHeight')).put(4)
    indexer = next(i for i, (kind, _) in enumerate(e.abc.names) if kind == 0x1b)
    for n in (2, 3):
        c.get(2).num(n).op(0x66, indexer).get(1).op(0x61, e.public('x'))
    c.get(2).num(1).op(0x66, indexer).op(0x66, e.public('graphics')).put(5)
    c.get(5).op(0x4f, e.public('clear'), 0)
    c.get(5)
    layout.field(0, slot(e, STATUS_PLATE, '_color')).num(1).op(0x4f, e.public('beginFill'), 2)
    for method, pitch, extended, bottom in [('moveTo', 2, False, False), ('lineTo', 2, True, False),
                                            ('lineTo', 3, True, True), ('lineTo', 1, False, True),
                                            ('lineTo', 2, False, False)]:
        c.get(5).get(3).num(pitch).op(0xa2)
        if extended:
            c.get(1).op(0xa0)
        c.get(4) if bottom else c.num(0)
        c.op(0x4f, e.public(method), 2)
    c.get(5).op(0x4f, e.public('endFill'), 0)
    layout.assign(0, last, lambda: c.get(1))
    scope = bodies[STATUS_PLATE + '::setSize']['scope_depth']
    e.add_method(STATUS_PLATE, 'codexExtendStatusCenter', c.label('done').op(0x47).finish(), scope, 6)


def extend_plate(e, resource):
    """Extend the location/date plate at its authored pitch."""
    shape = 'comData.global_scene_location::TriangleBG'
    owner = OWNERS[resource]
    scope = next(b['scope_depth'] for b in e.abc.bodies if b['name'] == shape + '::setSize')
    pitch = slot(e, shape, '_triangleWidth')
    count = slot(e, shape, '_triangleCount')
    c = Code().get(0).op(0x30)
    c.get(0).op(0x66, pitch).num(2).op(0xa3).put(2).get(2).num(0).branch(0x16, 'done')
    c.op(0x60, e.name('Math')).num(4).op(0x60, e.name('Math')).get(1).get(2).op(0xa3)
    c.op(0x46, e.public('ceil'), 1).op(0x46, e.public('max'), 2).put(3)
    c.get(3).get(0).op(0x66, count).branch(0x13, 'done')
    c.get(0).get(3).op(0x61, count)
    c.get(0).op(0x4f, slot(e, shape, 'drawBGTriangleCount'), 0).label('done').op(0x47)
    _, fit = e.add_method(shape, 'codexFitTriangleRun', c.finish(), scope, 4)
    c = Code().get(0).op(0x30)
    label = {191: '_dateText', 202: '_locationText'}[resource]
    c.get(0).op(0x66, slot(e, owner, label)).put(1)
    c.get(0).op(0x66, slot(e, owner, '_bg')).put(2)
    c.get(1).branch(0x12, 'done').get(2).branch(0x12, 'done')
    c.get(2).get(1).op(0x46, e.public('getTextWidth'), 0)
    c.get(1).op(0x66, e.public('x')).op(0xa0).num(32).op(0xa1).num(40).op(0xa0)
    c.op(0x4f, fit, 1).label('done').op(0x47)
    return c.finish()


def connect_layout(e, resource, boot=False):
    """Register on show/init and check dimensions without writing on normal frames."""
    owner = OWNERS[resource]
    bodies = {b['name']: b for b in e.abc.bodies}
    scope = bodies[owner + '::QDF_OnInitialize']['scope_depth']
    callback = e.public('codexBootNativeCover' if boot else 'codexScreenLayout')
    plate_callback = None
    if resource in DATE:
        _, plate_callback = e.add_method(owner, 'codexMeasurePlate', extend_plate(e, resource),
                                          scope, 3, optional_event=False)
    elif resource in STATE:
        status_components(e, resource, bodies)
    elif resource == 203:
        # The constructor keeps the track in local 1. Capture it before
        # that reference expires and reparent all three siblings together.
        group = e.add_slot(owner, 'codexProgressGroup')
        c = Code().get(0).op(0x60, e.name('flash.display::Sprite')).op(0x42, 0).op(0x61, group)
        c.get(0).get(0).op(0x66, group).op(0x4f, e.public('addChild'), 1)
        c.get(0).op(0x66, group).get(1).op(0x4f, e.public('addChild'), 1)
        for child in ('_loader', '_percentLabel'):
            c.get(0).op(0x66, group).get(0).op(0x66, slot(e, owner, child)).op(0x4f, e.public('addChild'), 1)
        e.append_before_return(bodies[owner+'::<init>']['method'], c.finish())
    if not boot:
        layout = Layout(e, resource)
        layout.viewport()
        if resource in (63, 64, 217):
            ready = e.add_slot(LIST, 'codexAfterListPlacement')
            if resource != 63:
                layout.panel()
            layout.buttons(ready)
            writer = next(b for n, b in bodies.items() if n.startswith(LIST + '::') and n.endswith('::_placeComponents'))
            notify = Code().get(0).op(0x30).get(0).op(0x66, ready).branch(0x12, 'done')
            notify.get(0).op(0x4f, ready, 0).label('done').op(0x47)
            _, name = e.add_method(LIST, 'codexListDidPlace', notify.finish(),
                                   writer['scope_depth'], 1, optional_event=False)
            e.append_before_return(writer['method'], Code().get(0).op(0x4f, name, 0).finish())
        else:
            layout.overlays()
        code = layout.c.label('done').op(0x47).finish()
        e.add_method(owner, 'codexScreenLayout', code, scope, 20)
        if resource in STATE:
            # Both callbacks finish positioning the local labels before we
            # measure them. Neither restarts the original show animation.
            for event in ('QDF_setText', 'QDF_OnLanguageChanged'):
                e.append_before_return(bodies[owner + '::' + event]['method'],
                                       Code().get(0).op(0x4f, callback, 0).finish())
        if resource == 217:
            # The diagnostic publisher already runs after the menu manager
            # has attached a new page and its newly constructed title.
            publisher = bodies[owner + '::codexPublishDiagnosticTargets']
            e.append_before_return(publisher['method'], Code().get(0).op(0x4f, callback, 0).finish())

    # Some ShowAll players do not dispatch Stage.RESIZE on every mode change.
    # Read two integers per movie tick and re-layout only on a real transition.
    cache = [e.add_slot(owner, 'codexLast' + dim) for dim in ('Width', 'Height')]
    c = Code().get(0).op(0x30).get(0).op(0x66, e.public('stage')).put(2)
    c.get(2).branch(0x12, 'done')
    for i, dim in enumerate(('stageWidth', 'stageHeight')):
        c.get(2).op(0x66, e.public(dim)).put(3+i).get(3+i).num(0).branch(0x16, 'done')
    c.get(3).get(0).op(0x66, cache[0]).branch(0x14, 'change')
    c.get(4).get(0).op(0x66, cache[1]).branch(0x13, 'done')
    c.label('change')
    for i, key in enumerate(cache):
        c.get(0).get(3+i).op(0x61, key)
    c.get(0).op(0x4f, callback, 0).label('done').op(0x47)
    _, check = e.add_method(owner, 'codexCheckDimensions', c.finish(), scope, 5)
    dispatcher = e.add_slot(owner, 'codexAnchorStage')
    stop = Code().get(0).op(0x30).get(0).op(0x66, dispatcher).put(1)
    stop.get(1).branch(0x12, 'done')
    stop.get(1).op(0x2c, e.string('enterFrame')).get(0).op(0x66, check)
    stop.op(0x4f, e.public('removeEventListener'), 2)
    stop.get(0).op(0x20).op(0x61, dispatcher).label('done').op(0x47)
    _, detach = e.add_method(owner, 'codexStopAnchors', stop.finish(), scope, 2, optional_event=False)
    c = Code().get(0).op(0x30)
    # DATE and STATE use root.hasEventListener(ENTER_FRAME) as the gate for
    # their original show animation. Observe the Stage's separate dispatcher.
    c.get(0).op(0x66, e.public('stage')).put(1)
    c.get(1).get(0).op(0x66, dispatcher).branch(0x13, 'layout')
    c.get(0).op(0x4f, detach, 0).get(1).branch(0x12, 'layout')
    c.get(1).op(0x2c, e.string('enterFrame')).get(0).op(0x66, check)
    c.op(0x27).num(0).op(0x26).op(0x4f, e.public('addEventListener'), 5)
    c.get(0).get(1).op(0x61, dispatcher)
    c.label('layout').get(0).op(0x4f, callback, 0).op(0x47)
    _, register = e.add_method(owner, 'codexStartAnchors', c.finish(), scope, 2, optional_event=False)
    for event in ('QDF_OnInitialize', 'QDF_show', 'QDF_onShow', 'QDF_updateContinue', 'QDF_toggleExtra'):
        b = bodies.get(owner + '::' + event)
        if not b:
            continue
        suffix = Code().get(0).op(0x4f, register, 0).finish()
        if plate_callback and event == 'QDF_show':
            # Build any extra triangles before the stock show method starts
            # animating them. Relative branches in the original body stay valid.
            if b['exceptions'] or b['code'][:2] != bytes([0xd0, 0x30]) or b['code'][-1:] != b'\x47':
                raise ValueError(b['name'])
            measure = Code().get(0).op(0x4f, plate_callback, 0).finish()
            e.replace_body(b['method'], b['code'][:2] + measure + b['code'][2:-1] + suffix + b'\x47')
        else:
            e.append_before_return(b['method'], suffix)
    b = bodies.get(owner + '::QDF_OnRelease')
    if b:
        e.append_before_return(b['method'], Code().get(0).op(0x4f, detach, 0).finish())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build():
    out = WORK / 'build/screen_anchors'
    out.mkdir(exist_ok=True)
    fps = json.loads((WORK / 'build/fps_menu/manifest.json').read_text())
    native = json.loads((WORK / 'build/native/manifest.json').read_text())
    if native['version'] != '0.8.3-anchors' or sha((WORK / 'build/native/winmm.dll').read_bytes()) != native['sha256']:
        raise ValueError('Build the matching diagnostics loader first')
    resources = [entry.copy() for entry in fps['resources'] if entry['id'] != 217]
    for i in OWNERS:
        original = (WORK / f'analysis/ui/{i}.bin').read_bytes()
        source = original
        block = next(abc_blocks(i))
        if i == 217:
            source = (WORK / 'build/fps_menu/217.bin').read_bytes()
            block = extract(source)
        if i == 125:
            _, _, boot = build_boot()
            source = Path(boot['path']).read_bytes()
            # ABC is the last part of its DoABC tag. Scan this modified resource.
            block = read_block(source, block)
        elif i in ROOTS:
            probes = Editor(block['data'])
            attach_probes(probes, i)
            abc, _ = probes.finish()
            source = repack(source, block, abc)
            block = dict(block, data=abc)
        e = Editor(block['data'])
        connect_layout(e, i, boot=(i == 125))
        rewritten, parsed = e.finish()
        if 'codexNativeLayoutReady' in parsed.strings:
            raise ValueError('Unexpected root transform ownership')
        data = repack(source, block, rewritten)
        path = out / f'{i}.bin'
        path.write_bytes(data)
        resources.append(dict(type=18002, id=i, path=str(path.resolve()),
                              original_sha256=sha(original), modified_sha256=sha(data)))
    manifest = dict(version='0.8.3-anchors', required_native_sha256=native['sha256'],
                    runtime_validated=False, resources=resources)
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(f'Built {len(resources)} resources in {out}')


def read_block(source, original):
    import struct
    off, start = original['swf_offset'], original['abc_offset']
    size = struct.unpack_from('<I', source, off+4)[0]
    swf = source[off:off+size]
    pos = 8 + (5 + 4*(swf[8] >> 3) + 7)//8 + 4
    while pos+2 <= len(swf):
        tag = struct.unpack_from('<H', swf, pos)[0]
        pos += 2
        length = tag & 63
        if length == 63:
            length = struct.unpack_from('<I', swf, pos)[0]
            pos += 4
        if tag >> 6 == 82 and pos <= start < pos+length:
            return dict(original, data=swf[start:pos+length])
        pos += length
    raise ValueError('DoABC not found')


if __name__ == '__main__':
    build()
