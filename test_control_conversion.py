# -*- coding: utf-8 -*-
"""Python 3.3+ lazy input/range conversion regressions across all targets."""
from __future__ import print_function
import io
import os
import sys
import types
import unittest

APP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Flowchart_Studio.py')
APP = types.ModuleType('flowchart_control_tests')
APP.__file__ = APP_PATH
with io.open(APP_PATH, encoding='utf-8') as f:
    exec(compile(f.read(), APP_PATH, 'exec'), APP.__dict__)

CASES = [
    ('prompts', "print(int(input('A: '))+int(input('B: ')))\n", '3\n4\n'),
    ('lazy_if', "n=int(input())\nif n and int(input()):print('yes')\nelse:print('no')\n", '0\n'),
    ('lazy_while', "while int(input())>0:\n    if int(input())==9:continue\n    print('body')\n", '1\n9\n1\n0\n0\n'),
    ('conditional_input', "print(int(input()) if int(input()) else int(input()))\n", '0\n7\n'),
    ('break_continue', "for i in range(1,8,2):\n    if i==3:continue\n    if i==5:break\n    print(i)\nprint(i)\n", ''),
    ('empty_range', "i=99\nfor i in range(0):print(i)\nprint(i)\n", ''),
    ('function_bound', "def count():\n    print('called')\n    return 3\nfor i in range(count()):print(i)\n", ''),
    ('input_bounds', "for i in range(int(input()),int(input()),int(input())):print(i)\n", '5\n0\n-2\n'),
    ('input_index', "values=[10,20,30]\nprint(values[int(input())])\n", '1\n'),
]


def reference(source, supplied):
    oldin, oldout = sys.stdin, sys.stdout
    out = io.StringIO()
    try:
        sys.stdin, sys.stdout = io.StringIO(supplied), out
        exec(compile(source, '<trusted conversion fixture>', 'exec'), {'__name__':'__main__'})
        return out.getvalue()
    finally:
        sys.stdin, sys.stdout = oldin, oldout


class ControlConversionTests(unittest.TestCase):
    pass


def test_case(source, supplied, language):
    def test(self):
        expected = reference(source, supplied)
        generated = APP.generate_source(language, APP.parse_python(source))
        chart = APP.parse_code(language, generated)
        inputs = iter(supplied.splitlines())
        chunks = []
        APP.Interpreter(chart, lambda _: next(inputs), lambda text, nl: chunks.append(str(text)+ ('\n' if nl else ''))).run()
        self.assertEqual(''.join(chunks), expected)
    return test


for name, source, supplied in CASES:
    for language in APP.LANGUAGES:
        safe = language.replace('+','plus').replace('#','sharp')
        setattr(ControlConversionTests, 'test_'+name+'_'+safe, test_case(source,supplied,language))

if __name__ == '__main__':
    unittest.main(verbosity=1)
