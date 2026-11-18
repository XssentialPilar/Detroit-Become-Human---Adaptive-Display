"""Exercise the packaged AVM2 methods with authored parent offsets and live dimensions."""
from pathlib import Path
import sys
import unittest

WORK = Path.cwd()
from build_screen_anchors import DATE, OWNERS, STATE, read_block
from inspect_abc import ABC, abc_blocks, opcode_table
from validate_prototype import execute


def node(**fields):
    return dict({'x': 0, 'y': 0, 'scaleX': 1, 'scaleY': 1}, **fields)


SIZES = [(1920, 1080), (1920, 1200), (1440, 1080), (1200, 1200), (1620, 1080),
         (1280, 1024), (1080, 1350), (2160, 1080), (2520, 1080), (2565, 1080),
         (1998, 1080), (2538, 1080), (2390, 1000), (2400, 1000), (2760, 1000),
         (1080, 1920), (2340, 1080), (2400, 1080), (1024, 768), (853, 479),
         (7800, 400)]


class ScreenAnchors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.movies = {}
        for i in OWNERS:
            data = (WORK / f'build/screen_anchors/{i}.bin').read_bytes()
            cls.movies[i] = ABC(read_block(data, next(abc_blocks(i)))['data'])

    def run_method(self, i, method, obj, arg=None):
        movie = self.movies[i]
        body, = (b for b in movie.bodies if b['name'].endswith('::' + method))
        return execute(movie, body, obj, arg)

    def test_visible_menu_rows_focus_frame_footer_and_plate(self):
        for i, count, parent_y in [(63, 5, 826), (64, 4, 640), (217, 5, 540)]:
            buttons = [node(width=297 if i == 217 else 300, height=50) for _ in range(count)]
            controls = node()
            menu_list = node(getComponents=lambda: buttons)
            title = node(x=-842, y=-300, z=50)
            group = node(_list=menu_list, _container=controls, _exit=node(), _title=title)
            plate, footer = node(x=960, y=540), node()
            root = node(_mainPage=group, _main=group, codexProbePage=group, _title=title, _bg={'get2DBG': lambda: plate},
                        _buttons=footer, stage={})
            root['codexScreenLayout'] = lambda: self.run_method(i, 'codexScreenLayout', root)
            for w, h in SIZES + list(reversed(SIZES)):
                with self.subTest(i=i, size=(w,h)):
                    root['stage'].update(stageWidth=w, stageHeight=h)
                    root['codexScreenLayout']()
                    # The real list reassigns each button's position before its callback.
                    for j, button in enumerate(buttons):
                        button['x'] = j*350
                    self.run_method(i, 'codexListDidPlace', menu_list)
                    s = min(w/1920, h/1080)
                    ox, oy = (w-1920*s)/2, (h-1080*s)/2
                    uniform = controls['scaleX']
                    self.assertEqual(uniform, controls['scaleY'])
                    rects = []
                    for b in buttons:
                        left = ox + (960+controls['x']+b['x']*uniform)*s
                        top = oy + (parent_y+controls['y']+b['y']*uniform)*s
                        # Include the authored focus brackets and the lower disabled caption.
                        rect = (left-20*s*uniform, top-20*s*uniform,
                                left+(b['width']+20)*s*uniform, top+130*s*uniform)
                        self.assertGreaterEqual(rect[0], -0.01)
                        self.assertGreaterEqual(rect[1], 0)
                        self.assertLessEqual(rect[2], w+0.01)
                        self.assertLessEqual(rect[3], h)
                        for r in rects:
                            # Decorative focus brackets may touch across adjacent cards.
                            self.assertTrue(r[2]-40*s*uniform <= rect[0]+0.01 or r[3] <= rect[1]+0.01)
                        rects.append(rect)
                    for y in set(r[1] for r in rects):
                        row = [r for r in rects if r[1] == y]
                        self.assertAlmostEqual(row[0][0]+row[-1][2], w)
                    if w < h:
                        self.assertGreater(len(set(r[1] for r in rects)), 1)
                    if i == 63:
                        button = group['_exit']
                        exit_top = oy + (parent_y+controls['y']+button['y']*uniform)*s
                        self.assertLess(exit_top+90*s*uniform, rects[0][1])
                    else:
                        if i == 217:
                            self.assertIs(root['codexProbeButton5'], buttons[4])
                        self.assertEqual(title['z'], 50)
                        self.assertLess(oy+(540+title['y']+100)*s, rects[0][1])
                        self.assertAlmostEqual(1920*plate['scaleX']*s, w)
                        self.assertAlmostEqual(1080*plate['scaleY']*s, h)
                        self.assertAlmostEqual(ox+(footer['x']+1920)*s, w)
                        self.assertAlmostEqual(oy+(footer['y']+1080)*s, h)
                        self.assertIs(root['codexProbePlate'], plate)

    def test_narrative_and_loading_edge_distances(self):
        for i in (111, *DATE):
            group = node()
            label = node(x=118 if i in DATE else 1740, getTextWidth=lambda: 582)
            root = node(_loader=group, _container=group, _bg=node(), _dateText=label,
                        _nameLabel=label, _locationText=label, safeY=86, stage={})
            for w,h in SIZES:
                root['stage'].update(stageWidth=w, stageHeight=h)
                self.run_method(i, 'codexScreenLayout', root)
                s = min(w/1920, h/1080)
                ox, oy = (w-1920*s)/2, (h-1080*s)/2
                actual = s*group['scaleX']
                self.assertEqual(group['scaleX'], group['scaleY'])
                x = ox+group['x']*s
                y = oy+group['y']*s
                if i == 111:
                    self.assertAlmostEqual(w-x, 128*actual)
                    self.assertAlmostEqual(y, 84*actual)
                    self.assertIs(root['codexProbeRing'], group)
                else:
                    self.assertAlmostEqual(x, 0)
                    self.assertAlmostEqual(h-y, 214*actual)
                self.assertEqual(root['codexLayoutResourceId'], i)

    def test_triangle_geometry_extends_at_authored_pitch(self):
        for i in DATE:
            pitch = 100
            label = node(x=118)
            draws = []
            plate = dict(_triangleWidth=2*pitch, _triangleCount=4, x=32 if i in DATE else 1470)
            plate['drawBGTriangleCount'] = lambda: draws.append(plate['_triangleCount'])
            plate['codexFitTriangleRun'] = lambda width: self.run_method(i, 'codexFitTriangleRun', plate, width)
            root = dict(_dateText=label, _locationText=label, _nameLabel=label, _bg=plate)
            for width in (582, 582, 890, 100):
                label['getTextWidth'] = lambda: width
                self.run_method(i, 'codexMeasurePlate', root)
                self.assertEqual(plate['_triangleWidth'], 2*pitch)
                self.assertGreaterEqual(plate['x']+plate['_triangleCount']*pitch, label['x']+width)
            self.assertEqual(len(draws), 3)

    def test_progress_track_fill_and_text_keep_their_bottom_left_anchor(self):
        group, fill, label = node(), node(x=108, y=955), node(x=108, y=970)
        root = node(codexProgressGroup=group, _loader=fill, _percentLabel=label, stage={})
        for w, h in SIZES + list(reversed(SIZES)):
            root['stage'].update(stageWidth=w, stageHeight=h)
            for percent in (1, 50, 99):
                fill['width'] = 500*percent/100
                self.run_method(203, 'codexScreenLayout', root)
                self.assertEqual(fill['width'], 500*percent/100)
                s = min(w/1920, h/1080)
                final = s*group['scaleX']
                self.assertEqual(group['scaleY'], group['scaleX'])
                x = (w-1920*s)/2 + group['x']*s + 108*final
                y = (h-1080*s)/2 + group['y']*s + 955*final
                self.assertAlmostEqual(x, 108*final)
                self.assertAlmostEqual(h-y, 125*final)
                self.assertLessEqual(x+500*final,w)
                self.assertLess(y+(15+30)*final,h)
        stock = ABC(next(abc_blocks(203))['data'])
        for method in ('_updateFrame',):
            orig, = (b for b in stock.bodies if b['name']==OWNERS[203]+'::'+method)
            built, = (b for b in self.movies[203].bodies if b['name']==orig['name'])
            self.assertEqual(orig['code'],built['code'])

    def test_connor_plate_tracks_visible_ink_across_resizes_and_state_changes(self):
        # The 0.8.1 trace measured a 1016.7-unit name even in the infected
        # state. The screenshot shows the 300-unit adjective actually flashing.
        for i in STATE:
            vertices, redraws = [], []
            def clear():
                vertices.clear()
                redraws.append(1)
            graphics = dict(clear=clear, beginFill=lambda *args: None, endFill=lambda: None,
                            moveTo=lambda x,y: vertices.append((x,y)), lineTo=lambda x,y: vertices.append((x,y)))
            faces = [node(alpha=a) for a in (.3, .5, .6, .3)]
            faces[1]['graphics'] = graphics
            plate = node(_triangles=faces, _triangleWidth=173, _triangleHeight=150, _color=0,
                         codexCenterExtension=None, getTriangleWidth=lambda: 173)
            plate['codexExtendStatusCenter'] = lambda extra: self.run_method(i, 'codexExtendStatusCenter', plate, extra)
            text = node()
            name = node(x=1734, getTextWidth=lambda: 1016.7)
            caption = node(x=1734, _adjLabel=text, hasAdjective=True, _topGhost=node(width=285),
                           _botGhost1=node(width=204), _botGhost2=node(width=190), _topDeviant=node(width=245))
            caption['codexPlaceStatusLetters'] = lambda: self.run_method(i, 'codexPlaceStatusLetters', caption)
            group = node()
            state = node(x=1774, codexChevron=node(x=8), getBGWidth=lambda: 460)
            root = node(_bg=plate, _container=group, _adjectiveLabel=caption, _nameLabel=name,
                        _tendancy=state, safeY=86, stage={}, codexLastWidth=None, codexLastHeight=None)
            root['codexScreenLayout'] = lambda: self.run_method(i, 'codexScreenLayout', root)
            original_faces = tuple(map(id, faces))
            # A recorded 1440x1080 window had a 1920x1440 logical stage.
            # Run the actual size-change callback with both coordinate spaces.
            displays = [(size, size) for size in SIZES]
            displays += [((1440, 1080), (1920, 1440)), ((1440, 900), (1920, 1200))]
            displays += list(reversed(displays))
            for connor, kind, label_width in [(0, 0, 302), (1, 1, 220), (-1, 2, 315),
                                              (-1, 3, 0), (1, 4, 315), (0, 5, 280),
                                              (0, -1, 302), (0, 0, 302)]:
                text.update(x=-label_width, getTextWidth=lambda: label_width)
                caption.update(_connorState=connor, hasAdjective=bool(label_width))
                root.update(_state=kind, _connorState=connor)
                root['stage'].update(stageWidth=1920, stageHeight=1080)
                root['codexScreenLayout']()
                for (w, h), (sw, sh) in displays:
                    with self.subTest(resource=i, size=(w,h), stage=(sw,sh), state=connor, kind=kind):
                        root['stage'].update(stageWidth=sw, stageHeight=sh)
                        self.run_method(i, 'codexCheckDimensions', root)
                        s=min(w/1920,h/1080)
                        scale=s*group['scaleX']
                        self.assertEqual(group['scaleX'],group['scaleY'])
                        origin=(w-1920*s)/2+s*group['x']
                        top=(h-1080*s)/2+s*group['y']
                        self.assertAlmostEqual(top, 86*scale)
                        self.assertLessEqual(top+150*scale,h)
                        pitch=86.5
                        left=plate['x']
                        extra=plate['codexCenterExtension']
                        right=left+5*pitch+extra
                        self.assertGreaterEqual(origin+left*scale,16*scale-.001)
                        self.assertGreaterEqual(w-(origin+right*scale),16*scale-.001)
                        # All four faces have native heights, contiguous seams
                        # and their original alpha targets, in every mode.
                        self.assertEqual(tuple(map(id,faces)),original_faces)
                        self.assertEqual([face['alpha'] for face in faces],[.3,.5,.6,.3])
                        self.assertEqual((faces[2]['x'], faces[3]['x']), (extra, extra))
                        self.assertEqual(vertices, [(2*pitch,0),(2*pitch+extra,0),(3*pitch+extra,150),
                                                    (pitch,150),(2*pitch,0)])
                        glyphs=[(1734-label_width,1734)]
                        if connor < 0:
                            glyphs.append((1734-1016.7,1734))
                            self.assertIs(root['codexProbeLabel'],name)
                        else:
                            # Even when only the first four sprites animate,
                            # the plate cannot start a screen away from the text.
                            self.assertGreater(left,1200)
                            self.assertIs(root['codexProbeLabel'],text)
                            for key in ('_topGhost','_botGhost1','_botGhost2') + (('_topDeviant',) if connor==1 else ()):
                                ghost=caption[key]
                                glyphs.append((1734+ghost['x'],1734+ghost['x']+ghost['width']))
                        if kind in (2,3):
                            glyphs.append((1774-4-460,1774))
                        if kind in (0, 1, 4, 5):
                            self.assertIs(root['codexProbeChevron'], state['codexChevron'])
                            self.assertEqual(root['codexStatusChange'], kind)
                            arrow_left = state['x'] + 8 - 32
                            self.assertGreaterEqual(arrow_left, max(last for _, last in glyphs) + 16)
                            glyphs.append((arrow_left, arrow_left + 64))
                        else:
                            self.assertEqual(state['x'], 1774)
                        for first,last in glyphs:
                            self.assertLessEqual(left+pitch,first-12+.001)
                            self.assertGreaterEqual(right-pitch,last+12-.001)
                        before=len(redraws)
                        self.run_method(i, 'codexScreenLayout', root)
                        self.assertEqual(len(redraws),before)

    def test_single_and_double_chevrons_use_native_orientation_and_stay_visible(self):
        for i in STATE:
            for change in (0, 1, 4, 5):
                points = []
                graphics = dict(clear=points.clear, lineStyle=lambda *args: None,
                                moveTo=lambda x,y: points.append((x,y)), lineTo=lambda x,y: points.append((x,y)))
                direction = -1 if change in (1, 5) else 1
                arrow = node(graphics=graphics, visible=False, alpha=0)
                arrow['scaleY'] = direction
                self.run_method(i, 'codexPrepareChevron', dict(_jacques=arrow, _state=change))
                self.assertTrue(arrow['visible'])
                self.assertEqual(arrow['alpha'], 1)
                self.assertEqual(arrow['scaleY'], direction)
                expected = [(-32,32),(0,0),(32,32)]
                if change >= 4:
                    expected.extend([(-32,48),(0,16),(32,48)])
                self.assertEqual(points, expected)
            movie = self.movies[i]
            animation, = (b for b in movie.bodies if b['name'].endswith('::chevronAnimation'))
            ins = movie.disassemble(animation, opcode_table())
            targets = [b['args'][0] for a,b in zip(ins, ins[1:])
                       if a['note'] == "'alpha'" and b['instruction'] == 'pushbyte']
            self.assertEqual(targets, [1,1,1,1])

    def test_status_uses_native_animation_and_updates_after_language_or_text(self):
        for i in STATE:
            stock=ABC(next(abc_blocks(i))['data'])
            encoded={body['name']:body for body in self.movies[i].bodies}
            for body in stock.bodies:
                key=body['name']
                if '::TriangleBG::' in key or key.endswith(('::onEnterFrame','::flashAnimationName','::flashAnimationAdj')):
                    self.assertEqual(body['code'],encoded[key]['code'])
            for event in ('QDF_setText','QDF_OnLanguageChanged'):
                tail=self.movies[i].disassemble(encoded[OWNERS[i]+'::'+event],opcode_table())[-3:]
                self.assertEqual(tail[1]['note'],'codexScreenLayout')
                self.assertEqual(tail[2]['instruction'],'returnvoid')

    def test_dimension_poll_only_calls_on_real_resize(self):
        for i in OWNERS:
            observed = []
            key = 'codexBootNativeCover' if i == 125 else 'codexScreenLayout'
            root = {key: lambda: observed.append(1), 'stage': {}, 'codexLastWidth': None, 'codexLastHeight': None}
            for w,h in [(0, 0), (1920,1200), (1920,1200), (1080,1920), (0,0), (1080,1920)]:
                root['stage'].update(stageWidth=w, stageHeight=h)
                self.run_method(i, 'codexCheckDimensions', root)
            self.assertEqual(len(observed), 2)

    def test_game_root_can_register_its_own_show_animation(self):
        for i in OWNERS:
            on_stage = []
            stage = {'addEventListener': lambda *args: on_stage.append(args[:2]),
                     'removeEventListener': lambda *args: on_stage.remove(args)}
            root = {'stage': stage, 'codexAnchorStage': None, 'codexCheckDimensions': object(),
                    'codexBootNativeCover': lambda: None, 'codexScreenLayout': lambda: None}
            root['codexStopAnchors'] = lambda: self.run_method(i, 'codexStopAnchors', root)
            self.run_method(i, 'codexStartAnchors', root)
            self.run_method(i, 'codexStartAnchors', root)
            self.assertEqual(on_stage, [('enterFrame', root['codexCheckDimensions'])])
            root['stage'] = None
            self.run_method(i, 'codexStopAnchors', root)
            self.assertFalse(on_stage)

    def test_boot_uniform_physical_scaling_and_center_crop(self):
        logo = node()
        root = {'stage': {}, '_logoVideo': logo, '_copyrightText': node(y=412)}
        for w,h in SIZES:
            root['stage'].update(stageWidth=w, stageHeight=h)
            self.run_method(125, 'codexBootNativeCover', root)
            contain = min(w/1920,h/1080)
            scale = max(w/1920,h/1080)
            self.assertAlmostEqual(logo['width']*contain/1920, scale)
            self.assertAlmostEqual(logo['height']*contain/1080, scale)
            self.assertAlmostEqual(2*logo['x']+logo['width'], 0)
            self.assertAlmostEqual(2*logo['y']+logo['height'], 0)
            self.assertEqual(root['_copyrightText']['y'], 412)


if __name__ == '__main__':
    unittest.main()
