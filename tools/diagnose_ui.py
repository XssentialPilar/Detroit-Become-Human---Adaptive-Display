"""Watch or summarize the local Detroit Adaptive Display trace."""
import argparse
from collections import Counter, deque
import csv
import math
from pathlib import Path
import sys
import time


TRACE = Path('DetroitAdaptiveDisplay.trace.csv')
SCREENS = {63: 'Principal', 64: 'Pausa', 111: 'Indicador de carga', 125: 'Arranque',
           191: 'Fecha y hora', 193: 'Estado de Connor', 202: 'Lugar y hora',
           203: 'Progreso de carga', 214: 'Estado de Connor (variante)', 217: 'Opciones'}
MODES = {0: 'pantalla completa', 1: 'ventana sin bordes', 2: 'ventana'}
GEOMETRY_MASK = 0b111111111
ANCHORS = {63: ('Controls',), 64: ('Controls', 'Plate'), 111: ('Ring',), 125: ('Video',),
           191: ('Plate', 'Label'), 193: ('Plate', 'Label', 'Chevron'), 202: ('Plate', 'Label'),
           203: ('Group', 'Progress', 'Label'), 214: ('Plate', 'Label', 'Chevron'), 217: ('Plate',)}
CHANGES = {'-1': 'sin cambio', '0': 'subida', '1': 'bajada', '2': 'desbloqueo',
           '3': 'bloqueo', '4': 'subida intensa', '5': 'bajada intensa'}


def changes(trace, follow):
    position = 0
    while True:
        try:
            with trace.open('rb') as stream:
                end = stream.seek(0, 2)
                if end < position:
                    position = 0
                    yield None
                stream.seek(position)
                data = stream.read(end - position)
        except FileNotFoundError:
            if not follow:
                raise
            data = b''
        last_line = data.rfind(b'\n') + 1
        position += last_line
        yield from csv.reader(data[:last_line].decode('ascii').splitlines())
        if not follow:
            return
        time.sleep(0.15)


def close_to(left, right):
    return all(abs(a-b)<tolerance for a,b,tolerance in zip(left,right,(1,1,.5,.02,.02,1,1)))


