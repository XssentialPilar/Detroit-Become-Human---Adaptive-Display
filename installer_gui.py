"""Graphical entry point for Detroit Adaptive Display."""
import ctypes
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from i18n import catalog, default_language, LANGUAGES
from install import RELEASE, error_text, game_folder, run

PAPER, DARK, INK, MUTED = '#faf9f6', '#182527', '#172b2c', '#45595a'
TEAL, LINE = '#006b66', '#c5cdca'
FONTS = {'ja':'Yu Gothic UI', 'ko':'Malgun Gothic', 'zh-Hans':'Microsoft YaHei UI',
         'zh-Hant':'Microsoft JhengHei UI', 'ar':'Tahoma'}


def label(parent, text, font, color=INK, bg=PAPER, **kwargs):
    return tk.Label(parent, text=text, font=font, bg=bg, fg=color, bd=0, **kwargs)


def button(parent, command, primary=False):
    return tk.Button(parent, command=command, bd=0, relief='flat', cursor='hand2',
                     highlightthickness=1, highlightcolor=TEAL, highlightbackground=LINE,
                     padx=14, pady=8, takefocus=True,
                     activebackground='#cbe7e0', activeforeground=INK,
                     bg=TEAL if primary else '#e8edeb', fg='white' if primary else INK,
                     disabledforeground='#80928f')


