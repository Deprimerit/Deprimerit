# -*- coding: utf-8 -*-
"""Actual connector hover / symbol help integration checks, Python 3.3+.

Run on a desktop display: python test_connector_hover.py
No application-source edits or third-party Python packages are needed.
"""
from __future__ import print_function
import inspect
import faulthandler
import io
import math
import os
import subprocess
import sys
import time
import traceback
import types
import tkinter as tk
from tkinter import ttk

APP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Flowchart_Studio.py')
APP = types.ModuleType('flowchart_hover_under_test')
APP.__file__ = APP_PATH
with io.open(APP_PATH, encoding='utf-8') as stream:
    exec(compile(stream.read(), APP_PATH, 'exec'), APP.__dict__)

checks, failures = [], []
original_mainloop = tk.Tk.mainloop
if os.environ.get('FLOWCHART_HOVER_TIMEOUT'):
    faulthandler.dump_traceback_later(float(os.environ['FLOWCHART_HOVER_TIMEOUT']), exit=True)


def check(condition, description):
    if not condition:
        raise AssertionError(description)
    checks.append(description)
    print('PASS:', description)


def descendants(widget):
    result = []
    for child in widget.winfo_children():
        result.append(child)
        result.extend(descendants(child))
    return result


def distance(x, y, coordinates):
    result = float('inf')
    for i in range(0, len(coordinates)-2, 2):
        ax, ay, bx, by = coordinates[i:i+4]
        dx, dy = bx-ax, by-ay
        scale = 0 if not (dx or dy) else ((x-ax)*dx+(y-ay)*dy)/(dx*dx+dy*dy)
        scale = min(1, max(0, scale))
        result = min(result, math.hypot(x-ax-scale*dx, y-ay-scale*dy))
    return result


