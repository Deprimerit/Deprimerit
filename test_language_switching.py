# -*- coding: utf-8 -*-
"""Actual desktop Python-to-language selection checks; Python 3.3+ syntax."""
from __future__ import print_function
import inspect
import io
import os
import sys
import traceback
import types
import tkinter as tk

APP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Flowchart_Studio.py')
APP = types.ModuleType('flowchart_language_switching')
APP.__file__ = APP_PATH
with io.open(APP_PATH, encoding='utf-8') as stream:
    exec(compile(stream.read(), APP_PATH, 'exec'), APP.__dict__)

PROGRAMS = [
    ('inline input range', 'for i in range(int(input())+1):print(i)\n'),
    ('assigned tuple', "r=(1,2,3)\nfor i in r:print(i)\n"),
    ('assigned dictionary', "r={'a':1,'b':2}\nfor i in r:print(i)\n"),
    ('dictionary items', "r={'a':1,'b':2}\nfor k,v in r.items():print(k,v)\n"),
    ('string', "r='abc'\nfor i in r:print(i)\n"),
    ('list', "r=[2,4,6]\nfor i in r:print(i)\n"),
]
checks, failures = [], []
original_mainloop = tk.Tk.mainloop


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    checks.append(message)


def test_mainloop(root, *unused):
    editor = inspect.currentframe().f_back.f_locals['app']
    root.report_callback_exception = lambda *args: failures.append(''.join(traceback.format_exception(*args)))
    try:
        root.update()
        for name, python in PROGRAMS:
            editor.replace_doc(APP.empty_document())
            editor.language.set('Python')
            editor.language_changed()
            editor.code.delete('1.0', 'end')
            editor.code.insert('1.0', python)
            editor.code.edit_modified(True)
            editor.code_modified()
            check(editor.code_timer is not None, name + ': input has a pending source update')
            for language in APP.LANGUAGES:
                editor.language.set(language)
                editor.language_changed()
                root.update()
                text = editor.code.get('1.0', 'end-1c')
                check(editor.language.get() == language, name + ': can select ' + language)
                check(editor.code_language == language, name + ': text language tracks ' + language)
                check(editor.source is not None and bool(text.strip()) and 'SOURCE NOT GENERATED' not in text,
                      name + ': actual source is generated for ' + language + ': ' + text[:250])
                check(editor.doc.get('python'), name + ': switching retains original Python chart')
            editor.language.set('Python')
            editor.language_changed()
            check(editor.source is not None, name + ': Python remains recoverable after all language selections')

        original_chart = editor.state()
        invalid = 'for i in range(:\n'
        editor.code.delete('1.0', 'end')
        editor.code.insert('1.0', invalid)
        editor.code.edit_modified(True)
        editor.code_modified()
        editor.language.set('Java')
        editor.language_changed()
        check(editor.language.get() == 'Python', 'invalid Python blocks switching instead of losing the draft')
        check(editor.code.get('1.0', 'end-1c') == invalid, 'invalid draft text is retained')
        check(editor.state() == original_chart, 'invalid source retains previous valid chart')
        check(not failures, 'no Tk callback errors during cross-language selection')
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
print('%d language-switching GUI checks passed on Python %s.' % (len(checks), sys.version.split()[0]))
