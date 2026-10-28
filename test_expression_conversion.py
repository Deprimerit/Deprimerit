# -*- coding: utf-8 -*-
"""Regression tests for expression dictionaries and the exact alphabet program.

The test harness supports Python 3.3+. Trusted, bounded fixtures use CPython as
the reference; the production converter never evaluates user source. Every
target is generated and parsed back. C/C++/JavaScript additionally run the
generated source through real installed compilers/runtimes.
"""
from __future__ import print_function
import io
import os
import shutil
import string
import subprocess
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.environ.get('FLOWCHART_MODULE', os.path.join(ROOT, 'Flowchart_Studio.py'))
APP = types.ModuleType('flowchart_expression_tests')
APP.__file__ = APP_PATH
with io.open(APP_PATH, 'r', encoding='utf-8') as stream:
    exec(compile(stream.read(), APP_PATH, 'exec'), APP.__dict__)
with io.open(os.path.join(ROOT, 'examples', 'alphabet_letters.py'), 'r', encoding='utf-8') as stream:
    ALPHABET = stream.read()

MARK = "def mark(n):\n    print(n)\n    return n\n"
MISSING_KEY = "key=input()\nprint({'a':10,'b':20}[key])\nprint('after')\n"
CASES = [
    ('inline_dynamic', "key=input()\nprint({'red':10,'blue':20}[key])\n", 'blue\n'),
    ('guard_valid_key', MISSING_KEY, 'b\n'),
    ('inline_constant', "print({'red':10,'blue':20}['blue'])\n", ''),
    ('named_dynamic', "d={'red':10,'blue':20}\nkey=input()\nprint(d[key])\n", 'red\n'),
    ('inline_runtime_loop', "for n in range(3):\n    print({'red':n,'blue':n*2}['blue'])\n", ''),
    ('named_runtime_loop', "for n in range(3):\n    d={'red':n,'blue':n*2}\n    key='red'\n    print(d[key])\n", ''),
    ('eager_entries', MARK + "key='b'\nprint({'a':mark(1),'b':mark(2)}[key])\n", ''),
    ('key_after_entries', MARK + "print({1:mark(10),2:mark(20)}[mark(2)])\n", ''),
    ('duplicate_entries', MARK + "key='a'\nprint({'a':mark(1),'b':mark(2),'a':mark(3)}[key])\n", ''),
    ('duplicate_overwritten_type', MARK + "print({'a':mark(1),'a':'x'}['a'])\n", ''),
    ('lookup_key_once', "def key():\n    print('key')\n    return 'b'\nprint({'a':1,'b':2}[key()])\n", ''),
    ('left_operand_before_dictionary', MARK + "print(mark(1)+{'a':mark(2)}['a'])\n", ''),
    ('call_argument_order', MARK + "print(mark(1),{'a':mark(2)}['a'],mark(3))\n", ''),
    ('named_alias_lookup', "d={'a':10,'b':20}\ne=d\nkey='b'\nprint(e[key])\n", ''),
    ('branch_local_dictionary', "flag=int(input())\nif flag:\n    d={'a':10}\n    print(d['a'])\nelse:\n    d={'a':20}\n    print(d['a'])\n", '0\n'),
    ('unchanged_branch_dictionary', "d={'a':10}\nif int(input()):\n    print(d['a'])\nelse:\n    print(d['a'])\nprint(d['a'])\n", '1\n'),
    ('conditional_lookup_false', "flag=0\nprint({'a':int(input())}['a'] if flag else 8)\n", ''),
    ('conditional_lookup_true', "flag=1\nprint({'a':int(input())}['a'] if flag else 8)\n", '7\n'),
    ('short_circuit_lookup', "flag=0\nif flag and {'a':int(input())}['a']:print('bad')\nprint('done')\n", ''),
    ('while_lookup', "while {'a':int(input())}['a']:\n    print('body')\n", '1\n0\n'),
    ('while_lookup_continue', "while {'a':int(input())}['a']:\n    print('body')\n    continue\n", '1\n1\n0\n'),
    ('boolean_values', "print(0 or 3, 2 or 7, 0 and 4, 2 and 7)\n", ''),
    ('string_boolean_values', "print('' or 'fallback','a' or 'b','' and 'x','a' and 'z')\n", ''),
    ('nested_lazy_calls', MARK + "print((0 and mark(1)) or (mark(2) if mark(3) else mark(4)))\nprint((mark(0) and mark(5)) or (mark(6) if mark(0) else mark(7)))\n", ''),
    ('integer_fallback', "b=4\nh=b//2 or 1\nprint(h,h*3)\n", ''),
    ('boolean_array', "flags=[True,False]\nprint('yes' if flags[0] else 'no')\nprint('yes' if flags[1] else 'no')\n", ''),
    ('alphabet_exit', ALPHABET, 'n\n'),
    ('alphabet_selected', ALPHABET, 'y\nA\n1\ny\nZ\n2\ny\nm\n1\nn\n'),
]
ALL_LETTERS_INPUT = ''.join('y\n{0}\n{1}\n'.format(letter, size)
                            for size in (1, 2) for letter in string.ascii_uppercase) + 'n\n'