def test_mainloop(root, *unused):
    editor = inspect.currentframe().f_back.f_locals['app']
    root.report_callback_exception = lambda *args: failures.append(''.join(traceback.format_exception(*args)))

    def pump(milliseconds=30):
        until = time.time() + milliseconds/1000.0
        while time.time() < until:
            root.update()
            time.sleep(0.005)
        root.update()

    def pickers():
        return [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)
                and w.winfo_exists() and w.title() == 'Add Shape']

    def move_outside():
        root.event_generate('<Motion>', x=5, y=5, warp=True)
        editor.canvas.event_generate('<Leave>')
        pump(260)

    def close_picker():
        move_outside()
        for window in pickers():
            window.destroy()
        pump(30)

    def world_pointer(x, y):
        cv = editor.canvas
        region = [float(v) for v in cv.cget('scrollregion').split()]
        if len(region) == 4:
            width, height = max(1, region[2]-region[0]), max(1, region[3]-region[1])
            cv.xview_moveto(max(0, min(1, (x-cv.winfo_width()/2-region[0])/width)))
            cv.yview_moveto(max(0, min(1, (y-cv.winfo_height()/2-region[1])/height)))
        root.update()
        local_x, local_y = int(round(x-cv.canvasx(0))), int(round(y-cv.canvasy(0)))
        check(0 <= local_x < cv.winfo_width() and 0 <= local_y < cv.winfo_height(), 'connector probe is visible after scrolling')
        cv.event_generate('<Motion>', x=local_x, y=local_y, warp=True)
        pump(35)

    def probe_for(tag):
        record = editor.connector_paths[tag]
        for coords in record['segments']:
            for i in range(0, len(coords)-2, 2):
                ax, ay, bx, by = coords[i:i+4]
                if math.hypot(bx-ax, by-ay) < 6:
                    continue
                for fraction in (0.25, 0.5, 0.75):
                    x, y = ax+(bx-ax)*fraction, ay+(by-ay)*fraction
                    event = types.SimpleNamespace(x=x-editor.canvas.canvasx(0), y=y-editor.canvas.canvasy(0))
                    hit = editor._canvas_hit_iid(event)
                    if hit and editor.mapping.get(hit, (None,))[0] == 'node':
                        continue
                    other = [distance(x, y, c) for key, r in editor.connector_paths.items()
                             if key != tag for c in r['segments']]
                    if not other or min(other) >= 10:
                        return x, y
        raise AssertionError('connector has no distinct hover point: ' + tag)

    def assert_hover(tag, description):
        close_picker()
        record = editor.connector_paths[tag]
        point = probe_for(tag)
        world_pointer(*point)
        drop = editor._nearest_drop(editor.canvas.winfo_rootx()+point[0]-editor.canvas.canvasx(0), editor.canvas.winfo_rooty()+point[1]-editor.canvas.canvasy(0))
        check(drop is not None and drop[2] is record['target'][0] and drop[3] == record['target'][1], description + ': palette drop targets the same full connector')
        check(editor.hover_connector == tag, description + ': hovering the actual line selects its connector (expected {0}, got {1}, point {2}, mouse {3})'.format(tag, editor.hover_connector, point, root.winfo_pointerxy()))
        halos = [editor.canvas.coords(item) for item in editor.canvas.find_withtag('connector_halo')]
        check(bool(halos), description + ': whole connector has a visible glow')
        check(all(any(len(h)==len(c) and all(abs(a-b)<0.1 for a,b in zip(h,c)) for h in halos)
                  for c in record['segments']), description + ': glow covers every complete polyline, including bends')
        pump(330)
        windows = pickers()
        check(len(windows) == 1 and editor.shape_picker is windows[0], description + ': hover opens one symbol picker without a click')
        check(editor.pending_insert is not None and editor.pending_insert[0] is record['target'][0]
              and editor.pending_insert[1] == record['target'][1], description + ': popup retains the exact insertion target')
        return windows[0]

    try:
        if os.environ.get('FLOWCHART_HOVER_SCREENSHOT'):
            root.geometry('%dx%d' % (root.winfo_screenwidth(), root.winfo_screenheight()))
        root.update()
        check(set(APP.KINDS).issubset(set(APP.SYMBOL_HELP)), 'every editable symbol has help data')
        check('Terminal' in APP.SYMBOL_HELP and bool(APP.SYMBOL_HELP['Terminal']['definition']), 'Main and End terminals also have a definition')
        for kind in APP.KINDS:
            check(bool(APP.SYMBOL_HELP[kind]['definition'].strip()) and bool(APP.SYMBOL_HELP[kind]['example'].strip()), kind + ' has a definition and example')
        check(bool(editor.connector_paths), 'empty chart exposes its actual connector paths')
        first = next(iter(editor.connector_paths))
        win = assert_hover(first, 'empty Main-to-End connection')
        scene = editor.capture_diagram_scene('Main')
        exported_lines = [item for item in scene['items'] if item['type']=='line']
        record = editor.connector_paths[first]
        check(all(any(len(item['coords'])==len(coords) and all(abs(a*editor.zoom-b)<0.1 for a,b in zip(item['coords'],coords)) for item in exported_lines) for coords in record['segments']), 'PDF scene retains the full real connector paths')
        check(all(item.get('width',0)<7 for item in exported_lines), 'PDF scene excludes the hover halo overlay')
        card = win.symbol_cards['Assign']
        card.event_generate('<Motion>', x=58, y=25, warp=True)
        card.event_generate('<Enter>')
        pump(260)
        check(win.winfo_exists(), 'picker stays open while the pointer is inside it')
        for kind, symbol in win.symbol_cards.items():
            symbol.event_generate('<Motion>', x=58, y=25, warp=True)
            pump(25)
            symbol.event_generate('<Enter>')
            root.update()
            text = win.symbol_help_text.get()
            check(win.symbol_help_kind.get() == kind and APP.SYMBOL_HELP[kind]['definition'] in text
                  and 'Example' in text, kind + ': actual picker hover shows its explanation')
        chosen = []
        original_add = editor.add_shape
        intended = editor.pending_insert
        editor.add_shape = lambda kind: chosen.append((kind, editor.pending_insert))
        try:
            win.symbol_cards['Assign'].event_generate('<Button-1>')
            pump(40)
        finally:
            editor.add_shape = original_add
        check(len(chosen)==1 and chosen[0][0]=='Assign' and chosen[0][1] is not None
              and chosen[0][1][0] is intended[0] and chosen[0][1][1]==intended[1], 'choosing a symbol uses the hovered insertion point')
        check(not pickers(), 'choosing a symbol closes the hover popup')

        doc = APP.empty_document()
        decision = APP.node('If', expression='i > 0', true=[APP.node('Output', expression='"yes"')], false=[])
        loop = APP.node('While', expression='i < 2', body=[APP.node('Assign', variable='i', expression='i + 1')])
        counted = APP.node('For', variable='i', end='2', body=[APP.node('Output', expression='i')])
        post = APP.node('Do', expression='i < 1', body=[APP.node('Output', expression='i')])
        doc['functions'][0]['body'] = [APP.node('Declare', name='i'), decision, loop, counted, post, APP.node('Output', expression='"done"')]
        editor.replace_doc(doc)
        editor.hide_tools()
        editor.fit_diagram()
        pump(50)
        paths = editor.connector_paths
        check(any(len(c)>4 for r in paths.values() for c in r['segments']), 'routed branch and loop connectors retain their entire bent paths')
        check(any(not r['target'][0] for r in paths.values()), 'empty branch has a hoverable insertion connector')
        for tag, record in paths.items():
            check(tag in editor.insert_hit_targets and len(record['parts']) == len(record['segments']), 'connector geometry and insertion mapping remain aligned')
            check(all(editor.canvas.type(part)=='line' and editor.canvas.coords(part)==coords for part, coords in zip(record['parts'], record['segments'])), 'each registered connector stores its complete drawn geometry')

        body = editor.doc['functions'][0]['body']
        requested = [
            (decision['true'], 0, 'decision true branch'),
            (decision['false'], 0, 'empty false branch'),
            (loop['body'], len(loop['body']), 'while return path'),
            (counted['body'], 0, 'for loop entry'),
            (post['body'], 0, 'do loop entry'),
            (body, len(body), 'connection before End'),
        ]
        for block, index, description in requested:
            matching = [tag for tag,r in paths.items() if r['target'][0] is block and r['target'][1] == index]
            check(bool(matching), description + ': connector is registered for the intended branch/index')
            window = assert_hover(matching[0], description)
            if description == 'while return path' and os.environ.get('FLOWCHART_HOVER_SCREENSHOT'):
                card = window.symbol_cards['For']
                card.event_generate('<Motion>', x=58, y=25, warp=True)
                pump(40)
                card.event_generate('<Enter>')
                pump(50)
                subprocess.check_call(['import', '-window', 'root', os.environ['FLOWCHART_HOVER_SCREENSHOT']])
        close_picker()
        check(not pickers() and editor.hover_connector is None, 'moving outside both diagram line and picker clears popup and glow')

        first = next(iter(editor.connector_paths))
        assert_hover(first, 'mouse-wheel cleanup probe')
        editor.canvas.event_generate('<MouseWheel>', delta=-120, state=0)
        pump(50)
        check(not pickers() and editor.hover_connector is None and not editor.canvas.find_withtag('connector_halo'), 'mouse wheel clears stale hover popup and glow before scrolling')
        assert_hover(first, 'scrollbar cleanup probe')
        editor.scroll_canvas('y', 'scroll', 1, 'units')
        pump(50)
        check(not pickers() and editor.hover_connector is None and not editor.canvas.find_withtag('connector_halo'), 'scrollbar command clears stale hover popup and glow')
        assert_hover(first, 'redraw cleanup probe')
        editor.set_zoom(1.15)
        pump(50)
        check(not pickers() and editor.hover_connector is None and not editor.canvas.find_withtag('connector_halo'), 'zoom/redraw removes stale hover popup and glow')
        check(bool(editor.connector_paths), 'zoom regenerates live connector geometry')
        root.event_generate('<Motion>', x=5, y=5, warp=True)

        editor.scroll_canvas('y', 'moveto', 0)
        first_node = editor.doc['functions'][0]['body'][0]
        node_tag = 'hit_' + editor.node_iids[id(first_node)]
        bounds = editor.canvas.bbox(node_tag)
        center = ((bounds[0]+bounds[2])/2.0, (bounds[1]+bounds[3])/2.0)
        world_pointer(*center)
        x = int(round(center[0]-editor.canvas.canvasx(0)))
        y = int(round(center[1]-editor.canvas.canvasy(0)))
        editor.canvas.event_generate('<ButtonPress-1>', x=x, y=y)
        check(editor.canvas_drag_iid is not None, 'ordinary symbol press is a real canvas click')
        editor.canvas.event_generate('<ButtonRelease-1>', x=x, y=y)
        pump(40)
        check(editor.canvas_drag_iid is None, 'ordinary symbol click clears the potential drag on release')
        assert_hover(next(iter(editor.connector_paths)), 'hover after selecting a symbol')
        close_picker()

        shape_class = inspect.getclosurevars(editor.edit_shape).nonlocals['ShapeDialog']
        original_wait = shape_class.wait_window
        original_document = editor.doc
        original_body = original_document['functions'][0]['body']
        original_size = len(original_body)
        editor.pending_insert = (original_body, 0)
        editor.code.delete('1.0', 'end')
        editor.code.insert('1.0', 'x = 42\n')
        def unexpected_dialog(*unused):
            raise AssertionError('stale insertion unexpectedly opened a symbol dialog')
        shape_class.wait_window = unexpected_dialog
        try:
            editor.add_shape('Output')
        finally:
            shape_class.wait_window = original_wait
        check(editor.doc is not original_document and len(original_body)==original_size and
              [n['kind'] for n in APP.walk(editor.doc['functions'][0]['body'])]==['Assign'],
              'source reconstruction cancels a stale popup insertion without adding a node')
        seen = []
        def inspect_dialog(dialog, *unused):
            text = '\n'.join(str(w.cget('text')) for w in descendants(dialog) if isinstance(w, (tk.Label, ttk.Label)))
            seen.append(APP.SYMBOL_HELP[dialog.original['kind']]['definition'] in text and 'Example' in text)
            dialog.cancel()
        shape_class.wait_window = inspect_dialog
        try:
            for kind in APP.KINDS:
                shape_class(root, APP.node(kind))
        finally:
            shape_class.wait_window = original_wait
        check(len(seen)==len(APP.KINDS) and all(seen), 'every actual symbol editing dialog visibly explains its behavior and example')
        check(not failures, 'hover, popup and symbol-help workflow has no Tk callback errors')
    except Exception:
        failures.append(traceback.format_exc())
    finally:
        root.destroy()


tk.Tk.mainloop = test_mainloop
try:
    result = APP.launch_gui()
finally:
    tk.Tk.mainloop = original_mainloop
if failures:
    print('\n'.join(failures), file=sys.stderr)
    sys.exit(1)
if result:
    sys.exit(result)
print('%d connector hover/help checks passed on Python %s.' % (len(checks), sys.version.split()[0]))
