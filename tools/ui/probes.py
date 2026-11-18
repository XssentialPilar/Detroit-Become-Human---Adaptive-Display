"""Attach passive probes to known interface components."""
from abc_extend import Code
from movie import BASE, PAGE, ROOT

MENU = 'comLib.QD_LIB_COMPONENTS.MENU::QD_UI_DATA_MENU'
MENU_PAGE = 'comLib.QD_LIB_COMPONENTS.MENU::MenuPage'
MANAGER = 'comLib.QD_LIB_COMPONENTS.MENU::MenuManager'
ROOTS = {63: 'comData::MENU_MAIN_01', 64: 'comData::MENU_PAUSE_01',
         125: 'comData::MENU_LEGAL_01', 217: ROOT}
MAIN_PAGES = {63: 'comData.menu_main_01::MenuMainMainPage',
              64: 'comData.menu_pause_01.pages::MenuPauseMainPage'}
NODES = {
    63: ['Group', 'Page', 'Controls', 'Button1', 'Button2', 'Button3', 'Button4', 'Button5', 'Exit'],
    64: ['Group', 'Page', 'Controls', 'Button1', 'Button2', 'Button3', 'Button4', 'Title', 'Footer', 'Back', 'Select'],
    125: ['Group', 'Video', 'Legal', 'Sony', 'Rating'],
    217: ['Group', 'Page', 'Controls', 'Title', 'Footer', 'Back', 'Select'],
}


def attach_probes(editor, resource):
    root = ROOTS[resource]
    bodies = {body['name']: body for body in editor.abc.bodies}
    initialize = bodies[root + '::QDF_OnInitialize']
    public = editor.public
    names = {node: editor.add_slot(root, 'codexProbe' + node) for node in NODES[resource]}
    identity = editor.add_slot(root, 'codexLayoutResourceId')
    code = Code().get(0).op(0x30).get(0).num(resource).op(0x61, identity)

    def field(local, *fields):
        code.get(local)
        for key in fields:
            code.op(0x66, key)

    def publish(node, local, *fields):
        code.get(0)
        field(local, *fields)
        code.op(0x61, names[node])

    if resource == 125:
        for node, name in [('Group', 'container'), ('Video', '_logoVideo'),
                           ('Legal', '_copyrightText'), ('Sony', '_sonyPresent'), ('Rating', '_ratings')]:
            publish(node, 0, editor.trait(root, name))
    if resource in MAIN_PAGES:
        page = MAIN_PAGES[resource]
        publish('Group', 0, editor.trait(root, '_container' if resource == 63 else '_movingContainer'))
        field(0, editor.trait(root, '_mainPage' if resource == 63 else '_main'))
        code.put(1).get(1).branch(0x12, 'done')
        publish('Page', 1)
        publish('Controls', 1, editor.trait(page, '_container'))
        field(1, editor.trait(page, '_list'))
        code.op(0x46, public('getComponents'), 0).put(2)
        dynamic = next(i for i, (kind, _) in enumerate(editor.abc.names) if kind == 0x1b)
        for index in range(5 if resource == 63 else 4):
            label = f'next_button_{index}'
            field(2, public('length'))
            code.num(index).branch(0x16, label)
            code.get(0).get(2).num(index).op(0x66, dynamic).op(0x61, names[f'Button{index + 1}'])
            code.label(label)
        if resource == 63:
            publish('Exit', 1, editor.trait(page, '_exit'))
        else:
            publish('Title', 0, editor.trait(root, '_title'))
    if resource == 217:
        publish('Group', 0, editor.trait(BASE, 'comData:MENU_OPTIONS_01::_movingContainer'))
        field(0, editor.trait(BASE, 'comData:MENU_OPTIONS_01::_menu'))
        code.put(2).get(2).branch(0x12, 'done')
        code.get(2).op(0x46, public('getCurrentPage'), 0).put(1)
        publish('Page', 1)
        code.get(0).op(0x20).op(0x61, names['Title'])
        code.get(0).op(0x20).op(0x61, names['Controls'])
        code.get(1).branch(0x12, 'footer')
        publish('Title', 1, editor.trait(MENU_PAGE, 'comLib.QD_LIB_COMPONENTS.MENU:MenuPage::_title'))
        code.get(1).op(0xb2, editor.name(PAGE)).branch(0x12, 'footer')
        publish('Controls', 1, editor.trait(PAGE, 'comData.menu_options_01.pages:MenuOptionsPage::_container'))
        code.label('footer')
    if resource in (64, 217):
        field(0, editor.trait(MENU, 'comLib.QD_LIB_COMPONENTS.MENU:QD_UI_DATA_MENU::_buttons'))
        code.put(3)
        publish('Footer', 3)
        code.get(3).branch(0x12, 'done')
        publish('Back', 3, public('backBtn'))
        publish('Select', 3, public('selectBtn'))

    code.label('done').op(0x47)
    _, publish_method = editor.add_method(root, 'codexPublishDiagnosticTargets', code.finish(),
                                           initialize['scope_depth'], 4, optional_event=False)
    callback = Code().get(0).op(0x4f, publish_method, 0).finish()
    for event in ['QDF_OnInitialize', 'QDF_show']:
        body = bodies.get(root + '::' + event)
        if body:
            editor.append_before_return(body['method'], callback)
    if resource == 217:
        # The manager has attached its new page and assigned _currentPage here.
        body = next(b for b in editor.abc.bodies if b['method'] == 403)
        if not body['name'].startswith(MANAGER + '::') or not body['name'].endswith('::_showPage'):
            raise ValueError('Unexpected page lifecycle')
        notify = Code().get(0).op(0x30)
        notify.get(0).op(0x66, editor.trait(MANAGER, 'comLib.QD_LIB_COMPONENTS.MENU:MenuManager::_currentPage'))
        notify.put(1).get(1).branch(0x12, 'done')
        notify.get(1).op(0x66, public('root')).put(2)
        notify.get(2).op(0xb2, editor.name(root)).branch(0x12, 'done')
        notify.get(2).op(0x4f, publish_method, 0).label('done').op(0x47)
        _, name = editor.add_method(MANAGER, 'codexUpdateDiagnosticPage', notify.finish(), body['scope_depth'], 3,
                                    optional_event=False)
        editor.append_before_return(body['method'], Code().get(0).op(0x4f, name, 0).finish())


