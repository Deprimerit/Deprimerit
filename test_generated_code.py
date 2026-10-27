# -*- coding: utf-8 -*-
"""Generated-code desktop regression checks, compatible with Python3.3+.
Run on a desktop display: python test_generated_code.py
"""
from __future__ import print_function
import inspect
import io
import os
import subprocess
import sys
import traceback
import types
import tkinter as tk

APP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Flowchart_Studio.py')
APP = types.ModuleType('flowchart_generated_code_test')
APP.__file__ = APP_PATH
with io.open(APP_PATH, encoding='utf-8') as stream:
    exec(compile(stream.read(), APP_PATH, 'exec'), APP.__dict__)

checks, failures = [], []
original_mainloop = tk.Tk.mainloop


def check(condition, description):
    if not condition:
        raise AssertionError(description)
    checks.append(description)
    print('PASS:', description)


def python_output(source, supplied=''):
    old_in, old_out = sys.stdin, sys.stdout
    output = io.StringIO()
    try:
        sys.stdin, sys.stdout = io.StringIO(supplied), output
        exec(compile(source, '<trusted generated fixture>', 'exec'), {'__name__': '__main__'})
    finally:
        sys.stdin, sys.stdout = old_in, old_out
    return output.getvalue()


def test_mainloop(root, *unused):
    editor = inspect.currentframe().f_back.f_locals['app']
    root.report_callback_exception = lambda *args: failures.append(''.join(traceback.format_exception(*args)))
    try:
        root.update()
        check(editor.tools_visible, 'generated code panel is visible on launch')
        check(editor.code.winfo_ismapped(), 'source editor actually appears in the desktop window')
        check(editor.notebook.index('current') == 0, 'generated code is the selected initial tool')
        check(editor.language_box.winfo_ismapped(), 'source language selector is visible')
        check(editor.source is not None, 'empty document has a valid generated program')
        initial = editor.code.get('1.0', 'end-1c')
        check('Main is empty' in initial and 'pass' in initial, 'empty chart explains how to create generated code')
        check(initial == APP.generate_source('Python', editor.doc), 'initial visible text is actual exported code')
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                for nested in descendants(child):
                    yield nested
        generate_button = next(w for w in descendants(root) if w.winfo_class()=='TButton' and w.cget('text')=='Generate code')
        check(generate_button.winfo_ismapped(), 'Generate code action is visible on the toolbar')
        check(python_output(editor.code.get('1.0', 'end-1c')) == '', 'initial generated Python is a valid empty program')
        editor.hide_tools()
        check(not editor.tools_visible, 'user can still close the source panel')
        generate_button.invoke()
        root.update()
        check(editor.tools_visible and editor.code.winfo_ismapped(), 'Generate code reopens the source panel')
        generate_button.invoke()
        check(editor.tools_visible, 'repeated Generate code does not hide the panel')

        editor.replace_doc(APP.sample_document())
        root.update()
        generated = editor.code.get('1.0', 'end-1c')
        check(bool(generated.strip()) and 'print' in generated, 'example chart shows generated Python')
        check(python_output(generated, '3\n') == 'Enter a positive number:\nSum = 6\n', 'generated example runs correctly')
        if os.environ.get('FLOWCHART_GENERATED_SCREENSHOT'):
            editor.fit_diagram()
            root.update()
            subprocess.check_call(['import', '-window', root.frame(), os.environ['FLOWCHART_GENERATED_SCREENSHOT']])
        editor.doc['functions'][0]['body'][-1]['expression'] = '"Changed output"'
        editor.refresh()
        generated = editor.code.get('1.0', 'end-1c')
        check('Changed output' in generated, 'chart edits refresh generated code')
        check(python_output(generated, '3\n').endswith('Changed output\n'), 'regenerated Python reflects the chart edit')

        source = 'for i in range(int(input())+1):print(i)\n'
        editor.replace_doc(APP.parse_python(source))
        generated = editor.code.get('1.0', 'end-1c')
        check(python_output(generated, '3\n') == '0\n1\n2\n3\n', 'reported inline-input loop has working generated Python')
        source = "r={'a':1,'b':2}\nfor key,value in sorted(r.items()):print(key,value)\n"
        editor.replace_doc(APP.parse_python(source))
        check(python_output(editor.code.get('1.0', 'end-1c')) == 'a 1\nb 2\n', 'dictionary loop has working generated Python')

        portable = APP.empty_document()
        portable['functions'][0]['body'] = [APP.node('Output', expression='"Generated hello"')]
        editor.replace_doc(portable)
        editor.language.set('Java')
        editor.language_changed()
        check('System.out.print' in editor.code.get('1.0', 'end-1c'), 'changing language displays Java generation')
        editor.language.set('Python')
        editor.language_changed()
        check(python_output(editor.code.get('1.0', 'end-1c')) == 'Generated hello\n', 'changing back displays working Python generation')

        old_chart = editor.state()
        invalid = 'for i in range(:\n'
        editor.code.delete('1.0', 'end')
        editor.code.insert('1.0', invalid)
        editor.show_generated_code()
        check(editor.code.get('1.0', 'end-1c') == invalid, 'Generate code preserves invalid unapplied source')
        check(editor.state() == old_chart, 'invalid draft does not replace the valid chart')
        check(editor.tools_visible and editor.notebook.index('current') == 0, 'invalid source stays visible for correction')
        editor.update_code()
        root.update()
        check(not failures, 'generated-code workflow has no Tcl callback failures')
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
print('%d generated-code GUI checks passed on Python %s.' % (len(checks), sys.version.split()[0]))
