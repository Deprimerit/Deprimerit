# -*- coding: utf-8 -*-
"""Common portable dictionary operations; Python 3.2-compatible test harness."""
from __future__ import print_function
import io
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_PATH = os.path.join(ROOT, 'Flowchart_Studio.py')
APP = types.ModuleType('collection_features_under_test')
APP.__file__ = APP_PATH
with io.open(APP_PATH, encoding='utf-8') as stream:
    exec(compile(stream.read(), APP_PATH, 'exec'), APP.__dict__)

MARK = "def mark(n):\n    print(n)\n    return n\n"
CASES = [
    ('get_present', "d={'a':10,'b':20}\nkey=input()\nprint(d.get(key,99))\n", 'b\n'),
    ('get_absent', "d={'a':10,'b':20}\nkey=input()\nprint(d.get(key,99))\n", 'z\n'),
    ('get_eager_default', MARK + "d={1:10}\nprint(d.get(mark(1),mark(99)))\n", ''),
    ('literal_get_order', MARK + "print({1:mark(10),2:mark(20)}.get(mark(2),mark(99)))\n", ''),
    ('get_strings', "d={'a':'yes'}\nkey=input()\nprint(d.get(key,'missing'))\n", 'z\n'),
    ('get_known_optional', "print({'a':10}.get('a'))\n", ''),
    ('get_empty', "d={}\nkey=input()\nprint(d.get(key,'empty'))\n", 'a\n'),
    ('get_runtime_loop', "for n in range(3):\n    d={'a':n,'b':n+1}\n    key='a'\n    print(d.get(key,-1))\n", ''),
    ('get_lazy_branch', "flag=0\nprint({'a':int(input())}.get('a',int(input())) if flag else 8)\n", ''),
    ('get_while', "d={'run':1,'stop':0}\nwhile d.get(input(),0):\n    print('body')\n", 'run\nstop\n'),
    ('membership_present_absent', "d={'a':10,'b':20}\nkey=input()\nprint('hit' if key in d else 'miss')\nprint('absent' if 'z' not in d else 'bad')\n", 'b\n'),
    ('literal_membership_order', MARK + "print('hit' if mark(1) in {1:mark(10),2:mark(20)} else 'miss')\n", ''),
    ('membership_lazy', "flag=0\nif flag and int(input()) in {'a':int(input())}:print('bad')\nprint('done')\n", ''),
    ('membership_empty', MARK + "print('empty' if mark(1) not in {} else 'bad')\n", ''),
    ('literal_keys', "for key in {'a':10,'b':20}.keys():print(key)\n", ''),
    ('literal_values', "for value in {'a':10,'b':20}.values():print(value)\n", ''),
    ('literal_items', "for key,value in {'a':10,'b':20}.items():print(key,value)\n", ''),
    ('literal_items_runtime', "for n in range(3):\n    for key,value in {'a':n}.items():print(key,value)\n", ''),
    ('negative_list_index', "values=[10,20,30]\nprint(values[-1],values[-3],values[0])\n", ''),
    ('negative_tuple_index', "values=('red','blue','green')\nprint(values[-1],values[-3])\n", ''),
    ('negative_string_index', "text='abc'\nprint(text[-1],text[-3],text[0])\n", ''),
    ('literal_negative_index', "print([10,20,30][-1],('red','blue')[-2],'abc'[-1])\n", ''),
    ('runtime_literal_index', "for n in range(3):\n    print([n,n+1][-1])\n", ''),
    ('indexed_call_order', "def text():\n    print('base')\n    return 'abc'\ndef index():\n    print('index')\n    return -1\nprint(text()[index()])\n", ''),
    ('literal_index_order', MARK + "print([mark(10),mark(20)][mark(-1)])\n", ''),
    ('negative_index_input', "values=[10,20,30]\nprint(values[int(input())])\n", '-2\n'),
    ('negative_store', "values=[1,2]\nvalues[-1]=9\nvalues[-2]+=5\nfor value in values:print(value)\n", ''),
    ('lazy_index', "flag=0\nprint('abc'[int(input())] if flag else 'skipped')\n", ''),
    ('cross_type_comparison_effects', "def number():\n    print('called')\n    return 1\nprint('equal' if number() == 'a' else 'different')\n", ''),
    ('container_bool', "values=[0]\nempty=[]\nd={'a':0}\nprint('yes' if bool(values) else 'no')\nprint('yes' if bool(empty) else 'no')\nprint('yes' if bool(d) else 'no')\nprint('yes' if bool({}) else 'no')\n", ''),
    ('literal_bool_effects', MARK + "print('yes' if bool([mark(1)]) else 'no')\nprint('yes' if bool({1:mark(2)}) else 'no')\n", ''),
]


def reference(source, supplied):
    previous = sys.stdin, sys.stdout
    output = io.StringIO()
    try:
        sys.stdin, sys.stdout = io.StringIO(supplied), output
        exec(compile(source, '<trusted collection fixture>', 'exec'), {'__name__': '__main__'})
        return output.getvalue()
    finally:
        sys.stdin, sys.stdout = previous


def comparable(name, output):
    if sys.version_info < (3, 7) and name in ('literal_keys', 'literal_values', 'literal_items'):
        return sorted(output.splitlines())
    return output


