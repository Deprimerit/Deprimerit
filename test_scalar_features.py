# -*- coding: utf-8 -*-
"""Shared scalar conversion regressions, including actual target execution.

Fixtures compare complete observable output to CPython. Compiler/runtime tests
are explicit skips if their toolchains are unavailable. Production never uses
Python eval/exec to translate or execute user programs.
"""
from __future__ import print_function
import unittest
import test_cross_language as MATRIX

MARK = 'def mark(value):\n    print(value)\n    return value\n'
CASES = [
    ('signed_integer_remainder', 'print(-7%3,7%-3,-7%-3,7%3)\n', ''),
    ('signed_real_remainder', 'print(-7.25%3.0,7.25%-3.0,-7.25%-3.0)\n', ''),
    ('mixed_real_remainder', 'print(-7.25%3,7%-3.25)\n', ''),
    ('remainder_operand_order', MARK + 'print(mark(-7)%mark(3))\n', ''),
    ('nested_remainder_input', 'print(int(input())%int(input()))\n', '-7\n3\n'),
    ('remainder_lazy_branch', "flag=0\nprint(int(input())%3 if flag else 9)\n", ''),
    ('augmented_remainder', 'value=-7\nvalue%=3\nprint(value)\n', ''),
    ('augmented_array_remainder', 'values=[-7,8]\nvalues[0]%=3\nprint(values[0])\n', ''),
    ('augmented_real_remainder', 'value=7.25\nvalue%=-3.0\nprint(value)\n', ''),
    ('bool_scalar', "print('yes' if bool(3) else 'no')\nprint('yes' if bool(0) else 'no')\nprint('yes' if bool(-0.5) else 'no')\n", ''),
    ('bool_text', "value=input()\nprint('yes' if bool(value) else 'no')\nprint('yes' if bool('') else 'no')\n", 'hello\n'),
    ('bool_no_argument', "print('yes' if bool() else 'no')\n", ''),
    ('bool_operand_once', MARK + "print('yes' if bool(mark(2)) else 'no')\n", ''),
    ('bool_array_parameter', 'def check(values):\n    return 1 if bool(values) else 0\nvalues=[1,2]\nprint(check(values))\n', ''),
    ('negative_integer_power', 'print(2**-1,2**-2,(-2)**-3)\n', ''),
    ('negative_power_variable_base', 'value=4\nprint(value**-1)\n', ''),
    ('negative_power_assignment', 'value=2**-1\nprint(value)\n', ''),
    ('chained_scalar_assignment', 'first=second=third=7\nprint(first,second,third)\n', ''),
    ('chained_assignment_call_once', MARK + 'first=second=mark(7)\nprint(first,second)\n', ''),
    ('chained_assignment_input_once', "first=second=input('value: ')\nprint(first,second)\n", 'hello\n'),
    ('chained_assignment_in_loop', 'for i in range(3):\n    first=second=i+2\n    print(first,second)\n', ''),
]


class ScalarRoundTripTests(unittest.TestCase):
    pass


class ScalarExecutionTests(unittest.TestCase):
    pass


class RemainderFailureTests(unittest.TestCase):
    pass


def zero_test(language):
    def test(self):
        source = "value=int(input())\nprint(7%value)\nprint('after')\n"
        generated = MATRIX.APP.generate_source(language, MATRIX.APP.parse_python(source))
        chart = MATRIX.APP.parse_code(language, generated)
        chunks = []
        with self.assertRaises(MATRIX.APP.FlowError) as failure:
            MATRIX.APP.Interpreter(chart, lambda prompt: '0', lambda text, newline: chunks.append(str(text))).run()
        self.assertNotIn('after', ''.join(chunks))
        if language == 'Python':
            self.assertIn('ZeroDivisionError', str(failure.exception))
        else:
            self.assertIn('Division by zero in remainder', str(failure.exception))
    return test


for _name, _source, _supplied in CASES:
    for _language in MATRIX.APP.LANGUAGES:
        _safe = _language.replace('+', 'plus').replace('#', 'sharp')
        setattr(ScalarRoundTripTests, 'test_' + _name + '_' + _safe,
                MATRIX.matrix_test(_language, _source, _supplied))
    for _language in ('C', 'C++', 'JavaScript'):
        _safe = _language.replace('+', 'plus')
        setattr(ScalarExecutionTests, 'test_' + _name + '_' + _safe,
                MATRIX.executable_test(_language, _source, _supplied))

for _language in MATRIX.APP.LANGUAGES:
    _safe = _language.replace('+', 'plus').replace('#', 'sharp')
    setattr(RemainderFailureTests, 'test_zero_' + _safe, zero_test(_language))


if __name__ == '__main__':
    unittest.main(verbosity=2)