REFERENCE_CACHE = {}


def reference(source, supplied):
    cache_key = source, supplied
    if cache_key in REFERENCE_CACHE:
        return REFERENCE_CACHE[cache_key]
    old_in, old_out = sys.stdin, sys.stdout
    output = io.StringIO()
    try:
        sys.stdin, sys.stdout = io.StringIO(supplied), output
        exec(compile(source, '<trusted expression fixture>', 'exec'), {'__name__': '__main__'})
        result = output.getvalue()
        REFERENCE_CACHE[cache_key] = result
        return result
    finally:
        sys.stdin, sys.stdout = old_in, old_out


def interpret(doc, supplied):
    stdin, stdout = io.StringIO(supplied), io.StringIO()
    def read_input(prompt):
        value = stdin.readline()
        if value == '':
            raise AssertionError('Generated chart requested input that the original program never requested.')
        return value.rstrip('\r\n')
    APP.Interpreter(doc, read_input,
                    lambda value, newline: stdout.write(str(value) + ('\n' if newline else '')),
                    limit=2000000).run()
    return stdout.getvalue()


def process(args, supplied='', cwd=None):
    child = subprocess.Popen(args, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True)
    try:
        output, error = child.communicate(supplied, timeout=45)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()
        raise AssertionError('Generated source/compiler timed out: ' + repr(args))
    if child.returncode:
        raise AssertionError('Generated source/compiler failed ({0}):\n{1}'.format(child.returncode, error))
    return output


class ExpressionRoundTripTests(unittest.TestCase):
    pass


class ExpressionExecutionTests(unittest.TestCase):
    pass


class MissingKeyTests(unittest.TestCase):
    pass


class ConditionalBindingTests(unittest.TestCase):
    pass


def round_trip_test(language, source, supplied):
    def test(self):
        generated = APP.generate_source(language, APP.parse_python(source))
        self.assertTrue(generated.strip())
        self.assertNotIn('SOURCE NOT GENERATED', generated)
        doc = APP.parse_code(language, generated)
        self.assertEqual(interpret(doc, supplied), reference(source, supplied), language + ' round trip changed output')
    return test


def execution_test(language, source, supplied):
    def test(self):
        command = {'C':'gcc', 'C++':'g++', 'JavaScript':'node'}[language]
        executable = shutil.which(command)
        if not executable:
            self.skipTest(language + ' compiler/runtime unavailable')
        directory = tempfile.mkdtemp(prefix='flowchart-expression-')
        try:
            path = os.path.join(directory, {'C':'main.c', 'C++':'main.cpp', 'JavaScript':'main.js'}[language])
            with io.open(path, 'w', encoding='utf-8') as stream:
                stream.write(APP.generate_source(language, APP.parse_python(source)))
            if language == 'JavaScript':
                output = process([executable, path], supplied, directory)
            else:
                binary = os.path.join(directory, 'program')
                standard = '-std=c99' if language == 'C' else '-std=c++11'
                process([executable, standard, path, '-lm', '-o', binary], cwd=directory)
                output = process([binary], supplied, directory)
            self.assertEqual(output, reference(source, supplied), language + ' execution changed output')
        finally:
            shutil.rmtree(directory)
    return test