class Report:
    def __init__(self):
        self.history = {}
        self.counts = Counter()
        self.targets = set()
        self.last_report = {}
        self.last_display = None
        self.last_video = None
        self.anchors = {}

    def observe(self, row):
        if row is None:
            self.history.clear()
            self.last_report.clear()
            self.last_display = None
            self.last_video = None
            self.anchors.clear()
            yield 'El capturador inició un archivo nuevo.'
            return
        if len(row) < 11 or row[0] not in ('display', 'ui', 'video'):
            return
        event, stamp, movie, resource, target, sw, sh, vw, vh, owned, valid = row[:11]
        now = int(stamp)
        if event == 'display':
            state = (sw, sh, vw, vh, owned)
            if state != self.last_display:
                self.history.clear()
                self.last_display = state
                yield f'{now/1000:.2f}s | {MODES.get(int(owned), "modo sin identificar")} | salida {sw}×{sh} | viewport {vw}×{vh}'
            if int(valid):
                self.counts['muestras perdidas'] += int(valid)
                yield f'{now/1000:.2f}s | Se omitieron {valid} muestras. La secuencia tiene huecos.'
            return
        if event == 'video':
            if valid == '0':
                self.last_video = None
                yield f'{now/1000:.2f}s | Terminó el dibujo de vídeo Bink a pantalla completa.'
                return
            state = tuple(row[5:19])
            if state != self.last_video:
                self.last_video = state
                status = 'UV disponibles' if owned == '1' else 'sin corrección UV'
                yield f'{now/1000:.2f}s | Bink {sw}×{sh} → {vw}×{vh} en ({row[11]}, {row[12]}) | {status}'
                if owned != '1':
                    self.counts['dibujos de vídeo sin corrección UV'] += 1
            return
        if len(row) not in (20, 21):
            return
        screen = SCREENS.get(int(resource), resource)
        self.targets.add((screen,target))
        prefix = f'{now/1000:.2f}s | {screen} / {target}'
        mask = int(valid)
        if mask == 0:
            self.history.pop((movie,resource,target),None)
            return
        if mask & GEOMETRY_MASK != GEOMETRY_MASK:
            self.counts['lecturas parciales'] += 1
            return
        numbers = tuple(map(float, row[11:20]))
        if not all(math.isfinite(value) for value in numbers):
            return
        if target in ANCHORS.get(int(resource), ()):
            self.anchors[(screen,target,sw,sh,vw,vh)] = numbers
        key = (movie,resource,target)
        state = (sw,sh,vw,vh,owned)
        history = self.history.setdefault(key, deque(maxlen=4))
        if history and history[-1][1] != state:
            history.clear()
        # Rotating loading segments alter the enclosing bounds each frame
        # without changing their position or scale. Keep the raw measurements.
        geometry = numbers[:5] if resource == '111' else numbers[:7]
        visible = int(bool(numbers[8]) and numbers[7] > .05)
        if target == 'Chevron' and len(row) == 21:
            change = CHANGES.get(row[20], 'estado desconocido')
            key_change = (movie, resource, 'última flecha')
            if self.last_report.get(key_change) != (change, visible):
                self.last_report[key_change] = (change, visible)
                yield f'{prefix} | {change} | ' + ('visible' if visible else 'oculta')
        if history and close_to(geometry,history[-1][2]) and visible==history[-1][3]:
            return
        flags = []
        if len(history)>=3 and visible and all(item[3] for item in history):
            third, second, last = list(history)[-3:]
            if now-third[0]<=300 and close_to(geometry,second[2]) and close_to(last[2],third[2]) and not close_to(geometry,last[2]):
                if close_to(geometry[:5], last[2][:5]):
                    flags.append('alternancia de ancho o alto')
                else:
                    flags.append('alternancia de geometría')
        if history and now-history[-1][0]<=250 and visible and history[-1][3]:
            prior = history[-1][2]
            if math.hypot(numbers[0]-prior[0],numbers[1]-prior[1])>=48:
                flags.append('salto de posición')
            if max(abs(numbers[3]-prior[3]),abs(numbers[4]-prior[4]))>=.15:
                flags.append('salto de escala')
        if len(history)>=3 and now-history[-3][0]<=300:
            if [item[3] for item in list(history)[-3:]]==[1-visible,visible,1-visible]:
                flags.append('visibilidad intermitente')
        history.append((now,state,geometry,visible))
        for flag in flags:
            self.counts[flag]+=1
            notice=(key,flag)
            if now-self.last_report.get(notice,-1000)>=500:
                self.last_report[notice]=now
                yield f'{prefix} | posible {flag} | posición local ({numbers[0]:.1f}, {numbers[1]:.1f}) | escala ({numbers[3]:.3f}, {numbers[4]:.3f})'


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace',type=Path,default=TRACE)
    parser.add_argument('--once',action='store_true',help='Resume el archivo actual y sale.')
    parser.add_argument('--raw',action='store_true',help='Muestra cada fila del CSV.')
    parser.add_argument('--anchors',action='store_true',help='Resume las últimas medidas locales de los anclajes por tamaño.')
    args=parser.parse_args()
    if not args.once:
        print(f'Escuchando {args.trace.name}. Ctrl+C para terminar.',flush=True)
    report=Report()
    try:
        for row in changes(args.trace,not args.once):
            if args.raw and row:
                print(','.join(row),flush=True)
            for line in report.observe(row):
                print(line,flush=True)
    except KeyboardInterrupt:
        pass
    except FileNotFoundError:
        parser.exit(1,'Todavía no hay captura. Inicia el juego con la versión de diagnóstico instalada.\n')
    except OSError as exc:
        parser.exit(1,f'No se pudo leer el registro: {exc}\n')
    print(f'{len(report.targets)} elementos observados.',flush=True)
    if args.anchors:
        for (screen, target, sw, sh, vw, vh), values in sorted(report.anchors.items()):
            x,y,_,sx,sy,width,height,*_ = values
            print(f'{screen} / {target} | Stage {sw}×{sh} | viewport {vw}×{vh} | '
                  f'posición local ({x:.1f}, {y:.1f}) | tamaño {width:.1f}×{height:.1f} | escala ({sx:.3f}, {sy:.3f})')
    for label,count in report.counts.most_common():
        print(f'{count} | {label}',flush=True)


if __name__=='__main__':
    main()
