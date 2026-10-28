# -*- coding: utf-8 -*-
"""Python -> all target languages regression matrix (Python 3.3+).

Each fixture must generate target source, parse back, and preserve its observable
output. Available C, C++ and JavaScript runtimes additionally compile/run the
actual generated source. Missing runtimes are explicit skips, not compiler passes.
Only the bounded, trusted fixture reference uses Python exec; production does not.
"""
from __future__ import print_function
import io
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest

APP_PATH = os.environ.get('FLOWCHART_MODULE', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Flowchart_Studio.py'))
APP = types.ModuleType('flowchart_cross_language_under_test')
APP.__file__ = APP_PATH
with io.open(APP_PATH, 'r', encoding='utf-8') as stream:
    exec(compile(stream.read(), APP_PATH, 'exec'), APP.__dict__)

PROGRAMS = {
    'hello': ("print('Hello, generated code')\n", ''),
    'assigned_input_sum': ('n=int(input())\ntotal=0\nfor i in range(n+1):total+=i\nprint(total)\n', '3\n'),
    'inline_input_range': ('for i in range(int(input())+1):print(i)\n', '3\n'),
    'input_arithmetic': ('print(int(input()) + int(input()))\n', '3\n7\n'),
    'string_iteration': ("r='abc'\nfor i in r:print(i)\n", ''),
    'list_iteration': ('r=[2,4,6]\nfor i in r:print(i)\n', ''),
    'tuple_iteration': ('r=(2,4,6)\nfor i in r:print(i)\n', ''),
    'literal_tuple_iteration': ("for i in ('red','blue'):print(i)\n", ''),
    'dictionary_keys': ("r={'a':10,'b':20}\nfor i in r:print(i)\n", ''),
    'dictionary_values': ("r={'a':10,'b':20}\nfor i in r.values():print(i)\n", ''),
    'dictionary_items': ("r={'a':10,'b':20}\nfor k,v in r.items():print(k,v)\n", ''),
    'dynamic_negative_step': ('step=-2\nfor i in range(5,0,step):print(i)\n', ''),
    'range_bound_snapshot': ('n=4\nfor i in range(n):\n    print(i)\n    n=0\n', ''),
    'range_last_value': ('for i in range(3):print(i)\nprint(i)\n', ''),
    'nested_loops': ("for i in range(2):\n    for j in ('a','b'):print(i,j)\n", ''),
    'assigned_range_snapshot': ('n=5\nr=range(n)\nn=2\nfor i in r:print(i)\n', ''),
    'enumerate_start_snapshot': ("start=3\nfor i,v in enumerate(('a','b'),start):\n    print(i,v)\n    start=9\n", ''),
    'dictionary_key_lookup': ("r={'a':10,'b':20}\nfor i in r:print(i,r[i])\n", ''),
    'string_snapshot': ("r='abc'\nfor i in r:\n    print(i)\n    r='x'\n", ''),
    'range_step_snapshot': ('step=1\nfor i in range(4,0,-step):\n    print(i)\n    step=2\n', ''),
    'for_else': ("for i in range(3):print(i)\nelse:print('done')\n", ''),
    'sum_generator': ('print(sum(i*i for i in range(4)))\n', ''),
}


def reference(source, supplied):
    old_in, old_out = sys.stdin, sys.stdout
    output = io.StringIO()
    try:
        sys.stdin, sys.stdout = io.StringIO(supplied), output
        exec(compile(source, '<trusted matrix fixture>', 'exec'), {'__name__': '__main__'})
        return output.getvalue()
    finally:
        sys.stdin, sys.stdout = old_in, old_out


def interpret(doc, supplied):
    stdin, stdout = io.StringIO(supplied), io.StringIO()
    def read_input(prompt):
        value = stdin.readline()
        if value == '':
            raise AssertionError('Generated chart requested more input than the reference.')
        return value.rstrip('\r\n')
    APP.Interpreter(doc, read_input, lambda value, newline: stdout.write(str(value) + ('\n' if newline else '')), limit=30000).run()
    return stdout.getvalue()


def comparable_output(source, output):
    # Older Python releases intentionally leave dictionary iteration order
    # unspecified. These fixtures have independent output rows, so compare
    # the complete key/value rows without imposing Python 3.7's order rule.
    unordered = ('dictionary_keys', 'dictionary_values', 'dictionary_items', 'dictionary_key_lookup')
    if sys.version_info < (3, 7) and source in [PROGRAMS[name][0] for name in unordered]:
        return sorted(output.splitlines())
    return output


def process(args, stdin='', cwd=None):
    child = subprocess.Popen(args, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    try:
        output, error = child.communicate(stdin, timeout=20)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()
        raise AssertionError('Generated program/compiler timed out: ' + repr(args))
    if child.returncode:
        raise AssertionError('Generated program/compiler failed ({0}):\n{1}'.format(child.returncode, error))
    return output


class TargetRoundTripTests(unittest.TestCase):
    pass


class TargetExecutionTests(unittest.TestCase):
    pass


def matrix_test(language, source, supplied):
    def test(self):
        expected = reference(source, supplied)
        doc = APP.parse_python(source)
        generated = APP.generate_source(language, doc)
        self.assertTrue(generated.strip(), 'No target code was generated')
        self.assertNotIn('SOURCE NOT GENERATED', generated)
        reparsed = APP.parse_code(language, generated)
        self.assertEqual(comparable_output(source, interpret(reparsed, supplied)), comparable_output(source, expected), language + ' target round trip changed observable behavior')
    return test


def executable_test(language, source, supplied):
    def test(self):
        tool = {'C': 'gcc', 'C++': 'g++', 'JavaScript': 'node'}[language]
        executable = shutil.which(tool)
        if not executable:
            self.skipTest(language + ' external compiler/runtime is unavailable')
        expected = reference(source, supplied)
        generated = APP.generate_source(language, APP.parse_python(source))
        directory = tempfile.mkdtemp(prefix='flowchart-target-')
        try:
            path = os.path.join(directory, {'C': 'main.c', 'C++': 'main.cpp', 'JavaScript': 'main.js'}[language])
            with io.open(path, 'w', encoding='utf-8') as stream:
                stream.write(generated)
            if language == 'JavaScript':
                actual = process([executable, path], supplied, directory)
            else:
                program = os.path.join(directory, 'program')
                flags = ['-std=c99'] if language == 'C' else ['-std=c++11']
                process([executable] + flags + [path, '-lm', '-o', program], cwd=directory)
                actual = process([program], supplied, directory)
            self.assertEqual(comparable_output(source, actual), comparable_output(source, expected), language + ' compiled/runtime output differs from CPython')
        finally:
            shutil.rmtree(directory)
    return test


for _name, (_source, _supplied) in PROGRAMS.items():
    for _language in APP.LANGUAGES:
        _safe = _language.replace('+', 'plus').replace('#', 'sharp')
        setattr(TargetRoundTripTests, 'test_' + _name + '_' + _safe, matrix_test(_language, _source, _supplied))
    for _language in ('C', 'C++', 'JavaScript'):
        _safe = _language.replace('+', 'plus')
        setattr(TargetExecutionTests, 'test_' + _name + '_' + _safe, executable_test(_language, _source, _supplied))


if __name__ == '__main__':
    unittest.main(verbosity=2)
