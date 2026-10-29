# -*- coding: utf-8 -*-
"""Actual desktop execution, cancellation and pause/resume checks (Python 3.3+).

Run with a desktop display: python test_execution_gui.py
The global watchdog also catches an unresponsive Tk interpreter during a test.
"""
from __future__ import print_function
try:
    import faulthandler
except ImportError:
    faulthandler = None  # Python 3.2: run this test with an external timeout.
import inspect
import io
import os
import sys
import time
import traceback
import types
import tkinter as tk

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(ROOT, 'Flowchart_Studio.py')
APP = types.ModuleType('flowchart_execution_gui_under_test')
APP.__file__ = APP_PATH
with io.open(APP_PATH, encoding='utf-8') as stream:
    exec(compile(stream.read(), APP_PATH, 'exec'), APP.__dict__)
with io.open(os.path.join(ROOT, 'examples', 'alphabet_letters.py'), encoding='utf-8') as stream:
    ALPHABET = stream.read()

checks, failures = [], []
original_mainloop = tk.Tk.mainloop
if faulthandler is not None:
    faulthandler.dump_traceback_later(float(os.environ.get('FLOWCHART_EXECUTION_TIMEOUT', '180')), exit=True)


def check(condition, description):
    if not condition:
        raise AssertionError(description)
    checks.append(description)
    print('PASS:', description)


def reference(source, supplied):
    old_in, old_out = sys.stdin, sys.stdout
    result = io.StringIO()
    try:
        sys.stdin, sys.stdout = io.StringIO(supplied), result
        exec(compile(source, '<trusted GUI fixture>', 'exec'), {'__name__': '__main__'})
        return result.getvalue()
    finally:
        sys.stdin, sys.stdout = old_in, old_out


