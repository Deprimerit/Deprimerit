# -*- coding: utf-8 -*-
"""Default execution must finish valid long programs (Python 3.3+).

These checks deliberately use the production Interpreter constructor without a
custom step budget. An explicitly requested budget still interrupts runaway
loops and generator evaluation. CPython is used only for trusted test fixtures.
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

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.environ.get('FLOWCHART_MODULE', os.path.join(ROOT, 'Flowchart_Studio.py'))
APP = types.ModuleType('flowchart_execution_limit_tests')
APP.__file__ = APP_PATH
with io.open(APP_PATH, 'r', encoding='utf-8') as stream:
    exec(compile(stream.read(), APP_PATH, 'exec'), APP.__dict__)
with io.open(os.path.join(ROOT, 'examples', 'alphabet_letters.py'), 'r', encoding='utf-8') as stream:
    ALPHABET = stream.read()

LONG_LOOP = 'n=0\nwhile n<20000:\n    n+=1\nprint(n)\n'
DEFAULT_LIMIT = object()


def reference(source, supplied=''):
    old_in, old_out = sys.stdin, sys.stdout
    result = io.StringIO()
    try:
        sys.stdin, sys.stdout = io.StringIO(supplied), result
        exec(compile(source, '<trusted execution fixture>', 'exec'), {'__name__':'__main__'})
        return result.getvalue()
    finally:
        sys.stdin, sys.stdout = old_in, old_out


def document(source, portable=False):
    chart = APP.parse_python(source)
    if portable:
        chart = APP.parse_code('C', APP.generate_source('C', chart))
        if chart.get('python'):
            raise AssertionError('Portable execution test accidentally retained native Python mode')
    return chart


def interpreter(chart, supplied='', limit=DEFAULT_LIMIT):
    supplied_input, output = io.StringIO(supplied), []
    def read_input(prompt):
        value = supplied_input.readline()
        if value == '':
            raise AssertionError('Interpreter requested input absent from the reference fixture')
        return value.rstrip('\r\n')
    def write(value, newline):
        output.append(str(value) + ('\n' if newline else ''))
    if limit is DEFAULT_LIMIT:
        runner = APP.Interpreter(chart, read_input, write)
    else:
        runner = APP.Interpreter(chart, read_input, write, limit=limit)
    return runner, output


class DefaultExecutionTests(unittest.TestCase):
    def check_program(self, source, supplied='', portable=False, limit=DEFAULT_LIMIT):
        runner, output = interpreter(document(source, portable), supplied, limit)
        runner.run()
        self.assertEqual(''.join(output), reference(source, supplied))
        self.assertGreater(runner.count, 100000, 'Fixture did not exercise the previous default cutoff')

    def test_native_long_loop_default_constructor(self):
        self.check_program(LONG_LOOP)

    def test_portable_long_loop_default_constructor(self):
        self.check_program(LONG_LOOP, portable=True)

    def test_native_explicit_unlimited(self):
        self.check_program(LONG_LOOP, limit=None)

    def test_portable_explicit_unlimited(self):
        self.check_program(LONG_LOOP, portable=True, limit=None)

    def test_native_long_numeric_expression_default_constructor(self):
        self.check_program('print(sum(i for i in range(60000)))\n')

    def test_portable_long_numeric_expression_default_constructor(self):
        self.check_program('print(sum(i for i in range(60000)))\n', portable=True)

    def test_exact_alphabet_size_2_default_constructor(self):
        self.check_program(ALPHABET, 'y\nA\n2\nn\n')

    def test_exact_alphabet_size_4_default_constructor(self):
        self.check_program(ALPHABET, 'y\nB\n4\nn\n')

    def test_exact_alphabet_repeated_inputs_default_constructor(self):
        self.check_program(ALPHABET, 'y\na\n1\ny\nZ\n1\nn\n')

    def test_portable_exact_alphabet_default_constructor(self):
        self.check_program(ALPHABET, 'y\nA\n2\nn\n', portable=True)


class ExplicitExecutionLimitTests(unittest.TestCase):
    def check_interrupted(self, source, portable=False, limit=75):
        runner, output = interpreter(document(source, portable), limit=limit)
        with self.assertRaises(APP.FlowError) as failure:
            runner.run()
        self.assertEqual(runner.count, limit + 1)
        self.assertNotIn('after', ''.join(output))
        self.assertIn('limit', str(failure.exception).lower())
        self.assertIn(str(limit), str(failure.exception), 'Error should identify the explicitly configured step budget')

    def test_native_infinite_loop_explicit_limit(self):
        self.check_interrupted("while True:\n    pass\nprint('after')\n")

    def test_portable_infinite_loop_explicit_limit(self):
        self.check_interrupted("while True:\n    pass\nprint('after')\n", portable=True)

    def test_native_comprehension_explicit_limit(self):
        self.check_interrupted("print(sum(i for i in range(1000000)))\nprint('after')\n", limit=200)

    def test_portable_comprehension_explicit_limit(self):
        self.check_interrupted("print(sum(i for i in range(1000000)))\nprint('after')\n", portable=True, limit=200)

    def test_native_valid_program_explicit_budget(self):
        self.check_interrupted(LONG_LOOP, limit=200)

    def test_portable_valid_program_explicit_budget(self):
        self.check_interrupted(LONG_LOOP, portable=True, limit=200)


class BudgetValidationTests(unittest.TestCase):
    def check_invalid(self, portable):
        chart = document("print('after')\n", portable)
        for value in (-1, True, 2.5, '10', {}):
            with self.assertRaises(APP.FlowError) as failure:
                interpreter(chart, limit=value)
            self.assertIn('nonnegative integer', str(failure.exception))

    def test_native_invalid_budget(self):
        self.check_invalid(False)

    def test_portable_invalid_budget(self):
        self.check_invalid(True)

    def check_zero(self, portable):
        runner, output = interpreter(document("print('after')\n", portable), limit=0)
        with self.assertRaises(APP.FlowError) as failure:
            runner.run()
        self.assertIn('0 operations', str(failure.exception))
        self.assertEqual(''.join(output), '')

    def test_native_zero_budget(self):
        self.check_zero(False)

    def test_portable_zero_budget(self):
        self.check_zero(True)


class CheckpointCancellationTests(unittest.TestCase):
    def check_cancellation(self, portable):
        chart = document("print(sum(i for i in range(1000000)))\nprint('after')\n", portable)
        calls, output = [], []
        def cancel():
            calls.append(True)
            raise APP.FlowError('Paused by checkpoint')
        runner = APP.Interpreter(chart, output_callback=lambda value, nl: output.append(str(value)),
                                 checkpoint=cancel)
        with self.assertRaises(APP.FlowError) as failure:
            runner.run()
        self.assertIn('Paused by checkpoint', str(failure.exception))
        self.assertEqual(len(calls), 1)
        self.assertLess(runner.count, 10000, 'Cancellation should interrupt work inside the large expression')
        self.assertNotIn('after', ''.join(output))

    def test_native_checkpoint_interrupts_expression(self):
        self.check_cancellation(False)

    def test_portable_checkpoint_interrupts_expression(self):
        self.check_cancellation(True)


class CommandLineExecutionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix='flowchart-execution-cli-')

    def tearDown(self):
        shutil.rmtree(self.directory)

    def execute(self, source, supplied='', portable=False, budget=DEFAULT_LIMIT):
        path = os.path.join(self.directory, 'program.json')
        APP.save_document(document(source, portable), path)
        args = [sys.executable, APP_PATH, '--run', path]
        if budget is not DEFAULT_LIMIT:
            args.extend(['--max-operations', str(budget)])
        child = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, universal_newlines=True)
        try:
            output, error = child.communicate(supplied, timeout=45)
        except subprocess.TimeoutExpired:
            child.kill()
            child.communicate()
            self.fail('CLI execution exceeded the fixture timeout')
        return child.returncode, output, error

    def test_native_cli_default_unlimited(self):
        code, output, error = self.execute(LONG_LOOP)
        self.assertEqual(code, 0, error)
        self.assertEqual(output, reference(LONG_LOOP))

    def test_portable_cli_default_unlimited(self):
        code, output, error = self.execute(LONG_LOOP, portable=True)
        self.assertEqual(code, 0, error)
        self.assertEqual(output, reference(LONG_LOOP))

    def test_exact_alphabet_cli_default_unlimited(self):
        supplied = 'y\nA\n2\nn\n'
        code, output, error = self.execute(ALPHABET, supplied)
        self.assertEqual(code, 0, error)
        self.assertEqual(output, reference(ALPHABET, supplied))

    def check_cli_budget(self, portable):
        code, output, error = self.execute("while True:\n    pass\nprint('after')\n",
                                           portable=portable, budget=75)
        self.assertNotEqual(code, 0)
        self.assertIn('75 operations', error)
        self.assertNotIn('after', output)

    def test_native_cli_explicit_budget(self):
        self.check_cli_budget(False)

    def test_portable_cli_explicit_budget(self):
        self.check_cli_budget(True)

    def test_cli_negative_budget(self):
        code, output, error = self.execute("print('after')\n", budget=-1)
        self.assertNotEqual(code, 0)
        self.assertIn('nonnegative', error)
        self.assertNotIn('after', output)


if __name__ == '__main__':
    unittest.main(verbosity=2)