class Installer:
    def __init__(self, window, language=None, folder=''):
        self.window = window
        self.events = queue.Queue()
        self.busy = False
        self.state = None
        self.message, self.extra = 'start', ''
        self.folder = tk.StringVar(value=folder)
        self.names = {catalog(c)['name']: c for c in LANGUAGES}
        window.title('Detroit Adaptive Display')
        window.iconbitmap(default=str(Path(__file__).resolve().parent/'assets/setup.ico'))
        window.configure(bg=PAPER)
        window.minsize(740, 360)
        window.geometry('800x380')
        window.protocol('WM_DELETE_WINDOW', self.close)
        self.header = tk.Frame(window, bg=DARK, padx=24, pady=16)
        self.header.pack(fill='x')
        self.brand = tk.Frame(self.header,bg=DARK)
        mark = tk.Canvas(self.brand, width=38,height=38,bg=DARK,highlightthickness=0)
        mark.pack(side='left',padx=(0,12))
        for points in ((3,16,3,5,29,5),(34,21,34,33,9,33)):
            mark.create_line(*points,fill='#9be0cb',width=3)
        mark.create_line(11,25,26,12,fill='#f2f8ef',width=3)
        label(self.brand,'Detroit Adaptive Display',('Segoe UI',17,'bold'),'#f7faf7',DARK).pack(anchor='w')
        label(self.brand,'Detroit: Become Human   /   v'+RELEASE['version'],('Segoe UI',9),'#bbcfcb',DARK).pack(anchor='w')
        self.lang_box = tk.Frame(self.header,bg=DARK)
        self.lang_label = label(self.lang_box,'',('Segoe UI',9),'#c3d6d1',DARK)
        self.language = ttk.Combobox(self.lang_box, state='readonly', width=24, values=tuple(self.names))
        self.language.bind('<<ComboboxSelected>>',lambda _: self.set_language(self.names[self.language.get()]))
        self.body = tk.Frame(window,bg=PAPER,padx=26,pady=18)
        self.body.pack(fill='both',expand=True)
        self.heading = label(self.body,'',('Segoe UI',18,'bold'))
        self.note = label(self.body,'',('Segoe UI',10),MUTED)
        self.row = tk.Frame(self.body,bg=PAPER)
        self.entry = ttk.Entry(self.row,textvariable=self.folder)
        self.browse = button(self.row, self.choose_folder)
        self.card = tk.Frame(self.body,bg='#eaf0ed',padx=12,pady=10)
        self.marker = tk.Frame(self.card,bg=TEAL,width=3)
        self.status = label(self.card,'',('Segoe UI',11),bg='#eaf0ed',wraplength=665)
        self.actions = tk.Frame(self.body,bg=PAPER)
        self.check = button(self.actions,lambda:self.start('verify'))
        self.restore = button(self.actions,lambda:self.start('restore'))
        self.apply = button(self.actions,lambda:self.start('install'),True)
        self.heading.pack(fill='x')
        self.note.pack(fill='x',pady=(3,8))
        self.row.pack(fill='x')
        self.actions.pack(side='bottom',fill='x',pady=(10,0))
        self.card.pack(fill='x',pady=(18,2))
        self.folder.trace_add('write',self.changed)
        self.set_language(language or default_language())
        self.window.after(65,self.poll)

    def font(self, size=10, weight='normal'):
        return (FONTS.get(self.code,'Segoe UI'),size,weight)

    def set_language(self, code):
        self.code, self.t = code, catalog(code)
        self.language.set(self.t['name'])
        rtl = code == 'ar'
        first,last,anchor = ('right','left','e') if rtl else ('left','right','w')
        align = 'right' if rtl else 'left'
        for w in (self.brand,self.lang_box,self.lang_label,self.language,self.entry,self.browse,
                  self.marker,self.status,self.check,self.apply,self.restore):
            w.pack_forget()
        self.brand.pack(side=first)
        self.lang_box.pack(side=last)
        self.lang_label.config(text=self.t['language'],font=self.font(9))
        self.lang_label.pack(anchor=anchor,pady=(0,3))
        self.language.config(font=self.font())
        self.language.pack()
        self.heading.config(text=self.t['folder'],font=self.font(17,'bold'),anchor=anchor)
        self.note.config(text=self.t['hint'],font=self.font(),anchor=anchor,justify=align)
        self.entry.config(font=self.font(11))
        self.entry.pack(side=first,fill='x',expand=True,ipady=5)
        self.browse.pack(side=last,padx=(6,6))
        self.marker.pack(side=first,fill='y')
        self.status.config(font=self.font(11),justify=align,anchor=anchor)
        self.status.pack(side=first,expand=True,fill='x',padx=10)
        for widget,key in ((self.check,'check'),(self.restore,'restore'),(self.apply,'install'),(self.browse,'browse')):
            widget.config(text=self.t[key],font=self.font())
        self.check.pack(side=first)
        self.apply.pack(side=last)
        self.restore.pack(side=last,padx=8)
        self.refresh()
        # Long button labels and the user's desktop font scale set the minimum
        # window width. The status is allowed to wrap as the window grows.
        self.window.update_idletasks()
        width = max(740, self.actions.winfo_reqwidth()+54, self.header.winfo_reqwidth()+12,
                    self.note.winfo_reqwidth()+54)
        height = max(360, self.header.winfo_reqheight()+self.body.winfo_reqheight()+40)
        self.window.minsize(width,height)

    def choose_folder(self):
        current = self.folder.get().strip()
        options = {}
        if current:
            try:
                if Path(current).is_dir():
                    options['initialdir'] = current
            except OSError:
                # A drive or network share may have gone away since it was selected.
                pass
        selected = filedialog.askdirectory(parent=self.window, title=self.t['folder'],
                                           mustexist=True, **options)
        if selected:
            self.folder.set(str(Path(selected)))
            self.start('verify')

    def changed(self,*_):
        self.state, self.message, self.extra = None,'start',''
        self.refresh()

    def refresh(self):
        self.status.config(text=self.t[self.message]+('  '+self.extra if self.extra else ''))
        self.marker.config(bg='#a3402e' if self.state=='error' else TEAL if self.state else '#7b8a87')
        free = not self.busy
        for w,enabled in ((self.browse,free),(self.entry,free),(self.check,free and self.folder.get().strip()),
                          (self.apply,free and self.state in ('ready','ready_ui','restored',
                                                              'installed','installed_ui','unmanaged')),
                          (self.restore,free and self.state in ('installed','installed_ui','recovery'))):
            w.config(state='normal' if enabled else 'disabled')

    def start(self, action):
        if self.busy:
            return
        self.busy, self.message, self.extra = True,'checking',''
        self.refresh()
        folder = self.folder.get().strip()
        expected = ('ready' if self.state == 'restored' else self.state) if action == 'install' else None
        def work():
            try:
                root = game_folder(folder)
                if str(root) != folder:
                    self.events.put(('folder', str(root), ''))
                state = run(action, root, lambda key:self.events.put(('progress',key,'')), expected=expected)
                self.events.put(('done',state,''))
            except Exception as exc:
                self.events.put(('error',*error_text(exc)))
        threading.Thread(target=work,daemon=False).start()

    def poll(self):
        while not self.events.empty():
            event,message,extra = self.events.get()
            if event == 'folder':
                self.folder.set(message)
                continue
            self.message,self.extra = message,extra
            if event != 'progress':
                self.busy = False
                self.state = self.message if event=='done' else 'error'
            self.refresh()
        self.window.after(65,self.poll)

    def close(self):
        if not self.busy:
            self.window.destroy()


def main(language=None, folder=''):
    ctypes.windll.user32.SetProcessDPIAware()
    window = tk.Tk()
    Installer(window,language,folder)
    window.mainloop()


if __name__ == '__main__':
    main()