def test_mainloop(root, *unused):
    editor = inspect.currentframe().f_back.f_locals['app']
    root.report_callback_exception = lambda *args: failures.append(''.join(traceback.format_exception(*args)))
    original_log = editor.log
    captured, timers = [], []

    def logged(value, newline=True):
        captured.append(str(value) + ('\n' if newline else ''))
        original_log(value, newline)
    editor.log = logged

    def exists():
        try:
            return bool(root.winfo_exists())
        except tk.TclError:
            return False

    def guarded(callback):
        def invoke():
            try:
                callback()
            except Exception:
                failures.append(traceback.format_exc())
                try:
                    editor.stop()
                except Exception:
                    pass
        return invoke

    def later(delay, callback):
        identifier = root.after(delay, guarded(callback))
        timers.append(identifier)
        return identifier

    def cancel_timers():
        while timers:
            try:
                root.after_cancel(timers.pop())
            except tk.TclError:
                pass

    def prepare(source, supplied=''):
        cancel_timers()
        editor.stop()
        editor.replace_doc(APP.parse_python(source))
        editor.language.set('Python')
        editor.code_language = 'Python'
        editor.speed.set(0)
        values = iter(supplied.splitlines())
        editor.read_input = lambda name: next(values)
        captured[:] = []
        root.update()

    def output():
        result = ''.join(captured)
        result = result.replace('--- Execution started ---\n', '')
        return result.replace('--- Execution finished ---\n', '')

    def run_to(predicate, description, timeout=20):
        deadline = time.time() + timeout
        expired = [False]
        def abort():
            expired[0] = True
            editor.stop()
        watchdog = later(int(timeout * 1000), abort)
        try:
            editor.run()
            while not predicate() and not expired[0] and time.time() < deadline:
                root.update()
                time.sleep(0.001)
            check(not expired[0] and predicate(), description)
        finally:
            try:
                root.after_cancel(watchdog)
            except tk.TclError:
                pass
        check(not failures, description + ': no Tk callback errors')

    def finished():
        return editor.iterator is None and not editor.running

    def when_active(callback, frames=False):
        deadline = time.time() + 10
        def poll():
            engine = editor.engine
            if (engine is not None and getattr(editor, '_advancing', False)
                    and engine.count >= 2048 and (not frames or bool(engine.frames))):
                callback()
            elif time.time() >= deadline:
                raise AssertionError('Execution never reached the active expression')
            else:
                later(1, poll)
        later(1, poll)

    try:
        root.update()
        supplied = 'y\nA\n2\ny\nB\n1\nn\n'
        prepare(ALPHABET, supplied)
        responsive = []
        when_active(lambda: responsive.append(editor.engine.count))
        run_to(finished, 'exact alphabet program completes through default GUI execution', timeout=60)
        check(editor.engine.limit is None, 'GUI uses the ordinary unlimited operation budget')
        check(editor.engine.count > 100000, 'valid alphabet execution passes the old lifetime cutoff')
        check(output() == reference(ALPHABET, supplied), 'complete alphabet GUI output matches CPython')
        check(bool(responsive), 'Tk callbacks run while the alphabet expression is evaluating')
        check('ERROR:' not in output(), 'alphabet execution has no false infinite-loop error')

        prepare('def forever():\n    total=0\n    while True:\n        total+=1\nforever()\nprint("never")\n')
        stopped = []
        when_active(lambda: (stopped.append(editor.engine.count), editor.stop()), frames=True)
        began = time.time()
        run_to(finished, 'Stop cancels an infinite user function')
        check(bool(stopped) and time.time()-began < 3, 'function cancellation remains responsive')
        check(editor.engine is None and editor.current_node is None, 'Stop resets active function debugger state')
        check('ERROR:' not in output() and 'never' not in output(), 'normal Stop produces no error or later program output')

        prepare('value=sum(i*i for i in range(1000000000))\nprint("never")\n')
        stopped = []
        when_active(lambda: (stopped.append(editor.engine.count), editor.stop()))
        run_to(finished, 'Stop cancels a long generator expression')
        check(bool(stopped) and 'ERROR:' not in output() and 'never' not in output(), 'generator cancellation stops before assignment/output without errors')

        source = 'def work():\n    print("started")\n    return sum(i for i in range(30000))\nvalue=work()\nprint(value)\nprint("done")\n'
        prepare(source)
        paused, resumed = [], []
        def pause_then_resume():
            editor.pause()
            def observe_pause():
                check(getattr(editor, '_execution_waiting', False), 'Pause suspends the active function stack')
                paused.append(editor.engine.count)
            def resume():
                check(paused and editor.engine.count == paused[-1], 'paused function performs no additional operations')
                check(not editor.running, 'paused function reports paused state')
                editor.run()
                resumed.append(True)
            later(15, observe_pause)
            later(60, resume)
        when_active(pause_then_resume, frames=True)
        run_to(finished, 'Run resumes a paused expression and finishes')
        check(bool(resumed) and output() == reference(source, ''), 'Pause/Run preserves work and calls without duplication')
        check(editor.engine.env.get('value') == sum(range(30000)), 'resumed function stores its complete result')

        prepare('value=sum(i for i in range(30000))\nprint("after-step")\n')
        stepped = []
        def pause_then_step():
            editor.pause()
            def step():
                check(getattr(editor, '_execution_waiting', False), 'Step can wake a paused expression')
                editor.step()
                stepped.append(True)
            later(30, step)
        when_active(pause_then_step)
        run_to(lambda: (bool(stepped) and not editor.running and not getattr(editor, '_advancing', False)),
               'Step finishes the current expression then returns to a chart boundary')
        check(editor.engine.env.get('value') == sum(range(30000)), 'Step preserves the unfinished expression result')
        check(editor.current_node is not None and editor.current_node['kind'] == 'Output', 'Step pauses before the following output shape')
        check('after-step' not in output(), 'following shape is not executed by the resume Step')
        run_to(finished, 'Run after resumed Step finishes the remaining chart')
        check(output() == 'after-step\n', 'remaining output executes exactly once')

        prepare('value=sum(i for i in range(1000000000))\nprint("stale")\n')
        changed = []
        def replace_and_run():
            editor.replace_doc(APP.parse_python('print("fresh")\n'))
            changed.append(True)
            editor.run()
        when_active(replace_and_run)
        run_to(lambda: bool(changed) and finished() and 'fresh\n' in output(), 'replacing a busy chart and immediately running starts only the new chart')
        check('stale' not in output() and 'ERROR:' not in output(), 'old expression cleanup cannot affect the replacement chart')
        check(output() == 'fresh\n', 'replacement chart output appears exactly once')

        prepare('value=input("prompt: ")\nprint("stale")\n')
        changed = []
        def replace_during_input(name):
            editor.replace_doc(APP.parse_python('print("fresh-input")\n'))
            changed.append(True)
            return 'old value'
        editor.read_input = replace_during_input
        run_to(lambda: bool(changed) and finished(), 'reset from an input callback cancels the old statement')
        check('stale' not in output() and 'ERROR:' not in output(), 'old input result does not resume a cancelled program')
        captured[:] = []
        run_to(finished, 'new chart runs after input cancellation')
        check(output() == 'fresh-input\n', 'input cancellation preserves the replacement chart')

        prepare('value=sum(i for i in range(1000000000))\nprint("stale")\n')
        closed = []
        editor.check_discard = lambda: True
        def close():
            closed.append(True)
            editor.close()
        when_active(close)
        editor.run()
        check(bool(closed) and not exists(), 'closing the window cancels active expression execution')
        check('stale' not in ''.join(captured) and 'ERROR:' not in ''.join(captured), 'window closure does not report a cancellation as an execution error')
        check(not failures, 'all execution controls complete without Tk callback errors')
    except Exception:
        failures.append(traceback.format_exc())
    finally:
        if exists():
            cancel_timers()
            try:
                editor.stop()
            finally:
                root.destroy()


tk.Tk.mainloop = test_mainloop
try:
    result = APP.launch_gui()
finally:
    tk.Tk.mainloop = original_mainloop
    if faulthandler is not None:
        faulthandler.cancel_dump_traceback_later()
if failures:
    print('\n'.join(failures), file=sys.stderr)
    sys.exit(1)
if result:
    sys.exit(result)
print('%d execution GUI checks passed on Python %s.' % (len(checks), sys.version.split()[0]))