def find_command(name):
    for directory in os.environ.get('PATH', '').split(os.pathsep):
        path = os.path.join(directory, name)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def process(args, supplied='', cwd=None):
    child = subprocess.Popen(args, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, universal_newlines=True)
    expired = []
    def timeout():
        expired.append(True)
        child.kill()
    watchdog = threading.Timer(30, timeout)
    watchdog.start()
    try:
        output, error = child.communicate(supplied)
    finally:
        watchdog.cancel()
    if expired:
        raise AssertionError('Compiler/generated program timed out')
    if child.returncode:
        raise AssertionError('Compiler/generated program failed: ' + error)
    return output


class CollectionRoundTripTests(unittest.TestCase):
    pass


class CollectionExecutionTests(unittest.TestCase):
    pass


def roundtrip(name, source, supplied, language):
    def test(self):
        generated = APP.generate_source(language, APP.parse_python(source))
        doc = APP.parse_code(language, generated)
        inputs = iter(supplied.splitlines())
        output = []
        APP.Interpreter(doc, lambda _: next(inputs),
                        lambda value, nl: output.append(str(value) + ('\n' if nl else '')), limit=30000).run()
        self.assertEqual(comparable(name, ''.join(output)), comparable(name, reference(source, supplied)))
    return test


def execution(name, source, supplied, language):
    def test(self):
        executable = find_command({'C':'gcc', 'C++':'g++', 'JavaScript':'node'}[language])
        if not executable:
            self.skipTest(language + ' compiler/runtime unavailable')
        directory = tempfile.mkdtemp(prefix='collection-features-')
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
            self.assertEqual(comparable(name, output), comparable(name, reference(source, supplied)))
        finally:
            shutil.rmtree(directory)
    return test


class CollectionLimitationTests(unittest.TestCase):
    def test_dynamic_optional_get_reports_none_limit(self):
        with self.assertRaises(APP.Unsupported) as failure:
            APP.generate_source('C', APP.parse_python("d={'a':10}\nkey=input()\nprint(d.get(key))\n"))
        self.assertIn('explicit scalar default', str(failure.exception))


class IndexBoundsTests(unittest.TestCase):
    pass


def invalid_index(language, source):
    def test(self):
        generated = APP.generate_source(language, APP.parse_python(source))
        chart = APP.parse_code(language, generated)
        output = []
        with self.assertRaises(APP.FlowError) as failure:
            APP.Interpreter(chart, output_callback=lambda value, nl: output.append(str(value))).run()
        self.assertIn('out of range', str(failure.exception))
        self.assertNotIn('after', ''.join(output))
    return test


def invalid_index_execution(language, source):
    def test(self):
        executable = find_command({'C':'gcc', 'C++':'g++', 'JavaScript':'node'}[language])
        if not executable:
            self.skipTest(language + ' compiler/runtime unavailable')
        directory = tempfile.mkdtemp(prefix='collection-index-error-')
        try:
            path = os.path.join(directory, {'C':'main.c', 'C++':'main.cpp', 'JavaScript':'main.js'}[language])
            with io.open(path, 'w', encoding='utf-8') as stream:
                stream.write(APP.generate_source(language, APP.parse_python(source)))
            if language == 'JavaScript':
                args = [executable, path]
            else:
                binary = os.path.join(directory, 'program')
                standard = '-std=c99' if language == 'C' else '-std=c++11'
                process([executable, standard, path, '-lm', '-o', binary], cwd=directory)
                args = [binary]
            child = subprocess.Popen(args, cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     universal_newlines=True)
            watchdog = threading.Timer(30, child.kill)
            watchdog.start()
            try:
                output, error = child.communicate()
            finally:
                watchdog.cancel()
            self.assertNotEqual(child.returncode, 0)
            self.assertNotIn('after', output)
            self.assertIn('Sequence index out of range', error)
        finally:
            shutil.rmtree(directory)
    return test


for _name, _source, _supplied in CASES:
    for _language in APP.LANGUAGES:
        _safe = _language.replace('+', 'plus').replace('#', 'sharp')
        setattr(CollectionRoundTripTests, 'test_' + _name + '_' + _safe,
                roundtrip(_name, _source, _supplied, _language))
    for _language in ('C', 'C++', 'JavaScript'):
        _safe = _language.replace('+', 'plus')
        setattr(CollectionExecutionTests, 'test_' + _name + '_' + _safe,
                execution(_name, _source, _supplied, _language))

for _name, _source in [
        ('past_list_end', "values=[1,2]\nprint(values[2])\nprint('after')\n"),
        ('before_list_start', "values=[1,2]\nprint(values[-3])\nprint('after')\n"),
        ('past_string_end', "print('ab'[2])\nprint('after')\n"),
        ('before_string_start', "print('ab'[-3])\nprint('after')\n"),
        ('empty_sequence', "print([][-1])\nprint('after')\n")]:
    for _language in APP.LANGUAGES:
        _safe = _language.replace('+', 'plus').replace('#', 'sharp')
        setattr(IndexBoundsTests, 'test_' + _name + '_' + _safe, invalid_index(_language, _source))
    for _language in ('C', 'C++', 'JavaScript'):
        _safe = _language.replace('+', 'plus')
        setattr(IndexBoundsTests, 'test_execution_' + _name + '_' + _safe,
                invalid_index_execution(_language, _source))


if __name__ == '__main__':
    unittest.main(verbosity=2)
