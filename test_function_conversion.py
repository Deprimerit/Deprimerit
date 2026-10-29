# -*- coding: utf-8 -*-
"""Scalar function defaults and keyword argument conversion, Python 3.3+ tests.

The app itself supports Python 3.2+. Fixtures compare observable output with
CPython across all targets and real C/C++/JavaScript execution when available.
"""
from __future__ import print_function
import unittest
import test_cross_language as matrix

APP = matrix.APP
MARK = 'def mark(x):\n    print(x)\n    return x\n'
PROGRAMS = [
    ('scalar_defaults', 'def add(a,b=3):\n    return a+b\nprint(add(2),add(2,4))\n', ''),
    ('keyword_reordering', 'def number(a,b,c=3):\n    return a*100+b*10+c\nprint(number(c=9,a=1,b=2),number(b=5,a=4))\n', ''),
    ('keyword_order', MARK + 'def number(a,b,c=3):\n    return a*100+b*10+c\nprint(number(b=mark(2),a=mark(1)))\n', ''),
    ('default_effect_once', MARK + 'def value(x=mark(3)):\n    return x\nprint(value(),value(),value(9))\n', ''),
    ('default_bind_time', 'x=2\ndef value(a=x):\n    return a\nx=9\nprint(value(),value(7))\n', ''),
    ('default_wrapper', 'def inner(a=3):\n    return a+1\ndef outer():\n    return inner()\nprint(outer())\n', ''),
    ('default_wrapper_chain', 'def inner(a=4):\n    return a\ndef middle():\n    return inner()\ndef outer():\n    return middle()\nprint(outer())\n', ''),
    ('recursive_default', 'def total(n,step=2):\n    if n<=0:return 0\n    return step+total(n-1)\nprint(total(3),total(2,5))\n', ''),
    ('recursive_keyword', 'def total(n,step=2):\n    if n<=0:return 0\n    return step+total(step=step,n=n-1)\nprint(total(step=3,n=4))\n', ''),
    ('earlier_function_default', 'def first(x=3):\n    return x+1\ndef second(x=first()):\n    return x\nprint(second(),first())\n', ''),
    ('multiple_default_effects', MARK + 'def value(a=mark(1),b=mark(2)):\n    return a*10+b\nprint(value(),value(b=8))\n', ''),
    ('lazy_keyword_call', MARK + 'def value(a,b=2):\n    return a+b\nflag=0\nprint(value(a=mark(1)) if flag else 8)\nif flag and value(a=mark(2)):print("bad")\nprint("done")\n', ''),
    ('nested_keyword_calls', MARK + 'def value(a,b=3):\n    return a+b\nprint(value(b=value(a=mark(2)),a=mark(1)))\n', ''),
    ('keyword_input', 'def subtract(a,b=2):\n    return a-b\nprint(subtract(b=int(input("B: ")),a=int(input("A: "))))\n', '2\n9\n'),
    ('keyword_dictionary', MARK + 'def add(a,b=3):\n    return a+b\nprint(add(b=mark(2),a={"a":mark(1)}["a"]))\n', ''),
    ('array_keyword', 'def first(a,n=2):\n    return a[0]+n\na=[5]\nprint(first(n=3,a=a))\n', ''),
    ('array_keyword_dictionary', 'def first(a,n=2):\n    return a[0]+n\na=[5]\nprint(first(a=a,n={"x":3}["x"]))\n', ''),
    ('string_default', 'def greet(name="world",prefix="hello "):\n    return prefix+name\nprint(greet(),greet(prefix="hi ",name="Ada"))\n', ''),
    ('string_concat_names', 'prefix="left "\nname="right"\nprint(prefix+name)\n', ''),
    ('function_without_defaults', MARK + 'def pair(a,b):\n    return a+b\nprint(pair(mark(1),mark(2)))\n', ''),
]

REJECTED = [
    ('missing_argument', 'def f(a,b=3):return a+b\nprint(f())\n', 'missing argument'),
    ('duplicate_argument', 'def f(a,b=3):return a+b\nprint(f(1,a=2))\n', 'supplied more than once'),
    ('unknown_keyword', 'def f(a=3):return a\nprint(f(other=2))\n', 'unknown keyword'),
    ('too_many_arguments', 'def f(a=3):return a\nprint(f(1,2))\n', 'too many arguments'),
    ('mutable_name_default', 'values=[1]\ndef f(a=values):return a[0]\nprint(f())\n', 'defaults must be scalar'),
    ('mutable_literal_default', 'def f(a=[1]):return a[0]\nprint(f())\n', 'defaults must be scalar'),
    ('default_not_bound_yet', 'def first():return second()\nprint(first())\ndef second(a=3):return a\n', 'not been evaluated yet'),
]


class FunctionRoundTripTests(unittest.TestCase):
    pass


class FunctionExecutionTests(unittest.TestCase):
    pass


class InvalidFunctionConversionTests(unittest.TestCase):
    pass


def rejection_test(language, source, diagnostic):
    def test(self):
        with self.assertRaises(APP.FlowError) as failure:
            APP.generate_source(language, APP.parse_python(source))
        self.assertIn(diagnostic, str(failure.exception))
    return test


for name, source, supplied in PROGRAMS:
    for language in APP.LANGUAGES:
        safe = language.replace('+','plus').replace('#','sharp')
        setattr(FunctionRoundTripTests, 'test_' + name + '_' + safe,
                matrix.matrix_test(language, source, supplied))
    for language in ('C','C++','JavaScript'):
        safe = language.replace('+','plus')
        setattr(FunctionExecutionTests, 'test_' + name + '_' + safe,
                matrix.executable_test(language, source, supplied))

for name, source, diagnostic in REJECTED:
    for language in APP.LANGUAGES:
        if language == 'Python':
            continue
        safe = language.replace('+','plus').replace('#','sharp')
        setattr(InvalidFunctionConversionTests, 'test_' + name + '_' + safe,
                rejection_test(language, source, diagnostic))

if __name__ == '__main__':
    unittest.main(verbosity=2)