def missing_key_test(language):
    def test(self):
        generated = APP.generate_source(language, APP.parse_python(MISSING_KEY))
        chart = APP.parse_code(language, generated)
        chunks = []
        with self.assertRaises(APP.FlowError) as failure:
            APP.Interpreter(chart, lambda prompt: 'z',
                            lambda value, newline: chunks.append(str(value) + ('\n' if newline else ''))).run()
        self.assertNotIn('after', ''.join(chunks))
        diagnostic = 'KeyError' if language == 'Python' else 'Dictionary key not found'
        self.assertIn(diagnostic, str(failure.exception))
    return test


def missing_key_execution_test(language):
    def test(self):
        command = {'C':'gcc', 'C++':'g++', 'JavaScript':'node'}[language]
        executable = shutil.which(command)
        if not executable:
            self.skipTest(language + ' compiler/runtime unavailable')
        directory = tempfile.mkdtemp(prefix='flowchart-expression-error-')
        try:
            path = os.path.join(directory, {'C':'main.c', 'C++':'main.cpp', 'JavaScript':'main.js'}[language])
            with io.open(path, 'w', encoding='utf-8') as stream:
                stream.write(APP.generate_source(language, APP.parse_python(MISSING_KEY)))
            if language == 'JavaScript':
                args = [executable, path]
            else:
                binary = os.path.join(directory, 'program')
                standard = '-std=c99' if language == 'C' else '-std=c++11'
                process([executable, standard, path, '-lm', '-o', binary], cwd=directory)
                args = [binary]
            child = subprocess.Popen(args, cwd=directory, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, universal_newlines=True)
            try:
                output, error = child.communicate('z\n', timeout=45)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate()
                self.fail('Missing dictionary key did not terminate generated program')
            self.assertNotEqual(child.returncode, 0)
            self.assertNotIn('after', output)
            self.assertIn('Dictionary key not found', error)
        finally:
            shutil.rmtree(directory)
    return test


def conditional_binding_test(language, source):
    def test(self):
        with self.assertRaises(APP.Unsupported) as failure:
            APP.generate_source(language, APP.parse_python(source))
        self.assertIn('different bindings', str(failure.exception))
    return test


for _name, _source, _supplied in CASES:
    for _language in APP.LANGUAGES:
        _safe = _language.replace('+', 'plus').replace('#', 'sharp')
        setattr(ExpressionRoundTripTests, 'test_' + _name + '_' + _safe,
                round_trip_test(_language, _source, _supplied))
    for _language in ('C', 'C++', 'JavaScript'):
        _safe = _language.replace('+', 'plus')
        setattr(ExpressionExecutionTests, 'test_' + _name + '_' + _safe,
                execution_test(_language, _source, _supplied))

for _language in ('C', 'C++', 'JavaScript'):
    _safe = _language.replace('+', 'plus')
    setattr(ExpressionExecutionTests, 'test_alphabet_all_letters_sizes_1_2_' + _safe,
            execution_test(_language, ALPHABET, ALL_LETTERS_INPUT))
    setattr(ExpressionExecutionTests, 'test_alphabet_thick_letters_size_4_' + _safe,
            execution_test(_language, ALPHABET, 'y\nA\n4\ny\nB\n4\ny\nS\n4\nn\n'))
    setattr(MissingKeyTests, 'test_execution_' + _safe, missing_key_execution_test(_language))

for _language in APP.LANGUAGES:
    _safe = _language.replace('+', 'plus').replace('#', 'sharp')
    setattr(MissingKeyTests, 'test_round_trip_' + _safe, missing_key_test(_language))
    if _language != 'Python':
        setattr(ConditionalBindingTests, 'test_branch_' + _safe, conditional_binding_test(_language,
                "flag=int(input())\nif flag:\n    d={'a':1}\nelse:\n    d={'a':2}\nprint(d['a'])\n"))
        setattr(ConditionalBindingTests, 'test_loop_' + _safe, conditional_binding_test(_language,
                "d={'a':1}\nfor i in range(2):\n    d={'a':i}\nprint(d['a'])\n"))


if __name__ == '__main__':
    unittest.main(verbosity=2)
