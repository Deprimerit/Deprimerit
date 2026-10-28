#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Flowchart Studio - single-file educational flowchart editor with drag-and-drop.
Works on Python 3.3 and newer; standard library only. Run this file to open the
Tk desktop UI (Tk must be part of your Python installation).

The source panel is two-way: edit Python or Pseudocode and the flowchart
changes; edit the flowchart and the code changes. Plain top-level scripts work
(no functions needed). 14 output languages are generated for the portable subset.

CLI: --self-test | --run FILE | --generate FILE --language Python [-o FILE]
     --from-code FILE.py|FILE.txt [-o chart.json]   (code -> flowchart)
Not an official Flowgorithm product or a complete feature-for-feature clone.
"""
from __future__ import print_function
import ast
import argparse
import copy
import io
import json
import math
import operator
import os
import random
import re
import sys
import tokenize
import xml.etree.ElementTree as ET

# Avoid relying on AST compatibility aliases removed by newer CPython releases.
_AST_CONSTANT = getattr(ast, 'Constant', ())
_AST_LEGACY = tuple(getattr(ast, k) for k in ('Num', 'Str', 'NameConstant') if hasattr(ast, k)) if sys.version_info < (3, 8) else ()
_AST_INDEX = getattr(ast, 'Index', ()) if sys.version_info < (3, 9) else ()

VERSION = '3.1.4'
LANGUAGES = ['Python', 'Pseudocode', 'C', 'C++', 'C#', 'Java', 'JavaScript', 'TypeScript',
             'Go', 'Kotlin', 'Swift', 'PHP', 'R', 'MATLAB']
# Every language can be generated AND parsed back, so code converts between any two.
TWO_WAY = tuple(LANGUAGES)
KINDS = ['Declare', 'Assign', 'Input', 'Output', 'If', 'While', 'Do', 'For',
         'Call', 'Return', 'Comment', 'Break', 'Continue']
DEFAULTS = {
    'Declare': {'name': 'x', 'type': 'Integer', 'array': False, 'size': '10'},
    'Assign': {'variable': 'x', 'expression': '0'},
    'Input': {'variable': 'x'},
    'Output': {'expression': '"Hello, world!"', 'newline': True},
    'If': {'expression': 'x > 0'}, 'While': {'expression': 'x < 10'},
    'Do': {'expression': 'x < 10'},
    'For': {'variable': 'i', 'start': '1', 'end': '10', 'step': '1', 'direction': 'inc'},
    'Call': {'expression': 'MyFunction()'}, 'Return': {'expression': '0'},
    'Comment': {'text': 'Comment'}, 'Break': {}, 'Continue': {}
}
BRANCHES = {'If': ['true', 'false'], 'While': ['body'], 'Do': ['body'], 'For': ['body']}

# Shared explanations keep the insertion picker, palette and edit dialogs in sync.
SYMBOL_HELP = {
    'Declare': {
        'definition': 'Creates named variables or arrays and sets their type before they are used.',
        'example': 'Declare total as Integer; its initial value is 0.',
        'python_example': 'total = 0',
        'note': 'Typed charts need declarations before Assign or Input. In Python, assignment creates the variable.'},
    'Assign': {
        'definition': 'Evaluates an expression and stores its result in a variable or array element, replacing the old value.',
        'example': 'total = total + 1',
        'note': 'The expression on the right is calculated before the target on the left is updated.'},
    'Input': {
        'definition': 'Pauses the program, asks the user for a value and stores it in the chosen variable.',
        'example': 'Input n, where n was declared as Integer.',
        'python_example': 'n = int(input("How many? "))',
        'note': 'Typed charts convert to the declared type. Python input() returns text; use int() or float() for numbers.'},
    'Output': {
        'definition': 'Evaluates an expression and writes the result to the program console.',
        'example': 'Output "Total: " & ToString(total)',
        'python_example': 'print("Total:", total)',
        'note': 'Newline starts a new output line. In Python, print(..., end="") keeps the next output on the same line.'},
    'If': {
        'definition': 'Tests a condition and follows exactly one branch: True when it passes, otherwise False.',
        'example': 'x > 0: put the positive-number steps in True and the other steps in False.',
        'note': 'After the selected branch finishes, both paths join and the program continues below the If.'},
    'While': {
        'definition': 'Checks its condition before each repetition and runs the body only while the condition is True.',
        'example': 'i < 3: output i, then assign i = i + 1 inside the body.',
        'note': 'The body may run zero times. Update the condition or use Break so the loop can finish.'},
    'Do': {
        'definition': 'Runs its body first, then repeats while its condition is True.',
        'example': 'Run the body, then repeat while x < 3.',
        'python_example': 'while True:\n    body()\n    if not condition: break',
        'note': 'The body always runs at least once. Unlike While, the condition is checked after the body.'},
    'For': {
        'definition': 'Repeats its body for each loop value or item in an iterable.',
        'example': 'i from 1 to 3 with step 1 visits 1, 2 and 3.',
        'python_example': 'for item in values: print(item)  |  range(3) visits 0, 1 and 2.',
        'note': 'Typed charts include the end value and use a positive step plus direction. Python range() excludes its stop; a dictionary loop visits keys.'},
    'Call': {
        'definition': 'Runs a defined function or procedure with the supplied arguments, then continues with the next shape.',
        'example': 'display(total)',
        'note': 'Define the function in the Functions menu or source. Use Assign when you need to keep its returned value.'},
    'Return': {
        'definition': 'Ends the current function immediately and sends its result back to the caller.',
        'example': 'Return total',
        'python_example': 'return total',
        'note': 'Use inside a function. An empty return ends the function without a result.'},
    'Comment': {
        'definition': 'Adds a plain-language note explaining the nearby steps.',
        'example': 'Calculate the running total.',
        'note': 'A plain comment changes no variable values and does not choose a path or repeat any steps.'},
    'Break': {
        'definition': 'Exits the innermost enclosing loop immediately and continues after that loop.',
        'example': 'Inside If x == 5, add Break to stop the loop.',
        'note': 'Break can be used only inside For, While or Do. It does not exit an outer loop automatically.'},
    'Continue': {
        'definition': 'Skips the remaining steps in the current loop repetition and starts the next repetition or condition check.',
        'example': 'Inside If x < 0, add Continue to skip processing that value.',
        'note': 'Continue can be used only inside For, While or Do. It does not end the whole loop.'},
    'Terminal': {
        'definition': 'Marks where the current function starts or finishes.',
        'example': 'Main starts the program; End finishes the current flowchart.',
        'note': 'Start and End are supplied automatically. Insert new symbols on a connector between them.'}
}


def symbol_help_text(kind, python_mode=False):
    info = SYMBOL_HELP.get(kind, {})
    example = info.get('python_example') if python_mode else None
    return ('{0}\n{1}\n\nExample: {2}\n\n{3}'.format(
        kind, info.get('definition', ''), example or info.get('example', ''), info.get('note', '')))

class FlowError(Exception):
    pass

class Unsupported(FlowError):
    pass

def node(kind, **kwargs):
    n = {'kind': kind}
    n.update(copy.deepcopy(DEFAULTS[kind]))
    n.update(kwargs)
    for b in BRANCHES.get(kind, []):
        n.setdefault(b, [])
    return n

def empty_document():
    return {'format': 'flowchart-studio-1', 'name': 'Untitled',
            'functions': [{'name': 'Main', 'type': 'None', 'variable': '',
                           'parameters': [], 'body': []}]}

def sample_document():
    d = empty_document()
    d['name'] = 'Sum from 1 to N'
    d['functions'][0]['body'] = [node('Declare', name='n, i, total'),
        node('Output', expression='"Enter a positive number:"'), node('Input', variable='n'),
        node('Assign', variable='total', expression='0'),
        node('For', end='n', body=[node('Assign', variable='total', expression='total + i')]),
        node('Output', expression='"Sum = " & ToString(total)')]
    return d

def walk(block):
    for n in block:
        yield n
        for b in BRANCHES.get(n['kind'], []):
            for child in walk(n[b]):
                yield child

def valid_name(name):
    return re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', name or '') is not None and not name.startswith('__')

def names(text):
    result = [v.strip() for v in text.split(',')]
    if not result or any(not valid_name(v) for v in result):
        raise FlowError('Names must be comma-separated identifiers (letters, digits, underscores).')
    return result

# Expressions are parsed into a restricted AST, never passed to eval or exec.
# Flowgorithm operators: = equality, <> inequality, ^ power, & string concatenation.
def normalize(text):
    pieces = re.split(r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')', text.strip())
    for i in range(0, len(pieces), 2):
        s = pieces[i]
        s = re.sub(r'\btrue\b', 'True', s, flags=re.I)
        s = re.sub(r'\bfalse\b', 'False', s, flags=re.I)
        s = re.sub(r'\b(and|or|not)\b', lambda m: m.group(0).lower(), s, flags=re.I)
        s = s.replace('&&', ' and ').replace('||', ' or ').replace('<>', '!=')
        s = re.sub(r'!(?!=)', ' not ', s)
        s = re.sub(r'(?<![<>=!])=(?!=)', '==', s)
        s = s.replace('^', '**')
        pieces[i] = s
    return ''.join(pieces).strip()

def parse_expr(text):
    if not text.strip():
        raise FlowError('Expression cannot be empty.')
    try:
        a = ast.parse(normalize(text), mode='eval').body
    except SyntaxError as e:
        raise FlowError('Invalid expression: {0}'.format(text))
    allowed = (ast.Expression, ast.Name, ast.Load, ast.BinOp,
               ast.UnaryOp, ast.BoolOp, ast.Compare, ast.Call, ast.Subscript,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
               ast.Mod, ast.Pow, ast.BitAnd, ast.USub, ast.UAdd, ast.Not,
               ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)
    extra = _AST_LEGACY + ((_AST_CONSTANT,) if _AST_CONSTANT else ()) + ((_AST_INDEX,) if _AST_INDEX else ())
    for x in ast.walk(a):
        if not isinstance(x, allowed + extra):
            raise FlowError('Unsupported expression construct: ' + type(x).__name__)
        if isinstance(x, ast.Name) and x.id.startswith('__'):
            raise FlowError('Private names are not allowed.')
        if isinstance(x, ast.Call):
            if not isinstance(x.func, ast.Name) or x.keywords or getattr(x, 'starargs', None) or getattr(x, 'kwargs', None):
                raise FlowError('Only named function calls with positional arguments are supported.')
    return a

def literal(a):
    if _AST_CONSTANT and isinstance(a, _AST_CONSTANT):
        if not isinstance(a.value, (str, int, float, bool)):
            raise FlowError('Only string, number and Boolean literals are supported.')
        return True, a.value
    if _AST_LEGACY and isinstance(a, _AST_LEGACY):
        if hasattr(a, 'n'):
            return True, a.n
        if hasattr(a, 's'):
            return True, a.s
        return True, a.value
    if isinstance(a, ast.Name) and a.id in ('True', 'False'):
        return True, a.id == 'True'
    return False, None

def index_ast(a):
    s = a.slice
    return s.value if _AST_INDEX and isinstance(s, _AST_INDEX) else s

def validate(doc):
    if isinstance(doc, dict) and doc.get("python"):
        return validate_python_document(doc)
    if not isinstance(doc, dict) or not isinstance(doc.get('functions'), list):
        raise FlowError('Invalid flowchart document.')
    if not doc['functions'] or doc['functions'][0]['name'] != 'Main':
        raise FlowError('The first function must be Main.')
    seen = set()
    for f in doc['functions']:
        if not valid_name(f['name']) or f['name'] in seen:
            raise FlowError('Invalid or duplicate function name: ' + f['name'])
        seen.add(f['name'])
        if f['type'] not in ('None', 'Integer', 'Real', 'String', 'Boolean'):
            raise FlowError('Unknown return type.')
        if f['name'] == 'Main' and (f['parameters'] or f['type'] != 'None'):
            raise FlowError('Main cannot have parameters or a return type.')
        parameter_names = set()
        for p in f['parameters']:
            if not valid_name(p['name']) or p['name'] in parameter_names:
                raise FlowError('Invalid or duplicate parameter name: ' + p['name'])
            if p['type'] not in ('Integer', 'Real', 'String', 'Boolean'):
                raise FlowError('Unknown parameter type.')
            parameter_names.add(p['name'])
        declared_names = set(parameter_names)
        for n in walk(f['body']):
            k = n['kind']
            if k not in KINDS:
                raise FlowError('Unsupported shape: ' + k)
            if k == 'Declare':
                for name in names(n['name']):
                    if name in declared_names:
                        raise FlowError('Duplicate variable declaration: ' + name)
                    declared_names.add(name)
                if n['type'] not in ('Integer', 'Real', 'String', 'Boolean'):
                    raise FlowError('Unknown variable type.')
                if n['array']:
                    parse_expr(n['size'])
            elif k in ('Assign', 'Input'):
                a = parse_expr(n['variable'])
                if not isinstance(a, (ast.Name, ast.Subscript)):
                    raise FlowError('Assignment/input target must be a variable or array element.')
                if k == 'Assign':
                    parse_expr(n['expression'])
            elif k == 'For':
                names(n['variable'])
                if len(names(n['variable'])) != 1:
                    raise FlowError('For requires exactly one loop variable.')
                for key in ('start', 'end', 'step'):
                    parse_expr(n[key])
                ok, val = literal(parse_expr(n['step']))
                if ok and (not isinstance(val, (int, float)) or isinstance(val, bool) or val <= 0):
                    raise FlowError('For step must be positive.')
                if n['direction'] not in ('inc', 'dec'):
                    raise FlowError('For direction must be inc or dec.')
            elif k not in ('Comment', 'Break', 'Continue'):
                if n.get('expression', '').strip():
                    parse_expr(n['expression'])
                elif k != 'Return':
                    raise FlowError('Missing expression.')
        check_loops(f['body'])
    return doc

def check_loops(block, inloop=False):
    for n in block:
        if n['kind'] in ('Break', 'Continue') and not inloop:
            raise FlowError(n['kind'] + ' can only be used inside a loop.')
        for b in BRANCHES.get(n['kind'], []):
            check_loops(n[b], inloop or n['kind'] in ('While', 'Do', 'For'))


def load_document(path):
    if path.lower().endswith('.json'):
        with open(path, 'r', encoding='utf-8') as h:
            return validate(json.load(h))
    root = ET.parse(path).getroot()
    if root.tag != 'flowgorithm':
        raise FlowError('Not a Flowgorithm .fprg file.')
    def read_block(el):
        result = []
        for e in el:
            k = e.tag.capitalize()
            if k not in KINDS:
                raise FlowError('This file contains an unsupported shape: ' + e.tag)
            n = node(k)
            for key in DEFAULTS[k]:
                if key in e.attrib:
                    n[key] = e.get(key)
            if k == 'Declare':
                n['array'] = str(n['array']).lower() == 'true'
            if k == 'Output':
                n['newline'] = str(n['newline']).lower() == 'true'
            for b in BRANCHES.get(k, []):
                sub = e.find(b)
                n[b] = read_block(sub) if sub is not None else []
            result.append(n)
        return result
    d = empty_document()
    d['name'] = os.path.splitext(os.path.basename(path))[0]
    d['functions'] = []
    for e in root.findall('function'):
        f = {'name': e.get('name', 'Main'), 'type': e.get('type', 'None'),
             'variable': e.get('variable', ''), 'parameters': [], 'body': []}
        ps = e.find('parameters')
        if ps is not None:
            for p in ps:
                f['parameters'].append({'name': p.get('name'), 'type': p.get('type', 'Integer'),
                                        'array': p.get('array', 'False').lower() == 'true'})
        body = e.find('body')
        f['body'] = read_block(body) if body is not None else []
        d['functions'].append(f)
    return validate(d)

def save_document(doc, path):
    validate(doc)
    if path.lower().endswith('.json'):
        with open(path, 'w', encoding='utf-8') as h:
            json.dump(doc, h, indent=2, ensure_ascii=False)
        return
    if doc.get("python"):
        raise FlowError("Dynamic Python charts must be saved as JSON; .fprg cannot preserve Python values and iterators.")
    root = ET.Element('flowgorithm', {'fileversion': '2.18'})
    attrs = ET.SubElement(root, 'attributes')
    ET.SubElement(attrs, 'attribute', {'name': 'name', 'value': doc['name']})
    ET.SubElement(attrs, 'attribute', {'name': 'authors', 'value': 'Flowchart Studio'})
    def write_block(parent, block):
        for n in block:
            at = {}
            for key in DEFAULTS[n['kind']]:
                value = n[key]
                at[key] = str(value)
            e = ET.SubElement(parent, n['kind'].lower(), at)
            for b in BRANCHES.get(n['kind'], []):
                write_block(ET.SubElement(e, b), n[b])
    for f in doc['functions']:
        e = ET.SubElement(root, 'function', dict((k, f[k]) for k in ('name', 'type', 'variable')))
        ps = ET.SubElement(e, 'parameters')
        for p in f['parameters']:
            ET.SubElement(ps, 'parameter', dict((k, str(v)) for k, v in p.items()))
        write_block(ET.SubElement(e, 'body'), f['body'])
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)

# Safe interpreter with resumable execution and a bounded operation count.
# Python programs use a separate dynamic model. The portable four-type model
# remains available for hand-built charts and the other language front-ends.
# No source text is evaluated/compiled/executed by the chart interpreter.
_PY_METHODS = {
    'str': {'upper', 'lower', 'strip', 'lstrip', 'rstrip', 'split', 'rsplit', 'join',
            'replace', 'startswith', 'endswith', 'find', 'rfind', 'index', 'count',
            'capitalize', 'title', 'swapcase', 'casefold', 'isdigit', 'isalpha',
            'isalnum', 'isspace', 'zfill', 'center', 'ljust', 'rjust', 'splitlines'},
    'list': {'append', 'extend', 'insert', 'remove', 'pop', 'clear', 'copy',
             'count', 'index', 'reverse', 'sort'},
    'tuple': {'count', 'index'},
    'dict': {'keys', 'values', 'items', 'get', 'pop', 'popitem', 'update',
             'setdefault', 'clear', 'copy', 'fromkeys'},
    'set': {'add', 'update', 'remove', 'discard', 'pop', 'clear', 'copy',
            'union', 'intersection', 'difference', 'symmetric_difference',
            'issubset', 'issuperset', 'isdisjoint', 'intersection_update',
            'difference_update', 'symmetric_difference_update'},
}
_PY_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
              ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
              ast.Mod: operator.mod, ast.Pow: operator.pow, ast.BitAnd: operator.and_,
              ast.BitOr: operator.or_, ast.BitXor: operator.xor,
              ast.LShift: operator.lshift, ast.RShift: operator.rshift}
_PY_COMPARE = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
              ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
              ast.In: lambda a,b: a in b, ast.NotIn: lambda a,b: a not in b,
              ast.Is: operator.is_, ast.IsNot: operator.is_not}


_AST_UNPARSE = getattr(ast, 'unparse', None)


def ast_source(node):
    """Return equivalent source on Python 3.3+ without requiring ast.unparse."""
    if _AST_UNPARSE is not None:
        return _AST_UNPARSE(node)
    return _ast_source_compat(node)


def _ast_source_compat(node):
    """Print supported expression/target/import ASTs, including legacy nodes."""
    def is_node(value, name):
        cls = getattr(ast, name, None)
        return cls is not None and isinstance(value, cls)

    def number(value):
        if isinstance(value, float):
            if math.isinf(value):
                return '-1e309' if value < 0 else '1e309'
            if math.isnan(value):
                return '(1e309 - 1e309)'
        if isinstance(value, complex):
            if math.isinf(value.imag):
                imaginary = '-1e309j' if value.imag < 0 else '1e309j'
                return '(' + number(value.real) + ' + (' + imaginary + '))'
        return repr(value)

    fexpr_depth = [0]

    def constant(value):
        if isinstance(value, str) and fexpr_depth[0] and '\\' not in value:
            # Before Python 3.12 a backslash anywhere inside an f-string
            # expression is illegal, even when it belongs to a string literal.
            # Pick an unescaped literal rather than repr's escaped spelling.
            for quote in ("'", '"', "'''", '"""'):
                if quote not in value and (len(quote) == 3 or ('\n' not in value and '\r' not in value)):
                    return quote + value + quote
        if value is Ellipsis:
            return '...'
        if isinstance(value, (int, float, complex)) and not isinstance(value, bool):
            return number(value)
        return repr(value)

    def slice_source(value):
        if is_node(value, 'Index'):
            return emit(value.value)
        if is_node(value, 'ExtSlice'):
            return ', '.join(slice_source(d) for d in value.dims)
        if isinstance(value, ast.Slice):
            bits = [(emit(value.lower) if value.lower is not None else ''),
                    (emit(value.upper) if value.upper is not None else '')]
            if value.step is not None:
                bits.append(emit(value.step))
            return ':'.join(bits)
        if isinstance(value, ast.Tuple):
            parts = [slice_source(x) for x in value.elts]
            return ', '.join(parts) + (',' if len(parts) == 1 else '')
        return emit(value)

    def generators(items):
        text = ''
        for item in items:
            text += (' async for ' if getattr(item, 'is_async', 0) else ' for ')
            text += emit(item.target) + ' in ' + emit(item.iter)
            for condition in item.ifs:
                text += ' if ' + emit(condition)
        return text

    def formatted(value, quote):
        fexpr_depth[0] += 1
        try:
            text = emit(value.value)
        finally:
            fexpr_depth[0] -= 1
        if value.conversion != -1:
            text += '!' + chr(value.conversion)
        if value.format_spec is not None:
            text += ':' + fstring_body(value.format_spec, quote)
        return '{' + text + '}'

    def fstring_body(value, quote):
        pieces = []
        for part in value.values:
            if is_node(part, 'FormattedValue'):
                pieces.append(formatted(part, quote))
            else:
                literal_value = part.value if is_node(part, 'Constant') else part.s
                text = literal_value.replace('\\', '\\\\').replace(quote, '\\' + quote)
                text = text.replace('{', '{{').replace('}', '}}')
                text = text.replace('\r', '\\r').replace('\n', '\\n').replace('\t', '\\t')
                pieces.append(text)
        return ''.join(pieces)

    binary = {'Add': '+', 'Sub': '-', 'Mult': '*', 'Div': '/', 'FloorDiv': '//',
              'Mod': '%', 'Pow': '**', 'BitAnd': '&', 'BitOr': '|', 'BitXor': '^',
              'LShift': '<<', 'RShift': '>>', 'MatMult': '@'}
    unary = {'UAdd': '+', 'USub': '-', 'Not': 'not ', 'Invert': '~'}
    compare = {'Eq': '==', 'NotEq': '!=', 'Lt': '<', 'LtE': '<=', 'Gt': '>',
               'GtE': '>=', 'In': 'in', 'NotIn': 'not in', 'Is': 'is', 'IsNot': 'is not'}

    def emit(value):
        if value is None:
            return 'None'
        if isinstance(value, ast.Expression):
            return emit(value.body)
        if is_node(value, 'Constant'):
            return constant(value.value)
        if is_node(value, 'NameConstant'):
            return constant(value.value)
        if is_node(value, 'Num'):
            return number(value.n)
        if is_node(value, 'Str') or is_node(value, 'Bytes'):
            return constant(value.s)
        if is_node(value, 'Ellipsis'):
            return '...'
        if isinstance(value, ast.Name):
            return value.id
        if isinstance(value, ast.Attribute):
            return '(' + emit(value.value) + ').' + value.attr
        if isinstance(value, ast.Subscript):
            return '(' + emit(value.value) + ')[' + slice_source(value.slice) + ']'
        if isinstance(value, ast.Starred):
            return '*' + emit(value.value)
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            parts = [emit(x) for x in value.elts]
            if isinstance(value, ast.List):
                return '[' + ', '.join(parts) + ']'
            if isinstance(value, ast.Tuple):
                return '(' + ', '.join(parts) + (',' if len(parts) == 1 else '') + ')'
            return '{' + ', '.join(parts) + '}' if parts else 'set()'
        if isinstance(value, ast.Dict):
            parts = []
            for key, item in zip(value.keys, value.values):
                parts.append(('**' + emit(item)) if key is None else emit(key) + ': ' + emit(item))
            return '{' + ', '.join(parts) + '}'
        if isinstance(value, ast.BinOp):
            return '(' + emit(value.left) + ' ' + binary[type(value.op).__name__] + ' ' + emit(value.right) + ')'
        if isinstance(value, ast.UnaryOp):
            return '(' + unary[type(value.op).__name__] + emit(value.operand) + ')'
        if isinstance(value, ast.BoolOp):
            operator_text = ' and ' if isinstance(value.op, ast.And) else ' or '
            return '(' + operator_text.join(emit(x) for x in value.values) + ')'
        if isinstance(value, ast.Compare):
            pieces = [emit(value.left)]
            for operator_node, right in zip(value.ops, value.comparators):
                pieces.extend([compare[type(operator_node).__name__], emit(right)])
            return '(' + ' '.join(pieces) + ')'
        if isinstance(value, ast.IfExp):
            return '(' + emit(value.body) + ' if ' + emit(value.test) + ' else ' + emit(value.orelse) + ')'
        if isinstance(value, ast.Call):
            args = [emit(x) for x in value.args]
            args.extend(('**' if keyword.arg is None else keyword.arg + '=') + emit(keyword.value)
                        for keyword in value.keywords)
            if getattr(value, 'starargs', None) is not None:
                args.append('*' + emit(value.starargs))
            if getattr(value, 'kwargs', None) is not None:
                args.append('**' + emit(value.kwargs))
            return '(' + emit(value.func) + ')(' + ', '.join(args) + ')'
        if isinstance(value, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            body = emit(value.elt) + generators(value.generators)
            if isinstance(value, ast.ListComp):
                return '[' + body + ']'
            if isinstance(value, ast.SetComp):
                return '{' + body + '}'
            return '(' + body + ')'
        if isinstance(value, ast.DictComp):
            return '{' + emit(value.key) + ': ' + emit(value.value) + generators(value.generators) + '}'
        if is_node(value, 'JoinedStr'):
            for quote in ('"', "'"):
                delimiter = quote * 3
                body = fstring_body(value, quote)
                if delimiter not in body:
                    return 'f' + delimiter + body + delimiter
            raise ValueError('Cannot safely quote this f-string on this Python version.')
        if isinstance(value, ast.Import):
            return 'import ' + ', '.join(emit(x) for x in value.names)
        if isinstance(value, ast.ImportFrom):
            return 'from ' + '.' * value.level + (value.module or '') + ' import ' + ', '.join(emit(x) for x in value.names)
        if isinstance(value, ast.alias):
            return value.name + (' as ' + value.asname if value.asname else '')
        if is_node(value, 'AnnAssign'):
            result = emit(value.target) + ': ' + emit(value.annotation)
            return result + (' = ' + emit(value.value) if value.value is not None else '')
        if isinstance(value, ast.Assign):
            return ' = '.join([emit(x) for x in value.targets] + [emit(value.value)])
        if isinstance(value, ast.AugAssign):
            return emit(value.target) + ' ' + binary[type(value.op).__name__] + '= ' + emit(value.value)
        if isinstance(value, ast.Expr):
            return emit(value.value)
        raise ValueError('Unsupported AST source construct: ' + type(value).__name__)

    return emit(node)


def _ast_types(*names):
    legacy_literals = ('Num', 'Str', 'Bytes', 'NameConstant', 'Ellipsis')
    return tuple(getattr(ast, name) for name in names
                 if not (sys.version_info >= (3, 8) and name in legacy_literals)
                 and not (sys.version_info >= (3, 9) and name in ('Index', 'ExtSlice'))
                 and hasattr(ast, name))


def python_literal(n):
    if _AST_CONSTANT and isinstance(n, _AST_CONSTANT):
        return True, n.value
    legacy = (('Num', 'n'), ('Str', 's'), ('Bytes', 's'), ('NameConstant', 'value')) if sys.version_info < (3, 8) else ()
    for cls, field in legacy:
        kind = getattr(ast, cls, ())
        if kind and isinstance(n, kind):
            return True, getattr(n, field)
    kind = getattr(ast, 'Ellipsis', ()) if sys.version_info < (3, 8) else ()
    if kind and isinstance(n, kind):
        return True, Ellipsis
    if isinstance(n, ast.Name) and n.id in ('True', 'False', 'None'):
        return True, {'True': True, 'False': False, 'None': None}[n.id]
    return False, None


def python_expr(text, target=False):
    """Validate Python syntax without applying Flowgorithm operator rewrites."""
    try:
        a = ast.parse(text, mode='eval').body
    except SyntaxError as exc:
        raise FlowError('Invalid Python expression: ' + str(exc))
    allowed = (ast.Name, ast.Load, ast.Store, ast.BinOp, ast.UnaryOp,
               ast.BoolOp, ast.Compare, ast.Call, ast.keyword, ast.Attribute,
               ast.Subscript, ast.Slice, ast.List, ast.Tuple, ast.Dict, ast.Set,
               ast.IfExp, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
               ast.comprehension, ast.Starred,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
               ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift, ast.RShift,
               ast.USub, ast.UAdd, ast.Not, ast.Invert, ast.And, ast.Or,
               ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
               ast.In, ast.NotIn, ast.Is, ast.IsNot) + _ast_types(
                   'Constant', 'Num', 'Str', 'Bytes', 'NameConstant', 'Ellipsis',
                   'Index', 'ExtSlice', 'JoinedStr', 'FormattedValue')
    for n in ast.walk(a):
        if not isinstance(n, allowed):
            raise FlowError('Unsupported Python expression: ' + type(n).__name__)
        if isinstance(n, ast.Name) and n.id in ('eval','exec','open','compile','getattr','setattr','globals','locals','vars'):
            raise FlowError('Unsupported built-in: ' + n.id)
        if isinstance(n, ast.Name) and n.id.startswith('__') and n.id != '__name__':
            raise FlowError('Private names are not allowed.')
        if isinstance(n, ast.Attribute) and n.attr.startswith('_'):
            raise FlowError('Private attributes are not allowed.')
        if isinstance(n, ast.comprehension) and getattr(n, 'is_async', False):
            raise FlowError('Asynchronous comprehensions are not supported.')
        if isinstance(n, ast.Call) and (any(k.arg is None for k in n.keywords) or getattr(n, 'kwargs', None) is not None):
            raise FlowError('Expanded keyword arguments are not supported.')
        if isinstance(n, ast.Attribute) and n.attr not in set().union(*_PY_METHODS.values()) | set(dir(math)) | set(dir(random)):
            raise FlowError('Unsupported attribute: ' + n.attr)
    if target:
        def check(t):
            if isinstance(t, ast.Name):
                if not valid_name(t.id):
                    raise FlowError('Invalid assignment name.')
            elif isinstance(t, ast.Subscript):
                pass
            elif isinstance(t, (ast.Tuple, ast.List)):
                for x in t.elts:
                    check(x)
            elif isinstance(t, ast.Starred):
                check(t.value)
            else:
                raise FlowError('Unsupported Python assignment target.')
        check(a)
    return a


def validate_python_document(doc):
    if not isinstance(doc.get('functions'), list) or not doc['functions'] or doc['functions'][0].get('name') != 'Main':
        raise FlowError('The first function must be Main.')
    seen = set()
    for f in doc['functions']:
        if not valid_name(f.get('name')) or f['name'] in seen:
            raise FlowError('Invalid or duplicate function name.')
        seen.add(f['name'])
        for n in walk(f['body']):
            k = n['kind']
            if k not in KINDS:
                raise FlowError('Unsupported shape: ' + k)
            if k in ('Assign', 'Input'):
                for t in n.get('targets', [n['variable']]):
                    python_expr(t, target=True)
                python_expr(n.get('expression', 'input()'))
            elif k == 'For':
                python_expr(n['variable'], target=True)
                python_expr(n.get('iterable', 'range({0}, ({1}) + 1, {2}{3})'.format(n['start'], n['end'], '-' if n['direction'] == 'dec' else '', n['step'])))
            elif k in ('Output', 'If', 'While', 'Do', 'Call', 'Return'):
                python_expr(n.get('expression') or 'None')
            elif k == 'Comment' and n.get('python_import'):
                _python_import_names(n['python_import'])
        for p in f.get('parameters', []):
            if not valid_name(p['name']):
                raise FlowError('Invalid parameter name.')
            if 'default' in p:
                python_expr(p['default'])
        check_loops(f['body'])
    return doc


def _python_import_names(source):
    stmt = ast.parse(source).body[0]
    if isinstance(stmt, ast.Import):
        if any(x.name not in ('math', 'random') for x in stmt.names):
            raise FlowError('Only the math and random modules are supported; imports are never silently discarded.')
    elif isinstance(stmt, ast.ImportFrom) and stmt.module in ('math', 'random') and not stmt.level:
        module = math if stmt.module == 'math' else random
        for x in stmt.names:
            if x.name.startswith('_') or not hasattr(module, x.name) or x.name == '*':
                raise FlowError('Unsupported imported name: ' + x.name)
    else:
        raise FlowError('Only the math and random modules are supported.')
    return stmt


class PythonProgramImporter(object):
    """Compile structured Python statements to editable chart nodes."""
    def __init__(self, text, tree):
        self.text, self.tree = text, tree
        self.counter = 0
        self.used = {x.id for x in ast.walk(tree) if isinstance(x, ast.Name)}
        self.loops = []
        self.in_function = False

    def fail(self, n, message):
        raise ParseError('Line {0}: {1}'.format(getattr(n, 'lineno', '?'), message))

    def expr(self, n):
        text = ast_source(n) if n is not None else 'None'
        try:
            python_expr(text)
        except FlowError as exc:
            self.fail(n, str(exc))
        return text

    def fresh(self):
        while True:
            self.counter += 1
            v = 'flowLoopCompleted' + str(self.counter)
            if v not in self.used:
                self.used.add(v)
                return v

    def block(self, stmts):
        result = []
        for s in stmts:
            result.extend(self.statement(s))
        return result

    def statement(self, s):
        if isinstance(s, ast.FunctionDef):
            return [node('Comment', text='Define ' + s.name, python_definition=s.name)]
        if isinstance(s, (ast.Import, ast.ImportFrom)):
            source = ast_source(s)
            try:
                _python_import_names(source)
            except FlowError as exc:
                self.fail(s, str(exc))
            return [node('Comment', text=source, python_import=source)]
        if isinstance(s, ast.Pass):
            return [node('Comment', text='pass')]
        if isinstance(s, ast.Assign):
            targets = [ast_source(t) for t in s.targets]
            for t in targets:
                python_expr(t, target=True)
            expr = self.expr(s.value)
            is_input = isinstance(s.value, ast.Call) and isinstance(s.value.func, ast.Name) and (s.value.func.id == 'input' or (s.value.func.id in ('int', 'float', 'str') and s.value.args and isinstance(s.value.args[0], ast.Call) and getattr(s.value.args[0].func, 'id', '') == 'input'))
            return [node('Input' if is_input else 'Assign', variable=targets[0], expression=expr, targets=targets)]
        if isinstance(s, _ast_types('AnnAssign')):
            if s.value is None:
                return [node('Comment', text=ast_source(s))]
            return self.statement(ast.copy_location(ast.Assign(targets=[s.target], value=s.value), s))
        if isinstance(s, ast.AugAssign):
            if type(s.op) not in _PY_BINARY:
                self.fail(s, 'Unsupported augmented assignment.')
            return [node('Assign', variable=ast_source(s.target), expression=self.expr(s.value), augmented=type(s.op).__name__)]
        if isinstance(s, ast.Expr):
            is_literal, value = python_literal(s.value)
            if is_literal and isinstance(value, str):
                return [node('Comment', text=value)]
            expr = self.expr(s.value)
            if isinstance(s.value, ast.Call) and getattr(s.value.func, 'id', '') == 'print':
                if any(k.arg == 'file' for k in s.value.keywords):
                    self.fail(s, 'print(file=...) is not supported; file output is not redirected to the console.')
                return [node('Output', expression=expr, python_call=True)]
            return [node('Call', expression=expr)]
        if isinstance(s, ast.If):
            return [node('If', expression=self.expr(s.test), true=self.block(s.body), false=self.block(s.orelse))]
        if isinstance(s, (ast.For, ast.While)):
            flag = self.fresh() if s.orelse else None
            self.loops.append(flag)
            body = self.block(s.body)
            self.loops.pop()
            if isinstance(s, ast.For):
                loop = node('For', variable=ast_source(s.target), iterable=self.expr(s.iter), body=body)
            else:
                loop = node('While', expression=self.expr(s.test), body=body)
            if flag:
                return [node('Assign', variable=flag, expression='True'), loop,
                        node('If', expression=flag, true=self.block(s.orelse))]
            return [loop]
        if isinstance(s, ast.Break):
            if not self.loops:
                self.fail(s, 'break outside loop')
            return ([node('Assign', variable=self.loops[-1], expression='False')] if self.loops[-1] else []) + [node('Break')]
        if isinstance(s, ast.Continue):
            if not self.loops:
                self.fail(s, 'continue outside loop')
            return [node('Continue')]
        if isinstance(s, ast.Return):
            if not self.in_function:
                self.fail(s, 'return outside function')
            return [node('Return', expression=self.expr(s.value))]
        self.fail(s, 'Unsupported Python statement: ' + type(s).__name__)

    def run(self):
        doc = empty_document()
        doc['python'] = True
        doc['python_version'] = 1
        funcs = [s for s in self.tree.body if isinstance(s, ast.FunctionDef)]
        main = list(self.tree.body)
        for f in funcs:
            self.in_function = True
            if f.decorator_list or f.args.vararg or f.args.kwarg or f.args.kwonlyargs or getattr(f.args, 'posonlyargs', []):
                self.fail(f, 'Decorators, positional-only/keyword-only parameters, *args and **kwargs are not supported.')
            params = []
            defaults = [None] * (len(f.args.args) - len(f.args.defaults)) + list(f.args.defaults)
            for arg, default in zip(f.args.args, defaults):
                p = {'name': arg.arg, 'type': 'Python', 'array': False}
                if default is not None:
                    p['default'] = self.expr(default)
                params.append(p)
            local_names = set(p['name'] for p in params)
            for child in ast.walk(f):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                    local_names.add(child.id)
                if isinstance(child, (ast.Import, ast.ImportFrom)):
                    for alias in child.names:
                        local_names.add(alias.asname or alias.name)
                if isinstance(child, ast.FunctionDef) and child is not f:
                    self.fail(child, 'Nested function definitions are not supported.')
            doc['functions'].append({'name': f.name, 'type': 'Python', 'variable': '',
                                     'parameters': params, 'locals': sorted(local_names), 'body': self.block(f.body)})
        self.in_function = False
        doc['functions'][0]['body'] = self.block(main)
        return validate_python_document(doc)


def generate_python_document(doc):
    lines = []
    symbols = {ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/',
               ast.FloorDiv: '//', ast.Mod: '%', ast.Pow: '**', ast.BitAnd: '&',
               ast.BitOr: '|', ast.BitXor: '^', ast.LShift: '<<', ast.RShift: '>>'}
    aug = {k.__name__: v for k,v in symbols.items()}
    def emit(block, level):
        if not block:
            lines.append('    ' * level + 'pass')
        for n in block:
            pre, k = '    ' * level, n['kind']
            if k == 'Comment':
                if n.get('python_definition'):
                    f = next(f for f in doc['functions'][1:] if f['name'] == n['python_definition'])
                    params = [p['name'] + ('=' + p['default'] if 'default' in p else '') for p in f['parameters']]
                    lines.append(pre + 'def ' + f['name'] + '(' + ', '.join(params) + '):')
                    emit(f['body'], level+1)
                elif n.get('python_import'):
                    lines.append(pre + n['python_import'])
                else:
                    for part in n.get('text', '').splitlines() or ['']:
                        lines.append(pre + '# ' + part)
                    # A comment alone is not a Python suite.
                    lines.append(pre + 'pass')
            elif k == 'Declare':
                for v in names(n['name']):
                    lines.append(pre + v + ' = ' + ('[0] * (' + n['size'] + ')' if n['array'] else {'Integer':'0','Real':'0.0','String':"''",'Boolean':'False'}.get(n['type'], 'None')))
            elif k in ('Assign', 'Input'):
                expr = n.get('expression', 'input()')
                if n.get('augmented'):
                    lines.append(pre + n['variable'] + ' ' + aug[n['augmented']] + '= ' + expr)
                else:
                    lines.append(pre + ' = '.join(n.get('targets', [n['variable']]) + [expr]))
            elif k == 'Output':
                lines.append(pre + (n['expression'] if n.get('python_call') else 'print(' + n['expression'] + (')' if n.get('newline', True) else ", end='')")))
            elif k in ('Call', 'Return'):
                lines.append(pre + ('return ' if k == 'Return' else '') + (n.get('expression') or 'None'))
            elif k in ('Break', 'Continue'):
                lines.append(pre + k.lower())
            elif k == 'If':
                lines.append(pre + 'if ' + n['expression'] + ':')
                emit(n['true'], level+1)
                if n['false']:
                    lines.append(pre + 'else:')
                    emit(n['false'], level+1)
            elif k in ('For', 'While', 'Do'):
                if k == 'For':
                    iterable = n.get('iterable') or 'range({0}, ({1}) {2} 1, {3}{4})'.format(n['start'], n['end'], '-' if n['direction']=='dec' else '+', '-' if n['direction']=='dec' else '', n['step'])
                    lines.append(pre + 'for ' + n['variable'] + ' in ' + iterable + ':')
                else:
                    lines.append(pre + 'while ' + ('True' if k == 'Do' else n['expression']) + ':')
                emit(n['body'], level+1)
                if k == 'Do':
                    lines.extend([pre+'    if not ('+n['expression']+'):', pre+'        break'])
    defined = {n.get('python_definition') for n in walk(doc['functions'][0]['body'])}
    for f in doc['functions'][1:]:
        if f['name'] in defined:
            continue
        params = [p['name'] + ('=' + p['default'] if 'default' in p else '') for p in f['parameters']]
        lines.append('def ' + f['name'] + '(' + ', '.join(params) + '):')
        emit(f['body'], 1)
        lines.append('')
    emit(doc['functions'][0]['body'], 0)
    return '\n'.join(lines).rstrip() + '\n'


class _PythonModule(object):
    def __init__(self, name):
        self.name = name
        self.module = math if name == 'math' else random


class PythonInterpreter(object):
    """Bounded interpreter of validated AST nodes, never Python eval/exec."""
    def __init__(self, doc, input_callback=None, output_callback=None, limit=100000):
        validate_python_document(doc)
        self.doc, self.limit, self.count = doc, limit, 0
        self.input = input_callback or (lambda name: input())
        self.output = output_callback or (lambda value, nl: print(value, end='\n' if nl else ''))
        self.env, self.types, self.frames = {}, {}, []
        self.globals = self.env
        self.function_defs = {f['name']: f for f in doc['functions'][1:]}
        self.functions = {}
        self.local_names = set()
        self.lexical = []
        self.result, self.defaults = None, {}
        self.builtins = {'int':int, 'float':float, 'str':str, 'bool':bool, 'abs':abs,
                         'round':round, 'len':len, 'range':range, 'ord':ord, 'chr':chr,
                         'divmod':divmod, 'pow':pow, 'isinstance':isinstance,
                         'list':list, 'tuple':tuple, 'dict':dict, 'set':set,
                         'enumerate':enumerate, 'zip':zip, 'reversed':reversed,
                         'sorted':sorted, 'sum':sum, 'min':min, 'max':max,
                         'all':all, 'any':any, 'map':map, 'filter':filter,
                         'print':self.print_value, 'input':self.read_input}

    def tick(self):
        self.count += 1
        if self.count > self.limit:
            raise FlowError('Execution limit reached; possible infinite loop/recursion.')

    def read_input(self, prompt=''):
        self.output(str(prompt), False)
        result = self.input('input')
        if result is None:
            raise FlowError('Input cancelled.')
        return str(result)

    def print_value(self, *values, **kwargs):
        if any(k not in ('sep', 'end', 'flush') for k in kwargs):
            raise FlowError('Unsupported print option; file output is not supported.')
        sep, end = kwargs.get('sep', ' '), kwargs.get('end', '\n')
        sep = ' ' if sep is None else sep
        end = '\n' if end is None else end
        if not isinstance(sep, str) or not isinstance(end, str):
            raise FlowError('print sep and end must be strings or None.')
        text = sep.join(str(v) for v in values) + end
        self.output(text, False)

    def iter_values(self, value):
        try:
            iterator = iter(value)
        except TypeError as exc:
            raise FlowError(str(exc))
        for x in iterator:
            self.tick()
            yield x

    def _slice(self, n):
        if _AST_INDEX and isinstance(n, _AST_INDEX):
            return self.eval_ast(n.value)
        if isinstance(n, _ast_types('ExtSlice')):
            return tuple(self._slice(dim) for dim in n.dims)
        if isinstance(n, ast.Slice):
            return slice(*(self.eval_ast(x) if x is not None else None for x in (n.lower, n.upper, n.step)))
        return self.eval_ast(n)

    def _assign(self, n, value):
        if isinstance(n, ast.Name):
            self.env[n.id] = value
            self.types[n.id] = (type(value).__name__.title(), isinstance(value, (list,tuple,dict,set)))
        elif isinstance(n, ast.Subscript):
            obj = self.eval_ast(n.value)
            obj[self._slice(n.slice)] = value
        elif isinstance(n, (ast.Tuple, ast.List)):
            values = list(self.iter_values(value))
            stars = [i for i,x in enumerate(n.elts) if isinstance(x, ast.Starred)]
            if len(stars) > 1:
                raise FlowError('Only one starred assignment target is allowed.')
            if stars:
                i = stars[0]
                tail = len(n.elts) - i - 1
                if len(values) < len(n.elts)-1:
                    raise FlowError('Not enough values to unpack.')
                bound = values[:i] + [values[i:len(values)-tail if tail else len(values)]] + (values[-tail:] if tail else [])
            elif len(values) == len(n.elts):
                bound = values
            else:
                raise FlowError('Wrong number of values to unpack.')
            for target, item in zip(n.elts, bound):
                self._assign(target.value if isinstance(target, ast.Starred) else target, item)
        else:
            raise FlowError('Unsupported assignment target.')

    def set_value(self, target, value):
        self._assign(python_expr(target, target=True), value)

    def evaluate(self, text):
        return self.eval_ast(python_expr(text))

    def _binary(self, op, left, right):
        if isinstance(op, ast.Pow) and isinstance(right, (int,float)) and abs(right) > 10000:
            raise FlowError('Exponent too large.')
        if isinstance(op, (ast.LShift,ast.RShift)) and (not isinstance(right,int) or abs(right)>100000):
            raise FlowError('Shift too large.')
        if isinstance(op, ast.Mult):
            for a,b in ((left,right),(right,left)):
                if isinstance(a,(str,list,tuple)) and isinstance(b,int) and len(a)*max(0,b)>100000:
                    raise FlowError('Sequence allocation limit reached.')
        return _PY_BINARY[type(op)](left,right)

    def _augmented(self, op, left, right):
        if isinstance(op, ast.Add) and isinstance(left, list):
            if right is left:
                right = tuple(right)
            for value in self.iter_values(right):
                if len(left) >= 100000:
                    raise FlowError('Sequence allocation limit reached.')
                left.append(value)
            return left
        if isinstance(op, ast.Mult) and isinstance(left, list):
            self._binary(op,left,right)  # validate allocation before mutation
            left *= right
            return left
        if isinstance(left, set) and type(op) in (ast.BitOr,ast.BitAnd,ast.BitXor,ast.Sub):
            return {ast.BitOr:operator.ior,ast.BitAnd:operator.iand,ast.BitXor:operator.ixor,ast.Sub:operator.isub}[type(op)](left,right)
        if isinstance(left,dict) and isinstance(op,ast.BitOr):
            return operator.ior(left,right)
        return self._binary(op,left,right)

    def _comprehension(self, n):
        outer = self.env
        lexical = [(outer,self.local_names)] + self.lexical
        local, local_types = {}, {}
        comp_names = {x.id for g in n.generators for x in ast.walk(g.target) if isinstance(x,ast.Name)}
        # The outer iterable is evaluated now, before the generator starts.
        first = iter(self.eval_ast(n.generators[0].iter))
        def generate(level):
            g = n.generators[level]
            seq = first if level == 0 else self.eval_ast(g.iter)
            for value in self.iter_values(seq):
                self._assign(g.target,value)
                if all(self.eval_ast(test) for test in g.ifs):
                    if level+1 < len(n.generators):
                        for result in generate(level+1):
                            yield result
                    else:
                        yield (self.eval_ast(n.key),self.eval_ast(n.value)) if isinstance(n,ast.DictComp) else self.eval_ast(n.elt)
        def scoped():
            generator = generate(0)
            while True:
                previous, previous_types = self.env, self.types
                previous_lexical, previous_locals = self.lexical, self.local_names
                self.env, self.types = local, local_types
                self.lexical, self.local_names = lexical, comp_names
                try:
                    result = next(generator)
                except StopIteration:
                    return
                finally:
                    self.env, self.types = previous, previous_types
                    self.lexical, self.local_names = previous_lexical, previous_locals
                yield result
        result = scoped()
        if isinstance(n,ast.GeneratorExp):
            return result
        return dict(result) if isinstance(n,ast.DictComp) else set(result) if isinstance(n,ast.SetComp) else list(result)

    def eval_ast(self, n):
        self.tick()
        is_literal, value = python_literal(n)
        if is_literal:
            return value
        if isinstance(n, ast.Name):
            if n.id == '__name__':
                return '__main__'
            if n.id in self.env:
                return self.env[n.id]
            if n.id in self.local_names:
                raise FlowError('Local variable referenced before assignment: ' + n.id)
            for values, declared in self.lexical:
                if n.id in values:
                    return values[n.id]
                if n.id in declared:
                    raise FlowError('Local variable referenced before assignment: ' + n.id)
            if n.id in self.globals:
                return self.globals[n.id]
            if n.id in self.functions:
                return lambda *a, **kw: self.invoke(n.id,a,kw)
            if n.id in self.builtins:
                return self.builtins[n.id]
            raise FlowError('Undefined name: ' + n.id)
        if isinstance(n, ast.Attribute):
            obj = self.eval_ast(n.value)
            if isinstance(obj,_PythonModule):
                if n.attr.startswith('_') or not hasattr(obj.module,n.attr):
                    raise FlowError('Unsupported module attribute: '+n.attr)
                value = getattr(obj.module,n.attr)
                if callable(value) or isinstance(value,(int,float)):
                    return value
                raise FlowError('Unsupported module attribute: '+n.attr)
            methods = _PY_METHODS.get(type(obj).__name__,set())
            if n.attr not in methods:
                raise FlowError('Unsupported method: '+type(obj).__name__+'.'+n.attr)
            return getattr(obj,n.attr)
        if isinstance(n, (ast.List,ast.Tuple,ast.Set)):
            result=[]
            for x in n.elts:
                if isinstance(x,ast.Starred):
                    result.extend(self.iter_values(self.eval_ast(x.value)))
                else:
                    result.append(self.eval_ast(x))
            return tuple(result) if isinstance(n,ast.Tuple) else set(result) if isinstance(n,ast.Set) else result
        if isinstance(n,ast.Dict):
            result={}
            for key,value in zip(n.keys,n.values):
                if key is None:
                    result.update(self.eval_ast(value))
                else:
                    result[self.eval_ast(key)]=self.eval_ast(value)
            return result
        if isinstance(n,ast.Subscript):
            return self.eval_ast(n.value)[self._slice(n.slice)]
        if isinstance(n,ast.BinOp):
            return self._binary(n.op,self.eval_ast(n.left),self.eval_ast(n.right))
        if isinstance(n,ast.UnaryOp):
            return {ast.USub:operator.neg,ast.UAdd:operator.pos,ast.Not:operator.not_,ast.Invert:operator.invert}[type(n.op)](self.eval_ast(n.operand))
        if isinstance(n,ast.BoolOp):
            value=self.eval_ast(n.values[0])
            for other in n.values[1:]:
                if (isinstance(n.op,ast.And) and not value) or (isinstance(n.op,ast.Or) and value):
                    return value
                value=self.eval_ast(other)
            return value
        if isinstance(n,ast.Compare):
            left=self.eval_ast(n.left)
            for op,right in zip(n.ops,n.comparators):
                value=self.eval_ast(right)
                if not _PY_COMPARE[type(op)](left,value):
                    return False
                left=value
            return True
        if isinstance(n,ast.IfExp):
            return self.eval_ast(n.body if self.eval_ast(n.test) else n.orelse)
        if isinstance(n,(ast.ListComp,ast.SetComp,ast.DictComp,ast.GeneratorExp)):
            return self._comprehension(n)
        if isinstance(n, _ast_types('JoinedStr')):
            return ''.join(str(self.eval_ast(x)) for x in n.values)
        if isinstance(n, _ast_types('FormattedValue')):
            value=self.eval_ast(n.value)
            if n.conversion != -1:
                value={115:str,114:repr,97:ascii}[n.conversion](value)
            spec=self.eval_ast(n.format_spec) if n.format_spec else ''
            if len(spec)>100 or re.search(r'\d{7}',spec):
                raise FlowError('Format width is too large.')
            return format(value,spec)
        if isinstance(n,ast.Call):
            fn=self.eval_ast(n.func)
            args=[]
            for a in n.args:
                if isinstance(a,ast.Starred):
                    args.extend(self.iter_values(self.eval_ast(a.value)))
                else:
                    args.append(self.eval_ast(a))
            if getattr(n, 'starargs', None) is not None:
                args.extend(self.iter_values(self.eval_ast(n.starargs)))
            kwargs={k.arg:self.eval_ast(k.value) for k in n.keywords}
            # Count consumption even inside otherwise atomic Python built-ins.
            if fn in (sum,all,any,list,tuple,set,sorted,dict,min,max) and args:
                if not isinstance(args[0],(int,float,bool)) and not (fn in (min,max) and len(args)>1):
                    if fn is dict and isinstance(args[0],dict):
                        pass
                    else:
                        args[0]=self.iter_values(args[0])
            if fn in (map,filter,enumerate,zip,reversed):
                if fn is zip:
                    args=[self.iter_values(a) for a in args]
                elif fn in (map,filter):
                    args=[args[0]]+[self.iter_values(a) for a in args[1:]]
                elif fn is enumerate:
                    args[0]=self.iter_values(args[0])
            if not callable(fn):
                raise FlowError('Value is not callable.')
            return fn(*args,**kwargs)
        raise FlowError('Unsupported Python expression: '+type(n).__name__)

    def invoke(self, name, args, kwargs=None):
        self.tick()
        if len(self.frames)>=64:
            raise FlowError('Maximum call depth reached.')
        f=self.functions[name]
        params=f['parameters']
        kwargs=kwargs or {}
        if len(args)>len(params) or any(k not in {p['name'] for p in params} for k in kwargs):
            raise FlowError('Wrong arguments for '+name)
        bound={}
        for i,p in enumerate(params):
            key=p['name']
            if i<len(args):
                if key in kwargs:
                    raise FlowError('Duplicate argument '+key)
                bound[key]=args[i]
            elif key in kwargs:
                bound[key]=kwargs[key]
            elif (name,key) in self.defaults:
                bound[key]=self.defaults[(name,key)]
            else:
                raise FlowError('Missing argument '+key)
        old=self.env,self.types
        previous_locals=self.local_names
        previous_lexical=self.lexical
        self.lexical=[]
        self.frames.append(old)
        self.env,self.types={},{}
        self.local_names=set(p['name'] for p in params)
        def add_target(target):
            if isinstance(target,ast.Name):
                self.local_names.add(target.id)
            elif isinstance(target,(ast.Tuple,ast.List)):
                for part in target.elts:
                    add_target(part.value if isinstance(part,ast.Starred) else part)
        for chart_node in walk(f['body']):
            if chart_node['kind'] in ('Assign','Input','For'):
                for target in chart_node.get('targets',[chart_node['variable']]):
                    add_target(python_expr(target,target=True))
            if chart_node['kind']=='Comment' and chart_node.get('python_import'):
                statement=_python_import_names(chart_node['python_import'])
                for alias in statement.names:
                    self.local_names.add(alias.asname or alias.name)
        try:
            for key,value in bound.items():
                self.set_value(key,value)
            try:
                for unused in self.execute(f['body']):
                    pass
            except Returned as result:
                return result.value
        finally:
            self.env,self.types=old
            self.local_names=previous_locals
            self.lexical=previous_lexical
            self.frames.pop()

    def execute(self, block):
        for n in block:
            self.tick()
            yield n
            k=n['kind']
            if k=='Comment':
                if n.get('python_definition'):
                    name=n['python_definition']
                    f=self.function_defs[name]
                    for p in f['parameters']:
                        if 'default' in p:
                            self.defaults[(name,p['name'])]=self.evaluate(p['default'])
                    self.functions[name]=f
                elif n.get('python_import'):
                    statement=_python_import_names(n['python_import'])
                    if isinstance(statement,ast.Import):
                        for x in statement.names:
                            self.set_value(x.asname or x.name,_PythonModule(x.name))
                    else:
                        module=_PythonModule(statement.module)
                        for x in statement.names:
                            self.set_value(x.asname or x.name,getattr(module.module,x.name))
            elif k=='Declare':
                initial={'Integer':0,'Real':0.0,'String':'','Boolean':False}.get(n['type'])
                for v in names(n['name']):
                    size=int(self.evaluate(n['size'])) if n['array'] else 0
                    if size<0 or size>100000:
                        raise FlowError('Array size out of range.')
                    self.set_value(v,[initial]*size if n['array'] else initial)
            elif k in ('Assign','Input'):
                if n.get('augmented'):
                    target=python_expr(n['variable'],target=True)
                    op=next(t() for t in _PY_BINARY if t.__name__==n['augmented'])
                    if isinstance(target,ast.Subscript):
                        obj=self.eval_ast(target.value)
                        key=self._slice(target.slice)
                        old=obj[key]
                        value=self.evaluate(n['expression'])
                        obj[key]=self._augmented(op,old,value)
                    else:
                        old=self.eval_ast(target)
                        self._assign(target,self._augmented(op,old,self.evaluate(n['expression'])))
                else:
                    value=self.evaluate(n.get('expression','input()'))
                    for target in n.get('targets',[n['variable']]):
                        self.set_value(target,value)
            elif k=='Output':
                if n.get('python_call'):
                    self.evaluate(n['expression'])
                else:
                    self.output(str(self.evaluate(n['expression'])),n.get('newline',True))
            elif k=='If':
                for item in self.execute(n['true'] if self.evaluate(n['expression']) else n['false']):
                    yield item
            elif k in ('For','While','Do'):
                if k=='For':
                    expr=n.get('iterable') or 'range({0}, ({1}) {2} 1, {3}{4})'.format(n['start'],n['end'],'-' if n['direction']=='dec' else '+','-' if n['direction']=='dec' else '',n['step'])
                    iterator=self.iter_values(self.evaluate(expr))
                first=True
                while True:
                    if k=='For':
                        try:
                            value=next(iterator)
                        except StopIteration:
                            break
                        self.set_value(n['variable'],value)
                    elif not (k=='Do' and first) and not self.evaluate(n['expression']):
                        break
                    first=False
                    try:
                        for item in self.execute(n['body']):
                            yield item
                    except LoopContinue:
                        pass
                    except LoopBreak:
                        break
                    self.tick()
                    yield n
            elif k=='Break':
                raise LoopBreak()
            elif k=='Continue':
                raise LoopContinue()
            elif k=='Call':
                self.evaluate(n['expression'])
            elif k=='Return':
                raise Returned(self.evaluate(n.get('expression') or 'None'))

    def steps(self):
        # Chart-created functions have no source-position definition marker.
        positioned={n.get('python_definition') for n in walk(self.doc['functions'][0]['body'])}
        for name,f in self.function_defs.items():
            if name not in positioned:
                for p in f['parameters']:
                    if 'default' in p:
                        self.defaults[(name,p['name'])]=self.evaluate(p['default'])
                self.functions[name]=f
        # Source definitions execute in order; defaults bind at that point.
        try:
            for n in self.execute(self.doc['functions'][0]['body']):
                yield n
        except Returned as r:
            self.result=r.value
        except (TypeError,ValueError,KeyError,IndexError,ZeroDivisionError,OverflowError,AttributeError,NameError) as exc:
            raise FlowError(type(exc).__name__+': '+str(exc))

    def run(self):
        for unused in self.steps():
            pass
        return self.env


class Interpreter(object):
    def __new__(cls, doc, input_callback=None, output_callback=None, limit=100000):
        if doc.get("python"):
            return PythonInterpreter(doc, input_callback, output_callback, limit)
        return object.__new__(cls)

    def __init__(self, doc, input_callback=None, output_callback=None, limit=100000):
        validate(doc)
        self.doc = doc
        self.functions = dict((f['name'], f) for f in doc['functions'])
        self.input = input_callback or (lambda name: input(name + ': '))
        self.output = output_callback or (lambda value, nl: print(value, end='\n' if nl else ''))
        self.limit = limit
        self.count = 0
        self.env = {}
        self.types = {}
        self.frames = []
        self.result = None
        self.builtins = {'abs': abs, 'sqrt': math.sqrt, 'sin': math.sin, 'cos': math.cos,
            'tan': math.tan, 'arcsin': math.asin, 'arccos': math.acos, 'arctan': math.atan,
            'log': math.log, 'log10': math.log10, 'floor': math.floor, 'ceiling': math.ceil,
            'round': round, 'int': int, 'tostring': self.string, 'tointeger': int, 'toreal': float,
            'str': self.string, 'float': float,
            'toboolean': self.boolean, 'len': len, 'length': len, 'size': len,
            'char': lambda s, i: s[self.index(i)], 'random': lambda n: random.randrange(int(n)),
            'min': min, 'max': max, 'sgn': lambda x: (x > 0) - (x < 0),
            'toupper': lambda s: str(s).upper(), 'tolower': lambda s: str(s).lower(),
            'trim': lambda s: str(s).strip(), 'contains': lambda s, t: str(t) in str(s),
            'ord': lambda s: ord(str(s)[0]), 'chr': lambda n: chr(int(n)),
            'flowdictionaryerror': self.dictionary_error}

    @staticmethod
    def dictionary_error(message):
        raise FlowError(str(message))

    def tick(self):
        self.count += 1
        if self.count > self.limit:
            raise FlowError('Execution limit reached; possible infinite loop/recursion.')

    @staticmethod
    def string(x):
        return str(x).lower() if isinstance(x, bool) else str(x)

    @staticmethod
    def boolean(x):
        if isinstance(x, str):
            if x.lower() in ('true', '1'):
                return True
            if x.lower() in ('false', '0'):
                return False
            raise FlowError('Boolean input must be true or false.')
        return bool(x)

    @staticmethod
    def index(x):
        if isinstance(x, bool) or not isinstance(x, int) or x < 0:
            raise FlowError('Array/string index must be a nonnegative integer.')
        return x

    def cast(self, value, typ):
        return {'Integer': int, 'Real': float, 'String': self.string, 'Boolean': self.boolean}[typ](value)

    def evaluate(self, text):
        return self.eval_ast(parse_expr(text))

    def eval_ast(self, a):
        self.tick()
        islit, val = literal(a)
        if islit:
            return val
        if isinstance(a, ast.Name):
            if a.id.lower() == 'pi':
                return math.pi
            if a.id not in self.env:
                raise FlowError('Undeclared variable: ' + a.id)
            return self.env[a.id]
        if isinstance(a, ast.Subscript):
            return self.eval_ast(a.value)[self.index(self.eval_ast(index_ast(a)))]
        if isinstance(a, ast.BinOp):
            left, right = self.eval_ast(a.left), self.eval_ast(a.right)
            if isinstance(a.op, ast.BitAnd):
                return self.string(left) + self.string(right)
            ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                   ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
                   ast.Mod: operator.mod, ast.Pow: operator.pow}
            if isinstance(a.op, ast.Pow) and abs(right) > 10000:
                raise FlowError('Exponent too large.')
            return ops[type(a.op)](left, right)
        if isinstance(a, ast.UnaryOp):
            return {ast.Not: operator.not_, ast.USub: operator.neg, ast.UAdd: operator.pos}[type(a.op)](self.eval_ast(a.operand))
        if isinstance(a, ast.BoolOp):
            if isinstance(a.op, ast.And):
                return all(self.eval_ast(x) for x in a.values)
            return any(self.eval_ast(x) for x in a.values)
        if isinstance(a, ast.Compare):
            left = self.eval_ast(a.left)
            ops = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
                   ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
            for op, right in zip(a.ops, a.comparators):
                val = self.eval_ast(right)
                if not ops[type(op)](left, val):
                    return False
                left = val
            return True
        if isinstance(a, ast.Call):
            args = [self.eval_ast(x) for x in a.args]
            name = a.func.id
            if name.lower() in self.builtins:
                return self.builtins[name.lower()](*args)
            return self.invoke(name, args)
        raise FlowError('Unknown expression.')

    def set_value(self, target, value):
        a = parse_expr(target)
        name = a.id if isinstance(a, ast.Name) else a.value.id if isinstance(a, ast.Subscript) and isinstance(a.value, ast.Name) else ''
        if name not in self.types:
            raise FlowError('Undeclared variable: ' + name)
        typ, array = self.types[name]
        if isinstance(a, ast.Subscript):
            if not array:
                raise FlowError('Not an array: ' + name)
            self.env[name][self.index(self.eval_ast(index_ast(a)))] = self.cast(value, typ)
        else:
            if array:
                raise FlowError('Assign an array element, not the whole array.')
            self.env[name] = self.cast(value, typ)

    def invoke(self, name, args):
        self.tick()
        if len(self.frames) >= 64:
            raise FlowError('Maximum call depth reached.')
        if name not in self.functions or name == 'Main':
            raise FlowError('Unknown function: ' + name)
        f = self.functions[name]
        if len(args) != len(f['parameters']):
            raise FlowError('Wrong argument count for ' + name)
        old = self.env, self.types
        self.frames.append(old)
        self.env, self.types = {}, {}
        try:
            for p, v in zip(f['parameters'], args):
                self.types[p['name']] = (p['type'], p['array'])
                self.env[p['name']] = v if p['array'] else self.cast(v, p['type'])
            try:
                for unused in self.execute(f['body']):
                    pass
            except Returned as r:
                return None if f['type'] == 'None' else self.cast(r.value, f['type'])
            if f['type'] != 'None':
                if f['variable'] in self.env:
                    return self.cast(self.env[f['variable']], f['type'])
                raise FlowError('Function ' + name + ' did not return a value.')
        finally:
            self.env, self.types = old
            self.frames.pop()

    def execute(self, block):
        for n in block:
            self.tick()
            yield n
            k = n['kind']
            if k == 'Declare':
                initial = {'Integer': 0, 'Real': 0.0, 'String': '', 'Boolean': False}[n['type']]
                size = self.evaluate(n['size']) if n['array'] else 0
                if n['array'] and (not isinstance(size, int) or size < 0 or size > 100000):
                    raise FlowError('Array size must be an integer from 0 to 100000.')
                for name in names(n['name']):
                    # Static validation rejects duplicate declarations; re-entering
                    # the same declaration in a loop simply reinitializes it.
                    self.types[name] = (n['type'], n['array'])
                    self.env[name] = [initial] * size if n['array'] else initial
            elif k == 'Assign':
                self.set_value(n['variable'], self.evaluate(n['expression']))
            elif k == 'Input':
                value = self.input(n['variable'])
                if value is None:
                    raise FlowError('Input cancelled.')
                self.set_value(n['variable'], value)
            elif k == 'Output':
                self.output(self.string(self.evaluate(n['expression'])), n['newline'])
            elif k == 'If':
                for item in self.execute(n['true'] if self.evaluate(n['expression']) else n['false']):
                    yield item
            elif k in ('While', 'Do'):
                first = True
                while (k == 'Do' and first) or self.evaluate(n['expression']):
                    first = False
                    try:
                        for item in self.execute(n['body']):
                            yield item
                    except LoopContinue:
                        pass
                    except LoopBreak:
                        break
                    self.tick()
                    yield n
            elif k == 'For':
                start = self.evaluate(n['start'])
                end = self.evaluate(n['end'])
                step = self.evaluate(n['step'])
                if step <= 0:
                    raise FlowError('For step must be positive; choose descending for a negative direction.')
                sign = -1 if n['direction'] == 'dec' else 1
                value = start
                while value >= end if sign < 0 else value <= end:
                    self.set_value(n['variable'], value)
                    try:
                        for item in self.execute(n['body']):
                            yield item
                    except LoopContinue:
                        pass
                    except LoopBreak:
                        break
                    value += sign * step
                    self.tick()
                    yield n
                self.set_value(n['variable'], value)
            elif k == 'Break':
                raise LoopBreak()
            elif k == 'Continue':
                raise LoopContinue()
            elif k == 'Call':
                self.evaluate(n['expression'])
            elif k == 'Return':
                raise Returned(self.evaluate(n['expression']) if n['expression'].strip() else None)

    def steps(self):
        try:
            for n in self.execute(self.doc['functions'][0]['body']):
                yield n
        except Returned as r:
            self.result = r.value

    def run(self):
        for unused in self.steps():
            pass
        return self.env

class LoopBreak(Exception):
    pass


class LoopContinue(Exception):
    pass


class Returned(Exception):
    def __init__(self, value):
        self.value = value

# ----------------------------------------------------------------------------
# Source generators.  One small class per language on top of a shared engine.
# Generated programs are "normal" code: for script languages the main program is
# plain top-level code (no Main() wrapper); user functions are ordinary
# functions.  Languages that need an entry point get the usual boilerplate.
# ----------------------------------------------------------------------------
BUILTIN_KEYS = {'abs', 'sqrt', 'sin', 'cos', 'tan', 'arcsin', 'arccos', 'arctan',
                'log', 'log10', 'floor', 'ceiling', 'round', 'int', 'tointeger', 'toupper', 'tolower', 'trim', 'contains',
                'toreal', 'float', 'tostring', 'str', 'toboolean', 'len', 'length',
                'size', 'char', 'random', 'min', 'max', 'sgn', 'ord', 'chr', 'flowdictionaryerror'}
ALIASES = {'tointeger': 'int', 'float': 'toreal', 'str': 'tostring',
           'length': 'len', 'size': 'len'}
SCALAR_TYPES = ('Integer', 'Real', 'String', 'Boolean')


def c_string(s, quote='"', ctl=None, dollar=False):
    out = []
    for ch in s:
        o = ord(ch)
        if ch == '\\':
            out.append('\\\\')
        elif ch == quote:
            out.append('\\' + ch)
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '\t':
            out.append('\\t')
        elif o < 32 or o == 127:
            out.append(ctl(o) if ctl else '\\u%04x' % o)
        elif ch == '$' and dollar:
            out.append('\\$')
        else:
            out.append(ch)
    return quote + ''.join(out) + quote


def strip_outer(code):
    """Remove one pair of parentheses that encloses the whole text."""
    if len(code) < 2 or code[0] != '(' or code[-1] != ')':
        return code
    depth = 0
    quote = None
    for i, ch in enumerate(code):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in '"\'':
            quote = ch
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0 and i != len(code) - 1:
                return code
    return code[1:-1]


HELP_BEGIN = 'flowchart-helpers-begin'
HELP_END = 'flowchart-helpers-end'
GENERATORS = {}


def register(language):
    def deco(cls):
        cls.language_name = language
        GENERATORS[language] = cls
        return cls
    return deco


class Gen(object):
    """Shared engine. Subclasses supply syntax through small hooks/tables."""
    ext = '.txt'
    cm = '//'
    semi = ';'
    minparen = True         # False: always parenthesise compound sub-expressions
    strip_top = False       # strip the outermost parentheses of a statement expression
    hoist = True            # block scoped declarations are hoisted to function top
    has_elif = False
    sigil = ''
    POWSYM = None           # infix power operator (None: use F['pow'] call)
    int_div_trap = True     # integer / integer truncates natively
    cast_both = False       # both operands must be converted for real division
    native_for = True
    INTDIV = None           # template for truncating integer division, e.g. '({0} / {1})'
    TRUE, FALSE = 'true', 'false'
    AND, OR, NOT = ' && ', ' || ', '!'
    CONCAT = ' + '
    T = {'Integer': 'int', 'Real': 'double', 'String': 'String', 'Boolean': 'boolean', 'None': 'void'}
    CMP = {'==': '==', '!=': '!=', '<': '<', '<=': '<=', '>': '>', '>=': '>='}
    F = {}
    notes = ''

    def __init__(self, language):
        self.lang = language
        self.lines = []
        self.depth = 0
        self.nest = 0
        self.vt = {}
        self.uses = set()
        self.hoisted = {}
        self.loops = []

    BREAK, CONTINUE = 'break', 'continue'

    # ------------------------------------------------------------ plumbing
    def emit(self, s=''):
        self.lines.append(('    ' * self.depth + s) if s else '')

    def stmt(self, s):
        self.emit(s + self.semi)

    def reject(self, what):
        raise Unsupported('{0}: {1} cannot be generated.'.format(self.lang, what))

    def comment_lines(self, text):
        for line in (text.splitlines() or ['']):
            self.emit((self.cm + ' ' + line).rstrip())

    def uni(self):
        return None

    # ------------------------------------------------------------ literals
    def lit(self, v):
        if isinstance(v, bool):
            return self.TRUE if v else self.FALSE
        if isinstance(v, str):
            return self.strlit(v)
        if isinstance(v, float):
            return self.reallit(v)
        return str(v)

    def reallit(self, v):
        r = repr(v)
        if 'e' not in r and 'E' not in r and '.' not in r and 'n' not in r:
            r += '.0'
        return r

    def strlit(self, s):
        return c_string(s)

    def init_value(self, t):
        return self.lit({'Integer': 0, 'Real': 0.0, 'String': '', 'Boolean': False}[t])

    def ref(self, name):
        return self.sigil + name

    def tname(self, t):
        return self.T[t]

    # ------------------------------------------------------------ typing
    def ty(self, a):
        ok, v = literal(a)
        if ok:
            return 'Boolean' if isinstance(v, bool) else 'String' if isinstance(v, str) else 'Real' if isinstance(v, float) else 'Integer'
        if isinstance(a, ast.Name):
            if a.id.lower() == 'pi':
                return 'Real'
            return self.vt.get(a.id, (None, False))[0]
        if isinstance(a, ast.Subscript):
            return self.ty(a.value)
        if isinstance(a, ast.BinOp):
            if isinstance(a.op, ast.BitAnd):
                return 'String'
            l, r = self.ty(a.left), self.ty(a.right)
            if isinstance(a.op, ast.Add) and 'String' in (l, r):
                return 'String'
            if isinstance(a.op, ast.Div):
                return 'Real'
            if isinstance(a.op, ast.Pow):
                return 'Integer' if (l, r) == ('Integer', 'Integer') else 'Real'
            return 'Real' if 'Real' in (l, r) else 'Integer'
        if isinstance(a, ast.UnaryOp):
            return 'Boolean' if isinstance(a.op, ast.Not) else self.ty(a.operand)
        if isinstance(a, (ast.Compare, ast.BoolOp)):
            return 'Boolean'
        if isinstance(a, ast.Call):
            key = ALIASES.get(a.func.id.lower(), a.func.id.lower())
            if key in BUILTIN_KEYS:
                if key in ('tostring', 'char', 'toupper', 'tolower', 'trim', 'chr'):
                    return 'String'
                if key == 'contains':
                    return 'Boolean'
                if key in ('int', 'floor', 'ceiling', 'round', 'len', 'random', 'sgn', 'ord'):
                    return 'Integer'
                if key == 'toboolean':
                    return 'Boolean'
                if key in ('abs', 'min', 'max'):
                    ts = [self.ty(x) for x in a.args]
                    return 'Real' if 'Real' in ts else (ts[0] if ts else None)
                return 'Real'
            f = self.ftypes.get(a.func.id)
            return None if f is None or f['type'] == 'None' else f['type']
        return None

    def is_array(self, a):
        return isinstance(a, ast.Name) and self.vt.get(a.id, (None, False))[1]

    # ------------------------------------------------------------ expressions
    def wrap(self, code, p, need, right=False):
        if re.match(r'^[\w.$@]+$', code):
            return code
        if not self.minparen:
            return code
        return '(' + code + ')' if (p < need or (p == need and right)) else code

    def paren(self, code, p):
        if self.minparen:
            return code, p
        return '(' + code + ')', 100

    def sub(self, a, need, right=False):
        code, p = self.exp(a)
        if not self.minparen:
            return code
        return '(' + code + ')' if (p < need or (p == need and right)) else code

    def ex(self, a):
        code = self.exp(a)[0]
        return strip_outer(code) if (self.strip_top and not self.minparen) else code

    def expr(self, text):
        return self.ex(parse_expr(text))

    def cond(self, text):
        return self.expr(text)

    def exp(self, a):
        ok, v = literal(a)
        if ok:
            return self.lit(v), 100
        if isinstance(a, ast.Name):
            if a.id.lower() == 'pi' and a.id not in self.vt:
                return '3.141592653589793', 100
            if a.id not in self.vt:
                raise FlowError('Declare variable before use: ' + a.id)
            return self.ref(a.id), 100
        if isinstance(a, ast.Subscript):
            okb, vb = literal(a.value)
            oki, vi = literal(index_ast(a))
            if okb and isinstance(vb, str) and oki and isinstance(vi, int) and not isinstance(vi, bool) and 0 <= vi < len(vb):
                return self.lit(vb[vi]), 100
            if not self.is_array(a.value) and self.ty(a.value) != 'String':
                raise FlowError('Not an array: ' + getattr(a.value, 'id', '?'))
            return self.index(self.sub(a.value, 100), self.ex(index_ast(a)), a), 100
        if isinstance(a, ast.BinOp):
            return self.binary(a)
        if isinstance(a, ast.UnaryOp):
            if isinstance(a.op, ast.Not):
                return self.paren(self.NOT + self.sub(a.operand, 8), 3)
            sym = '-' if isinstance(a.op, ast.USub) else '+'
            return self.paren(sym + self.sub(a.operand, 8), 8)
        if isinstance(a, ast.BoolOp):
            isand = isinstance(a.op, ast.And)
            sep = self.AND if isand else self.OR
            p = 2 if isand else 1
            return self.paren(sep.join(self.sub(v, p + 1) for v in a.values), p)
        if isinstance(a, ast.Compare):
            return self.compare(a)
        if isinstance(a, ast.Call):
            return self.call(a), 100
        self.reject('expression ' + type(a).__name__)

    def strpart(self, a, need, right=False):
        """Code of `a` converted to a string, wrapped for use at precedence `need`."""
        t = self.ty(a)
        if t == 'String':
            if literal(a)[0]:
                return self.strlit_concat(self.sub(a, need, right))
            return self.sub(a, need, right)
        return self.tostr(self.ex(a), t)

    def strlit_concat(self, code):
        return code

    def binary(self, a):
        op = type(a.op)
        lt, rt = self.ty(a.left), self.ty(a.right)
        if op is ast.BitAnd or (op is ast.Add and 'String' in (lt, rt)):
            return self.concat(a.left, a.right)
        if op is ast.Pow:
            if self.POWSYM:
                return self.paren(self.sub(a.left, 10) + self.POWSYM + self.sub(a.right, 10), 9)
            return self.pow(self.ex(a.left), self.ex(a.right), lt, rt), 100
        if op is ast.Div:
            return self.rdiv(a.left, a.right, lt, rt)
        if op is ast.FloorDiv:
            q = self.rdiv(a.left, a.right, lt, rt)[0]
            return self.builtin_code('floor', [q], ['Real']), 100
        if op is ast.Mod:
            return self.mod(a.left, a.right, lt, rt)
        sym = {ast.Add: '+', ast.Sub: '-', ast.Mult: '*'}[op]
        p = 7 if op is ast.Mult else 6
        return self.paren(self.sub(a.left, p) + ' ' + sym + ' ' + self.sub(a.right, p, True), p)

    def concat(self, left, right):
        return self.paren(self.strpart(left, 5) + self.CONCAT + self.strpart(right, 5, True), 5)

    def pow(self, l, r, lt, rt):
        return self.F['pow'].format(l, r)

    def rdiv(self, left, right, lt, rt):
        l, r = self.sub(left, 7), self.sub(right, 7, True)
        if lt == 'Integer' and rt == 'Integer' and self.int_div_trap:
            l = self.int2real(self.ex(left), wrap=True)
            if self.cast_both:
                r = self.int2real(self.ex(right), wrap=True)
        return self.paren(l + ' / ' + r, 7)

    def mod(self, left, right, lt, rt):
        return self.paren(self.sub(left, 7) + ' % ' + self.sub(right, 7, True), 7)

    def int2real(self, code, wrap=False):
        return '(1.0 * ' + code + ')' if wrap else code

    def real2int(self, code):
        return '(int)(' + code + ')'

    def index(self, base, idx, a):
        return base + '[' + idx + ']'

    def tostr(self, code, t):
        return self.fmt(self.F['tostr'], [code])

    def compare(self, a):
        parts = []
        left = a.left
        for op, right in zip(a.ops, a.comparators):
            sym = {ast.Eq: '==', ast.NotEq: '!=', ast.Lt: '<', ast.LtE: '<=', ast.Gt: '>', ast.GtE: '>='}[type(op)]
            lt, rt = self.ty(left), self.ty(right)
            parts.append(self.cmp(sym, left, right, lt, rt))
            left = right
        if len(parts) == 1:
            return parts[0]
        return self.paren(self.AND.join(self.wrap(p[0], p[1], 3) for p in parts), 2)

    def cmp(self, sym, left, right, lt, rt):
        return self.paren(self.sub(left, 5) + ' ' + self.CMP[sym] + ' ' + self.sub(right, 5, True), 4)

    # ------------------------------------------------------------ built-ins
    def call(self, a):
        name = a.func.id
        key = ALIASES.get(name.lower(), name.lower())
        if key in BUILTIN_KEYS:
            return self.builtin(key, a)
        if name in self.ftypes:
            return self.user_call(name, a.args)
        raise FlowError('Unknown function: ' + name)

    def user_call(self, name, args):
        f = self.ftypes[name]
        if len(args) != len(f['parameters']):
            raise FlowError('Wrong argument count for ' + name)
        out = []
        for x, prm in zip(args, f['parameters']):
            code = self.ex(x)
            if not prm['array']:
                code = self.coerce(code, self.ty(x), prm['type'])
            out.append(code)
        return name + '(' + ', '.join(out) + ')'

    def builtin(self, key, a):
        args = [self.ex(x) for x in a.args]
        types = [self.ty(x) for x in a.args]
        need = {'random': 1, 'min': 2, 'max': 2, 'char': 2, 'contains': 2}.get(key, 1)
        if len(args) != need:
            raise FlowError('{0} expects {1} argument(s).'.format(a.func.id, need))
        if key == 'char':
            okb, vb = literal(a.args[0])
            oki, vi = literal(a.args[1])
            if okb and isinstance(vb, str) and oki and isinstance(vi, int) and not isinstance(vi, bool) and 0 <= vi < len(vb):
                return self.lit(vb[vi])
        if key == 'len' and self.is_array(a.args[0]):
            return self.array_len(a.args[0].id, args[0])
        if key == 'int' and self.INTDIV and isinstance(a.args[0], ast.BinOp) and isinstance(a.args[0].op, ast.Div) \
                and self.ty(a.args[0].left) == 'Integer' and self.ty(a.args[0].right) == 'Integer':
            return self.INTDIV.format(self.sub(a.args[0].left, 7), self.sub(a.args[0].right, 7, True))
        return self.builtin_code(key, args, types)

    def array_len(self, name, code):
        return self.fmt(self.F['alen'], [code])

    def builtin_code(self, key, args, types):
        t = types[0] if types else None
        if key == 'flowdictionaryerror':
            # Raising through an empty lookup also remains valid in the
            # restricted Python interpreter, without executing arbitrary code.
            if self.lang == 'Python':
                return '({})[' + args[0] + ']'
            if self.lang == 'MATLAB':
                return 'error(' + args[0] + ')'
            return 'flowDictionaryError(' + args[0] + ')'
        if key == 'tostring':
            return self.tostr(args[0], t)
        if key == 'int':
            if t == 'String':
                return self.fmt(self.F['parseint'], args)
            return args[0] if t == 'Integer' else self.fmt(self.F['trunc'], args)
        if key == 'toreal':
            if t == 'String':
                return self.fmt(self.F['parsereal'], args)
            return self.int2real(args[0], wrap=True) if t == 'Integer' else args[0]
        if key == 'toboolean':
            return self.fmt(self.F['parsebool'], args) if t == 'String' else args[0]
        if key in ('floor', 'ceiling', 'round') and t == 'Integer':
            return args[0]
        if key == 'sgn':
            return self.fmt(self.F['sgn'], args)
        if key not in self.F:
            self.reject('built-in function ' + key)
        if key == 'random':
            self.uses.add('random')
        return self.fmt(self.F[key], args)

    def fmt(self, tpl, args):
        for i, a in enumerate(args):
            if re.match(r'^[\w.$@]+$', a) or re.match(r'^[\w.$@]+\([^()]*\)$', a):
                tpl = re.sub(r"(?<![\w\]'\s])\(\{%d\}\)" % i, '{%d}' % i, tpl)
        return tpl.format(*args)

    # ------------------------------------------------------------ coercion
    implicit_widen = True

    def coerce(self, code, src, dst):
        if dst == 'Real' and src == 'Integer':
            if re.match(r'^\d+$', code):
                return code + '.0'
            return code if self.implicit_widen else self.int2real(code, wrap=True)
        if dst == 'Integer' and src == 'Real':
            return self.real2int(code)
        return code

    # ------------------------------------------------------------ statements
    def assign(self, target, code):
        self.stmt(target + ' = ' + code)

    def n_Assign(self, n):
        ta = parse_expr(n['variable'])
        self.check_target(ta)
        ea = parse_expr(n['expression'])
        code = self.coerce(self.ex(ea), self.ty(ea), self.ty(ta))
        self.assign(self.ex(ta), code)

    def check_target(self, ta):
        name = ta.id if isinstance(ta, ast.Name) else ta.value.id
        if name not in self.vt:
            raise FlowError('Declare variable before use: ' + name)

    dead_init = False

    @staticmethod
    def touches(n, name):
        return re.search(r'\b' + re.escape(name) + r'\b', json.dumps(n)) is not None

    def init_is_dead(self, name, rest):
        for s in rest:
            if s['kind'] == 'Assign':
                ta = parse_expr(s['variable'])
                if isinstance(ta, ast.Name) and ta.id == name:
                    return not self.touches(s['expression'], name)
            if s['kind'] == 'Input':
                ta = parse_expr(s['variable'])
                if isinstance(ta, ast.Name) and ta.id == name:
                    return True
            if self.touches(s, name):
                return False
        return False

    def n_Declare(self, n, skip=()):
        for name in names(n['name']):
            t = n['type']
            if name in skip:
                self.vt[name] = (t, False)
                continue
            if n['array']:
                self.vt[name] = (t, True)
                self.decl_array(name, t, self.expr(n['size']))
            else:
                self.vt[name] = (t, False)
                if self.nest > 0 and self.hoist:
                    self.assign(self.ref(name), self.init_value(t))
                else:
                    self.decl_scalar(name, t)

    def decl_scalar(self, name, t):
        self.stmt(self.tname(t) + ' ' + self.ref(name) + ' = ' + self.init_value(t))

    def decl_array(self, name, t, size):
        self.reject('arrays')

    def n_Input(self, n):
        ta = parse_expr(n['variable'])
        self.check_target(ta)
        name = ta.id if isinstance(ta, ast.Name) else ta.value.id
        self.uses.add('input')
        self.read(self.ex(ta), self.ty(ta), name)

    def n_Output(self, n):
        a = parse_expr(n['expression'])
        t = self.ty(a)
        code = self.ex(a) if t == 'String' else self.tostr(self.ex(a), t) if self.out_needs_string(t) else self.ex(a)
        self.write(code, n['newline'], t)

    def out_needs_string(self, t):
        return t == 'Boolean'

    def indented(self, block):
        self.depth += 1
        self.nest += 1
        if not block:
            self.empty_body()
        self.block(block)
        self.nest -= 1
        self.depth -= 1

    def empty_body(self):
        pass

    def n_If(self, n):
        self.if_open(self.cond(n['expression']))
        self.indented(n['true'])
        f = n['false']
        while f:
            if self.has_elif and len(f) == 1 and f[0]['kind'] == 'If':
                n = f[0]
                self.elif_open(self.cond(n['expression']))
                self.indented(n['true'])
                f = n['false']
            else:
                self.else_open()
                self.indented(f)
                break
        self.if_close()

    def n_While(self, n):
        self.while_open(self.cond(n['expression']))
        self.indented(n['body'])
        self.while_close()

    def n_Do(self, n):
        self.do_open()
        self.indented(n['body'])
        self.do_close(self.cond(n['expression']))

    def n_For(self, n):
        v = n['variable']
        if v not in self.vt or self.vt[v][0] not in ('Integer', 'Real') or self.vt[v][1]:
            raise FlowError('Declare a numeric loop variable before For: ' + v)
        sa, ea, pa = parse_expr(n['start']), parse_expr(n['end']), parse_expr(n['step'])
        dec = n['direction'] == 'dec'
        self.for_loop(v, sa, ea, pa, dec, n['body'])

    def for_loop(self, v, sa, ea, pa, dec, body):
        """Default: lower to assignment + while (inclusive bounds)."""
        self.assign(self.ref(v), self.coerce(self.ex(sa), self.ty(sa), self.vt[v][0]))
        sym = '>=' if dec else '<='
        c = self.cmp(sym, ast.Name(id=v), ea, self.vt[v][0], self.ty(ea))
        self.while_open(strip_outer(c[0]) if not self.minparen else c[0])
        self.depth += 1
        self.nest += 1
        stepper = lambda: self.assign(self.ref(v), self.step_expr(v, pa, dec))
        if self.loops:
            self.loops[-1]['step'] = stepper
        self.block(body)
        stepper()
        self.nest -= 1
        self.depth -= 1
        self.while_close()

    def step_expr(self, v, pa, dec):
        t = self.vt[v][0]
        r = self.binary(ast.BinOp(left=ast.Name(id=v), op=ast.Sub() if dec else ast.Add(), right=pa))
        return self.coerce(strip_outer(r[0]) if not self.minparen else r[0], self.ty(ast.BinOp(left=ast.Name(id=v), op=ast.Add(), right=pa)), t)

    def n_Call(self, n):
        a = parse_expr(n['expression'])
        self.stmt(self.ex(a))

    def n_Return(self, n):
        if self.cur['name'] == 'Main':
            return self.main_return()
        if not n['expression'].strip():
            return self.s_return(None)
        a = parse_expr(n['expression'])
        code = self.ex(a)
        if self.cur['type'] != 'None':
            code = self.coerce(code, self.ty(a), self.cur['type'])
        self.s_return(code)

    def main_return(self):
        self.stmt('return')

    def s_return(self, code):
        self.stmt('return' + (' ' + code if code else ''))

    def n_Comment(self, n):
        self.comment_lines(n['text'])

    def dispatch(self, n):
        looped = n['kind'] in ('While', 'Do', 'For')
        if looped:
            self.loops.append({})
        try:
            getattr(self, 'n_' + n['kind'])(n)
        finally:
            if looped:
                self.loops.pop()

    def block(self, block):
        for i, n in enumerate(block):
            if self.dead_init and n['kind'] == 'Declare' and not n['array'] and self.nest == 0:
                skip = set(nm for nm in names(n['name']) if self.init_is_dead(nm, block[i + 1:]))
                self.n_Declare(n, skip)
            else:
                self.dispatch(n)

    def n_Break(self, n):
        self.stmt(self.BREAK)

    def n_Continue(self, n):
        info = self.loops[-1] if self.loops else {}
        if info.get('step'):
            info['step']()
        if info.get('check'):
            info['check']()
        self.stmt(self.CONTINUE)

    # ------------------------------------------------------------ structure
    def generate(self, doc):
        if doc.get("python"):
            validate(doc)
            if self.lang == "Python":
                return generate_python_document(doc)
            doc = _portable_python_document(doc)
        validate(doc)
        self.funcs = doc['functions']
        self.ftypes = dict((f['name'], f) for f in self.funcs)
        self.check(doc)
        self.build()
        head = self.header()
        text = '\n'.join(head + self.lines).rstrip('\n') + '\n'
        return text

    def check(self, doc):
        pass

    def header(self):
        return []

    def build(self):
        self.pre_build()
        self.emit_dictionary_error_helper()
        for f in self.funcs[1:]:
            self.function(f)
            self.emit()
        self.main_open()
        self.body(self.funcs[0])
        self.main_close()

    def emit_dictionary_error_helper(self):
        """A failed fixed-map search must stop before the array access."""
        needed = False
        for f in self.funcs:
            for n in walk(f['body']):
                if n['kind'] != 'Call':
                    continue
                call = parse_expr(n['expression'])
                if isinstance(call, ast.Call) and call.func.id.lower() == 'flowdictionaryerror':
                    needed = True
                    break
        if not needed or self.lang in ('Python', 'MATLAB', 'Pseudocode'):
            return
        helpers = {
            'C': ['static void flowDictionaryError(const char *message) {',
                  '    fprintf(stderr, "%s\\n", message);', '    exit(EXIT_FAILURE);', '}'],
            'C++': ['void flowDictionaryError(const std::string& message) {',
                    '    std::cerr << message << std::endl;', '    std::exit(EXIT_FAILURE);', '}'],
            'JavaScript': ['function flowDictionaryError(message) { throw new Error(message); }'],
            'TypeScript': ['function flowDictionaryError(message: string): never { throw new Error(message); }'],
            'Java': ['static void flowDictionaryError(String message) { throw new IllegalArgumentException(message); }'],
            'C#': ['static void flowDictionaryError(string message) { throw new ArgumentException(message); }'],
            'PHP': ['function flowDictionaryError($message) { throw new RuntimeException($message); }'],
            'Go': ['func flowDictionaryError(message string) { panic(message) }'],
            'Kotlin': ['fun flowDictionaryError(message: String): Nothing { error(message) }'],
            'Swift': ['func flowDictionaryError(_ message: String) -> Never { fatalError(message) }'],
            'R': ['flowDictionaryError <- function(message) { stop(message, call. = FALSE) }'],
        }
        self.emit(self.cm + ' ' + HELP_BEGIN)
        for line in helpers[self.lang]:
            self.emit(line)
        self.emit(self.cm + ' ' + HELP_END)
        self.emit()

    def pre_build(self):
        pass

    def main_open(self):
        pass

    def main_close(self):
        pass

    def func_open(self, f):
        raise NotImplementedError

    def func_close(self, f):
        pass

    def function(self, f):
        self.func_open(f)
        self.depth += 1
        self.body(f, is_main=False)
        self.depth -= 1
        self.func_close(f)

    def begin_scope(self, f):
        self.vt = dict((p['name'], (p['type'], p['array'])) for p in f['parameters'])
        self.nest = 0
        self.hoisted = {}
        if self.hoist:
            for n in walk(f['body']):
                if n['kind'] == 'Declare' and not n['array']:
                    pass
            self.hoist_pass(f['body'], 0)

    def hoist_pass(self, block, level):
        for n in block:
            if n['kind'] == 'Declare' and level > 0 and not n['array']:
                for name in names(n['name']):
                    self.hoisted[name] = n['type']
            for b in BRANCHES.get(n['kind'], []):
                self.hoist_pass(n[b], level + 1)

    def body(self, f, is_main=True):
        self.cur = f
        self.begin_scope(f)
        for name in sorted(self.hoisted):
            t = self.hoisted[name]
            self.vt[name] = (t, False)
            self.decl_scalar(name, t)
        self.block(f['body'])
        if f['name'] != 'Main' and f['type'] != 'None' and f['variable']:
            self.s_return(self.ref(f['variable']))

    # ---- hooks that every language provides
    def if_open(self, c): raise NotImplementedError
    def elif_open(self, c): raise NotImplementedError
    def else_open(self): raise NotImplementedError
    def if_close(self): raise NotImplementedError
    def while_open(self, c): raise NotImplementedError
    def while_close(self): raise NotImplementedError
    def do_open(self): raise NotImplementedError
    def do_close(self, c): raise NotImplementedError
    def read(self, target, t, name): raise NotImplementedError
    def write(self, code, newline, t): raise NotImplementedError


def ea_is_simple(a):
    return isinstance(a, (ast.Name,)) or literal(a)[0]


class BraceGen(Gen):
    """Languages that use { } blocks."""
    has_elif = True

    def if_open(self, c):
        self.emit('if (' + c + ') {')

    def elif_open(self, c):
        self.emit('} else if (' + c + ') {')

    def else_open(self):
        self.emit('} else {')

    def if_close(self):
        self.emit('}')

    def while_open(self, c):
        self.emit('while (' + c + ') {')

    def while_close(self):
        self.emit('}')

    def do_open(self):
        self.emit('do {')

    def do_close(self, c):
        self.emit('} while (' + c + ')' + self.semi)

    def for_loop(self, v, sa, ea, pa, dec, body):
        if not self.native_for or self.vt[v][1]:
            return Gen.for_loop(self, v, sa, ea, pa, dec, body)
        t = self.vt[v][0]
        init = self.ref(v) + ' = ' + self.coerce(self.ex(sa), self.ty(sa), t)
        c = self.cmp('>=' if dec else '<=', ast.Name(id=v), ea, t, self.ty(ea))[0]
        step = self.step_expr(v, pa, dec)
        self.emit('for (' + init + '; ' + strip_outer(c) + '; ' + self.ref(v) + ' = ' + step + ') {')
        self.indented(body)
        self.emit('}')

    def func_close(self, f):
        self.emit('}')


def str_runs(s):
    """Split a string into printable runs and control characters."""
    runs, cur = [], ''
    for ch in s:
        if ord(ch) < 32 or ord(ch) == 127:
            if cur:
                runs.append(('t', cur))
                cur = ''
            runs.append(('c', ord(ch)))
        else:
            cur += ch
    if cur:
        runs.append(('t', cur))
    return runs





def idx_literal(a):
    ok, v = literal(index_ast(a))
    return v if ok and isinstance(v, int) and not isinstance(v, bool) else None


# ------------------------------------------------------------------ Python

@register('Python')
class PyGen(Gen):
    ext = '.py'
    cm = '#'
    semi = ''
    hoist = False
    has_elif = True
    dead_init = True
    int_div_trap = False
    implicit_widen = False
    POWSYM = ' ** '
    TRUE, FALSE = 'True', 'False'
    AND, OR, NOT = ' and ', ' or ', 'not '
    T = {'Integer': 'int', 'Real': 'float', 'String': 'str', 'Boolean': 'bool', 'None': 'None'}
    F = {'abs': 'abs({0})', 'sqrt': 'math.sqrt({0})', 'sin': 'math.sin({0})', 'cos': 'math.cos({0})',
         'tan': 'math.tan({0})', 'arcsin': 'math.asin({0})', 'arccos': 'math.acos({0})',
         'arctan': 'math.atan({0})', 'log': 'math.log({0})', 'log10': 'math.log10({0})',
         'floor': 'math.floor({0})', 'ceiling': 'math.ceil({0})', 'round': 'round({0})',
         'trunc': 'int({0})', 'parseint': 'int({0})', 'parsereal': 'float({0})',
         'parsebool': '(({0}).strip().lower() in ("true", "1"))', 'len': 'len({0})', 'alen': 'len({0})',
         'char': '({0})[{1}]', 'random': 'random.randrange({0})', 'min': 'min({0}, {1})',
         'max': 'max({0}, {1})', 'sgn': '((({0}) > 0) - (({0}) < 0))',
         'toupper': '({0}).upper()', 'tolower': '({0}).lower()', 'trim': '({0}).strip()', 'contains': '(({1}) in ({0}))'}

    def main_open(self):
        if not self.funcs[0]['body']:
            self.emit('# Main is empty. Add shapes or import code to build a program.')
            self.emit('pass')

    def header(self):
        text = '\n'.join(self.lines)
        mods = [m for m in ('math', 'random') if re.search(r'\b' + m + r'\.', text)]
        return ['import ' + m for m in mods] + ([''] if mods else [])

    def int2real(self, code, wrap=False):
        return 'float(' + code + ')'

    def real2int(self, code):
        return 'int(' + code + ')'

    def tostr(self, code, t):
        if t == 'String':
            return code
        return 'str(' + code + ').lower()' if t == 'Boolean' else 'str(' + code + ')'

    def decl_scalar(self, name, t):
        self.emit(name + ' = ' + self.init_value(t))

    def decl_array(self, name, t, size):
        self.emit(name + ' = [' + self.init_value(t) + '] * ' + self.wrap(size, 0, 7))

    def assign(self, target, code):
        self.emit(target + ' = ' + code)

    def read(self, target, t, name):
        src = 'input()'
        conv = {'Integer': 'int(input())', 'Real': 'float(input())', 'String': src,
                'Boolean': 'input().strip().lower() in ("true", "1")'}[t]
        self.emit(target + ' = ' + conv)

    def write(self, code, newline, t):
        self.emit('print(' + code + ('' if newline else ', end=""') + ')')

    def if_open(self, c):
        self.emit('if ' + c + ':')

    def elif_open(self, c):
        self.emit('elif ' + c + ':')

    def else_open(self):
        self.emit('else:')

    def if_close(self):
        pass

    def while_open(self, c):
        self.emit('while ' + c + ':')

    def while_close(self):
        pass

    def empty_body(self):
        self.emit('pass')

    def n_Do(self, n):
        self.emit('while True:')
        self.depth += 1
        self.nest += 1
        neg = ast.UnaryOp(op=ast.Not(), operand=parse_expr(n['expression']))

        def check():
            self.emit('if ' + self.ex(neg) + ':')
            self.emit('    break')
        self.loops[-1]['check'] = check
        self.block(n['body'])
        check()
        self.nest -= 1
        self.depth -= 1

    def main_return(self):
        self.emit('raise SystemExit')

    def s_return(self, code):
        self.emit('return' + (' ' + code if code else ''))

    def for_loop(self, v, sa, ea, pa, dec, body):
        ints = all(self.ty(x) == 'Integer' for x in (sa, ea, pa)) and self.vt[v][0] == 'Integer'
        if not ints:
            return Gen.for_loop(self, v, sa, ea, pa, dec, body)
        ok, sv = literal(pa)
        stepc = self.ex(pa)
        start = self.ex(sa)
        ok0, s0 = literal(sa)
        if dec:
            stop = self.shift(ea, -1)
            step = '-' + (stepc if ok else self.sub(pa, 8))
        else:
            stop = self.shift(ea, 1)
            step = stepc
        args = []
        if not (ok0 and s0 == 0 and not dec and ok and sv == 1):
            args.append(start)
        args.append(stop)
        if dec or not (ok and sv == 1):
            if not args[:-1]:
                args.insert(0, start)
            args.append(step)
        self.emit('for ' + v + ' in range(' + ', '.join(args) + '):')
        self.indented(body)

    def shift(self, a, k):
        ok, v = literal(a)
        if ok and isinstance(v, int):
            return str(v + k)
        if isinstance(a, ast.BinOp) and isinstance(a.op, (ast.Add, ast.Sub)):
            ok2, v2 = literal(a.right)
            if ok2 and isinstance(v2, int) and not isinstance(v2, bool):
                delta = v2 if isinstance(a.op, ast.Add) else -v2
                delta += k
                base = self.sub(a.left, 6)
                if delta == 0:
                    return strip_outer(base) if not self.minparen else base
                return base + (' + ' if delta > 0 else ' - ') + str(abs(delta))
        return self.sub(a, 6) + (' + ' if k > 0 else ' - ') + str(abs(k))

    def func_open(self, f):
        ps = []
        for p in f['parameters']:
            ps.append(p['name'] + ': ' + ('list' if p['array'] else self.T[p['type']]))
        ret = '' if f['type'] == 'None' else ' -> ' + self.T[f['type']]
        self.emit('def ' + f['name'] + '(' + ', '.join(ps) + ')' + ret + ':')

    def function(self, f):
        self.func_open(f)
        self.depth += 1
        n0 = len(self.lines)
        self.body(f, is_main=False)
        if len(self.lines) == n0:
            self.emit('pass')
        self.depth -= 1




@register('JavaScript')
class JsGen(BraceGen):
    ext = '.js'
    int_div_trap = False
    POWSYM = ' ** '
    typed = False
    CMP = {'==': '===', '!=': '!==', '<': '<', '<=': '<=', '>': '>', '>=': '>='}
    T = {'Integer': 'number', 'Real': 'number', 'String': 'string', 'Boolean': 'boolean', 'None': 'void'}
    F = {'abs': 'Math.abs({0})', 'sqrt': 'Math.sqrt({0})', 'sin': 'Math.sin({0})', 'cos': 'Math.cos({0})',
         'tan': 'Math.tan({0})', 'arcsin': 'Math.asin({0})', 'arccos': 'Math.acos({0})',
         'arctan': 'Math.atan({0})', 'log': 'Math.log({0})', 'log10': '(Math.log({0}) / Math.LN10)',
         'floor': 'Math.floor({0})', 'ceiling': 'Math.ceil({0})', 'round': 'Math.round({0})',
         'trunc': '_trunc({0})', 'parseint': 'parseInt({0}, 10)', 'parsereal': 'parseFloat({0})',
         'parsebool': '(/^(true|1)$/i.test(({0}).trim()))', 'len': '({0}).length', 'alen': '{0}.length',
         'char': '({0}).charAt({1})', 'random': 'Math.floor(Math.random() * {0})',
         'min': 'Math.min({0}, {1})', 'max': 'Math.max({0}, {1})', 'sgn': '_sgn({0})', 'tostr': 'String({0})',
         'toupper': '({0}).toUpperCase()', 'tolower': '({0}).toLowerCase()', 'trim': '({0}).trim()', 'contains': '(({0}).indexOf({1}) >= 0)'}

    def int2real(self, code, wrap=False):
        return code

    def tostr(self, code, t):
        return code if t == 'String' else 'String(' + code + ')'

    def ann(self, t, arr=False):
        return (': ' + self.T[t] + ('[]' if arr else '')) if self.typed else ''

    def decl_scalar(self, name, t):
        self.stmt('let ' + name + self.ann(t) + ' = ' + self.init_value(t))

    def decl_array(self, name, t, size):
        self.stmt('let ' + name + self.ann(t, True) + ' = []')
        self.emit('for (let _k = 0; _k < ' + self.wrap(size, 0, 5) + '; _k++) {')
        self.emit('    ' + name + '.push(' + self.init_value(t) + ');')
        self.emit('}')

    def read(self, target, t, name):
        src = '_readLine()'
        conv = {'Integer': 'parseInt(' + src + ', 10)', 'Real': 'parseFloat(' + src + ')', 'String': src,
                'Boolean': '/^(true|1)$/i.test(' + src + '.trim())'}[t]
        self.stmt(target + ' = ' + conv)

    def write(self, code, newline, t):
        if newline:
            self.stmt('console.log(' + code + ')')
        else:
            self.stmt('process.stdout.write(String(' + code + '))')

    def real2int(self, code):
        return '_trunc(' + code + ')'

    def func_open(self, f):
        ps = ', '.join(p['name'] + self.ann(p['type'], p['array']) for p in f['parameters'])
        ret = (': ' + self.T[f['type']]) if self.typed else ''
        self.emit('function ' + f['name'] + '(' + ps + ')' + ret + ' {')

    def s_return(self, code):
        self.stmt('return' + (' ' + code if code else ''))

    def header(self):
        text = '\n'.join(self.lines)
        out = []
        if self.typed:
            if 'process.' in text:
                out.append('declare var process: any;')
            if 'input' in self.uses:
                out.append('declare function require(name: string): any;')
        if 'input' in self.uses:
            if self.typed:
                out += ["const _lines: string[] = require('fs').readFileSync(0, 'utf8').split(/\\r?\\n/);",
                        'let _pos: number = 0;',
                        "function _readLine(): string { return _pos < _lines.length ? _lines[_pos++] : ''; }"]
            else:
                out += ["const _lines = require('fs').readFileSync(0, 'utf8').split(/\\r?\\n/);",
                        'let _pos = 0;',
                        "function _readLine() { return _pos < _lines.length ? _lines[_pos++] : ''; }"]
        t = ': number' if self.typed else ''
        if '_trunc(' in text:
            out.append('function _trunc(x' + t + ')' + t + ' { return x < 0 ? Math.ceil(x) : Math.floor(x); }')
        if '_sgn(' in text:
            out.append('function _sgn(x' + t + ')' + t + ' { return x > 0 ? 1 : (x < 0 ? -1 : 0); }')
        return (['// ' + HELP_BEGIN] + out + ['// ' + HELP_END, '']) if out else []

    def main_return(self):
        self.stmt('process.exit(0)')




@register('TypeScript')
class TsGen(JsGen):
    ext = '.ts'
    typed = True

    # the main program lives in a function scope so names such as `name`
    # cannot clash with the DOM globals that TypeScript knows about
    def main_open(self):
        self.emit('(function () {')
        self.depth += 1

    def main_close(self):
        self.depth -= 1
        self.emit('})();')

    def main_return(self):
        self.stmt('return')



@register('PHP')
class PhpGen(BraceGen):
    INTDIV = 'intdiv({0}, {1})'
    ext = '.php'
    sigil = '$'
    hoist = False
    dead_init = False
    int_div_trap = False
    POWSYM = ' ** '
    CONCAT = ' . '
    F = {'abs': 'abs({0})', 'sqrt': 'sqrt({0})', 'sin': 'sin({0})', 'cos': 'cos({0})', 'tan': 'tan({0})',
         'arcsin': 'asin({0})', 'arccos': 'acos({0})', 'arctan': 'atan({0})', 'log': 'log({0})',
         'log10': 'log10({0})', 'floor': '(int)floor({0})', 'ceiling': '(int)ceil({0})',
         'round': '(int)round({0})', 'trunc': '(int)({0})', 'parseint': 'intval({0})',
         'parsereal': 'floatval({0})', 'parsebool': '(strtolower(trim({0})) === "true")',
         'len': 'strlen({0})', 'alen': 'count({0})', 'char': 'substr({0}, {1}, 1)',
         'random': 'mt_rand(0, {0} - 1)', 'min': 'min({0}, {1})', 'max': 'max({0}, {1})',
         'sgn': '(({0}) <=> 0)',
         'toupper': 'strtoupper({0})', 'tolower': 'strtolower({0})', 'trim': 'trim({0})', 'contains': '(strpos({0}, {1}) !== false)'}

    def int2real(self, code, wrap=False):
        return '(float)(' + code + ')'

    def tostr(self, code, t):
        if t == 'String':
            return code
        return '(' + code + ' ? "true" : "false")' if t == 'Boolean' else 'strval(' + code + ')'

    def strlit(self, s):
        if any(ord(c) < 32 or c == '\x7f' for c in s):
            return c_string(s, ctl=lambda o: '\\%03o' % o, dollar=True)
        return "'" + s.replace('\\', '\\\\').replace("'", "\\'") + "'"

    def cmp(self, sym, left, right, lt, rt):
        if 'String' in (lt, rt):
            l, r = self.ex(left), self.ex(right)
            if sym == '==':
                return '(' + l + ' === ' + r + ')', 100
            if sym == '!=':
                return '(' + l + ' !== ' + r + ')', 100
            return '(strcmp(' + l + ', ' + r + ') ' + sym + ' 0)', 100
        return Gen.cmp(self, sym, left, right, lt, rt)

    def header(self):
        return ['<?php']

    def decl_scalar(self, name, t):
        self.stmt(self.ref(name) + ' = ' + self.init_value(t))

    def decl_array(self, name, t, size):
        self.stmt(self.ref(name) + ' = array_fill(0, ' + size + ', ' + self.init_value(t) + ')')

    def elif_open(self, c):
        self.emit('} elseif (' + c + ') {')

    def read(self, target, t, name):
        src = 'trim(fgets(STDIN))'
        conv = {'Integer': 'intval(' + src + ')', 'Real': 'floatval(' + src + ')', 'String': src,
                'Boolean': '(strtolower(' + src + ') === "true" || ' + src + ' === "1")'}[t]
        if t == 'Boolean':
            conv = 'in_array(strtolower(' + src + '), array("true", "1"))'
        self.stmt(target + ' = ' + conv)

    def write(self, code, newline, t):
        self.stmt('echo ' + code + (', "\\n"' if newline else ''))

    def func_open(self, f):
        self.emit('function ' + f['name'] + '(' + ', '.join('$' + p['name'] for p in f['parameters']) + ') {')

    def main_return(self):
        self.stmt('exit')


    def index(self, base, idx, a):
        return base + '[' + idx + ']'





# --------------------------------------------------------------------- C++

@register('C++')
class CppGen(BraceGen):
    INTDIV = '({0} / {1})'
    ext = '.cpp'
    T = {'Integer': 'long long', 'Real': 'double', 'String': 'std::string', 'Boolean': 'bool', 'None': 'void'}
    F = {'abs': 'std::abs({0})', 'sqrt': 'std::sqrt({0})', 'sin': 'std::sin({0})', 'cos': 'std::cos({0})',
         'tan': 'std::tan({0})', 'arcsin': 'std::asin({0})', 'arccos': 'std::acos({0})',
         'arctan': 'std::atan({0})', 'log': 'std::log({0})', 'log10': 'std::log10({0})',
         'floor': 'static_cast<long long>(std::floor({0}))', 'ceiling': 'static_cast<long long>(std::ceil({0}))',
         'round': 'std::llround({0})', 'trunc': 'static_cast<long long>({0})', 'parseint': 'std::stoll({0})',
         'parsereal': 'std::stod({0})', 'parsebool': 'flowBool({0})', 'len': 'static_cast<long long>(({0}).size())',
         'alen': 'static_cast<long long>({0}.size())', 'char': 'std::string(1, ({0})[{1}])',
         'random': 'flowRandom({0})', 'sgn': '((({0}) > 0) - (({0}) < 0))',
         'toupper': 'flowUpper({0})', 'tolower': 'flowLower({0})', 'trim': 'flowTrim({0})', 'contains': '(std::string({0}).find({1}) != std::string::npos)'}

    def int2real(self, code, wrap=False):
        return '(double)(' + code + ')'

    def real2int(self, code):
        return 'static_cast<long long>(' + code + ')'

    def tostr(self, code, t):
        return code if t == 'String' else 'flowString(' + code + ')'

    def strlit_concat(self, code):
        return 'std::string(' + code + ')' if code.startswith('"') else code

    def pow(self, l, r, lt, rt):
        c = 'std::pow(' + l + ', ' + r + ')'
        return 'static_cast<long long>(std::llround(' + c + '))' if (lt, rt) == ('Integer', 'Integer') else c

    def mod(self, left, right, lt, rt):
        if 'Real' in (lt, rt):
            return 'std::fmod(' + self.ex(left) + ', ' + self.ex(right) + ')', 100
        return Gen.mod(self, left, right, lt, rt)

    def builtin_code(self, key, args, types):
        if key in ('min', 'max'):
            t = 'long long' if types == ['Integer', 'Integer'] else 'double'
            return 'std::' + key + '<' + t + '>(' + args[0] + ', ' + args[1] + ')'
        return Gen.builtin_code(self, key, args, types)

    def index(self, base, idx, a):
        if self.ty(a.value) == 'String' and not self.is_array(a.value):
            return 'std::string(1, ' + base + '[' + idx + '])'
        return base + '[' + idx + ']'

    def array_len(self, name, code):
        return 'static_cast<long long>(' + code + '.size())'

    def decl_array(self, name, t, size):
        self.stmt('std::vector<' + self.T[t] + '> ' + name + '(' + size + ', ' + self.init_value(t) + ')')

    def read(self, target, t, name):
        src = 'flowReadLine()'
        conv = {'Integer': 'std::stoll(' + src + ')', 'Real': 'std::stod(' + src + ')', 'String': src,
                'Boolean': 'flowBool(' + src + ')'}[t]
        self.stmt(target + ' = ' + conv)

    def write(self, code, newline, t):
        self.stmt('std::cout << ' + code + (' << std::endl' if newline else ''))

    def out_needs_string(self, t):
        return t == 'Boolean'

    def sig(self, f):
        ps = []
        for p in f['parameters']:
            ps.append(('std::vector<' + self.T[p['type']] + '>& ' if p['array'] else self.T[p['type']] + ' ') + p['name'])
        return self.T[f['type']] + ' ' + f['name'] + '(' + ', '.join(ps) + ')'

    def pre_build(self):
        for f in self.funcs[1:]:
            self.emit(self.sig(f) + ';')
        if len(self.funcs) > 1:
            self.emit()

    def func_open(self, f):
        self.emit(self.sig(f) + ' {')

    def main_open(self):
        self.emit('int main() {')
        self.depth += 1
        self.emit('std::cout << std::setprecision(15);')

    def main_close(self):
        self.emit('return 0;')
        self.depth -= 1
        self.emit('}')

    def main_return(self):
        self.stmt('return 0')


    def header(self):
        text = '\n'.join(self.lines)
        out = ['#include <iostream>', '#include <iomanip>', '#include <string>', '#include <vector>',
               '#include <cmath>', '#include <cstdlib>', '#include <cctype>', '#include <sstream>', '#include <algorithm>']
        if 'flowRandom' in text:
            out.append('#include <random>')
        out += ['', '// ' + HELP_BEGIN, 'template <typename T> std::string flowString(const T& v) {',
                '    std::ostringstream s; s << std::setprecision(15) << v; return s.str();', '}',
                'inline std::string flowString(bool v) { return v ? "true" : "false"; }']
        if 'flowReadLine' in text or 'flowBool' in text:
            out += ['inline std::string flowReadLine() { std::string s; std::getline(std::cin, s); return s; }',
                    'inline bool flowBool(const std::string& s) { return s == "true" || s == "True" || s == "1"; }']
        if 'flowUpper' in text or 'flowLower' in text or 'flowTrim' in text:
            out += ['inline std::string flowUpper(std::string s) { for (auto& c : s) c = (char)std::toupper((unsigned char)c); return s; }',
                    'inline std::string flowLower(std::string s) { for (auto& c : s) c = (char)std::tolower((unsigned char)c); return s; }',
                    'inline std::string flowTrim(const std::string& s) {',
                    '    size_t a = s.find_first_not_of(" \\t\\r\\n"); if (a == std::string::npos) return "";',
                    '    return s.substr(a, s.find_last_not_of(" \\t\\r\\n") - a + 1);', '}']
        if 'flowRandom' in text:
            out += ['inline long long flowRandom(long long n) {',
                    '    static std::mt19937_64 g{std::random_device{}()};',
                    '    return static_cast<long long>(g() % static_cast<unsigned long long>(n));', '}']
        return out + ['// ' + HELP_END, '']



@register('Java')
class JavaGen(BraceGen):
    INTDIV = '({0} / {1})'
    ext = '.java'
    T = {'Integer': 'long', 'Real': 'double', 'String': 'String', 'Boolean': 'boolean', 'None': 'void'}
    F = {'abs': 'Math.abs({0})', 'sqrt': 'Math.sqrt({0})', 'sin': 'Math.sin({0})', 'cos': 'Math.cos({0})',
         'tan': 'Math.tan({0})', 'arcsin': 'Math.asin({0})', 'arccos': 'Math.acos({0})',
         'arctan': 'Math.atan({0})', 'log': 'Math.log({0})', 'log10': 'Math.log10({0})',
         'floor': '(long) Math.floor({0})', 'ceiling': '(long) Math.ceil({0})', 'round': 'Math.round({0})',
         'trunc': '(long) ({0})', 'parseint': 'Long.parseLong(({0}).trim())',
         'parsereal': 'Double.parseDouble(({0}).trim())', 'parsebool': 'Boolean.parseBoolean(({0}).trim())',
         'len': '(long) ({0}).length()', 'alen': '(long) {0}.length',
         'char': 'String.valueOf(({0}).charAt((int) ({1})))', 'random': '(long) (Math.random() * {0})',
         'min': 'Math.min({0}, {1})', 'max': 'Math.max({0}, {1})', 'sgn': '(long) Math.signum((double) ({0}))',
         'toupper': '({0}).toUpperCase()', 'tolower': '({0}).toLowerCase()', 'trim': '({0}).trim()', 'contains': '({0}).contains({1})'}

    def int2real(self, code, wrap=False):
        return '(double) (' + code + ')'

    def real2int(self, code):
        return '(long) (' + code + ')'

    def tostr(self, code, t):
        return code if t == 'String' else 'String.valueOf(' + code + ')'

    def pow(self, l, r, lt, rt):
        c = 'Math.pow(' + l + ', ' + r + ')'
        return '(long) ' + c if (lt, rt) == ('Integer', 'Integer') else c

    def index(self, base, idx, a):
        if self.ty(a.value) == 'String' and not self.is_array(a.value):
            return 'String.valueOf(' + base + '.charAt((int) (' + idx + ')))'
        return base + '[' + (idx if idx_literal(a) is not None else '(int) (' + idx + ')') + ']'

    def cmp(self, sym, left, right, lt, rt):
        if 'String' in (lt, rt):
            l, r = self.sub(left, 100), self.sub(right, 100)
            if sym == '==':
                return l + '.equals(' + r + ')', 100
            if sym == '!=':
                return '!' + l + '.equals(' + r + ')', 100
            return '(' + l + '.compareTo(' + r + ') ' + sym + ' 0)', 100
        return Gen.cmp(self, sym, left, right, lt, rt)

    def decl_array(self, name, t, size):
        self.stmt(self.T[t] + '[] ' + name + ' = new ' + self.T[t] + '[(int) (' + size + ')]')
        if t == 'String':
            self.stmt('java.util.Arrays.fill(' + name + ', "")')

    def read(self, target, t, name):
        src = '_readLine()'
        conv = {'Integer': 'Long.parseLong(' + src + '.trim())', 'Real': 'Double.parseDouble(' + src + '.trim())',
                'String': src, 'Boolean': 'Boolean.parseBoolean(' + src + '.trim())'}[t]
        self.stmt(target + ' = ' + conv)

    def write(self, code, newline, t):
        self.stmt('System.out.' + ('println' if newline else 'print') + '(' + code + ')')

    def sig(self, f):
        ps = ', '.join(self.T[p['type']] + ('[]' if p['array'] else '') + ' ' + p['name'] for p in f['parameters'])
        return 'static ' + self.T[f['type']] + ' ' + f['name'] + '(' + ps + ')'

    def func_open(self, f):
        self.emit(self.sig(f) + ' {')

    def main_open(self):
        self.emit('public static void main(String[] args) {')
        self.depth += 1

    def main_close(self):
        self.depth -= 1
        self.emit('}')

    def build(self):
        self.emit('public class Main {')
        self.depth += 1
        if 'input' in self.uses_precheck():
            self.emit('// ' + HELP_BEGIN)
            self.emit('static java.io.BufferedReader _in = new java.io.BufferedReader(new java.io.InputStreamReader(System.in));')
            self.emit('static String _readLine() {')
            self.emit('    try { String s = _in.readLine(); return s == null ? "" : s; } catch (java.io.IOException e) { return ""; }')
            self.emit('}')
            self.emit('// ' + HELP_END)
            self.emit()
        Gen.build(self)
        self.depth -= 1
        self.emit('}')

    def uses_precheck(self):
        s = set()
        for f in self.funcs:
            for n in walk(f['body']):
                if n['kind'] == 'Input':
                    s.add('input')
        return s

    def main_return(self):
        self.stmt('return')




@register('C#')
class CSharpGen(BraceGen):
    INTDIV = '({0} / {1})'
    ext = '.cs'
    T = {'Integer': 'long', 'Real': 'double', 'String': 'string', 'Boolean': 'bool', 'None': 'void'}
    F = {'abs': 'Math.Abs({0})', 'sqrt': 'Math.Sqrt({0})', 'sin': 'Math.Sin({0})', 'cos': 'Math.Cos({0})',
         'tan': 'Math.Tan({0})', 'arcsin': 'Math.Asin({0})', 'arccos': 'Math.Acos({0})',
         'arctan': 'Math.Atan({0})', 'log': 'Math.Log({0})', 'log10': 'Math.Log10({0})',
         'floor': '(long)Math.Floor({0})', 'ceiling': '(long)Math.Ceiling({0})', 'round': '(long)Math.Round({0})',
         'trunc': '(long)({0})', 'parseint': 'long.Parse(({0}).Trim())',
         'parsereal': 'double.Parse(({0}).Trim(), System.Globalization.CultureInfo.InvariantCulture)',
         'parsebool': '(({0}).Trim().ToLower() == "true")', 'len': '(long)({0}).Length', 'alen': '(long){0}.Length',
         'char': '({0})[(int)({1})].ToString()', 'random': '(long)(_rng.NextDouble() * {0})',
         'min': 'Math.Min({0}, {1})', 'max': 'Math.Max({0}, {1})', 'sgn': '(long)Math.Sign({0})',
         'toupper': '({0}).ToUpper()', 'tolower': '({0}).ToLower()', 'trim': '({0}).Trim()', 'contains': '({0}).Contains({1})'}

    def int2real(self, code, wrap=False):
        return '(double)(' + code + ')'

    def real2int(self, code):
        return '(long)(' + code + ')'

    def tostr(self, code, t):
        if t == 'String':
            return code
        return '(' + code + ' ? "true" : "false")' if t == 'Boolean' else 'Convert.ToString(' + code + ')'

    def pow(self, l, r, lt, rt):
        c = 'Math.Pow(' + l + ', ' + r + ')'
        return '(long)' + c if (lt, rt) == ('Integer', 'Integer') else c

    def index(self, base, idx, a):
        if self.ty(a.value) == 'String' and not self.is_array(a.value):
            return base + '[(int)(' + idx + ')].ToString()'
        return base + '[' + (idx if idx_literal(a) is not None else '(int)(' + idx + ')') + ']'

    def cmp(self, sym, left, right, lt, rt):
        if 'String' in (lt, rt) and sym not in ('==', '!='):
            return '(string.CompareOrdinal(' + self.ex(left) + ', ' + self.ex(right) + ') ' + sym + ' 0)', 100
        return Gen.cmp(self, sym, left, right, lt, rt)

    def decl_array(self, name, t, size):
        self.stmt(self.T[t] + '[] ' + name + ' = new ' + self.T[t] + '[(int)(' + size + ')]')
        if t == 'String':
            self.emit('for (int _k = 0; _k < ' + name + '.Length; _k++) { ' + name + '[_k] = ""; }')

    def read(self, target, t, name):
        src = '(Console.ReadLine() ?? "")'
        conv = {'Integer': 'long.Parse(' + src + '.Trim())',
                'Real': 'double.Parse(' + src + '.Trim(), System.Globalization.CultureInfo.InvariantCulture)',
                'String': src, 'Boolean': '(' + src + '.Trim().ToLower() == "true")'}[t]
        self.stmt(target + ' = ' + conv)

    def write(self, code, newline, t):
        self.stmt('Console.' + ('WriteLine' if newline else 'Write') + '(' + code + ')')

    def sig(self, f):
        ps = ', '.join(self.T[p['type']] + ('[]' if p['array'] else '') + ' ' + p['name'] for p in f['parameters'])
        return 'static ' + self.T[f['type']] + ' ' + f['name'] + '(' + ps + ')'

    def func_open(self, f):
        self.emit(self.sig(f) + ' {')

    def main_open(self):
        self.emit('public static void Main() {')
        self.depth += 1

    def main_close(self):
        self.depth -= 1
        self.emit('}')

    def build(self):
        self.emit('public class Program {')
        self.depth += 1
        if any('random' == k for k in [x for x in self.rand_check()]):
            self.emit('// ' + HELP_BEGIN)
            self.emit('static Random _rng = new Random();')
            self.emit('// ' + HELP_END)
            self.emit()
        Gen.build(self)
        self.depth -= 1
        self.emit('}')

    def rand_check(self):
        for f in self.funcs:
            for n in walk(f['body']):
                if re.search(r'\brandom\s*\(', json.dumps(n), re.I):
                    yield 'random'

    def header(self):
        return ['using System;', '']

    def main_return(self):
        self.stmt('return')




class StrictNum(object):
    """Mixin for languages that never convert Integer to Real implicitly."""
    implicit_widen = False

    def mixed(self, lt, rt):
        return set((lt, rt)) == set(('Integer', 'Real'))

    def opnd(self, a, t, p, right=False):
        if t == 'Integer' and self.mixed(self.ty(a), 'Real') is False:
            pass
        return self.sub(a, p, right)

    def binary(self, a):
        op = type(a.op)
        lt, rt = self.ty(a.left), self.ty(a.right)
        if op in (ast.Add, ast.Sub, ast.Mult) and self.mixed(lt, rt):
            p = 7 if op is ast.Mult else 6
            sym = {ast.Add: '+', ast.Sub: '-', ast.Mult: '*'}[op]
            l = self.int2real(self.ex(a.left), wrap=True) if lt == 'Integer' else self.sub(a.left, p)
            r = self.int2real(self.ex(a.right), wrap=True) if rt == 'Integer' else self.sub(a.right, p, True)
            return self.paren(l + ' ' + sym + ' ' + r, p)
        return Gen.binary(self, a)

    def cmp(self, sym, left, right, lt, rt):
        if self.mixed(lt, rt):
            l = self.int2real(self.ex(left), wrap=True) if lt == 'Integer' else self.sub(left, 5)
            r = self.int2real(self.ex(right), wrap=True) if rt == 'Integer' else self.sub(right, 5, True)
            return self.paren(l + ' ' + self.CMP[sym] + ' ' + r, 4)
        return Gen.cmp(self, sym, left, right, lt, rt)


# ------------------------------------------------------------------ MATLAB

@register('MATLAB')
class MatlabGen(Gen):
    INTDIV = 'fix({0} / {1})'
    ext = '.m'
    cm = '%'
    hoist = False
    has_elif = True
    int_div_trap = False
    POWSYM = ' ^ '
    AND, OR, NOT = ' && ', ' || ', '~'
    CMP = {'==': '==', '!=': '~=', '<': '<', '<=': '<=', '>': '>', '>=': '>='}
    F = {'abs': 'abs({0})', 'sqrt': 'sqrt({0})', 'sin': 'sin({0})', 'cos': 'cos({0})', 'tan': 'tan({0})',
         'arcsin': 'asin({0})', 'arccos': 'acos({0})', 'arctan': 'atan({0})', 'log': 'log({0})',
         'log10': 'log10({0})', 'floor': 'floor({0})', 'ceiling': 'ceil({0})', 'round': 'round({0})',
         'trunc': 'fix({0})', 'parseint': 'fix(str2double({0}))', 'parsereal': 'str2double({0})',
         'parsebool': "strcmpi(strtrim({0}), 'true')", 'len': 'length({0})', 'alen': 'numel({0})',
         'char': '{0}(({1}) + 1)', 'random': 'floor(rand() * {0})', 'min': 'min({0}, {1})',
         'max': 'max({0}, {1})', 'sgn': 'sign({0})',
         'toupper': 'upper({0})', 'tolower': 'lower({0})', 'trim': 'strtrim({0})', 'contains': '(~isempty(strfind({0}, {1})))'}

    def strlit(self, s):
        runs = str_runs(s)
        if not runs:
            return "''"
        parts = ["'" + t.replace("'", "''") + "'" if k == 't' else 'char(' + str(t) + ')' for k, t in runs]
        return parts[0] if len(parts) == 1 else '[' + ', '.join(parts) + ']'

    def tostr(self, code, t):
        if t == 'String':
            return code
        if t == 'Real':
            return "sprintf('%.15g', " + code + ')'
        if t == 'Boolean':
            return 'mat2str(logical(' + code + '))'
        return "sprintf('%d', " + code + ')'

    def mod(self, left, right, lt, rt):
        return 'mod(' + self.ex(left) + ', ' + self.ex(right) + ')', 100

    def concat_parts(self, a):
        if isinstance(a, ast.BinOp) and (isinstance(a.op, ast.BitAnd) or (
                isinstance(a.op, ast.Add) and 'String' in (self.ty(a.left), self.ty(a.right)))):
            return self.concat_parts(a.left) + self.concat_parts(a.right)
        return [self.strpart(a, 0)]

    def concat(self, left, right):
        parts = self.concat_parts(left) + self.concat_parts(right)
        return '[' + ', '.join(parts) + ']', 100

    def index(self, base, idx, a):
        k = idx_literal(a)
        i = str(k + 1) if k is not None else idx + ' + 1'
        if self.is_array(a.value) and self.vt[a.value.id][0] == 'String':
            return base + '{' + i + '}'
        return base + '(' + i + ')'

    def cmp(self, sym, left, right, lt, rt):
        if 'String' in (lt, rt):
            if sym in ('==', '!='):
                c = 'strcmp(' + self.ex(left) + ', ' + self.ex(right) + ')'
                return (c if sym == '==' else '~' + c), 100
            l, r = self.ex(left), self.ex(right)
            if sym == '<':
                return '(issorted({' + l + ', ' + r + '}) && ~strcmp(' + l + ', ' + r + '))', 100
            if sym == '<=':
                return 'issorted({' + l + ', ' + r + '})', 100
            if sym == '>':
                return '(~issorted({' + l + ', ' + r + '}))', 100
            return 'issorted({' + r + ', ' + l + '})', 100
        return Gen.cmp(self, sym, left, right, lt, rt)

    def out_needs_string(self, t):
        return t != 'String'

    def decl_scalar(self, name, t):
        self.emit(name + ' = ' + self.init_value(t) + ';')

    def decl_array(self, name, t, size):
        if t == 'String':
            self.emit(name + " = repmat({''}, 1, " + size + ');')
        elif t == 'Boolean':
            self.emit(name + ' = false(1, ' + size + ');')
        else:
            self.emit(name + ' = zeros(1, ' + size + ');')

    def assign(self, target, code):
        if '{' in target:
            pass
        self.emit(target + ' = ' + code + ';')

    def read(self, target, t, name):
        src = "input('', 's')"
        conv = {'Integer': 'fix(str2double(' + src + '))', 'Real': 'str2double(' + src + ')', 'String': src,
                'Boolean': "strcmpi(strtrim(" + src + "), 'true')"}[t]
        self.emit(target + ' = ' + conv + ';')

    def write(self, code, newline, t):
        self.emit("fprintf('%s" + ('\\n' if newline else '') + "', " + code + ');')

    def if_open(self, c):
        self.emit('if ' + c)

    def elif_open(self, c):
        self.emit('elseif ' + c)

    def else_open(self):
        self.emit('else')

    def if_close(self):
        self.emit('end')

    def while_open(self, c):
        self.emit('while ' + c)

    def while_close(self):
        self.emit('end')

    def n_Do(self, n):
        self.emit('while true')
        self.depth += 1
        self.nest += 1
        cond = self.cond(n['expression'])

        def check():
            self.emit('if ~(' + cond + ')')
            self.emit('    break;')
            self.emit('end')
        self.loops[-1]['check'] = check
        self.block(n['body'])
        check()
        self.nest -= 1
        self.depth -= 1
        self.emit('end')

    def for_loop(self, v, sa, ea, pa, dec, body):
        ok, sv = literal(pa)
        step = '' if (ok and sv == 1 and not dec) else (('-' if dec else '') + self.sub(pa, 8) + ':')
        self.emit('for ' + v + ' = ' + self.sub(sa, 5) + ':' + step + self.sub(ea, 5))
        self.indented(body)
        self.emit('end')

    def s_return(self, code):
        if code:
            self.emit('res = ' + code + ';')
        self.emit('return;')

    def main_return(self):
        self.emit('return;')

    def func_open(self, f):
        ps = ', '.join(p['name'] for p in f['parameters'])
        self.emit('function ' + ('' if f['type'] == 'None' else 'res = ') + f['name'] + '(' + ps + ')')

    def func_close(self, f):
        self.emit('end')

    def n_Call(self, n):
        self.emit(self.ex(parse_expr(n['expression'])) + ';')

    def build(self):
        self.main_open()
        self.body(self.funcs[0])
        for f in self.funcs[1:]:
            self.emit()
            self.function(f)

    def header(self):
        return []



@register('Kotlin')
class KotlinGen(StrictNum, BraceGen):
    INTDIV = '({0} / {1})'
    ext = '.kt'
    semi = ''
    native_for = False
    T = {'Integer': 'Long', 'Real': 'Double', 'String': 'String', 'Boolean': 'Boolean', 'None': 'Unit'}
    AT = {'Integer': 'LongArray', 'Real': 'DoubleArray', 'String': 'Array<String>', 'Boolean': 'BooleanArray'}
    F = {'abs': 'Math.abs({0})', 'sqrt': 'Math.sqrt({0})', 'sin': 'Math.sin({0})', 'cos': 'Math.cos({0})',
         'tan': 'Math.tan({0})', 'arcsin': 'Math.asin({0})', 'arccos': 'Math.acos({0})',
         'arctan': 'Math.atan({0})', 'log': 'Math.log({0})', 'log10': 'Math.log10({0})',
         'floor': 'Math.floor({0}).toLong()', 'ceiling': 'Math.ceil({0}).toLong()',
         'round': 'Math.round({0})', 'trunc': '({0}).toLong()', 'parseint': '({0}).trim().toLong()',
         'parsereal': '({0}).trim().toDouble()', 'parsebool': '(({0}).trim().lowercase() == "true")',
         'len': '({0}).length.toLong()', 'alen': '{0}.size.toLong()',
         'char': '({0})[({1}).toInt()].toString()', 'random': '(Math.random() * {0}).toLong()',
         'min': 'Math.min({0}, {1})', 'max': 'Math.max({0}, {1})',
         'sgn': 'Math.signum(({0}).toDouble()).toLong()',
         'toupper': '({0}).uppercase()', 'tolower': '({0}).lowercase()', 'trim': '({0}).trim()', 'contains': '({0}).contains({1})'}

    def strlit(self, s):
        return c_string(s, dollar=True)

    def int2real(self, code, wrap=False):
        return '(' + code + ').toDouble()'

    def real2int(self, code):
        return '(' + code + ').toLong()'

    def tostr(self, code, t):
        return code if t == 'String' else '(' + code + ').toString()'

    def pow(self, l, r, lt, rt):
        c = 'Math.pow((' + l + ').toDouble(), (' + r + ').toDouble())'
        return c + '.toLong()' if (lt, rt) == ('Integer', 'Integer') else c

    def builtin_code(self, key, args, types):
        if key in ('min', 'max') and types[0] != types[1]:
            args = [('(' + x + ').toDouble()') if ty == 'Integer' else x for x, ty in zip(args, types)]
        return Gen.builtin_code(self, key, args, types)

    def index(self, base, idx, a):
        if self.ty(a.value) == 'String' and not self.is_array(a.value):
            return base + '[(' + idx + ').toInt()].toString()'
        return base + '[' + (idx if idx_literal(a) is not None else '(' + idx + ').toInt()') + ']'

    def decl_scalar(self, name, t):
        self.emit('var ' + name + ': ' + self.T[t] + ' = ' + self.init_value(t))

    def decl_array(self, name, t, size):
        n = '(' + size + ').toInt()'
        if t == 'String':
            self.emit('var ' + name + ': Array<String> = Array(' + n + ') { "" }')
        else:
            self.emit('var ' + name + ': ' + self.AT[t] + ' = ' + self.AT[t] + '(' + n + ')')

    def read(self, target, t, name):
        src = '(readLine() ?: "")'
        conv = {'Integer': src + '.trim().toLong()', 'Real': src + '.trim().toDouble()', 'String': src,
                'Boolean': '(' + src + '.trim().lowercase() == "true")'}[t]
        self.emit(target + ' = ' + conv)

    def write(self, code, newline, t):
        self.emit(('println(' if newline else 'print(') + code + ')')

    def sig(self, f):
        ps = ', '.join(p['name'] + ': ' + (self.AT[p['type']] if p['array'] else self.T[p['type']]) for p in f['parameters'])
        return 'fun ' + f['name'] + '(' + ps + ')' + ('' if f['type'] == 'None' else ': ' + self.T[f['type']])

    def func_open(self, f):
        self.emit(self.sig(f) + ' {')

    def main_open(self):
        self.emit('fun main() {')
        self.depth += 1

    def main_close(self):
        self.depth -= 1
        self.emit('}')

    def main_return(self):
        self.emit('return')

    def s_return(self, code):
        self.emit('return' + (' ' + code if code else ''))



@register('Swift')
class SwiftGen(StrictNum, BraceGen):
    INTDIV = '({0} / {1})'
    ext = '.swift'
    semi = ''
    native_for = False
    cast_both = True
    T = {'Integer': 'Int', 'Real': 'Double', 'String': 'String', 'Boolean': 'Bool', 'None': 'Void'}
    F = {'abs': 'abs({0})', 'sqrt': 'sqrt({0})', 'sin': 'sin({0})', 'cos': 'cos({0})', 'tan': 'tan({0})',
         'arcsin': 'asin({0})', 'arccos': 'acos({0})', 'arctan': 'atan({0})', 'log': 'log({0})',
         'log10': 'log10({0})', 'floor': 'Int(floor({0}))', 'ceiling': 'Int(ceil({0}))',
         'round': 'Int(({0}).rounded())', 'trunc': 'Int({0})',
         'parseint': '(Int(({0}).trimmingCharacters(in: .whitespacesAndNewlines)) ?? 0)',
         'parsereal': '(Double(({0}).trimmingCharacters(in: .whitespacesAndNewlines)) ?? 0.0)',
         'parsebool': '(({0}).trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == "true")',
         'len': '({0}).count', 'alen': '{0}.count', 'char': 'String(Array({0})[{1}])',
         'random': 'Int.random(in: 0..<({0}))', 'min': 'min({0}, {1})', 'max': 'max({0}, {1})',
         'sgn': '(({0}) > 0 ? 1 : (({0}) < 0 ? -1 : 0))',
         'toupper': '({0}).uppercased()', 'tolower': '({0}).lowercased()', 'trim': '({0}).trimmingCharacters(in: .whitespacesAndNewlines)', 'contains': '({0}).contains({1})'}
    MATH = ('sqrt', 'sin', 'cos', 'tan', 'arcsin', 'arccos', 'arctan', 'log', 'log10', 'floor', 'ceiling', 'round')

    def int2real(self, code, wrap=False):
        return 'Double(' + code + ')'

    def real2int(self, code):
        return 'Int(' + code + ')'

    def tostr(self, code, t):
        return code if t == 'String' else 'String(' + code + ')'

    def pow(self, l, r, lt, rt):
        c = 'pow(Double(' + l + '), Double(' + r + '))'
        return 'Int(' + c + ')' if (lt, rt) == ('Integer', 'Integer') else c

    def mod(self, left, right, lt, rt):
        if 'Real' in (lt, rt):
            return 'fmod(' + self.coerce(self.ex(left), lt, 'Real') + ', ' + self.coerce(self.ex(right), rt, 'Real') + ')', 100
        return Gen.mod(self, left, right, lt, rt)

    def builtin_code(self, key, args, types):
        if key in self.MATH and types and types[0] == 'Integer' and key not in ('floor', 'ceiling', 'round'):
            args = ['Double(' + args[0] + ')']
        if key in ('min', 'max') and types[0] != types[1]:
            args = ['Double(' + x + ')' if ty == 'Integer' else x for x, ty in zip(args, types)]
        return Gen.builtin_code(self, key, args, types)

    def decl_scalar(self, name, t):
        self.emit('var ' + name + ': ' + self.T[t] + ' = ' + self.init_value(t))

    def decl_array(self, name, t, size):
        self.emit('var ' + name + ': [' + self.T[t] + '] = Array(repeating: ' + self.init_value(t) + ', count: ' + size + ')')

    def index(self, base, idx, a):
        if self.ty(a.value) == 'String' and not self.is_array(a.value):
            return 'String(Array(' + base + ')[' + idx + '])'
        return base + '[' + idx + ']'

    def read(self, target, t, name):
        src = '(readLine() ?? "")'
        trim = src + '.trimmingCharacters(in: .whitespacesAndNewlines)'
        conv = {'Integer': 'Int(' + trim + ') ?? 0', 'Real': 'Double(' + trim + ') ?? 0.0', 'String': src,
                'Boolean': '(' + trim + '.lowercased() == "true")'}[t]
        self.emit(target + ' = ' + conv)

    def write(self, code, newline, t):
        self.emit('print(' + code + ('' if newline else ', terminator: ""') + ')')

    def if_open(self, c):
        self.emit('if ' + c + ' {')

    def elif_open(self, c):
        self.emit('} else if ' + c + ' {')

    def while_open(self, c):
        self.emit('while ' + c + ' {')

    def do_open(self):
        self.emit('repeat {')

    def do_close(self, c):
        self.emit('} while ' + c)

    def user_call(self, name, args):
        f = self.ftypes[name]
        out = []
        for x, p in zip(args, f['parameters']):
            out.append('&' + x.id if p['array'] else self.coerce(self.ex(x), self.ty(x), p['type']))
        return name + '(' + ', '.join(out) + ')'

    def sig(self, f):
        ps = ', '.join('_ ' + p['name'] + ': ' + ('inout [' + self.T[p['type']] + ']' if p['array'] else self.T[p['type']])
                       for p in f['parameters'])
        return 'func ' + f['name'] + '(' + ps + ')' + ('' if f['type'] == 'None' else ' -> ' + self.T[f['type']])

    def func_open(self, f):
        self.emit(self.sig(f) + ' {')

    def main_return(self):
        self.emit('exit(0)')

    def header(self):
        return ['import Foundation', '']


# ----------------------------------------------------------------------- C
@register('C')
class CGen(BraceGen):
    ext = '.c'
    INTDIV = '({0} / {1})'
    T = {'Integer': 'long long', 'Real': 'double', 'String': 'char *', 'Boolean': 'bool', 'None': 'void'}
    F = {'abs': 'fabs({0})', 'sqrt': 'sqrt({0})', 'sin': 'sin({0})', 'cos': 'cos({0})', 'tan': 'tan({0})',
         'arcsin': 'asin({0})', 'arccos': 'acos({0})', 'arctan': 'atan({0})', 'log': 'log({0})',
         'log10': 'log10({0})', 'floor': '(long long)floor({0})', 'ceiling': '(long long)ceil({0})',
         'round': 'llround({0})', 'trunc': '(long long)({0})', 'parseint': 'strtoll({0}, NULL, 10)',
         'parsereal': 'strtod({0}, NULL)', 'parsebool': 'flow_bool({0})', 'len': '(long long)strlen({0})',
         'char': 'flow_char({0}, {1})', 'random': '(long long)(rand() % ({0}))',
         'min': '(({0}) < ({1}) ? ({0}) : ({1}))', 'max': '(({0}) > ({1}) ? ({0}) : ({1}))',
         'sgn': '((({0}) > 0) - (({0}) < 0))', 'toupper': 'flow_upper({0})', 'tolower': 'flow_lower({0})',
         'trim': 'flow_trim({0})', 'contains': 'flow_contains({0}, {1})'}

    def int2real(self, code, wrap=False):
        return '(double)(' + code + ')'

    def real2int(self, code):
        return '(long long)(' + code + ')'

    def tostr(self, code, t):
        if t == 'String':
            return code
        return {'Real': 'flow_str_r', 'Boolean': 'flow_str_b'}.get(t, 'flow_str_i') + '(' + code + ')'

    def concat(self, left, right):
        return 'flow_cat(' + self.strpart(left, 0) + ', ' + self.strpart(right, 0) + ')', 100

    def pow(self, l, r, lt, rt):
        c = 'pow(' + l + ', ' + r + ')'
        return '(long long)llround(' + c + ')' if (lt, rt) == ('Integer', 'Integer') else c

    def mod(self, left, right, lt, rt):
        if 'Real' in (lt, rt):
            return 'fmod(' + self.ex(left) + ', ' + self.ex(right) + ')', 100
        return Gen.mod(self, left, right, lt, rt)

    def cmp(self, sym, left, right, lt, rt):
        if 'String' in (lt, rt):
            return '(strcmp(' + self.ex(left) + ', ' + self.ex(right) + ') ' + sym + ' 0)', 100
        return Gen.cmp(self, sym, left, right, lt, rt)

    def builtin_code(self, key, args, types):
        if key == 'abs' and types[0] == 'Integer':
            return 'llabs(' + args[0] + ')'
        return Gen.builtin_code(self, key, args, types)

    def index(self, base, idx, a):
        if self.ty(a.value) == 'String' and not self.is_array(a.value):
            return 'flow_char(' + base + ', ' + idx + ')'
        return base + '[' + idx + ']'

    def begin_scope(self, f):
        Gen.begin_scope(self, f)
        self.asize = dict((p['name'], p['name'] + '_len') for p in f['parameters'] if p['array'])

    def array_len(self, name, code):
        return self.asize[name]

    def decl_array(self, name, t, size):
        self.asize[name] = '(' + size + ')' if not re.match(r'^[\w]+$', size) else size
        if t == 'String':
            self.stmt('char **' + name + ' = malloc(sizeof(char *) * (size_t)(' + size + '))')
            self.emit('for (long long _k = 0; _k < ' + self.asize[name] + '; _k++) ' + name + '[_k] = "";')
        else:
            self.stmt(self.T[t].strip() + ' *' + name + ' = calloc((size_t)(' + size + '), sizeof(' + self.T[t].strip() + '))')

    def decl_scalar(self, name, t):
        self.stmt(self.T[t] + ('' if self.T[t].endswith('*') else ' ') + name + ' = ' + self.init_value(t))

    def user_call(self, name, args):
        f = self.ftypes[name]
        out = []
        for x, p in zip(args, f['parameters']):
            if p['array']:
                out.append(x.id + ', ' + self.asize[x.id])
            else:
                out.append(self.coerce(self.ex(x), self.ty(x), p['type']))
        return name + '(' + ', '.join(out) + ')'

    def read(self, target, t, name):
        src = 'flow_read()'
        conv = {'Integer': 'strtoll(' + src + ', NULL, 10)', 'Real': 'strtod(' + src + ', NULL)', 'String': src,
                'Boolean': 'flow_bool(' + src + ')'}[t]
        self.stmt(target + ' = ' + conv)

    def out_needs_string(self, t):
        return False

    def write(self, code, newline, t):
        nl = '\\n' if newline else ''
        if t == 'String':
            self.stmt('printf("%s' + nl + '", ' + code + ')')
        elif t == 'Real':
            self.stmt('printf("%.15g' + nl + '", ' + code + ')')
        elif t == 'Boolean':
            self.stmt('printf("%s' + nl + '", (' + code + ') ? "true" : "false")')
        else:
            self.stmt('printf("%lld' + nl + '", (long long)(' + code + '))')

    def sig(self, f):
        ps = []
        for p in f['parameters']:
            if p['array']:
                ps.append(('char **' if p['type'] == 'String' else self.T[p['type']] + ' *') + p['name'] + ', long long ' + p['name'] + '_len')
            else:
                ps.append(self.T[p['type']] + ('' if self.T[p['type']].endswith('*') else ' ') + p['name'])
        return self.T[f['type']] + ('' if self.T[f['type']].endswith('*') else ' ') + f['name'] + '(' + (', '.join(ps) or 'void') + ')'

    def pre_build(self):
        for f in self.funcs[1:]:
            self.emit(self.sig(f) + ';')
        if len(self.funcs) > 1:
            self.emit()

    def func_open(self, f):
        self.emit(self.sig(f) + ' {')

    def main_open(self):
        self.emit('int main(void) {')
        self.depth += 1
        self.emit('/*SRAND*/')

    def main_close(self):
        self.emit('return 0;')
        self.depth -= 1
        self.emit('}')

    def main_return(self):
        self.stmt('return 0')

    HELPERS = [
        ('flow_read', ['static char *flow_read(void) {', '    size_t cap = 128, n = 0; char *b = malloc(cap); int c;',
                       '    while ((c = getchar()) != EOF && c != \'\\n\') {',
                       '        if (n + 2 >= cap) { cap *= 2; b = realloc(b, cap); }', '        b[n++] = (char)c;', '    }',
                       '    b[n] = 0; if (n && b[n - 1] == \'\\r\') b[n - 1] = 0;', '    return b;', '}']),
        ('flow_cat', ['static char *flow_cat(const char *a, const char *b) {',
                      '    char *r = malloc(strlen(a) + strlen(b) + 1); strcpy(r, a); strcat(r, b); return r;', '}']),
        ('flow_str_i', ['static char *flow_str_i(long long v) { char *r = malloc(32); snprintf(r, 32, "%lld", v); return r; }']),
        ('flow_str_r', ['static char *flow_str_r(double v) { char *r = malloc(40); snprintf(r, 40, "%.15g", v); return r; }']),
        ('flow_str_b', ['static char *flow_str_b(bool v) { return v ? "true" : "false"; }']),
        ('flow_bool', ['static bool flow_bool(const char *s) {', '    while (isspace((unsigned char)*s)) s++;',
                       '    return strncmp(s, "true", 4) == 0 || strncmp(s, "True", 4) == 0 || *s == \'1\';', '}']),
        ('flow_char', ['static char *flow_char(const char *s, long long i) { char *r = malloc(2); r[0] = s[i]; r[1] = 0; return r; }']),
        ('flow_upper', ['static char *flow_upper(const char *s) {', '    char *r = malloc(strlen(s) + 1); strcpy(r, s); for (char *p = r; *p; p++) *p = (char)toupper((unsigned char)*p); return r;', '}']),
        ('flow_lower', ['static char *flow_lower(const char *s) {', '    char *r = malloc(strlen(s) + 1); strcpy(r, s); for (char *p = r; *p; p++) *p = (char)tolower((unsigned char)*p); return r;', '}']),
        ('flow_trim', ['static char *flow_trim(const char *s) {', '    while (isspace((unsigned char)*s)) s++;',
                       '    size_t n = strlen(s); while (n && isspace((unsigned char)s[n - 1])) n--;',
                       '    char *r = malloc(n + 1); memcpy(r, s, n); r[n] = 0; return r;', '}']),
        ('flow_contains', ['static bool flow_contains(const char *a, const char *b) { return strstr(a, b) != NULL; }'])]

    def header(self):
        text = '\n'.join(self.lines)
        out = ['#include <stdio.h>', '#include <stdlib.h>', '#include <string.h>', '#include <math.h>',
               '#include <stdbool.h>', '#include <ctype.h>']
        if 'rand()' in text:
            out.append('#include <time.h>')
        out.append('')
        helpers = []
        for name, code in self.HELPERS:
            if name + '(' in text or any(name + '(' in '\n'.join(c) for n2, c in self.HELPERS if n2 != name and n2 + '(' in text):
                helpers += code
        if helpers:
            out += ['/* ' + HELP_BEGIN + ' */'] + helpers + ['/* ' + HELP_END + ' */']
        return out + ['']

    def generate(self, doc):
        text = Gen.generate(self, doc)
        if 'rand()' in text:
            text = text.replace('/*SRAND*/', 'srand((unsigned)time(NULL));')
        else:
            text = text.replace('    /*SRAND*/\n', '')
        return text


# ------------------------------------------------------------------------ Go
@register('Go')
class GoGen(StrictNum, BraceGen):
    ext = '.go'
    semi = ''
    native_for = True
    cast_both = True
    INTDIV = '({0} / {1})'
    T = {'Integer': 'int64', 'Real': 'float64', 'String': 'string', 'Boolean': 'bool', 'None': ''}
    F = {'abs': 'math.Abs({0})', 'sqrt': 'math.Sqrt({0})', 'sin': 'math.Sin({0})', 'cos': 'math.Cos({0})',
         'tan': 'math.Tan({0})', 'arcsin': 'math.Asin({0})', 'arccos': 'math.Acos({0})',
         'arctan': 'math.Atan({0})', 'log': 'math.Log({0})', 'log10': 'math.Log10({0})',
         'floor': 'int64(math.Floor({0}))', 'ceiling': 'int64(math.Ceil({0}))',
         'round': 'int64(math.RoundToEven({0}))', 'trunc': 'int64({0})', 'parseint': 'flowInt({0})',
         'parsereal': 'flowFloat({0})', 'parsebool': 'flowBool({0})', 'len': 'int64(len({0}))',
         'alen': 'int64(len({0}))', 'char': 'string(({0})[{1}])', 'random': 'rand.Int63n({0})',
         'min': 'min({0}, {1})', 'max': 'max({0}, {1})', 'sgn': 'flowSgn({0})',
         'toupper': 'strings.ToUpper({0})', 'tolower': 'strings.ToLower({0})', 'trim': 'strings.TrimSpace({0})',
         'contains': 'strings.Contains({0}, {1})'}
    MATH = ('sqrt', 'sin', 'cos', 'tan', 'arcsin', 'arccos', 'arctan', 'log', 'log10')

    def int2real(self, code, wrap=False):
        return 'float64(' + code + ')'

    def real2int(self, code):
        return 'int64(' + code + ')'

    def tostr(self, code, t):
        if t == 'String':
            return code
        if t == 'Real':
            return "strconv.FormatFloat(" + code + ", 'f', -1, 64)"
        if t == 'Boolean':
            return 'strconv.FormatBool(' + code + ')'
        return 'strconv.FormatInt(' + code + ', 10)'

    def pow(self, l, r, lt, rt):
        c = 'math.Pow(float64(' + l + '), float64(' + r + '))'
        return 'int64(' + c + ')' if (lt, rt) == ('Integer', 'Integer') else c.replace('float64(' + l + ')', self.coerce(l, lt, 'Real')).replace('float64(' + r + ')', self.coerce(r, rt, 'Real'))

    def mod(self, left, right, lt, rt):
        if 'Real' in (lt, rt):
            return 'math.Mod(' + self.coerce(self.ex(left), lt, 'Real') + ', ' + self.coerce(self.ex(right), rt, 'Real') + ')', 100
        return Gen.mod(self, left, right, lt, rt)

    def builtin_code(self, key, args, types):
        if key in self.MATH and types[0] == 'Integer':
            args = ['float64(' + args[0] + ')']
        if key == 'abs' and types[0] == 'Integer':
            return 'flowAbs(' + args[0] + ')'
        if key in ('min', 'max') and types[0] != types[1]:
            args = ['float64(' + x + ')' if ty == 'Integer' else x for x, ty in zip(args, types)]
        if key == 'sgn':
            return 'flowSgn(' + self.coerce(args[0], types[0], 'Real') + ')'
        return Gen.builtin_code(self, key, args, types)

    def decl_scalar(self, name, t):
        self.emit('var ' + name + ' ' + self.T[t] + ' = ' + self.init_value(t))
        if name in self.unused:
            self.emit('_ = ' + name)

    def decl_array(self, name, t, size):
        self.emit('var ' + name + ' []' + self.T[t] + ' = make([]' + self.T[t] + ', ' + size + ')')
        if t == 'String':
            self.emit('for _k := range ' + name + ' { ' + name + '[_k] = "" }')
        if name in self.unused:
            self.emit('_ = ' + name)

    def begin_scope(self, f):
        Gen.begin_scope(self, f)
        reads = set()
        for n in walk(f['body']):
            for key in ('expression', 'start', 'end', 'step', 'size'):
                if n.get(key):
                    reads.update(re.findall(r'[A-Za-z_]\w*', n[key]))
            if n['kind'] in ('Assign', 'Input'):
                m = re.match(r'^[A-Za-z_]\w*\s*\[(.*)\]$', n['variable'].strip())
                if m:
                    reads.update(re.findall(r'[A-Za-z_]\w*', m.group(1)))
                    reads.add(re.match(r'[A-Za-z_]\w*', n['variable'].strip()).group(0))
        if f['type'] != 'None' and f['variable']:
            reads.add(f['variable'])
        self.unused = set(nm for nm in set(self.decl_names(f)) if nm not in reads)

    def decl_names(self, f):
        for n in walk(f['body']):
            if n['kind'] == 'Declare':
                for nm in names(n['name']):
                    yield nm

    def index(self, base, idx, a):
        if self.ty(a.value) == 'String' and not self.is_array(a.value):
            return 'string(' + base + '[' + idx + '])'
        return base + '[' + idx + ']'

    def assign(self, target, code):
        self.emit(target + ' = ' + code)

    def read(self, target, t, name):
        src = 'flowReadLine()'
        conv = {'Integer': 'flowInt(' + src + ')', 'Real': 'flowFloat(' + src + ')', 'String': src,
                'Boolean': 'flowBool(' + src + ')'}[t]
        self.emit(target + ' = ' + conv)

    def write(self, code, newline, t):
        self.emit('fmt.' + ('Println' if newline else 'Print') + '(' + code + ')')

    def if_open(self, c):
        self.emit('if ' + c + ' {')

    def elif_open(self, c):
        self.emit('} else if ' + c + ' {')

    def while_open(self, c):
        self.emit('for ' + c + ' {')

    def n_Do(self, n):
        self.emit('for {')
        self.depth += 1
        self.nest += 1
        cond = self.cond(n['expression'])

        def check():
            self.emit('if !(' + cond + ') {')
            self.emit('    break')
            self.emit('}')
        self.loops[-1]['check'] = check
        self.block(n['body'])
        check()
        self.nest -= 1
        self.depth -= 1
        self.emit('}')

    def for_loop(self, v, sa, ea, pa, dec, body):
        t = self.vt[v][0]
        init = self.ref(v) + ' = ' + self.coerce(self.ex(sa), self.ty(sa), t)
        c = self.cmp('>=' if dec else '<=', ast.Name(id=v), ea, t, self.ty(ea))[0]
        self.emit('for ' + init + '; ' + strip_outer(c) + '; ' + self.ref(v) + ' = ' + self.step_expr(v, pa, dec) + ' {')
        self.indented(body)
        self.emit('}')

    def sig(self, f):
        ps = ', '.join(p['name'] + ' ' + ('[]' if p['array'] else '') + self.T[p['type']] for p in f['parameters'])
        return 'func ' + f['name'] + '(' + ps + ')' + ('' if f['type'] == 'None' else ' ' + self.T[f['type']])

    def func_open(self, f):
        self.emit(self.sig(f) + ' {')

    def main_open(self):
        self.emit('func main() {')
        self.depth += 1

    def main_close(self):
        self.depth -= 1
        self.emit('}')

    def main_return(self):
        self.emit('return')

    def header(self):
        text = '\n'.join(self.lines)
        helpers = []
        if 'flowReadLine' in text:
            helpers += ['var flowReader = bufio.NewReader(os.Stdin)', '',
                        'func flowReadLine() string {', '    s, _ := flowReader.ReadString(\'\\n\')',
                        '    return strings.TrimRight(s, "\\r\\n")', '}', '']
        if 'flowInt(' in text:
            helpers += ['func flowInt(s string) int64 {', '    v, _ := strconv.ParseInt(strings.TrimSpace(s), 10, 64)', '    return v', '}', '']
        if 'flowFloat(' in text:
            helpers += ['func flowFloat(s string) float64 {', '    v, _ := strconv.ParseFloat(strings.TrimSpace(s), 64)', '    return v', '}', '']
        if 'flowBool(' in text:
            helpers += ['func flowBool(s string) bool {', '    s = strings.ToLower(strings.TrimSpace(s))', '    return s == "true" || s == "1"', '}', '']
        if 'flowAbs(' in text:
            helpers += ['func flowAbs(x int64) int64 {', '    if x < 0 {', '        return -x', '    }', '    return x', '}', '']
        if 'flowSgn(' in text:
            helpers += ['func flowSgn(x float64) int64 {', '    if x > 0 {', '        return 1', '    }', '    if x < 0 {', '        return -1', '    }',
                        '    return 0', '}', '']
        body = '\n'.join(helpers) + '\n' + text
        if helpers:
            helpers = ['// ' + HELP_BEGIN] + helpers + ['// ' + HELP_END]
        imports = []
        for pkg, marker in (('bufio', 'bufio.'), ('fmt', 'fmt.'), ('math', 'math.'), ('math/rand', 'rand.'),
                            ('os', 'os.'), ('strconv', 'strconv.'), ('strings', 'strings.')):
            if marker in body:
                imports.append(pkg)
        out = ['package main', '']
        if imports:
            out += ['import ('] + ['    "' + i + '"' for i in imports] + [')', '']
        return out + helpers


# ------------------------------------------------------------------------ R
@register('R')
class RGen(BraceGen):
    ext = '.R'
    cm = '#'
    semi = ''
    sigil = ''
    hoist = False
    native_for = False
    int_div_trap = False
    POWSYM = ' ^ '
    CONCAT = None
    INTDIV = 'trunc({0} / {1})'
    TRUE, FALSE = 'TRUE', 'FALSE'
    CONTINUE = 'next'
    F = {'abs': 'abs({0})', 'sqrt': 'sqrt({0})', 'sin': 'sin({0})', 'cos': 'cos({0})', 'tan': 'tan({0})',
         'arcsin': 'asin({0})', 'arccos': 'acos({0})', 'arctan': 'atan({0})', 'log': 'log({0})',
         'log10': 'log10({0})', 'floor': 'floor({0})', 'ceiling': 'ceiling({0})', 'round': 'round({0})',
         'trunc': 'trunc({0})', 'parseint': 'as.integer({0})', 'parsereal': 'as.numeric({0})',
         'parsebool': '(tolower(trimws({0})) %in% c("true", "1"))', 'len': 'nchar({0})', 'alen': 'length({0})',
         'char': 'substr({0}, ({1}) + 1, ({1}) + 1)', 'random': 'floor(runif(1) * {0})', 'min': 'min({0}, {1})',
         'max': 'max({0}, {1})', 'sgn': 'sign({0})', 'toupper': 'toupper({0})', 'tolower': 'tolower({0})',
         'trim': 'trimws({0})', 'contains': 'grepl({1}, {0}, fixed = TRUE)'}

    def lit(self, v):
        if isinstance(v, int) and not isinstance(v, bool):
            return str(v)
        return Gen.lit(self, v)

    def int2real(self, code, wrap=False):
        return code

    def tostr(self, code, t):
        if t == 'String':
            return code
        return 'tolower(as.character(' + code + '))' if t == 'Boolean' else 'as.character(' + code + ')'

    def concat(self, left, right):
        return 'paste0(' + self.strpart(left, 0) + ', ' + self.strpart(right, 0) + ')', 100

    def mod(self, left, right, lt, rt):
        return self.paren(self.sub(left, 7) + ' %% ' + self.sub(right, 7, True), 7)

    def index(self, base, idx, a):
        k = idx_literal(a)
        i = str(k + 1) if k is not None else idx + ' + 1'
        if self.ty(a.value) == 'String' and not self.is_array(a.value):
            return 'substr(' + base + ', ' + i + ', ' + i + ')'
        return base + '[' + i + ']'

    def decl_scalar(self, name, t):
        self.emit(name + ' <- ' + self.init_value(t))

    def decl_array(self, name, t, size):
        self.emit(name + ' <- rep(' + self.init_value(t) + ', ' + size + ')')

    def assign(self, target, code):
        self.emit(target + ' <- ' + code)

    def read(self, target, t, name):
        src = 'readLines(.flow_in, n = 1)'
        conv = {'Integer': 'as.integer(' + src + ')', 'Real': 'as.numeric(' + src + ')', 'String': src,
                'Boolean': '(tolower(trimws(' + src + ')) %in% c("true", "1"))'}[t]
        self.emit(target + ' <- ' + conv)

    def write(self, code, newline, t):
        self.emit('cat(' + code + (', "\\n", sep = ""' if newline else ', sep = ""') + ')')

    def while_open(self, c):
        self.emit('while (' + c + ') {')

    def n_Do(self, n):
        self.emit('repeat {')
        self.depth += 1
        self.nest += 1
        cond = self.cond(n['expression'])

        def check():
            self.emit('if (!(' + cond + ')) break')
        self.loops[-1]['check'] = check
        self.block(n['body'])
        check()
        self.nest -= 1
        self.depth -= 1
        self.emit('}')

    def s_return(self, code):
        self.emit('return(' + (code if code else 'invisible(NULL)') + ')')

    def main_return(self):
        self.emit('quit(save = "no")')

    def func_open(self, f):
        self.emit(f['name'] + ' <- function(' + ', '.join(p['name'] for p in f['parameters']) + ') {')

    def header(self):
        out = ['# ' + HELP_BEGIN, 'options(digits = 15)']
        if 'input' in self.uses:
            out.append('.flow_in <- file("stdin", "r")')
        return out + ['# ' + HELP_END, '']


# ----------------------------------------------------------------------------
# Pseudocode: generator and parser (lossless, the editing format)
# ----------------------------------------------------------------------------
class ParseError(FlowError):
    pass


@register('Pseudocode')
class PseudoGen(Gen):
    ext = '.txt'
    cm = '//'

    def generate(self, doc):
        if doc.get("python"):
            validate(doc)
            if self.lang == "Python":
                return generate_python_document(doc)
            doc = _portable_python_document(doc)
        validate(doc)
        self.lines = []
        main = doc['functions'][0]
        self.block(main['body'])
        for f in doc['functions'][1:]:
            if self.lines:
                self.lines.append('')
            ps = ', '.join('{0} {1}{2}'.format(p['type'], p['name'], '[]' if p['array'] else '') for p in f['parameters'])
            self.lines.append('Function {0}({1}){2}'.format(f['name'], ps, '' if f['type'] == 'None' else ' Returns ' + f['type']))
            self.depth = 1
            self.block(f['body'])
            if f['type'] != 'None' and f['variable']:
                self.emit('Return ' + f['variable'])
            self.depth = 0
            self.lines.append('End Function')
        return '\n'.join(self.lines).rstrip('\n') + '\n'

    def n_Declare(self, n):
        if n['array']:
            self.emit('Declare {0} {1}[{2}]'.format(n['type'], n['name'], n['size']))
        else:
            self.emit('Declare {0} {1}'.format(n['type'], n['name']))

    def n_Assign(self, n):
        self.emit('{0} = {1}'.format(n['variable'], n['expression']))

    def n_Input(self, n):
        self.emit('Input ' + n['variable'])

    def n_Output(self, n):
        self.emit('Output ' + n['expression'] + ('' if n['newline'] else ' NoNewline'))

    def n_Call(self, n):
        self.emit('Call ' + n['expression'])

    def n_Break(self, n):
        self.emit('Break')

    def n_Continue(self, n):
        self.emit('Continue')

    def n_Return(self, n):
        self.emit(('Return ' + n['expression']).rstrip())

    def n_If(self, n, first=True):
        self.emit(('If ' if first else 'Else If ') + n['expression'] + ' Then')
        self.depth += 1
        self.block(n['true'])
        self.depth -= 1
        f = n['false']
        if len(f) == 1 and f[0]['kind'] == 'If':
            self.n_If(f[0], False)
        elif f:
            self.emit('Else')
            self.depth += 1
            self.block(f)
            self.depth -= 1
        if first:
            self.emit('End If')

    def n_While(self, n):
        self.emit('While ' + n['expression'])
        self.depth += 1
        self.block(n['body'])
        self.depth -= 1
        self.emit('End While')

    def n_Do(self, n):
        self.emit('Do')
        self.depth += 1
        self.block(n['body'])
        self.depth -= 1
        self.emit('Loop While ' + n['expression'])

    def n_For(self, n):
        step = '' if n['step'].strip() == '1' else ' Step ' + n['step']
        self.emit('For {0} = {1} {2} {3}{4}'.format(n['variable'], n['start'], 'DownTo' if n['direction'] == 'dec' else 'To', n['end'], step))
        self.depth += 1
        self.block(n['body'])
        self.depth -= 1
        self.emit('End For')


def split_top(text, word):
    """Position of the keyword `word` (whole word, case-insensitive) outside strings/brackets."""
    depth, quote, i = 0, None, 0
    pat = re.compile(r'\s' + re.escape(word) + r'(?=\s|$)', re.I)
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == '\\':
                i += 1
            elif ch == quote:
                quote = None
        elif ch in '"\'':
            quote = ch
        elif ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif depth == 0 and ch.isspace():
            m = pat.match(text, i)
            if m:
                return i, m.end()
        i += 1
    return None


def split_commas(text):
    parts, depth, quote, cur = [], 0, None, ''
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            cur += ch
            if ch == '\\' and i + 1 < len(text):
                cur += text[i + 1]
                i += 1
            elif ch == quote:
                quote = None
        elif ch in '"\'':
            quote = ch
            cur += ch
        elif ch in '([':
            depth += 1
            cur += ch
        elif ch in ')]':
            depth -= 1
            cur += ch
        elif ch == ',' and depth == 0:
            parts.append(cur.strip())
            cur = ''
        else:
            cur += ch
        i += 1
    if cur.strip() or parts:
        parts.append(cur.strip())
    return parts


# Python's ord()/chr() are common, especially in character algorithms.  Supply
# target-language spellings where their string model makes the conversion direct.
# C and C++ use their native narrow-character model here; non-ASCII code points
# are not guaranteed to round-trip in those targets.
for _lang, _ord_tpl, _chr_tpl in [
    ('Python', 'ord({0})', 'chr({0})'),
    ('JavaScript', '({0}).charCodeAt(0)', 'String.fromCharCode({0})'),
    ('TypeScript', '({0}).charCodeAt(0)', 'String.fromCharCode({0})'),
    ('PHP', 'ord({0})', 'chr({0})'),
    ('Java', '(long)(({0}).charAt(0))', 'Character.toString((char)({0}))'),
    ('C#', '(long)(({0})[0])', '((char)({0})).ToString()'),
    ('C++', '(long long)(unsigned char)(({0})[0])', 'std::string(1, (char)({0}))'),
    ('C', '(long)((unsigned char)({0})[0])', '((char[]){(char)({0}), \\0})'),
    ('Go', 'int([]rune({0})[0])', 'string(rune({0}))'),
    ('Kotlin', '({0})[0].code', '({0}).toInt().toChar().toString()'),
    ('Swift', 'Int(({0}).unicodeScalars.first!.value)', 'String(UnicodeScalar(Int({0}))!)'),
    ('R', 'utf8ToInt({0})[1]', 'intToUtf8({0})'),
    ('MATLAB', 'double(char({0}(1)))', 'char({0})'),
    ('Pseudocode', 'Ord({0})', 'Chr({0})'),
]:
    if _lang in GENERATORS:
        GENERATORS[_lang].F.setdefault('ord', _ord_tpl)
        GENERATORS[_lang].F.setdefault('chr', _chr_tpl)

TYPE_WORDS = {'integer': 'Integer', 'real': 'Real', 'string': 'String', 'boolean': 'Boolean', 'none': 'None'}


def parse_pseudocode(text):
    doc = empty_document()
    main = doc['functions'][0]
    frames = [{'kind': 'root', 'block': main['body']}]
    lineno = 0

    def err(msg):
        raise ParseError('Line {0}: {1}'.format(lineno, msg))

    def chk(expr):
        if not expr.strip():
            err('missing expression')
        try:
            parse_expr(expr)
        except FlowError as e:
            err(str(e))
        return expr.strip()

    def add(n):
        frames[-1]['block'].append(n)

    def pop_to(kind):
        if not any(f['kind'] == kind for f in frames):
            err('unexpected End ' + kind)
        while True:
            f = frames.pop()
            if f['kind'] == kind and not f.get('chain'):
                return

    for raw in text.replace('\r', '').split('\n'):
        lineno += 1
        line = raw.strip()
        if not line:
            continue
        if line.startswith('//'):
            add(node('Comment', text=line[2:].strip()))
            continue
        m = re.match(r'^(\w+)\b\s*(.*)$', line)
        word = m.group(1).lower() if m else ''
        rest = m.group(2).strip() if m else ''
        if word == 'declare':
            mm = re.match(r'^(\w+)\s+(.+)$', rest)
            if not mm or mm.group(1).lower() not in TYPE_WORDS or mm.group(1).lower() == 'none':
                err('Declare needs a type: Declare Integer n, total')
            t = TYPE_WORDS[mm.group(1).lower()]
            body = mm.group(2).strip()
            am = re.match(r'^([A-Za-z_]\w*)\s*\[(.*)\]$', body)
            if am:
                add(node('Declare', name=am.group(1), type=t, array=True, size=chk(am.group(2))))
            else:
                try:
                    names(body)
                except FlowError as e:
                    err(str(e))
                add(node('Declare', name=', '.join(v.strip() for v in body.split(',')), type=t, array=False))
        elif word == 'input':
            add(node('Input', variable=chk(rest)))
        elif word == 'output':
            nl = True
            mm = re.match(r'^(.*\S)\s+NoNewline$', rest, re.I)
            if mm:
                rest, nl = mm.group(1), False
            add(node('Output', expression=chk(rest), newline=nl))
        elif word == 'call':
            add(node('Call', expression=chk(rest)))
        elif word == 'break' and not rest:
            add(node('Break'))
        elif word == 'continue' and not rest:
            add(node('Continue'))
        elif word == 'return':
            if frames[-1]['kind'] == 'root' or True:
                add(node('Return', expression=chk(rest) if rest else ''))
        elif word == 'if':
            if not re.search(r'\s+then$', rest, re.I):
                err('If needs Then at the end of the line')
            n = node('If', expression=chk(re.sub(r'\s+then$', '', rest, flags=re.I)))
            add(n)
            frames.append({'kind': 'If', 'node': n, 'block': n['true']})
        elif word == 'else':
            top = frames[-1]
            if top['kind'] != 'If':
                err('Else without If')
            mm = re.match(r'^if\b\s*(.*)$', rest, re.I)
            if mm:
                if not re.search(r'\s+then$', mm.group(1), re.I):
                    err('Else If needs Then at the end of the line')
                n = node('If', expression=chk(re.sub(r'\s+then$', '', mm.group(1), flags=re.I)))
                top['node']['false'].append(n)
                frames.append({'kind': 'If', 'node': n, 'block': n['true'], 'chain': True})
            elif rest:
                err('unexpected text after Else')
            else:
                top['block'] = top['node']['false']
        elif word == 'while':
            n = node('While', expression=chk(rest))
            add(n)
            frames.append({'kind': 'While', 'node': n, 'block': n['body']})
        elif word == 'do':
            n = node('Do', expression='true')
            add(n)
            frames.append({'kind': 'Do', 'node': n, 'block': n['body']})
        elif word == 'loop':
            mm = re.match(r'^while\b\s*(.*)$', rest, re.I)
            if not mm or frames[-1]['kind'] != 'Do':
                err('Loop While must close a Do block')
            frames[-1]['node']['expression'] = chk(mm.group(1))
            frames.pop()
        elif word == 'for':
            mm = re.match(r'^([A-Za-z_]\w*)\s*=\s*(.+)$', rest)
            if not mm:
                err('For syntax: For i = 1 To 10 [Step 2]')
            v, spec = mm.group(1), mm.group(2)
            pos = split_top(' ' + spec, 'To')
            direction = 'inc'
            pos2 = split_top(' ' + spec, 'DownTo')
            if pos2 and (not pos or pos2[0] < pos[0]):
                pos, direction = pos2, 'dec'
            if not pos:
                err('For needs To (or DownTo)')
            sp = ' ' + spec
            start = sp[:pos[0]].strip()
            tail = sp[pos[1]:].strip()
            step = '1'
            st = split_top(' ' + tail, 'Step')
            if st:
                step = (' ' + tail)[st[1]:].strip()
                tail = (' ' + tail)[:st[0]].strip()
            n = node('For', variable=v, start=chk(start), end=chk(tail), step=chk(step), direction=direction)
            add(n)
            frames.append({'kind': 'For', 'node': n, 'block': n['body']})
        elif word == 'end':
            kind = rest.lower()
            if kind == 'if':
                pop_to('If')
            elif kind == 'while':
                pop_to('While')
            elif kind == 'for':
                pop_to('For')
            elif kind == 'function':
                if frames[-1]['kind'] != 'Function':
                    err('End Function without matching Function')
                frames.pop()
            else:
                err('unknown block end: End ' + rest)
        elif word == 'function':
            if frames[-1]['kind'] != 'root':
                err('Functions cannot be nested')
            mm = re.match(r'^([A-Za-z_]\w*)\s*\((.*)\)\s*(?:returns\s+(\w+))?$', rest, re.I)
            if not mm:
                err('Function syntax: Function Name(Integer a, Real b[]) Returns Integer')
            params = []
            for p in split_commas(mm.group(2)):
                if not p:
                    continue
                pm = re.match(r'^(\w+)\s+([A-Za-z_]\w*)\s*(\[\s*\])?$', p)
                if not pm or pm.group(1).lower() not in TYPE_WORDS or pm.group(1).lower() == 'none':
                    err('bad parameter: ' + p)
                params.append({'name': pm.group(2), 'type': TYPE_WORDS[pm.group(1).lower()], 'array': bool(pm.group(3))})
            rt = 'None'
            if mm.group(3):
                if mm.group(3).lower() not in TYPE_WORDS:
                    err('unknown return type ' + mm.group(3))
                rt = TYPE_WORDS[mm.group(3).lower()]
            f = {'name': mm.group(1), 'type': rt, 'variable': '', 'parameters': params, 'body': []}
            doc['functions'].append(f)
            frames.append({'kind': 'Function', 'block': f['body']})
        else:
            am = re.match(r'^([A-Za-z_]\w*(?:\s*\[.*\])?)\s*(?:<-|=)(?!=)\s*(.+)$', line)
            if not am:
                err('cannot understand: ' + line)
            add(node('Assign', variable=chk(am.group(1)), expression=chk(am.group(2))))
    if len(frames) > 1:
        lineno += 1
        err('missing End for ' + frames[-1]['kind'])
    try:
        validate(doc)
    except FlowError as e:
        raise ParseError(str(e))
    return doc


# ----------------------------------------------------------------------------
# Python -> flowchart
# ----------------------------------------------------------------------------
PY_TYPES = {'int': 'Integer', 'float': 'Real', 'str': 'String', 'bool': 'Boolean'}
MATH_MAP = {'sqrt': 'Sqrt', 'sin': 'Sin', 'cos': 'Cos', 'tan': 'Tan', 'asin': 'Arcsin', 'acos': 'Arccos',
            'atan': 'Arctan', 'log': 'Log', 'log10': 'Log10', 'floor': 'Floor', 'ceil': 'Ceiling',
            'fabs': 'Abs'}
BUILTIN_MAP = {'str': 'ToString', 'int': 'ToInteger', 'float': 'ToReal', 'len': 'Length', 'abs': 'Abs',
               'round': 'Round', 'min': 'Min', 'max': 'Max', 'ord': 'Ord', 'chr': 'Chr',
               'flowDictionaryError': 'FlowDictionaryError', 'FlowDictionaryError': 'FlowDictionaryError',
               'error': 'FlowDictionaryError'}
PREC = {'or': 1, 'and': 2, 'not': 3, 'cmp': 4, 'cat': 5, 'add': 6, 'mul': 7, 'neg': 8, 'pow': 9, 'atom': 100}


def join_type(a, b, name='?'):
    if a is None:
        return b
    if b is None or a == b:
        return a
    if set((a, b)) == set(('Integer', 'Real')):
        return 'Real'
    raise ParseError('Variable {0} is used as both {1} and {2}; a flowchart variable has one type.'.format(name, a, b))


def pslice(n):
    s = n.slice
    return s.value if isinstance(s, _AST_INDEX) and _AST_INDEX else s


def cval(n):
    """Return (True, value) for a constant node (any Python version)."""
    if _AST_CONSTANT and isinstance(n, _AST_CONSTANT):
        return True, n.value
    if _AST_LEGACY and isinstance(n, _AST_LEGACY):
        for attr in ('n', 's', 'value'):
            if hasattr(n, attr):
                return True, getattr(n, attr)
    if isinstance(n, ast.Name) and n.id in ('True', 'False'):
        return True, n.id == 'True'
    return False, None


class Scope(object):
    def __init__(self, name):
        self.name = name
        self.vars = {}
        self.ret = None
        self.ret_fixed = False
        self.params = []
        self.declared = set()
        self.fixed = set()


class PyImporter(object):
    def __init__(self, text):
        self.text = text
        self.lines = text.split('\n')
        self.comments = []
        try:
            for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                if tok[0] == tokenize.COMMENT:
                    row, col = tok[2]
                    if self.lines[row - 1][:col].strip() == '':
                        c = tok[1].lstrip('#')
                        if not c.startswith('!') and 'coding' not in c[:12]:
                            self.comments.append([row, col, c.strip(), False])
        except (tokenize.TokenError, IndentationError, SyntaxError):
            pass
        self.funcs = {}
        self.scopes = {}
        self.counter = 0

    def fail(self, node, msg):
        raise ParseError('Line {0}: {1}'.format(getattr(node, 'lineno', '?'), msg))

    # ------------------------------------------------------------- inference
    def elem_list(self, n):
        """If n builds a list, return (element type or None, True) else None."""
        if isinstance(n, ast.ListComp) and len(n.generators) == 1 and isinstance(n.generators[0].target, ast.Name):
            g = n.generators[0]
            sc = self.cur_scope
            if g.target.id not in sc.vars:
                sc.vars[g.target.id] = ['Integer', False]
            return (self.infer(n.elt, sc), True)
        if isinstance(n, ast.List):
            t = None
            for e in getattr(n, '_portable_type_values', n.elts):
                t = join_type(t, self.infer(e, self.cur_scope), 'list')
            return (t, True)
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Mult):
            for a, b in ((n.left, n.right), (n.right, n.left)):
                if isinstance(a, ast.List) and len(a.elts) == 1:
                    return (self.infer(a.elts[0], self.cur_scope), True)
        return None

    def input_kind(self, n):
        """Detect input(...) patterns: returns (type, prompt_node or None) or None."""
        def is_input(x):
            return isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == 'input'
        while isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ('strip', 'rstrip', 'lstrip') and not n.args:
            n = n.func.value
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ('int', 'float', 'str') and len(n.args) == 1:
            inner = n.args[0]
            while isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr in ('strip', 'rstrip', 'lstrip') and not inner.args:
                inner = inner.func.value
            n = ast.Call(func=n.func, args=[inner], keywords=[])
        if is_input(n):
            return 'String', (n.args[0] if n.args else None)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ('int', 'float', 'str') \
                and len(n.args) == 1 and is_input(n.args[0]):
            return PY_TYPES[n.func.id], (n.args[0].args[0] if n.args[0].args else None)
        if isinstance(n, ast.Compare) and len(n.ops) == 1 and isinstance(n.ops[0], ast.In):
            x = n.left
            while isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute) and x.func.attr in ('strip', 'lower'):
                x = x.func.value
            if is_input(x):
                return 'Boolean', (x.args[0] if x.args else None)
        return None

    def infer(self, n, sc):
        ok, v = cval(n)
        if ok:
            return 'Boolean' if isinstance(v, bool) else 'Integer' if isinstance(v, int) else 'Real' if isinstance(v, float) else 'String' if isinstance(v, str) else None
        if isinstance(n, ast.Name):
            if n.id in sc.vars:
                return sc.vars[n.id][0]
            return None
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == 'math' and n.attr == 'pi':
            return 'Real'
        if isinstance(n, ast.Subscript):
            if isinstance(n.value, ast.Name) and n.value.id in sc.vars:
                return sc.vars[n.value.id][0]
            return None
        if hasattr(ast, 'JoinedStr') and isinstance(n, ast.JoinedStr):
            return 'String'
        if isinstance(n, ast.BinOp):
            l, r = self.infer(n.left, sc), self.infer(n.right, sc)
            if isinstance(n.op, ast.BitAnd):
                return 'String'
            if isinstance(n.op, ast.Add) and 'String' in (l, r):
                return 'String'
            if isinstance(n.op, ast.Div) and getattr(n, '_cdiv', False) and (l, r) == ('Integer', 'Integer'):
                return 'Integer'
            if isinstance(n.op, ast.Div):
                return 'Real'
            if isinstance(n.op, ast.Pow):
                return 'Integer' if (l, r) == ('Integer', 'Integer') else 'Real' if l and r else None
            if l is None or r is None:
                return l or r
            return 'Real' if 'Real' in (l, r) else l
        if isinstance(n, ast.UnaryOp):
            return 'Boolean' if isinstance(n.op, ast.Not) else self.infer(n.operand, sc)
        if isinstance(n, (ast.Compare, ast.BoolOp)):
            return 'Boolean'
        if isinstance(n, ast.IfExp):
            a, b = self.infer(n.body, sc), self.infer(n.orelse, sc)
            return a if b is None or a == b else b if a is None else ('Real' if set((a, b)) == set(('Integer', 'Real')) else a)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ('upper', 'strip', 'lstrip', 'rstrip', 'lower'):
            return 'String'
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'contains':
            return 'Boolean'
        if isinstance(n, ast.Call):
            ik = self.input_kind(n)
            if ik:
                return ik[0]
            if isinstance(n.func, ast.Name):
                nm = n.func.id
                if nm in self.funcs:
                    return self.scopes[nm].ret
                if nm in ('int', 'len', 'round', 'ord'):
                    return 'Integer' if not (nm == 'round' and len(n.args) > 1) else 'Real'
                if nm == 'float':
                    return 'Real'
                if nm in ('str', 'chr'):
                    return 'String'
                if nm == 'bool':
                    return 'Boolean'
                if nm in ('abs', 'min', 'max'):
                    t = None
                    for a in n.args:
                        t = join_type(t, self.infer(a, sc)) if t != 'Real' else t
                    return t
            if isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name):
                if n.func.value.id == 'math':
                    return 'Integer' if n.func.attr in ('floor', 'ceil') else 'Real'
                if n.func.value.id == 'random':
                    return 'Integer'
        return None

    def collect(self, stmts, sc):
        """One inference pass over statements; returns True if anything changed."""
        changed = [False]

        def setvar(name, t, arr=False):
            if name in sc.fixed:
                return
            old = sc.vars.get(name)
            if old is None:
                sc.vars[name] = [t, arr]
                changed[0] = True
                return
            nt = join_type(old[0], t, name)
            if nt != old[0] or (arr and not old[1]):
                old[0] = nt
                old[1] = old[1] or arr
                changed[0] = True

        for s in stmts:
            for sub in ast.walk(s):
                if isinstance(sub, (ast.FunctionDef, ast.ClassDef)) and sub is not s:
                    continue
                if isinstance(sub, ast.Assign):
                    for tg in sub.targets:
                        tgs = tg.elts if isinstance(tg, ast.Tuple) else [tg]
                        vals = sub.value.elts if isinstance(sub.value, ast.Tuple) and len(sub.value.elts) == len(tgs) else [sub.value] * len(tgs)
                        for t1, v1 in zip(tgs, vals):
                            if isinstance(t1, ast.Name):
                                el = self.elem_list(v1)
                                if el:
                                    setvar(t1.id, el[0], True)
                                else:
                                    setvar(t1.id, self.infer(v1, sc))
                            elif isinstance(t1, ast.Subscript) and isinstance(t1.value, ast.Name):
                                setvar(t1.value.id, self.infer(v1, sc), True)
                elif isinstance(sub, ast.AugAssign) and isinstance(sub.target, ast.Name):
                    setvar(sub.target.id, self.infer(ast.BinOp(left=sub.target, op=sub.op, right=sub.value), sc))
                elif isinstance(sub, ast.For) and isinstance(sub.target, ast.Name):
                    it = sub.iter
                    if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == 'range':
                        setvar(sub.target.id, 'Integer')
                    elif isinstance(it, ast.Name) and it.id in sc.vars:
                        setvar(sub.target.id, sc.vars[it.id][0] if sc.vars[it.id][1] else 'String')
                elif isinstance(sub, ast.For) and isinstance(sub.target, ast.Tuple) and len(sub.target.elts) == 2 \
                        and isinstance(sub.iter, ast.Call) and getattr(sub.iter.func, 'id', '') == 'enumerate' and sub.iter.args:
                    setvar(sub.target.elts[0].id, 'Integer')
                    a0 = sub.iter.args[0]
                    if isinstance(a0, ast.Name) and a0.id in sc.vars:
                        setvar(sub.target.elts[1].id, sc.vars[a0.id][0] if sc.vars[a0.id][1] else 'String')
                elif isinstance(sub, ast.Return) and sub.value is not None and not sc.ret_fixed:
                    val = sub.value.body if isinstance(sub.value, ast.IfExp) else sub.value
                    nt = join_type(sc.ret, self.infer(val, sc), 'return value')
                    if nt != sc.ret:
                        sc.ret = nt
                        changed[0] = True
                elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id in self.funcs:
                    callee = self.scopes[sub.func.id]
                    for p, a in zip(callee.params, sub.args):
                        if isinstance(a, ast.Name) and a.id in sc.vars and sc.vars[a.id][1]:
                            old = callee.vars[p]
                            if not old[1] or old[0] is None and sc.vars[a.id][0]:
                                join = join_type(old[0], sc.vars[a.id][0], p)
                                callee.vars[p] = [join, True]
                                changed[0] = True
                        else:
                            t = self.infer(a, sc)
                            old = callee.vars[p]
                            nt = join_type(old[0], t, p)
                            if nt != old[0]:
                                old[0] = nt
                                changed[0] = True
        return changed[0]

    # ------------------------------------------------------------- expressions
    def S(self, n, need=0, right=False):
        t, p = self.U(n)
        return '(' + t + ')' if (p < need or (p == need and right)) else t

    def ctype(self, n):
        return self.infer(n, self.cur_scope)

    def U(self, n):
        sc = self.cur_scope
        ok, v = cval(n)
        if ok:
            if isinstance(v, bool):
                return ('true' if v else 'false'), PREC['atom']
            if isinstance(v, str):
                return json.dumps(v, ensure_ascii=False), PREC['atom']
            if isinstance(v, (int, float)):
                return repr(v), PREC['atom']
            self.fail(n, 'this constant is not supported')
        if isinstance(n, ast.Name):
            return n.id, PREC['atom']
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == 'math' and n.attr == 'pi':
            return 'Pi', PREC['atom']
        if isinstance(n, ast.Subscript):
            if isinstance(pslice(n), ast.Slice):
                self.fail(n, 'slices are not supported')
            return self.S(n.value, PREC['atom']) + '[' + self.S(pslice(n)) + ']', PREC['atom']
        if hasattr(ast, 'JoinedStr') and isinstance(n, ast.JoinedStr):
            parts = []
            for e in n.values:
                if hasattr(ast, 'FormattedValue') and isinstance(e, ast.FormattedValue):
                    parts.append(self.tostring(e.value))
                else:
                    parts.append(self.S(e, PREC['cat']))
            return (' & '.join(parts) if parts else '""'), PREC['cat']
        if isinstance(n, ast.BinOp):
            op = type(n.op)
            lt, rt = self.ctype(n.left), self.ctype(n.right)
            if (op is ast.Add and 'String' in (lt, rt)) or op is ast.BitAnd:
                return self.S(n.left, PREC['cat']) + ' & ' + self.S(n.right, PREC['cat'], True), PREC['cat']
            if op is ast.Div and getattr(n, '_cdiv', False) and lt == 'Integer' and rt == 'Integer':
                return 'ToInteger(' + self.S(n.left, PREC['mul']) + ' / ' + self.S(n.right, PREC['mul'], True) + ')', PREC['atom']
            sym, p = {ast.Add: ('+', 6), ast.Sub: ('-', 6), ast.Mult: ('*', 7), ast.Div: ('/', 7),
                      ast.FloorDiv: ('//', 7), ast.Mod: ('%', 7), ast.Pow: ('^', 9)}.get(op, (None, 0))
            if sym is None:
                self.fail(n, 'operator not supported')
            if op is ast.Pow:
                return self.S(n.left, 10) + ' ^ ' + self.S(n.right, 10), p
            return self.S(n.left, p) + ' ' + sym + ' ' + self.S(n.right, p, True), p
        if isinstance(n, ast.UnaryOp):
            if isinstance(n.op, ast.Not):
                if self.ctype(n.operand) in ('Integer', 'Real') and not isinstance(n.operand, (ast.Compare, ast.BoolOp, ast.UnaryOp)):
                    return self.S(n.operand, PREC['cmp']) + ' == 0', PREC['cmp']
                return 'not ' + self.SB(n.operand, PREC['not']), PREC['not']
            if isinstance(n.op, ast.USub):
                return '-' + self.S(n.operand, PREC['neg']), PREC['neg']
            if isinstance(n.op, ast.UAdd):
                return self.S(n.operand, PREC['neg']), PREC['neg']
            self.fail(n, 'operator not supported')
        if isinstance(n, ast.BoolOp):
            isand = isinstance(n.op, ast.And)
            p = PREC['and'] if isand else PREC['or']
            return (' and ' if isand else ' or ').join(self.SB(v, p + 1) for v in n.values), p
        if isinstance(n, ast.Compare):
            syms = {ast.Eq: '==', ast.NotEq: '!=', ast.Lt: '<', ast.LtE: '<=', ast.Gt: '>', ast.GtE: '>='}
            parts, left = [], n.left
            for op, right in zip(n.ops, n.comparators):
                if isinstance(op, (ast.In, ast.NotIn)) and self.ctype(right) == 'String':
                    c = 'Contains(' + self.S(right) + ', ' + self.S(left) + ')'
                    parts.append(c if isinstance(op, ast.In) else 'not ' + c)
                    left = right
                    continue
                if type(op) not in syms:
                    self.fail(n, 'only == != < <= > >= comparisons (and `in` for strings) are supported')
                parts.append(self.S(left, 5) + ' ' + syms[type(op)] + ' ' + self.S(right, 5, True))
                left = right
            return (' and '.join(parts), PREC['and']) if len(parts) > 1 else (parts[0], PREC['cmp'])
        if isinstance(n, ast.Call):
            return self.ucall(n), PREC['atom']
        if isinstance(n, ast.IfExp):
            self.fail(n, 'a conditional expression (a if c else b) is supported only as `x = ...` or `return ...`')
        self.fail(n, 'this expression is not supported (' + type(n).__name__ + ')')

    def UB(self, n):
        """Expression used as a condition: integers/reals mean `!= 0` (C-style truthiness)."""
        ok, v = cval(n)
        if ok and isinstance(v, (int, float)) and not isinstance(v, bool):
            return ('true' if v else 'false'), PREC['atom']
        if self.ctype(n) == 'String':
            return 'Length(' + self.S(n) + ') != 0', PREC['cmp']
        if not isinstance(n, (ast.Compare, ast.BoolOp, ast.UnaryOp)) and self.ctype(n) in ('Integer', 'Real') \
                and not (isinstance(n, ast.Call) and getattr(n.func, 'id', '') in ('input',)):
            return self.S(n, PREC['cmp']) + ' != 0', PREC['cmp']
        return self.U(n)

    def SB(self, n, need, right=False):
        t, p = self.UB(n)
        return '(' + t + ')' if (p < need or (p == need and right)) else t

    def tostring(self, n):
        return self.S(n, PREC['cat']) if self.ctype(n) == 'String' else 'ToString(' + self.S(n) + ')'

    def ucall(self, n):
        if n.keywords or any(isinstance(a, ast.Starred) for a in n.args):
            self.fail(n, 'keyword/star arguments are not supported')
        args = [self.S(a) for a in n.args]
        if getattr(n, '_portable_fail', False):
            return 'FlowDictionaryError(' + ', '.join(args) + ')'
        f = n.func
        if isinstance(f, ast.Name):
            if f.id in self.funcs:
                return f.id + '(' + ', '.join(args) + ')'
            if f.id in BUILTIN_MAP:
                if f.id == 'int' and n.args and self.ctype(n.args[0]) == 'Real' and False:
                    pass
                return BUILTIN_MAP[f.id] + '(' + ', '.join(args) + ')'
            if f.id == 'pow' and len(args) == 2:
                return '(' + self.S(n.args[0], 10) + ' ^ ' + self.S(n.args[1], 10) + ')'
            if f.id == 'input':
                self.fail(n, 'input() must be used as `x = input()`, `x = int(input())` or `x = float(input())`')
            self.fail(n, 'unknown function ' + f.id)
        if isinstance(f, ast.Attribute) and f.attr == 'lower' and not n.args and isinstance(f.value, ast.Call) \
                and isinstance(f.value.func, ast.Name) and f.value.func.id == 'str' and len(f.value.args) == 1:
            return 'ToString(' + self.S(f.value.args[0]) + ')'
        if isinstance(f, ast.Attribute) and not n.args and f.attr in ('upper', 'lower', 'strip', 'lstrip', 'rstrip'):
            return {'upper': 'ToUpper', 'lower': 'ToLower'}.get(f.attr, 'Trim') + '(' + self.S(f.value) + ')'
        if isinstance(f, ast.Attribute) and f.attr == 'contains' and len(n.args) == 1:
            return 'Contains(' + self.S(f.value) + ', ' + self.S(n.args[0]) + ')'
        if isinstance(f, ast.Attribute) and not n.args and f.attr in ('isupper', 'islower'):
            value = self.S(f.value)
            upper = 'ToUpper(' + value + ')'
            lower = 'ToLower(' + value + ')'
            # Python's single-character ASCII behaviour, including the requirement
            # that the character has a case, is preserved for ordinary text input.
            return '(' + value + ' == ' + upper + ' and ' + value + ' != ' + lower + ')' if f.attr == 'isupper' else '(' + value + ' == ' + lower + ' and ' + value + ' != ' + upper + ')'
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
            if f.value.id == 'math' and f.attr in MATH_MAP:
                return MATH_MAP[f.attr] + '(' + ', '.join(args) + ')'
            if f.value.id == 'math' and f.attr == 'pow' and len(args) == 2:
                return '(' + self.S(n.args[0], 10) + ' ^ ' + self.S(n.args[1], 10) + ')'
            if f.value.id == 'random' and f.attr == 'randrange' and len(args) == 1:
                return 'Random(' + args[0] + ')'
            if f.value.id == 'random' and f.attr == 'randint' and len(args) == 2:
                return '(' + args[0] + ' + Random(' + self.S(n.args[1], 6) + ' - ' + self.S(n.args[0], 6, True) + ' + 1))'
        self.fail(n, 'this function call is not supported')

    # ------------------------------------------------------------- statements
    def comments_in(self, col, lo, hi):
        out = []
        for c in self.comments:
            if not c[3] and c[1] == col and lo <= c[0] <= hi:
                c[3] = True
                out.append(c)
        return out

    def end_line(self, s):
        return max([getattr(x, 'lineno', 0) for x in ast.walk(s)] + [getattr(s, 'lineno', 0)])

    def block(self, stmts, lo, hi, level):
        """Convert statements into nodes, interleaving standalone comments."""
        out = []
        if not stmts:
            return out
        col = stmts[0].col_offset
        items = []
        for i, s in enumerate(stmts):
            nxt = stmts[i + 1].lineno - 1 if i + 1 < len(stmts) else hi
            items.append((s.lineno, 'S', s, nxt))
        for c in self.comments_in(col, lo, hi):
            items.append((c[0], 'C', c, 0))
        items.sort(key=lambda x: (x[0], x[1] == 'S'))
        for line, kind, obj, nxt in items:
            if kind == 'C':
                out.append(node('Comment', text=obj[2]))
                continue
            before = len(self.hoist)
            nodes = self.stmt(obj, nxt, level)
            if level > 0 and len(self.hoist) > before:
                pass
            out.extend(nodes)
        return out

    def declare_nodes(self, name, t, arr=False, size=None):
        sc = self.cur_scope
        sc.declared.add(name)
        if arr:
            return node('Declare', name=name, type=t or 'Integer', array=True, size=size)
        return node('Declare', name=name, type=t or 'Integer', array=False)

    def ensure(self, name, node_for, level, default_ok=False):
        """Return Declare nodes needed before the first assignment of `name`."""
        sc = self.cur_scope
        if name in sc.declared:
            return []
        info = sc.vars.get(name, [None, False])
        d = self.declare_nodes(name, info[0])
        if level > 0:
            self.hoist.append(d)
            return []
        return [d]

    def lower_ifexp(self, expr, pre, level):
        """Replace conditional expressions nested inside `expr` by temporaries set by If statements."""
        sc = self.cur_scope
        if isinstance(expr, ast.IfExp):
            test = self.lower_ifexp(expr.test, pre, level)
            a = self.lower_ifexp(expr.body, pre, level)
            b = self.lower_ifexp(expr.orelse, pre, level)
            self.counter += 1
            tmp = 'cond' if self.counter == 1 else 'cond' + str(self.counter)
            t = self.infer(a, sc) or self.infer(b, sc) or 'Integer'
            sc.vars[tmp] = [t, False]
            pre.extend(self.ensure(tmp, None, level))
            pre.append(node('If', expression=self.UB(test)[0],
                            true=[node('Assign', variable=tmp, expression=self.U(a)[0])],
                            false=[node('Assign', variable=tmp, expression=self.U(b)[0])]))
            return NM(tmp)
        for field, value in ast.iter_fields(expr):
            if isinstance(value, ast.AST):
                setattr(expr, field, self.lower_ifexp(value, pre, level))
            elif isinstance(value, list):
                setattr(expr, field, [self.lower_ifexp(v, pre, level) if isinstance(v, ast.AST) else v for v in value])
        return expr

    def has_ifexp(self, expr):
        return any(isinstance(x, ast.IfExp) for x in ast.walk(expr))

    def stmt(self, s, nxt, level):
        top = isinstance(s, ast.Expr) or isinstance(s, ast.AugAssign) or (isinstance(s, ast.Return) and s.value is not None
                                                                          and not isinstance(s.value, ast.IfExp)) \
            or (isinstance(s, ast.Assign) and not isinstance(s.value, (ast.IfExp, ast.ListComp))) or isinstance(s, ast.If)
        if top:
            fld = 'test' if isinstance(s, ast.If) else 'value'
            val = getattr(s, fld, None)
            if val is not None and self.has_ifexp(val):
                pre = []
                setattr(s, fld, self.lower_ifexp(val, pre, level))
                return pre + self.stmt(s, nxt, level)
        sc = self.cur_scope
        if isinstance(s, ast.Expr):
            return self.expr_stmt(s)
        if isinstance(s, ast.Assign):
            return self.assign(s, level)
        if isinstance(s, ast.AugAssign):
            if not isinstance(s.target, (ast.Name, ast.Subscript)):
                self.fail(s, 'unsupported assignment target')
            sym = {ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/', ast.FloorDiv: '//', ast.Mod: '%', ast.Pow: '^'}.get(type(s.op))
            if not sym:
                self.fail(s, 'operator not supported')
            tgt = self.S(s.target)
            tmp = ast.BinOp(left=s.target, op=s.op, right=s.value)
            ast.copy_location(tmp, s)
            pre = self.ensure(s.target.id, None, level) if isinstance(s.target, ast.Name) else []
            return pre + [node('Assign', variable=tgt, expression=self.U(tmp)[0])]
        if isinstance(s, ast.If):
            lo = s.lineno + 1
            hi = (s.orelse[0].lineno - 2) if s.orelse else nxt
            t = self.block(s.body, lo, hi, level + 1)
            f = self.block(s.orelse, (s.orelse[0].lineno - 1) if s.orelse else 0, nxt, level + 1) if s.orelse else []
            return [node('If', expression=self.UB(s.test)[0], true=t, false=f)]
        if isinstance(s, ast.While):
            return self.while_stmt(s, nxt, level)
        if isinstance(s, ast.For):
            return self.for_stmt(s, nxt, level)
        if isinstance(s, ast.FunctionDef):
            self.fail(s, 'functions can only be defined at the top level')
        if isinstance(s, ast.Return):
            if sc.name == 'Main' and s.value is None:
                return [node('Return', expression='')]
            if isinstance(s.value, ast.IfExp):
                v = s.value
                return [node('If', expression=self.U(v.test)[0], true=[node('Return', expression=self.U(v.body)[0])],
                             false=[node('Return', expression=self.U(v.orelse)[0])])]
            return [node('Return', expression=self.U(s.value)[0] if s.value is not None else '')]
        if isinstance(s, (ast.Pass, ast.Import, ast.ImportFrom)):
            return []
        if isinstance(s, ast.Raise):
            ex = s.exc
            if isinstance(ex, ast.Name) and ex.id == 'SystemExit' or (isinstance(ex, ast.Call) and isinstance(ex.func, ast.Name) and ex.func.id == 'SystemExit'):
                return [node('Return', expression='')]
        if isinstance(s, ast.Break):
            return [node('Break')]
        if isinstance(s, ast.Continue):
            return [node('Continue')]
        self.fail(s, type(s).__name__ + ' statements are not supported by flowchart shapes')

    def expr_stmt(self, s):
        v = s.value
        ok, c = cval(v)
        if ok:
            if isinstance(c, str):
                return [node('Comment', text=line.strip()) for line in c.strip().splitlines()]
            return []
        if isinstance(v, ast.Call):
            f = v.func
            if getattr(v, '_portable_fail', False) or (isinstance(f, ast.Name) and f.id in ('flowDictionaryError', 'FlowDictionaryError', 'error') and f.id not in self.funcs):
                return [node('Call', expression=self.U(v)[0])]
            if isinstance(f, ast.Name) and f.id == 'print':
                return [self.print_node(v)]
            if isinstance(f, ast.Name) and f.id in ('exit', 'quit'):
                return [node('Return', expression='')]
            if isinstance(f, ast.Attribute) and f.attr == 'exit' and isinstance(f.value, ast.Name) and f.value.id == 'sys':
                return [node('Return', expression='')]
            if isinstance(f, ast.Name) and f.id in self.funcs:
                return [node('Call', expression=self.U(v)[0])]
        self.fail(s, 'this statement is not supported (use print, input, assignments, calls to your own functions)')

    def print_node(self, v):
        sep, end = ' ', '\n'
        for kw in v.keywords:
            ok, c = cval(kw.value)
            if kw.arg == 'end' and ok and isinstance(c, str):
                end = c
            elif kw.arg == 'sep' and ok and isinstance(c, str):
                sep = c
            elif kw.arg == 'file' or kw.arg == 'flush':
                continue
            else:
                self.fail(v, 'print() option not supported: ' + str(kw.arg))
        if any(isinstance(a, ast.Starred) for a in v.args):
            self.fail(v, 'print(*args) is not supported')
        if not v.args:
            parts = ['""']
        elif len(v.args) == 1:
            parts = [self.U(v.args[0])[0]]
        else:
            parts = []
            for i, a in enumerate(v.args):
                if i and sep != '':
                    parts.append(json.dumps(sep))
                parts.append(self.tostring(a))
            parts = [' & '.join(parts)]
        expr = parts[0]
        nl = True
        if end == '':
            nl = False
        elif end != '\n':
            expr = expr + ' & ' + json.dumps(end)
            nl = False
        return node('Output', expression=expr, newline=nl)

    def assign(self, s, level):
        sc = self.cur_scope
        if len(s.targets) != 1:
            self.fail(s, 'chained assignment is not supported')
        tg = s.targets[0]
        if isinstance(tg, ast.Tuple):
            if not isinstance(s.value, ast.Tuple) or len(tg.elts) != len(s.value.elts):
                self.fail(s, 'tuple assignment needs the same number of values')
            used = set(x.id for x in ast.walk(s.value) if isinstance(x, ast.Name))
            if any(isinstance(t, ast.Name) and t.id in used for t in tg.elts) or any(isinstance(t, ast.Subscript) for t in tg.elts):
                out, temps = [], []
                for v1 in s.value.elts:
                    self.counter += 1
                    tmp = 'swap' if self.counter == 1 else 'swap' + str(self.counter)
                    self.cur_scope.vars[tmp] = [self.infer(v1, self.cur_scope), False]
                    temps.append(tmp)
                    fake = ast.Assign(targets=[ast.Name(id=tmp)], value=v1)
                    ast.copy_location(fake, s)
                    out.extend(self.assign(fake, level))
                for t1, tmp in zip(tg.elts, temps):
                    fake = ast.Assign(targets=[t1], value=ast.Name(id=tmp))
                    ast.copy_location(fake, s)
                    out.extend(self.assign(fake, level))
                return out
            out = []
            for t1, v1 in zip(tg.elts, s.value.elts):
                fake = ast.Assign(targets=[t1], value=v1)
                ast.copy_location(fake, s)
                out.extend(self.assign(fake, level))
            return out
        if not isinstance(tg, (ast.Name, ast.Subscript)):
            self.fail(s, 'unsupported assignment target')
        if isinstance(s.value, ast.IfExp):
            v = s.value
            pre = self.ensure(tg.id, None, level) if isinstance(tg, ast.Name) else []
            tgt = self.S(tg)
            return pre + [node('If', expression=self.UB(v.test)[0],
                               true=[node('Assign', variable=tgt, expression=self.U(v.body)[0])],
                               false=[node('Assign', variable=tgt, expression=self.U(v.orelse)[0])])]
        if isinstance(s.value, ast.ListComp) and isinstance(tg, ast.Name):
            return self.comprehension(s, tg.id, level)
        ik = self.input_kind(s.value)
        if ik:
            pre = self.ensure(tg.id, None, level) if isinstance(tg, ast.Name) else []
            out = list(pre)
            if ik[1] is not None:
                out.append(node('Output', expression=self.U(ik[1])[0], newline=False))
            out.append(node('Input', variable=self.S(tg)))
            return out
        if isinstance(tg, ast.Name):
            el = self.elem_list(s.value)
            if el:
                return self.array_assign(s, tg.id, el, level)
            if tg.id in sc.vars and sc.vars[tg.id][1] and not isinstance(s.value, ast.Name):
                self.fail(s, 'array {0} is re-created; assign its elements instead'.format(tg.id))
            pre = []
            if tg.id not in sc.declared:
                info = sc.vars.get(tg.id, [None, False])
                ok, c = cval(s.value)
                default = {'Integer': 0, 'Real': 0.0, 'String': '', 'Boolean': False}.get(info[0])
                if level == 0 and ok and info[0] and type(c) == type(default) and c == default:
                    return [self.merge_decl(self.declare_nodes(tg.id, info[0]))]
                pre = self.ensure(tg.id, None, level)
            return pre + [node('Assign', variable=tg.id, expression=self.U(s.value)[0])]
        return [node('Assign', variable=self.S(tg), expression=self.U(s.value)[0])]

    def merge_decl(self, d):
        return d

    def comprehension(self, s, name, level):
        """x = [expr for v in range(...)]  ->  array + For loop."""
        v = s.value
        g = v.generators[0]
        it = g.iter
        if level > 0 or g.ifs or not isinstance(g.target, ast.Name) or not (
                isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == 'range'
                and 1 <= len(it.args) <= 2):
            self.fail(s, 'list comprehensions are supported as `x = [expr for v in range(a, b)]` at the top level')
        sc = self.cur_scope
        if name in sc.declared:
            self.fail(s, 'array {0} is re-created; assign its elements instead'.format(name))
        var = g.target.id
        start = '0' if len(it.args) == 1 else self.U(it.args[0])[0]
        stop_node = it.args[0] if len(it.args) == 1 else it.args[1]
        size = self.U(stop_node)[0] if start == '0' else self.S(stop_node, PREC['add']) + ' - ' + self.S(it.args[0], PREC['add'], True)
        info = sc.vars.get(name, ['Integer', True])
        t = info[0] or 'Integer'
        nodes = [self.declare_nodes(name, t, True, size)]
        nodes.extend(self.ensure(var, None, level))
        idx = var if start == '0' else '{0} - {1}'.format(var, start)
        body = [node('Assign', variable='{0}[{1}]'.format(name, idx), expression=self.U(v.elt)[0])]
        nodes.append(node('For', variable=var, start=start, end=self.shift_end(stop_node, -1), step='1', direction='inc', body=body))
        return nodes

    def array_assign(self, s, name, el, level):
        sc = self.cur_scope
        if name in sc.declared:
            self.fail(s, 'array {0} is re-created; assign its elements instead'.format(name))
        t = el[0] or 'Integer'
        v = s.value
        if isinstance(v, ast.List):
            d = self.declare_nodes(name, t, True, str(getattr(v, '_portable_size', len(v.elts))))
            nodes = [d] + [node('Assign', variable='{0}[{1}]'.format(name, i), expression=self.U(e)[0]) for i, e in enumerate(v.elts)]
        else:
            lst, cnt = (v.left, v.right) if isinstance(v.left, ast.List) else (v.right, v.left)
            nodes = [self.declare_nodes(name, t, True, self.U(cnt)[0])]
            ok, c = cval(lst.elts[0])
            default = {'Integer': 0, 'Real': 0.0, 'String': '', 'Boolean': False}[t]
            if not (ok and type(c) == type(default) and c == default):
                self.fail(s, 'arrays are created with default values: use [0] * n, [0.0] * n, [""] * n or [False] * n')
        if level > 0:
            self.fail(s, 'create arrays at the top level of the program or function')
        return nodes

    def while_stmt(self, s, nxt, level):
        ok, c = cval(s.test)
        body = s.body
        if ok and c is True and body and isinstance(body[-1], ast.If) and not body[-1].orelse \
                and len(body[-1].body) == 1 and isinstance(body[-1].body[0], ast.Break):
            last = body[-1]
            test = last.test
            cond = self.UB(test.operand)[0] if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) \
                else 'not ' + self.SB(test, PREC['not'])
            inner = self.block(body[:-1], s.lineno + 1, last.lineno - 1, level + 1)
            return [node('Do', expression=cond, body=inner)]
        inner = self.block(body, s.lineno + 1, nxt, level + 1)
        return [node('While', expression=self.UB(s.test)[0], body=inner)]

    def shift_end(self, a, k):
        ok, v = cval(a)
        if ok and isinstance(v, int) and not isinstance(v, bool):
            return str(v + k)
        if isinstance(a, ast.BinOp) and isinstance(a.op, (ast.Add, ast.Sub)):
            ok2, v2 = cval(a.right)
            if ok2 and isinstance(v2, int) and not isinstance(v2, bool):
                d = (v2 if isinstance(a.op, ast.Add) else -v2) + k
                base = self.S(a.left, PREC['add'])
                if d == 0:
                    return self.U(a.left)[0]
                return base + (' + ' if d > 0 else ' - ') + str(abs(d))
        return self.S(a, PREC['add']) + (' + ' if k > 0 else ' - ') + str(abs(k))

    def for_stmt(self, s, nxt, level):
        if s.orelse:
            self.fail(s, 'for/else is not supported')
        if isinstance(s.iter, ast.List):
            self.counter += 1
            tmp = 'items' if self.counter == 1 else 'items' + str(self.counter)
            fake = ast.Assign(targets=[NM(tmp)], value=s.iter)
            ast.copy_location(fake, s)
            self.cur_scope.vars.setdefault(tmp, [self.infer(s.iter.elts[0], self.cur_scope) if s.iter.elts else 'Integer', True])
            pre0 = self.assign(fake, level)
            s.iter = NM(tmp)
            return pre0 + self.for_stmt(s, nxt, level)
        if isinstance(s.target, ast.Tuple) and len(s.target.elts) == 2 and all(isinstance(e, ast.Name) for e in s.target.elts) \
                and isinstance(s.iter, ast.Call) and isinstance(s.iter.func, ast.Name) and s.iter.func.id == 'enumerate' \
                and len(s.iter.args) == 1:
            iv, ev = s.target.elts[0].id, s.target.elts[1].id
            seq = self.U(s.iter.args[0])[0]
            pre = self.ensure(iv, None, level) + self.ensure(ev, None, level)
            body = [node('Assign', variable=ev, expression='{0}[{1}]'.format(seq, iv))] + self.block(s.body, s.lineno + 1, nxt, level + 1)
            return pre + [node('For', variable=iv, start='0', end='Length({0}) - 1'.format(seq), body=body)]
        if not isinstance(s.target, ast.Name):
            self.fail(s, 'the loop variable must be a plain name')
        v = s.target.id
        it = s.iter
        pre = self.ensure(v, None, level)
        lo, hi = s.lineno + 1, nxt
        if isinstance(it, ast.Call) and isinstance(it.func, ast.Name) and it.func.id == 'range' and 1 <= len(it.args) <= 3 and not it.keywords:
            a = it.args
            start = '0' if len(a) == 1 else self.U(a[0])[0]
            stop = a[0] if len(a) == 1 else a[1]
            step, dec = '1', False
            if len(a) == 3:
                st = a[2]
                if isinstance(st, ast.UnaryOp) and isinstance(st.op, ast.USub):
                    ok, c = cval(st.operand)
                    dec = True
                    step = self.U(st.operand)[0]
                else:
                    ok, c = cval(st)
                    if ok and isinstance(c, int) and c < 0:
                        dec, step = True, str(-c)
                    else:
                        step = self.U(st)[0]
                        if not ok:
                            return pre + self.while_range(s, v, start, stop, step, nxt, level)
            end = self.shift_end(stop, 1 if dec else -1)
            body = self.block(s.body, lo, hi, level + 1)
            return pre + [node('For', variable=v, start=start, end=end, step=step, direction='dec' if dec else 'inc', body=body)]
        if isinstance(it, ast.Name) and it.id in self.cur_scope.vars or (isinstance(it, ast.Call) is False and cval(it)[0]):
            self.counter += 1
            idx = 'idx' if self.counter == 1 else 'idx' + str(self.counter)
            self.cur_scope.declared.add(idx)
            d = [node('Declare', name=idx, type='Integer')]
            seq = self.U(it)[0]
            body = [node('Assign', variable=v, expression='{0}[{1}]'.format(seq, idx))] + self.block(s.body, lo, hi, level + 1)
            return pre + d + [node('For', variable=idx, start='0', end='Length({0}) - 1'.format(seq), body=body)]
        self.fail(s, 'for loops support range(...) or looping over an array/string variable')

    def while_range(self, s, v, start, stop, step, nxt, level):
        body = self.block(s.body, s.lineno + 1, nxt, level + 1)
        body.append(node('Assign', variable=v, expression='{0} + {1}'.format(v, step)))
        return [node('Assign', variable=v, expression=start),
                node('While', expression='{0} < {1}'.format(v, self.U(stop)[0]), body=body)]

    # ------------------------------------------------------------- whole module
    def run(self, tree):
        top_defs = [s for s in tree.body if isinstance(s, ast.FunctionDef)]
        for d in top_defs:
            self.funcs[d.name] = d
        main_stmts = []
        for s in tree.body:
            if isinstance(s, ast.FunctionDef):
                continue
            if isinstance(s, ast.If) and isinstance(s.test, ast.Compare) and isinstance(s.test.left, ast.Name) \
                    and s.test.left.id == '__name__':
                main_stmts.extend(s.body)
            else:
                main_stmts.append(s)
        # a lone `def main(): ...` + `main()` becomes the Main body
        main_def = None
        for nm in ('main', 'Main'):
            if nm in self.funcs and not self.funcs[nm].args.args:
                calls = [s for s in main_stmts if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                         and isinstance(s.value.func, ast.Name) and s.value.func.id == nm]
                rest = [s for s in main_stmts if s not in calls and not isinstance(s, (ast.Import, ast.ImportFrom, ast.Pass))
                        and not (isinstance(s, ast.Expr) and cval(s.value)[0])]
                if calls and not rest:
                    main_def = self.funcs.pop(nm)
                    main_stmts = main_def.body
                    break
        for nm in list(self.funcs):
            if nm in ('Main',) or not valid_name(nm):
                raise ParseError('Function name not allowed: ' + nm)
        # scopes + parameter seeds from annotations
        self.scopes = {}
        for nm, d in self.funcs.items():
            sc = Scope(nm)
            for a in d.args.args:
                t, arr = None, False
                ann = getattr(a, 'annotation', None)
                if isinstance(ann, ast.Name):
                    if ann.id in PY_TYPES:
                        t = PY_TYPES[ann.id]
                    elif ann.id == 'list':
                        arr = True
                sc.params.append(a.arg)
                sc.vars[a.arg] = [t, arr]
            if d.args.vararg or d.args.kwarg or d.args.defaults or getattr(d.args, 'kwonlyargs', None):
                raise ParseError('Line {0}: *args, **kwargs and default values are not supported'.format(d.lineno))
            rann = getattr(d, 'returns', None)
            if isinstance(rann, ast.Name) and rann.id in PY_TYPES:
                sc.ret = PY_TYPES[rann.id]
            pt = getattr(d, '_ptypes', None)
            if pt:
                for a, spec in zip(d.args.args, pt):
                    if spec:
                        sc.vars[a.arg] = [spec[0], spec[1]]
                        sc.fixed.add(a.arg)
            rr = getattr(d, '_ret', None)
            if rr is not None:
                sc.ret = None if rr == 'None' else rr
                sc.ret_fixed = True
            for vn, spec in getattr(d, '_seed', {}).items():
                sc.vars[vn] = [spec[0], spec[1]]
                sc.fixed.add(vn)
            self.scopes[nm] = sc
        mainsc = Scope('Main')
        for vn, spec in getattr(tree, '_seed', {}).items():
            mainsc.vars[vn] = [spec[0], spec[1]]
            mainsc.fixed.add(vn)
        self.scopes['Main'] = mainsc
        bodies = [(mainsc, main_stmts)] + [(self.scopes[nm], self.funcs[nm].body) for nm in self.funcs]
        for _ in range(8):
            changed = False
            for sc, stmts in bodies:
                self.cur_scope = sc
                if self.collect(stmts, sc):
                    changed = True
            if not changed:
                break
        doc = empty_document()
        self.hoist = []
        for sc, stmts in bodies:
            self.cur_scope = sc
            sc.declared = set(sc.params)
            if sc.name == 'Main':
                lo = 1
                hi = len(self.lines)
                stmts2 = stmts
                if main_def is not None:
                    lo, hi = main_def.lineno + 1, len(self.lines)
                nodes = self.top_block(stmts2, lo, hi)
                doc['functions'][0]['body'] = nodes
            else:
                d = self.funcs[sc.name]
                nodes = self.top_block(d.body, d.lineno + 1, self.end_line(d) + 1)
                params = []
                for a in d.args.args:
                    info = sc.vars.get(a.arg, [None, False])
                    params.append({'name': a.arg, 'type': info[0] or 'Integer', 'array': bool(info[1])})
                doc['functions'].append({'name': sc.name, 'type': sc.ret or 'None', 'variable': '',
                                         'parameters': params, 'body': nodes})
        # leftover top-level comments (before the first statement etc.)
        merge_declares(doc)
        validate(doc)
        return doc

    def top_block(self, stmts, lo, hi):
        """Top-level block of one function: hoisted declarations go before their statement."""
        out = []
        if not stmts:
            return [node('Comment', text=c[2]) for c in self.comments_in(0, lo, hi)]
        col = stmts[0].col_offset
        items = []
        for i, s in enumerate(stmts):
            nxt = stmts[i + 1].lineno - 1 if i + 1 < len(stmts) else hi
            items.append((s.lineno, 1, s, nxt))
        for c in self.comments_in(col, lo, hi):
            items.append((c[0], 0, c, 0))
        items.sort(key=lambda x: (x[0], x[1]))
        for line, isstmt, obj, nxt in items:
            if not isstmt:
                out.append(node('Comment', text=obj[2]))
                continue
            self.hoist = []
            nodes = self.stmt(obj, nxt, 0)
            out.extend(self.hoist)
            out.extend(nodes)
        return out


def merge_declares(doc):
    """Merge neighbouring scalar Declare nodes of the same type: Declare Integer a, b, c."""
    def fix(block):
        i = 0
        while i < len(block):
            n = block[i]
            for b in BRANCHES.get(n['kind'], []):
                fix(n[b])
            if n['kind'] == 'Declare' and not n['array'] and i + 1 < len(block):
                m = block[i + 1]
                if m['kind'] == 'Declare' and not m['array'] and m['type'] == n['type']:
                    n['name'] += ', ' + m['name']
                    del block[i + 1]
                    continue
            i += 1
    for f in doc['functions']:
        fix(f['body'])


def _lower_python_join_generators(tree):
    """Lower ''.join(expr for item in sequence) to explicit flowchart-compatible loops.

    This handles the common, unfiltered, single-generator form. It deliberately
    rejects neither unrelated generators nor changes to the source text; unsupported
    join shapes remain for the importer to diagnose accurately.
    """
    class Finder(ast.NodeVisitor):
        def __init__(self): self.found = []
        def visit_Call(self, n):
            f = n.func
            sep_ok, sep_value = cval(f.value) if isinstance(f, ast.Attribute) else (False, None)
            if (isinstance(f, ast.Attribute) and f.attr == 'join' and sep_ok and sep_value == '' and
                len(n.args) == 1 and isinstance(n.args[0], ast.GeneratorExp)):
                g = n.args[0]
                if len(g.generators) == 1 and not g.generators[0].ifs and isinstance(g.generators[0].target, ast.Name):
                    self.found.append(n)
            self.generic_visit(n)
    class Replace(ast.NodeTransformer):
        def __init__(self, mapping): self.mapping = mapping
        def visit_Call(self, n):
            n = self.generic_visit(n)
            if id(n) in self.mapping:
                return ast.copy_location(ast.Name(id=self.mapping[id(n)], ctx=ast.Load()), n)
            return n
    def rewrite_block(body, counter):
        out=[]
        for stmt in body:
            # Process nested statement blocks first, preserving their local placement.
            for field, value in ast.iter_fields(stmt):
                if isinstance(value, list) and value and all(isinstance(x, ast.stmt) for x in value):
                    setattr(stmt, field, rewrite_block(value, counter))
            finder=Finder(); finder.visit(stmt)
            if not finder.found:
                out.append(stmt); continue
            mapping={}; prefix=[]
            for call in finder.found:
                gen=call.args[0]; comp=gen.generators[0]
                counter[0]+=1; temp='flowJoinResult'+str(counter[0])
                # Avoid colliding with names already present in the module.
                while temp in all_names: counter[0]+=1; temp='flowJoinResult'+str(counter[0])
                all_names.add(temp); mapping[id(call)]=temp
                init=ast.Assign(targets=[ast.Name(id=temp, ctx=ast.Store())], value=K(''))
                loop=ast.For(target=comp.target, iter=comp.iter, body=[ast.AugAssign(target=ast.Name(id=temp,ctx=ast.Store()), op=ast.Add(), value=gen.elt)], orelse=[])
                ast.copy_location(init, call); ast.copy_location(loop, call)
                prefix.extend([init, loop])
            stmt=Replace(mapping).visit(stmt)
            out.extend(prefix); out.append(stmt)
        return out
    all_names=set(n.id for n in ast.walk(tree) if isinstance(n, ast.Name))
    tree.body=rewrite_block(tree.body,[0])
    return ast.fix_missing_locations(tree)


def _lower_python_expression_comprehensions(tree):
    """Lower common expression-level comprehensions into ordinary loops.

    Supports list comprehensions as printable list representations and sum/all/any
    over generator expressions. This is a semantic lowering into the shared
    flowchart model, not an attempt to preserve Python's dynamic-list object.
    """
    counter = [0]
    def fresh(prefix):
        counter[0] += 1
        return 'flow{0}{1}'.format(prefix, counter[0])
    def name(n, ctx=None):
        return ast.Name(id=n, ctx=ctx or ast.Load())
    def const(v):
        return K(v)
    def copyloc(new, old):
        return ast.copy_location(new, old)
    def call(fn, args, old):
        return copyloc(ast.Call(func=name(fn), args=args, keywords=[]), old)
    def aug(target, op, value, old):
        return copyloc(ast.AugAssign(target=name(target, ast.Store()), op=op(), value=value), old)
    def assign(target, value, old):
        return copyloc(ast.Assign(targets=[name(target, ast.Store())], value=value), old)
    def loop_nest(generators, body, old):
        def build(index, tail):
            if index >= len(generators):
                return tail
            gen = generators[index]
            if not isinstance(gen.target, ast.Name):
                raise ParseError('Line {0}: comprehension targets must be simple variable names'.format(getattr(gen, 'lineno', getattr(old, 'lineno', '?'))))
            result = build(index + 1, tail)
            for cond in reversed(gen.ifs):
                local=[]
                test=transform_expr(cond, local)
                result = local + [copyloc(ast.If(test=test, body=result, orelse=[]), old)]
            iter_pre=[]
            iterator=transform_expr(gen.iter, iter_pre)
            result = [copyloc(ast.For(target=gen.target, iter=iterator, body=result, orelse=[]), old)]
            return iter_pre + result
        return build(0, body)
    def transform_expr(expr, pre):
        # sum/all/any(generator expression)
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id in ('sum','all','any') \
                and len(expr.args) == 1 and isinstance(expr.args[0], ast.GeneratorExp) and not expr.keywords:
            gen = expr.args[0]
            if all(isinstance(g.target, ast.Name) for g in gen.generators):
                acc = fresh(expr.func.id)
                init = 0 if expr.func.id == 'sum' else (True if expr.func.id == 'all' else False)
                pre.append(assign(acc, const(init), expr))
                elt = transform_expr(gen.elt, pre)
                if expr.func.id == 'sum':
                    body = [aug(acc, ast.Add, elt, expr)]
                elif expr.func.id == 'all':
                    body = [copyloc(ast.If(test=copyloc(ast.UnaryOp(op=ast.Not(), operand=elt), expr), body=[assign(acc, const(False), expr)], orelse=[]), expr)]
                else:
                    body = [copyloc(ast.If(test=elt, body=[assign(acc, const(True), expr)], orelse=[]), expr)]
                pre.extend(loop_nest(gen.generators, body, expr))
                return name(acc)
        # A list comprehension in expression position is represented as Python-like text.
        if isinstance(expr, ast.ListComp) and all(isinstance(g.target, ast.Name) for g in expr.generators):
            acc, idx = fresh('list'), fresh('idx')
            pre.append(assign(acc, const('['), expr))
            pre.append(assign(idx, const(0), expr))
            elt = transform_expr(expr.elt, pre)
            sep = copyloc(ast.If(test=copyloc(ast.Compare(left=name(idx), ops=[ast.Gt()], comparators=[const(0)]), expr),
                                 body=[aug(acc, ast.Add, const(', '), expr)], orelse=[]), expr)
            add = aug(acc, ast.Add, call('str', [elt], expr), expr)
            inc = aug(idx, ast.Add, const(1), expr)
            body = [sep, add, inc]
            pre.extend(loop_nest(expr.generators, body, expr))
            pre.append(aug(acc, ast.Add, const(']'), expr))
            return name(acc)
        # Any other nested expression is recursively transformed in place.
        for field, value in ast.iter_fields(expr):
            if isinstance(value, ast.expr):
                setattr(expr, field, transform_expr(value, pre))
            elif isinstance(value, list):
                setattr(expr, field, [transform_expr(x, pre) if isinstance(x, ast.expr) else x for x in value])
        return expr
    def transform_block(stmts):
        out=[]
        for stmt in stmts:
            # Keep generated prelude in the same control-flow block as its expression.
            for field, value in ast.iter_fields(stmt):
                if isinstance(value, list) and value and all(isinstance(x, ast.stmt) for x in value):
                    setattr(stmt, field, transform_block(value))
            pre=[]
            for field, value in ast.iter_fields(stmt):
                # Preserve the established fixed-array lowering for a direct
                # assignment such as `a = [i*i for i in range(n)]`.
                if isinstance(stmt, ast.Assign) and field == 'value' and isinstance(value, ast.ListComp):
                    continue
                if isinstance(value, ast.expr):
                    setattr(stmt, field, transform_expr(value, pre))
                elif isinstance(value, list):
                    setattr(stmt, field, [transform_expr(x, pre) if isinstance(x, ast.expr) else x for x in value])
            out.extend(pre)
            out.append(stmt)
        return out
    tree.body=transform_block(tree.body)
    return ast.fix_missing_locations(tree)


def parse_python(text):
    try:
        tree = ast.parse(text)
        return PythonProgramImporter(text, tree).run()
    except SyntaxError as e:
        raise ParseError('Line {0}: {1}'.format(e.lineno, e.msg))
    except (ValueError, TypeError, FlowError) as e:
        if isinstance(e, ParseError):
            raise
        raise ParseError(str(e))
    except RuntimeError:
        raise ParseError('The program is nested too deeply.')


def lower_portable_collections(tree):
    """Lower collection representation; keep all element evaluation in the program.

    Dictionaries use parallel key/value arrays. Their fixed storage is declared
    once; entries are evaluated in source order in their original control scope.
    No user program is evaluated while translating. Keys are scalar literals.
    """
    class Collections(object):
        def __init__(self):
            self.used = set(n.id for n in ast.walk(tree) if isinstance(n, ast.Name))
            self.counter = 0
            self.env = {}
            self.hoisted = []
            self.key_indices = {}

        def fresh(self, role):
            while True:
                self.counter += 1
                name = 'collection_' + role + '_' + str(self.counter)
                if name not in self.used:
                    self.used.add(name)
                    return name

        def name(self, text, store=False):
            return ast.Name(id=text, ctx=ast.Store() if store else ast.Load())

        def assign(self, target, value):
            return ast.Assign(targets=[self.name(target, True) if isinstance(target, str) else target], value=value)

        def call(self, name, args):
            return ast.Call(func=self.name(name), args=args, keywords=[])

        def failure(self, message):
            call = self.call('Fail', [K(message)])
            call._portable_fail = True
            return ast.Expr(value=call)

        def index(self, base, key, store=False):
            if _AST_INDEX:
                key = ast.Index(value=key)
            return ast.Subscript(value=copy.deepcopy(base), slice=key, ctx=ast.Store() if store else ast.Load())

        def fail(self, n, message):
            raise Unsupported('Line {0}: {1}'.format(getattr(n, 'lineno', '?'), message))

        def checked(self, desc, original):
            if desc and desc['kind'] == 'conditional':
                self.fail(original, 'this dictionary or range has different bindings on different control paths; keep its lookup in the branch or loop that creates it')
            return desc

        def merge_env(self, left, right):
            merged = {}
            for variable in set(left) | set(right):
                first, second = left.get(variable), right.get(variable)
                if first is second:
                    if first is not None:
                        merged[variable] = first
                elif any(desc and desc['kind'] in ('dict', 'range', 'conditional') for desc in (first, second)):
                    merged[variable] = {'kind': 'conditional'}
                elif first and second and first.get('string') == second.get('string'):
                    merged[variable] = first
            return merged

        def loop_blocks(self, statement, depth):
            before = self.env.copy()
            statement.body = self.block(statement.body, depth + 1)
            body_env = self.env.copy()
            self.env = self.merge_env(before, body_env)
            statement.orelse = self.block(statement.orelse, depth + 1)
            self.env = self.merge_env(body_env, self.env)

        def sequence(self, value, prefix, depth):
            if isinstance(value, ast.Name) and value.id in self.env:
                return self.checked(self.env[value.id], value)
            if isinstance(value, ast.Dict):
                return self.dictionary(value, prefix, depth)
            if isinstance(value, (ast.List, ast.Tuple)):
                array = ast.List(elts=[self.expr(x, prefix, depth) for x in value.elts], ctx=ast.Load())
                temp = self.fresh('items')
                statement = self.assign(temp, array)
                if depth:
                    if not all(cval(x)[0] for x in array.elts):
                        self.fail(value, 'nested collection literals need scalar literal elements for portable conversion')
                    self.hoisted.append(statement)
                else:
                    prefix.append(statement)
                return {'kind': 'sequence', 'expr': self.name(temp), 'string': False}
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and not value.args:
                base = value.func.value
                desc = self.env.get(base.id) if isinstance(base, ast.Name) else None
                if desc and desc['kind'] == 'dict' and value.func.attr in ('keys', 'values', 'items'):
                    return {'kind': value.func.attr, 'dict': desc}
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in ('list', 'tuple') and len(value.args) == 1 and not value.keywords:
                return self.sequence(value.args[0], prefix, depth)
            transformed = self.expr(value, prefix, depth)
            ok, constant = cval(transformed)
            is_string = ok and isinstance(constant, str)
            if is_string or not isinstance(transformed, ast.Name):
                temp = self.fresh('sequence')
                prefix.append(self.assign(temp, transformed))
                transformed = self.name(temp)
            return {'kind': 'sequence', 'expr': transformed, 'string': is_string}

        def dictionary(self, value, prefix, depth):
            keys, values, known, entries = [], [], [], []
            for key, item in zip(value.keys, value.values):
                if key is None:
                    self.fail(value, 'expanded dictionaries need a dynamic target map and are not portable')
                ok, scalar = cval(key)
                if not ok or not isinstance(scalar, (str, int, float, bool)):
                    self.fail(key, 'portable dictionary keys must be scalar literals')
                positions = [i for i, previous in enumerate(known) if scalar == previous]
                if positions:
                    index = positions[0]
                else:
                    index = len(known)
                    known.append(scalar)
                    keys.append(copy.deepcopy(key))
                entries.append((index, item))
            key_name, value_name = self.fresh('keys'), self.fresh('values')
            key_assign = self.assign(key_name, ast.List(elts=keys, ctx=ast.Load()))
            # A private allocation hint separates type inference and fixed-size
            # declaration from evaluation. Empty initializer elements cannot run
            # user expressions before their enclosing loop/branch is entered.
            storage = ast.List(elts=[], ctx=ast.Load())
            storage._portable_size = len(known)
            storage._portable_type_values = values
            value_assign = self.assign(value_name, storage)
            self.hoisted.extend([key_assign, value_assign])
            last_positions = dict((index, position) for position, (index, item) in enumerate(entries))
            for position, (index, item) in enumerate(entries):
                transformed = self.expr(item, prefix, depth)
                if last_positions[index] != position:
                    # Overwritten entries still execute (and may raise), but
                    # their temporary type need not match the final value.
                    self.snapshot(transformed, prefix, 'overwritten')
                else:
                    values.append(copy.deepcopy(transformed))
                    prefix.append(self.assign(self.index(self.name(value_name), K(index), True), transformed))
            return {'kind': 'dict', 'keys': self.name(key_name), 'values': self.name(value_name), 'known': known}

        def dictionary_index(self, desc, key, original, prefix, depth, required=True):
            ok, scalar = cval(key)
            if ok:
                for index, candidate in enumerate(desc['known']):
                    if scalar == candidate:
                        return K(index)
                if required:
                    prefix.append(self.failure('Dictionary key not found: ' + str(scalar)))
                return K(len(desc['known']))
            if isinstance(key, ast.Name):
                bound = self.key_indices.get(key.id)
                if bound and bound[0] is desc:
                    return self.name(bound[1])
            key_name, index_name = self.fresh('lookup_key'), self.fresh('lookup_index')
            prefix.append(self.assign(key_name, key))
            prefix.append(self.assign(index_name, K(len(desc['known']))))
            for index, candidate in enumerate(desc['known']):
                test = ast.Compare(left=self.name(key_name), ops=[ast.Eq()], comparators=[K(candidate)])
                prefix.append(ast.If(test=test, body=[self.assign(index_name, K(index))], orelse=[]))
            if required:
                missing = ast.Compare(left=self.name(index_name), ops=[ast.Eq()], comparators=[K(len(desc['known']))])
                prefix.append(ast.If(test=missing, body=[self.failure('Dictionary key not found')], orelse=[]))
            return self.name(index_name)

        def snapshot(self, value, prefix, role='value'):
            temp = self.fresh(role)
            prefix.append(self.assign(temp, value))
            return self.name(temp)

        def ordered(self, children, prefix, depth):
            result = []
            for child in children:
                before = []
                changed = self.expr(child, before, depth)
                if before:
                    # Earlier reads/calls precede a later child's statements.
                    # In particular f(), {'a': g()}[key] must call f before g.
                    for i, prior in enumerate(result):
                        if not cval(prior)[0]:
                            result[i] = self.snapshot(prior, prefix)
                    prefix.extend(before)
                result.append(changed)
            return result

        def expr(self, value, prefix, depth):
            if value is None:
                return None
            if isinstance(value, ast.Name):
                desc = self.checked(self.env.get(value.id), value)
                if desc and desc['kind'] in ('dict', 'range'):
                    self.fail(value, 'a dictionary or range value can be iterated but cannot be used as a scalar in portable code')
                return value
            if isinstance(value, ast.Subscript):
                desc = (self.dictionary(value.value, prefix, depth) if isinstance(value.value, ast.Dict)
                        else self.env.get(value.value.id) if isinstance(value.value, ast.Name) else None)
                self.checked(desc, value)
                if desc and desc['kind'] == 'dict':
                    key = self.expr(pslice(value), prefix, depth)
                    return self.index(desc['values'], self.dictionary_index(desc, key, value, prefix, depth), isinstance(value.ctx, ast.Store))
                if not isinstance(pslice(value), ast.Slice):
                    base, key = self.ordered([value.value, pslice(value)], prefix, depth)
                    return self.index(base, key, isinstance(value.ctx, ast.Store))
            if isinstance(value, ast.IfExp):
                test = self.expr(value.test, prefix, depth)
                yes, no = [], []
                body, other = self.expr(value.body, yes, depth), self.expr(value.orelse, no, depth)
                if yes or no:
                    temp = self.fresh('conditional')
                    prefix.append(ast.If(test=test, body=yes + [self.assign(temp, body)], orelse=no + [self.assign(temp, other)]))
                    return self.name(temp)
                value.test, value.body, value.orelse = test, body, other
                return value
            if isinstance(value, ast.BoolOp):
                pieces = []
                for part in value.values:
                    before = []
                    pieces.append((before, self.expr(part, before, depth)))
                if any(before for before, part in pieces):
                    temp = self.fresh('boolean')
                    first, part = pieces[0]
                    prefix.extend(first + [self.assign(temp, part)])
                    for before, part in pieces[1:]:
                        test = self.name(temp)
                        if isinstance(value.op, ast.Or):
                            test = ast.UnaryOp(op=ast.Not(), operand=test)
                        prefix.append(ast.If(test=test, body=before + [self.assign(temp, part)], orelse=[]))
                    return self.name(temp)
                value.values = [part for before, part in pieces]
                return value
            if isinstance(value, ast.Compare) and len(value.ops) > 1:
                children = []
                for child in [value.left] + value.comparators:
                    before = []
                    children.append((before, self.expr(child, before, depth)))
                if any(before for before, part in children):
                    before, first = children[0]
                    prefix.extend(before)
                    previous = self.snapshot(first, prefix, 'comparison')
                    temp = self.fresh('compared')
                    prefix.append(self.assign(temp, K(True)))
                    for op, (before, part) in zip(value.ops, children[1:]):
                        branch = list(before)
                        current = self.snapshot(part, branch, 'comparison')
                        branch.append(self.assign(temp, ast.Compare(left=previous, ops=[op], comparators=[current])))
                        branch.append(self.assign(previous.id, current))
                        prefix.append(ast.If(test=self.name(temp), body=branch, orelse=[]))
                    return self.name(temp)
                value.left, value.comparators = children[0][1], [part for before, part in children[1:]]
                return value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == 'len' and len(value.args) == 1:
                arg = value.args[0]
                desc = (self.dictionary(arg, prefix, depth) if isinstance(arg, ast.Dict)
                        else self.env.get(arg.id) if isinstance(arg, ast.Name) else None)
                if desc and desc['kind'] == 'dict':
                    return self.call('len', [copy.deepcopy(desc['keys'])])
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
                base = value.func.value
                desc = self.env.get(base.id) if isinstance(base, ast.Name) else None
                if desc and desc['kind'] == 'dict':
                    self.fail(value, 'dictionary methods are portable when used in keys(), values() or items() iteration')
            if isinstance(value, ast.Dict):
                self.fail(value, 'use a named dictionary or iterate its keys, values or items for portable conversion')
            if isinstance(value, ast.Call):
                # Named function objects are not portable values. Only their
                # receiver/arguments take part in expression evaluation.
                if isinstance(value.func, ast.Attribute):
                    value.func.value = self.expr(value.func.value, prefix, depth)
                args = list(value.args) + [keyword.value for keyword in value.keywords]
                changed = self.ordered(args, prefix, depth)
                value.args = changed[:len(value.args)]
                for keyword, part in zip(value.keywords, changed[len(value.args):]):
                    keyword.value = part
                return value
            children, slots = [], []
            for field, child in ast.iter_fields(value):
                if isinstance(child, ast.expr):
                    children.append(child); slots.append((field, None))
                elif isinstance(child, list):
                    for i, part in enumerate(child):
                        if isinstance(part, ast.expr):
                            children.append(part); slots.append((field, i))
            for (field, index), changed in zip(slots, self.ordered(children, prefix, depth)):
                if index is None:
                    setattr(value, field, changed)
                else:
                    getattr(value, field)[index] = changed
            return value

        def bind(self, target, expression):
            if isinstance(target, (ast.Tuple, ast.List)):
                if not isinstance(expression, (ast.Tuple, ast.List)) or len(target.elts) != len(expression.elts):
                    self.fail(target, 'portable unpacking needs a fixed tuple of values')
                result = []
                for left, right in zip(target.elts, expression.elts):
                    result.extend(self.bind(left, right))
                return result
            if not isinstance(target, (ast.Name, ast.Subscript)):
                self.fail(target, 'unsupported portable iteration target')
            return [self.assign(copy.deepcopy(target), expression)]

        def loop(self, statement, depth):
            prefix = []
            original_indices = self.key_indices.copy()
            iterable = statement.iter
            if isinstance(iterable, ast.Call) and isinstance(iterable.func, ast.Name) and iterable.func.id == 'range':
                statement.iter = self.expr(iterable, prefix, depth)
                self.loop_blocks(statement, depth)
                return prefix + [statement]
            enum_start = None
            if isinstance(iterable, ast.Call) and isinstance(iterable.func, ast.Name) and iterable.func.id == 'enumerate':
                if len(iterable.args) not in (1, 2) or iterable.keywords:
                    self.fail(iterable, 'portable enumerate accepts one iterable and an optional start')
                enum_start = iterable.args[1] if len(iterable.args) == 2 else K(0)
                iterable = iterable.args[0]
            desc = self.sequence(iterable, prefix, depth)
            if desc['kind'] == 'range':
                if enum_start is not None:
                    self.fail(statement, 'enumerate over an assigned range needs an explicit range loop for portable conversion')
                statement.iter = copy.deepcopy(desc['expr'])
                self.loop_blocks(statement, depth)
                return prefix + [statement]
            if desc['kind'] == 'dict':
                desc = {'kind': 'keys', 'dict': desc}
            if enum_start is not None:
                start_name = self.fresh('enumerate_start')
                prefix.append(self.assign(start_name, self.expr(enum_start, prefix, depth)))
                enum_start = self.name(start_name)
            index = self.fresh('index')
            if desc['kind'] in ('keys', 'values', 'items'):
                mapping = desc['dict']
                seq = mapping['keys']
                element = (ast.Tuple(elts=[self.index(mapping['keys'], self.name(index)), self.index(mapping['values'], self.name(index))], ctx=ast.Load())
                           if desc['kind'] == 'items' else self.index(mapping['values'] if desc['kind'] == 'values' else mapping['keys'], self.name(index)))
                if desc['kind'] == 'keys' and isinstance(statement.target, ast.Name):
                    self.key_indices[statement.target.id] = (mapping, index)
            else:
                seq = desc['expr']
                if desc.get('string'):
                    snapshot = self.fresh('text')
                    prefix.append(self.assign(snapshot, copy.deepcopy(seq)))
                    seq = self.name(snapshot)
                element = self.index(seq, self.name(index))
            if enum_start is not None:
                element = ast.Tuple(elts=[ast.BinOp(left=copy.deepcopy(enum_start), op=ast.Add(), right=self.name(index)), element], ctx=ast.Load())
            binding = self.bind(statement.target, element)
            self.loop_blocks(statement, depth)
            body = binding + statement.body
            orelse = statement.orelse
            self.key_indices = original_indices
            loop = ast.For(target=self.name(index, True), iter=self.call('range', [self.call('len', [copy.deepcopy(seq)])]), body=body, orelse=orelse)
            ast.copy_location(loop, statement)
            return prefix + [loop]

        def block(self, statements, depth=0):
            result = []
            for statement in statements:
                prefix = []
                if isinstance(statement, ast.FunctionDef):
                    old_env, old_hoisted, old_indices = self.env, self.hoisted, self.key_indices
                    self.env, self.hoisted, self.key_indices = {}, [], {}
                    statement.body = self.block(statement.body)
                    statement.body = self.hoisted + statement.body
                    self.env, self.hoisted, self.key_indices = old_env, old_hoisted, old_indices
                    result.append(statement)
                    continue
                if isinstance(statement, ast.For):
                    result.extend(self.loop(statement, depth))
                    continue
                if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
                    name, value = statement.targets[0].id, statement.value
                    if isinstance(value, ast.Dict):
                        self.env[name] = self.dictionary(value, prefix, depth)
                        result.extend(prefix)
                        continue
                    if isinstance(value, ast.Tuple):
                        value = ast.List(elts=value.elts, ctx=ast.Load())
                        statement.value = value
                    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == 'range':
                        if value.keywords or len(value.args) not in (1, 2, 3):
                            self.fail(value, 'portable range accepts one to three positional arguments')
                        arguments = []
                        for argument in value.args:
                            bound = self.fresh('range_bound')
                            transformed = self.expr(argument, prefix, depth)
                            prefix.append(self.assign(bound, transformed))
                            arguments.append(self.name(bound))
                        self.env[name] = {'kind': 'range', 'expr': self.call('range', arguments)}
                        result.extend(prefix)
                        continue
                    if isinstance(value, ast.Name) and value.id in self.env and self.env[value.id]['kind'] in ('dict', 'range'):
                        self.env[name] = self.env[value.id]
                        continue
                    old_desc = self.env.get(value.id) if isinstance(value, ast.Name) else None
                    input_spec = PyImporter.input_kind(None, value)
                    string_value = bool(old_desc and old_desc.get('string')) or bool(input_spec and input_spec[0] == 'String')
                    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == 'str':
                        string_value = True
                    if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr in ('upper', 'lower', 'strip', 'lstrip', 'rstrip', 'capitalize', 'title', 'replace'):
                        base = value.func.value
                        string_value = bool(isinstance(base, ast.Name) and self.env.get(base.id, {}).get('string'))
                    transformed_value = self.expr(statement.value, prefix, depth)
                    if isinstance(value, (ast.List, ast.ListComp)):
                        self.env[name] = {'kind': 'sequence', 'expr': self.name(name), 'string': False}
                    else:
                        ok, literal_value = cval(value)
                        if (ok and isinstance(literal_value, str)) or string_value:
                            self.env[name] = {'kind': 'sequence', 'expr': self.name(name), 'string': True}
                        else:
                            self.env.pop(name, None)
                    statement.value = transformed_value
                elif isinstance(statement, (ast.If, ast.While)):
                    statement.test = self.expr(statement.test, prefix, depth)
                    if isinstance(statement, ast.While):
                        self.loop_blocks(statement, depth)
                    else:
                        before = self.env.copy()
                        statement.body = self.block(statement.body, depth + 1)
                        yes_env = self.env.copy()
                        self.env = before.copy()
                        statement.orelse = self.block(statement.orelse, depth + 1)
                        self.env = self.merge_env(yes_env, self.env)
                    if isinstance(statement, ast.While) and prefix:
                        # A condition dictionary is rebuilt on every test,
                        # including tests reached through continue. Move the
                        # original else onto the false-condition path so user
                        # breaks still skip it.
                        stop = ast.If(test=ast.UnaryOp(op=ast.Not(), operand=statement.test),
                                      body=statement.orelse + [ast.Break()], orelse=[])
                        statement.test = K(True)
                        statement.body = prefix + [stop] + statement.body
                        statement.orelse = []
                        prefix = []
                elif isinstance(statement, ast.AugAssign):
                    statement.target = self.expr(statement.target, prefix, depth)
                    statement.value = self.expr(statement.value, prefix, depth)
                elif isinstance(statement, ast.Assign):
                    statement.value = self.expr(statement.value, prefix, depth)
                    before = []
                    statement.targets = [self.expr(t, before, depth) for t in statement.targets]
                    if before:
                        statement.value = self.snapshot(statement.value, prefix)
                        prefix.extend(before)
                elif isinstance(statement, ast.Expr):
                    statement.value = self.expr(statement.value, prefix, depth)
                elif isinstance(statement, ast.Return):
                    statement.value = self.expr(statement.value, prefix, depth)
                if isinstance(statement, (ast.Assign, ast.AugAssign)):
                    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                    for target in targets:
                        for target_name in ast.walk(target):
                            if isinstance(target_name, ast.Name) and isinstance(target_name.ctx, ast.Store):
                                self.key_indices.pop(target_name.id, None)
                result.extend(prefix)
                result.append(statement)
            return result

        def run(self):
            tree.body = self.block(tree.body)
            tree.body = self.hoisted + tree.body
            return ast.fix_missing_locations(tree)
    return Collections().run()


def lower_portable_controls(tree):
    """Snapshot Python ranges and make expression-level input explicit.

    The portable importer accepts input only as the complete RHS of an
    assignment. Prelude statements remain in their original conditional scope;
    input in a while condition is repeated on every test, including continue.
    """
    class Lower(object):
        def __init__(self):
            self.used = set(n.id for n in ast.walk(tree) if isinstance(n, ast.Name))
            self.count = 0
            self.flags = []

        def fresh(self, role):
            while True:
                self.count += 1
                name = 'fc' + role.title().replace('_', '') + str(self.count)
                if name not in self.used:
                    self.used.add(name)
                    return name

        def name(self, value):
            return ast.Name(id=value, ctx=ast.Load())

        def const(self, value):
            return ast.parse(repr(value), mode='eval').body

        def assign(self, name, value):
            target = self.name(name) if isinstance(name, str) else copy.deepcopy(name)
            for n in ast.walk(target):
                if hasattr(n, 'ctx'):
                    n.ctx = ast.Store()
            return ast.Assign(targets=[target], value=value)

        def call(self, name, args):
            result = ast.Call(func=self.name(name), args=args, keywords=[])
            if 'starargs' in ast.Call._fields:
                result.starargs, result.kwargs = None, None
            return result

        def input_call(self, n):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                if n.func.id == 'input':
                    return n
                if n.func.id in ('int', 'float', 'str') and len(n.args) == 1:
                    a = n.args[0]
                    if isinstance(a, ast.Call) and isinstance(a.func, ast.Name) and a.func.id == 'input':
                        return a
            return None

        def snapshot(self, value, pre, role='value'):
            name = self.fresh(role)
            pre.append(self.assign(name, value))
            return self.name(name)

        def ordered(self, values):
            """Lower children left-to-right, retaining prior call side effects."""
            pre, output = [], []
            for value in values:
                before, changed = self.expr(value)
                if before:
                    for i, prior in enumerate(output):
                        if any(isinstance(x, ast.Call) for x in ast.walk(prior)):
                            output[i] = self.snapshot(prior, pre)
                    pre.extend(before)
                output.append(changed)
            return pre, output

        def expr(self, value, truth=False):
            if value is None:
                return [], None
            value = copy.deepcopy(value)
            special = self.input_call(value)
            if special is not None:
                pre, args = self.ordered(special.args)
                special.args = args
                name = self.fresh('input')
                return pre + [self.assign(name, value)], self.name(name)
            if isinstance(value, ast.IfExp):
                pre, test = self.expr(value.test, True)
                bp, body = self.expr(value.body, truth)
                ep, other = self.expr(value.orelse, truth)
                if truth:
                    body = ast.UnaryOp(op=ast.Not(), operand=ast.UnaryOp(op=ast.Not(), operand=body))
                    other = ast.UnaryOp(op=ast.Not(), operand=ast.UnaryOp(op=ast.Not(), operand=other))
                name = self.fresh('conditional')
                pre.append(ast.If(test=test, body=bp+[self.assign(name, body)], orelse=ep+[self.assign(name, other)]))
                return pre, self.name(name)
            if isinstance(value, ast.BoolOp):
                pieces = [self.expr(v, truth) for v in value.values]
                def boolean_result(part):
                    ok, literal_value = cval(part)
                    return (isinstance(part, ast.Compare) or
                            isinstance(part, ast.UnaryOp) and isinstance(part.op, ast.Not) or
                            ok and isinstance(literal_value, bool) or
                            isinstance(part, ast.BoolOp) and all(boolean_result(x) for x in part.values))
                # Python returns an operand from and/or. Only a condition (or
                # operands already known to be Boolean) can use the portable
                # Boolean operators without losing the original value.
                if not any(p for p,v in pieces) and (truth or all(boolean_result(v) for p,v in pieces)):
                    value.values = [v for p,v in pieces]
                    return [], value
                if truth:
                    pieces = [(p, ast.UnaryOp(op=ast.Not(), operand=ast.UnaryOp(op=ast.Not(), operand=v))) for p,v in pieces]
                pre, first = pieces[0]
                name = self.fresh('boolean')
                pre = pre + [self.assign(name, first)]
                for before, part in pieces[1:]:
                    test = self.name(name)
                    if isinstance(value.op, ast.Or):
                        test = ast.UnaryOp(op=ast.Not(), operand=test)
                    pre.append(ast.If(test=test, body=before+[self.assign(name, part)], orelse=[]))
                return pre, self.name(name)
            if isinstance(value, ast.Compare) and len(value.ops) > 1:
                pieces = [self.expr(value.left)] + [self.expr(x) for x in value.comparators]
                if any(p for p,v in pieces) or any(isinstance(n,ast.Call) for n in ast.walk(value)):
                    pre, left = pieces[0]
                    previous = self.snapshot(left, pre, 'comparison')
                    result = self.fresh('compared')
                    pre.append(self.assign(result, self.const(True)))
                    for op, (before, right) in zip(value.ops, pieces[1:]):
                        inner = list(before)
                        current = self.snapshot(right, inner, 'comparison')
                        inner.append(self.assign(result, ast.Compare(left=previous, ops=[op], comparators=[current])))
                        inner.append(self.assign(previous.id, current))
                        pre.append(ast.If(test=self.name(result), body=inner, orelse=[]))
                    return pre, self.name(result)
            # Regular expression children can be lowered in their AST order.
            children, slots = [], []
            for field, child in ast.iter_fields(value):
                legacy_index = getattr(ast, 'Index', ()) if sys.version_info < (3, 9) else ()
                if isinstance(child, ast.expr) or (legacy_index and isinstance(child, legacy_index)):
                    slots.append((field, None)); children.append(child)
                elif isinstance(child, list):
                    for index, item in enumerate(child):
                        if isinstance(item, ast.expr):
                            slots.append((field, index)); children.append(item)
                        elif isinstance(item, ast.keyword):
                            slots.append((item, 'value')); children.append(item.value)
            pre, lowered = self.ordered(children)
            for (field, index), part in zip(slots, lowered):
                if isinstance(field, ast.keyword):
                    field.value = part
                elif index is None:
                    setattr(value, field, part)
                else:
                    getattr(value, field)[index] = part
            return pre, value

        def block(self, statements):
            output = []
            for statement in statements:
                output.extend(self.statement(copy.deepcopy(statement)))
            return output

        def statement(self, s):
            if isinstance(s, ast.FunctionDef):
                old = self.flags
                self.flags = []
                s.body = self.block(s.body)
                self.flags = old
                return [s]
            if isinstance(s, ast.If):
                pre, s.test = self.expr(s.test, True)
                s.body, s.orelse = self.block(s.body), self.block(s.orelse)
                return pre + [s]
            if isinstance(s, (ast.For, ast.While)):
                flag = self.fresh('completed') if s.orelse else None
                self.flags.append(flag)
                body = self.block(s.body)
                self.flags.pop()
                after = self.block(s.orelse)
                pre = [self.assign(flag, self.const(True))] if flag else []
                if isinstance(s, ast.For):
                    iterator = s.iter
                    if isinstance(iterator, ast.Call) and isinstance(iterator.func, ast.Name) and iterator.func.id == 'range' and 1 <= len(iterator.args) <= 3 and not iterator.keywords:
                        values = []
                        for arg in iterator.args:
                            before, value = self.expr(arg)
                            pre.extend(before)
                            values.append(self.snapshot(value, pre, 'range_argument'))
                        if len(values) == 1:
                            start, stop, step = self.const(0), values[0], self.const(1)
                        else:
                            start, stop = values[:2]
                            step = values[2] if len(values) == 3 else self.const(1)
                        # Separate counter permits changes to the user loop variable.
                        counter = self.fresh('range_counter')
                        pre.append(self.assign(counter, start))
                        zero = self.const(0)
                        forward = ast.BoolOp(op=ast.And(), values=[ast.Compare(left=step, ops=[ast.Gt()], comparators=[zero]), ast.Compare(left=self.name(counter), ops=[ast.Lt()], comparators=[stop])])
                        backward = ast.BoolOp(op=ast.And(), values=[ast.Compare(left=step, ops=[ast.Lt()], comparators=[zero]), ast.Compare(left=self.name(counter), ops=[ast.Gt()], comparators=[stop])])
                        test = ast.BoolOp(op=ast.Or(), values=[forward, backward])
                        iteration = [self.assign(s.target, self.name(counter)), self.assign(counter, ast.BinOp(left=self.name(counter), op=ast.Add(), right=step))] + body
                        pre.append(ast.While(test=test, body=iteration, orelse=[]))
                    else:
                        before, s.iter = self.expr(s.iter)
                        pre.extend(before)
                        s.body, s.orelse = body, []
                        pre.append(s)
                else:
                    before, test = self.expr(s.test, True)
                    if before:
                        s.test = self.const(True)
                        s.body = before + [ast.If(test=ast.UnaryOp(op=ast.Not(), operand=test), body=[ast.Break()], orelse=[])] + body
                    else:
                        s.test, s.body = test, body
                    s.orelse = []
                    pre.append(s)
                if flag:
                    pre.append(ast.If(test=self.name(flag), body=after or [ast.Pass()], orelse=[]))
                return pre
            if isinstance(s, ast.Break):
                return ([self.assign(self.flags[-1], self.const(False))] if self.flags and self.flags[-1] else []) + [s]
            if isinstance(s, (ast.Assign, ast.AugAssign, ast.Expr, ast.Return)):
                if getattr(s, 'value', None) is not None:
                    pre, s.value = self.expr(s.value)
                    return pre + [s]
            return [s]

    changed = Lower().block(tree.body)
    tree.body = changed
    # The old importer sorts statements by line number. Give all introduced
    # statements unique structural positions so preludes cannot move after use.
    line = [0]
    def locate(statements, level=0):
        for statement in statements:
            line[0] += 1
            statement.lineno, statement.col_offset = line[0], level * 4
            if hasattr(statement, 'end_lineno'):
                statement.end_lineno, statement.end_col_offset = line[0], level*4+1
            for field in ('body', 'orelse', 'finalbody'):
                nested = getattr(statement, field, None)
                if isinstance(nested, list) and nested:
                    locate(nested, level+1)
    locate(tree.body)
    return ast.fix_missing_locations(tree)


def _portable_python_document(doc):
    """Lower representable Python constructs into the shared target model."""
    source = generate_python_document(doc)
    try:
        tree = ast.parse(source)
        tree = lower_portable_collections(tree)
        tree = _lower_python_join_generators(tree)
        tree = _lower_python_expression_comprehensions(tree)
        tree = lower_portable_controls(tree)
        return PyImporter('').run(tree)
    except (FlowError, ValueError, TypeError) as exc:
        raise Unsupported('Cannot translate this Python program to the portable model: ' + str(exc))


# ----------------------------------------------------------------------------
# Language front-ends.  Every language is parsed into a Python-style syntax
# tree (with a few type hints attached); the shared importer above turns that
# into the flowchart.  So any language can be converted to any other one.
# ----------------------------------------------------------------------------
def K(v):
    if _AST_CONSTANT:
        return ast.Constant(value=v)
    if v is None:
        return ast.Name(id='None')
    if isinstance(v, bool):
        return ast.Name(id='True' if v else 'False')
    return ast.Str(s=v) if isinstance(v, str) else ast.Num(n=v)


def NM(name):
    return ast.Name(id=name)


def CALL(fn, *args, **kw):
    return ast.Call(func=NM(fn) if isinstance(fn, str) else fn, args=list(args),
                    keywords=[ast.keyword(arg=k, value=v) for k, v in sorted(kw.items())])


def BIN(op, l, r):
    return ast.BinOp(left=l, op=op(), right=r)


def MEMBER(obj, attr):
    return ast.Attribute(value=obj, attr=attr)


def SUBS(base, idx):
    return ast.Subscript(value=base, slice=idx)


def AT(n, line):
    n.lineno = line
    n.col_offset = 0
    return n


def stmt_list(nodes, line):
    for n in nodes:
        if not hasattr(n, 'lineno'):
            AT(n, line)
    return nodes


class AssignExpr(ast.AST):
    _fields = ('op', 'target', 'value')


class IncrExpr(ast.AST):
    _fields = ('target', 'delta', 'prefix')


class OutExpr(ast.AST):
    _fields = ('items',)


class InExpr(ast.AST):
    _fields = ('targets',)


class RangeExpr(ast.AST):
    _fields = ('start', 'stop', 'step', 'inclusive')


SKIP = object()          # a statement that has no flowchart meaning (imports, Scanner setup, ...)
INT_T = set('''int long short byte sbyte uint ulong ushort Integer Long Short Byte size_t ssize_t int8_t int16_t
int32_t int64_t uint8_t uint16_t uint32_t uint64_t Int Int8 Int16 Int32 Int64 UInt UInt8 UInt16 UInt32 UInt64
int8 int16 int32 int64 uint8 uint16 uint32 uint64 rune uintptr BigInteger'''.split())
REAL_T = set('float double Float Double float32 float64 Float32 Float64 CGFloat decimal Decimal Real'.split())
STR_T = set('String string str char Character NSString CharSequence StringBuilder'.split())
BOOL_T = set('bool boolean Boolean Bool'.split())
VOID_T = set('void Unit Void'.split())
ANY_T = set('var auto let val def const any object dynamic Any number'.split())
MODIFIERS = set('''const static final public private protected readonly volatile register extern unsigned signed
inline virtual override abstract open internal sealed partial async mut'''.split())
ARRAY_T = {'IntArray': 'Integer', 'LongArray': 'Integer', 'ShortArray': 'Integer', 'ByteArray': 'Integer',
           'DoubleArray': 'Real', 'FloatArray': 'Real', 'BooleanArray': 'Boolean'}
OPS3 = ['>>>=', '<<=', '>>=', '===', '!==', '...', '..<']
OPS2 = ['->', '=>', '::', '++', '--', '&&', '||', '??', '?.', '.=', '+=', '-=', '*=', '/=', '%=', '&=', '|=', '^=',
        '==', '!=', '<=', '>=', '<<', '>>', ':=', '**', '..']
NUM_RE = re.compile(r'(0[xX][0-9a-fA-F_]+|(?:\d[\d_]*(?:\.\d[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?\d+)?)([uUlLfFdD]*)')
ID_RE = re.compile(r'\$?[A-Za-z_]\w*')


def unescape(s, lang, quote):
    out, i = [], 0
    simple = {'n': '\n', 't': '\t', 'r': '\r', '0': '\0', 'b': '\b', 'f': '\f', 'a': '\a', 'v': '\v'}
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s):
            d = s[i + 1]
            if lang == 'PHP' and quote == "'":
                out.append(d if d in "\\'" else '\\' + d)
                i += 2
            elif d in simple:
                out.append(simple[d])
                i += 2
            elif d == 'x' and re.match(r'[0-9a-fA-F]{2}', s[i + 2:i + 4]):
                out.append(chr(int(s[i + 2:i + 4], 16)))
                i += 4
            elif d == 'u' and s[i + 2:i + 3] == '{':
                j = s.index('}', i)
                out.append(chr(int(s[i + 3:j], 16)))
                i = j + 1
            elif d == 'u' and re.match(r'[0-9a-fA-F]{4}', s[i + 2:i + 6]):
                out.append(chr(int(s[i + 2:i + 6], 16)))
                i += 6
            else:
                out.append(d)
                i += 2
        else:
            out.append(c)
            i += 1
    return ''.join(out)


def read_string(src, i, quote, lang, interp_csharp=False):
    """Read a string starting after the opening quote. Returns (value, new_i); value is str or list of parts."""
    n = len(src)
    parts, buf = [], []
    interp = (quote == '`' and lang in ('JavaScript', 'TypeScript')) or \
             (quote == '"' and lang in ('Kotlin', 'Swift', 'PHP')) or interp_csharp
    j = i
    while j < n and src[j] != quote:
        c = src[j]
        if c == '\\' and j + 1 < n:
            if lang == 'Swift' and src[j + 1] == '(':
                depth, k = 1, j + 2
                while k < n and depth:
                    depth += (src[k] == '(') - (src[k] == ')')
                    k += 1
                if buf:
                    parts.append(unescape(''.join(buf), lang, quote))
                    buf = []
                parts.append(('e', src[j + 2:k - 1]))
                j = k
                continue
            buf.append(src[j:j + 2])
            j += 2
            continue
        if interp and c == '$' and lang in ('JavaScript', 'TypeScript') and src[j + 1:j + 2] == '{':
            pass
        if interp and ((c == '$' and src[j + 1:j + 2] == '{' and lang != 'PHP') or
                       (c == '{' and (interp_csharp or (lang == 'PHP' and src[j + 1:j + 2] == '$')))):
            if interp_csharp and src[j + 1:j + 2] == '{':
                buf.append('{')
                j += 2
                continue
            start = j + (2 if c == '$' else 1)
            depth, k = 1, start
            while k < n and depth:
                depth += (src[k] == '{') - (src[k] == '}')
                k += 1
            if buf:
                parts.append(unescape(''.join(buf), lang, quote))
                buf = []
            e = src[start:k - 1]
            if interp_csharp:
                e = re.split(r'[:,](?![^()]*\))', e)[0]
            parts.append(('e', e))
            j = k
            continue
        if interp and c == '$' and lang in ('Kotlin', 'PHP') and re.match(r'[A-Za-z_]', src[j + 1:j + 2]):
            m = re.compile(r'\$?[A-Za-z_]\w*').match(src, j + 1 if lang == 'Kotlin' else j)
            name = m.group(0)
            end = m.end()
            if lang == 'PHP':
                mm = re.compile(r'\[[^\]]*\]').match(src, end)
                if mm:
                    name += mm.group(0)
                    end = mm.end()
            if buf:
                parts.append(unescape(''.join(buf), lang, quote))
                buf = []
            parts.append(('e', name))
            j = end
            continue
        if interp_csharp and c == '}' and src[j + 1:j + 2] == '}':
            buf.append('}')
            j += 2
            continue
        buf.append(c)
        j += 1
    if buf or not parts:
        parts.append(unescape(''.join(buf), lang, quote) if quote != '`' or lang != 'Go' else ''.join(buf))
    if len(parts) == 1 and isinstance(parts[0], str):
        return parts[0], j + 1
    return parts, j + 1


def tokenize_clike(src, lang):
    toks, comments, defines = [], [], {}
    if lang == 'PHP':
        src = re.sub(r'^\s*<\?(?:php)?', '', src)
        src = re.sub(r'\?>\s*$', '', src)
    i, n, line, nl = 0, len(src), 1, True

    def push(kind, val):
        toks.append((kind, val, line, nl))

    while i < n:
        c = src[i]
        if c == '\n':
            line += 1
            nl = True
            i += 1
            continue
        if c in ' \t\r\f':
            i += 1
            continue
        two = src[i:i + 2]
        if two == '//' or (c == '#' and lang in ('PHP',)) :
            j = src.find('\n', i)
            j = n if j < 0 else j
            comments.append((line, src[i + (2 if two == '//' else 1):j].strip()))
            i = j
            continue
        if two == '/*':
            j = src.find('*/', i + 2)
            j = n if j < 0 else j
            for k, ln in enumerate(src[i + 2:j].split('\n')):
                t = ln.strip().lstrip('*').strip()
                if t:
                    comments.append((line + k, t))
            line += src.count('\n', i, j)
            i = j + 2
            continue
        if c == '#' and lang in ('C', 'C++'):
            j = src.find('\n', i)
            j = n if j < 0 else j
            m = re.match(r'#\s*define\s+([A-Za-z_]\w*)\s+(.+)$', src[i:j])
            if m:
                defines[m.group(1)] = m.group(2).strip()
            i = j
            continue
        m = NUM_RE.match(src, i) if (c.isdigit() or (c == '.' and src[i + 1:i + 2].isdigit())) else None
        if m:
            body, suf = m.group(1).replace('_', ''), m.group(2)
            if body[:2] in ('0x', '0X'):
                val = int(body, 16)
            elif '.' in body or 'e' in body.lower() or suf.lower() in ('f', 'd'):
                val = float(body)
            else:
                val = int(body, 8) if (len(body) > 1 and body.startswith('0') and body.isdigit() and lang not in ('Kotlin',) and False) else int(body)
            push('num', val)
            i = m.end()
            continue
        if c == '$' and lang == 'C#' and src[i + 1:i + 2] == '"':
            val, i = read_string(src, i + 2, '"', lang, interp_csharp=True)
            push('tpl' if isinstance(val, list) else 'str', val)
            continue
        if c == '@' and lang == 'C#' and src[i + 1:i + 2] == '"':
            j = src.find('"', i + 2)
            push('str', src[i + 2:j])
            i = j + 1
            continue
        if c in '"\'`':
            if c == '`' and lang == 'Go':
                j = src.find('`', i + 1)
                push('str', src[i + 1:j])
                line += src.count('\n', i, j)
                i = j + 1
                continue
            if c == '"' and src[i:i + 3] == '"""' and lang in ('Kotlin', 'Swift'):
                j = src.find('"""', i + 3)
                push('str', src[i + 3:j].strip('\n'))
                line += src.count('\n', i, j)
                i = j + 3
                continue
            val, i2 = read_string(src, i + 1, c, lang)
            push('tpl' if isinstance(val, list) else 'str', val)
            line += src.count('\n', i, i2)
            i = i2
            continue
        m = ID_RE.match(src, i)
        if m:
            push('id', m.group(0))
            i = m.end()
            continue
        for op in OPS3:
            if src.startswith(op, i):
                push('op', op)
                i += len(op)
                break
        else:
            if two in OPS2 or (two == '!!' and lang == 'Kotlin') or (two == '?:' and lang == 'Kotlin'):
                push('op', two)
                i += 2
            else:
                push('op', c)
                i += 1
        nl = False
        continue
    toks.append(('eof', '', line, True))
    fixed, prev_line = [], 0
    for k, v, ln, _ in toks:
        fixed.append((k, v, ln, ln != prev_line))
        prev_line = ln
    return fixed, comments, defines


class SkipExpr(ast.Name):
    skip = True


PRINTLN = set(['println', 'System.out.println', 'Console.WriteLine', 'console.log', 'fmt.Println', 'puts', 'Println',
               'System.out.println', 'console.info', 'Console.Out.WriteLine'])
PRINTNL = set(['print', 'System.out.print', 'Console.Write', 'fmt.Print', 'process.stdout.write', 'System.out.write',
               'putchar', 'Console.Out.Write', 'Print'])
PRINTF = set(['printf', 'System.out.printf', 'System.out.format', 'fmt.Printf', 'Console.Out.WriteLine'])
SPRINTF = set(['fmt.Sprintf', 'String.format', 'sprintf', 'string.Format', 'String.Format'])
INT_CONV = set(['parseInt', 'Integer.parseInt', 'Long.parseLong', 'Short.parseShort', 'Integer.valueOf', 'Long.valueOf',
                'int.Parse', 'Int32.Parse', 'Int64.Parse', 'Convert.ToInt32', 'Convert.ToInt64', 'long.Parse', 'atoi',
                'atol', 'atoll', 'stoi', 'stol', 'stoll', 'intval', 'strconv.Atoi', 'strconv.ParseInt', 'Byte.parseByte',
                'Int.parseInt', 'toInt', 'toLong', 'toShort', 'flowInt', 'int', 'ToInt32', 'ToInt64', 'strtol', 'strtoll', 'strtoul', 'strtoull'])
REAL_CONV = set(['parseFloat', 'Double.parseDouble', 'Float.parseFloat', 'double.Parse', 'Double.Parse', 'float.Parse',
                 'Convert.ToDouble', 'Convert.ToSingle', 'atof', 'stod', 'stof', 'floatval', 'strconv.ParseFloat',
                 'toDouble', 'toFloat', 'flowFloat', 'doubleval', 'Number', 'float', 'ToDouble', 'Double.valueOf', 'strtod', 'strtof'])
STR_CONV = set(['String.valueOf', 'Integer.toString', 'Long.toString', 'Double.toString', 'to_string', 'strconv.Itoa',
                'strconv.FormatInt', 'strconv.FormatFloat', 'strconv.FormatBool', 'Convert.ToString', 'strval',
                'toString', 'ToString', 'flowString', 'flow_str_i', 'flow_str_r', 'flow_str_b', 'Boolean.toString',
                'Float.toString', 'Char.toString'])
INPUT_NAMES = set(['readLine', 'readln', 'readlnOrNull', 'Console.ReadLine', 'ReadLine', 'prompt', 'readline', '_readLine',
                   'flowReadLine', 'flow_read', 'readLineSync', 'question'])
MATH_FUNCS = {'sqrt': 'sqrt', 'sin': 'sin', 'cos': 'cos', 'tan': 'tan', 'asin': 'asin', 'acos': 'acos', 'atan': 'atan',
              'log': 'log', 'log10': 'log10', 'ln': 'log', 'floor': 'floor', 'ceil': 'ceil', 'ceiling': 'ceil',
              'sqr': 'sqrt'}
MATH_NS = set(['Math', 'math', 'std', 'kotlin.math', 'Foundation', 'System.Math', 'java.lang.Math', 'Double'])
SIZE_PROPS = set(['length', 'Length', 'size', 'count', 'Count'])
CAST_NAMES = {'integer': 'int', 'double': 'float', 'string': 'str', 'bool': 'bool', 'boolean': 'bool', 'float': 'float'}
IGNORED_CALLS = set(['srand', 'setbuf', 'fflush', 'system', 'sleep', 'usleep', 'setprecision', 'require', 'free', 'fclose',
                     'ios_base::sync_with_stdio', 'sync_with_stdio', 'tie', 'close', 'Scan', 'flush', 'seed',
                     'createInterface', 'setEncoding', 'Flush', 'Close', 'Randomize', 'GC.Collect', 'ReadKey', 'ob_start',
                     'error_reporting', 'ini_set', 'setlocale', 'Sleep', 'Thread.sleep', 'time.Sleep', 'exec', 'unset'])
EXIT_NAMES = set(['exit', 'System.exit', 'os.Exit', 'Environment.Exit', 'quit', 'process.exit', 'Process.exit', 'die', 'exitProcess'])


HELPER_FUNCS = {'flow_cat': 'cat', 'flow_upper': 'upper', 'flowUpper': 'upper', 'flow_lower': 'lower', 'flowLower': 'lower',
                'flow_trim': 'strip', 'flowTrim': 'strip', 'flow_contains': 'contains', 'flow_char': 'char',
                '_trunc': 'int', 'flowAbs': 'abs'}


class CExprMixin(object):
    def expr(self):
        left = self.ternary()
        t = self.tk()
        if self.lang == 'Go' and self.is_op(',') and self.depth == 0 and isinstance(left, (ast.Name, ast.Subscript)):
            save = self.i
            targets = [left]
            while self.accept(','):
                targets.append(self.ternary())
            if self.tk()[0] == 'op' and self.tk()[1] in (':=', '='):
                op = self.adv()[1]
                vals = [self.ternary()]
                while self.accept(','):
                    vals.append(self.ternary())
                return AssignExpr(op=op, target=ast.Tuple(elts=targets), value=vals[0] if len(vals) == 1 else ast.Tuple(elts=vals))
            self.i = save
            return left
        if t[0] == 'op' and t[1] in ASSIGN_OPS and not (self.nlsens and t[3] and self.depth == 0):
            op = self.adv()[1]
            return AssignExpr(op=op, target=left, value=self.expr())
        return left

    def ternary(self):
        c = self.binary(3)
        if self.is_op('?') and not (self.nlsens and self.tk()[3] and self.depth == 0):
            self.adv()
            a = self.expr()
            self.expect(':')
            b = self.expr()
            if cval(a) == (True, 'true') and cval(b) == (True, 'false'):
                return CALL('str', c)
            if isinstance(c, ast.Compare) and len(c.ops) == 1 and type(c.ops[0]) in (ast.Lt, ast.LtE, ast.Gt, ast.GtE):
                l, r = c.left, c.comparators[0]
                same = lambda x, y: ast.dump(x) == ast.dump(y)
                small = type(c.ops[0]) in (ast.Lt, ast.LtE)
                if same(a, l) and same(b, r):
                    return CALL('min' if small else 'max', a, b)
                if same(a, r) and same(b, l):
                    return CALL('max' if small else 'min', a, b)
            return ast.IfExp(test=c, body=a, orelse=b)
        return c

    def binary(self, minprec):
        left = self.unary()
        while True:
            t = self.tk()
            op = None
            if t[0] == 'op':
                op = t[1]
            elif t[0] == 'id' and ((t[1] in ('and', 'or') and self.lang == 'PHP') or (t[1] == 'as' and self.lang in ('TypeScript', 'Kotlin', 'Swift', 'C#'))):
                op = {'and': '&&', 'or': '||'}.get(t[1], t[1])
            elif t[0] == 'id' and t[1] in ('is',) and self.lang in ('Kotlin', 'C#'):
                break
            if op is None or (self.nlsens and t[3] and self.depth == 0):
                break
            if op == '.' and self.lang == 'PHP':
                prec = 12
            elif op == '?:':
                prec = 3
            elif op == 'as':
                self.adv()
                if self.parse_type() is None:
                    self.err('cannot understand this type')
                self.accept('?')
                continue
            else:
                prec = BIN_PREC.get(op)
            if prec is None or prec < minprec:
                break
            self.adv()
            if op == '<<' and isinstance(left, OutExpr):
                left.items.append(self.binary(12))
                continue
            if op == '>>' and isinstance(left, InExpr):
                left.targets.append(self.unary())
                continue
            right = self.binary(prec if op == '**' else prec + 1)
            left = self.mk_bin(op, left, right)
        return left

    def mk_bin(self, op, l, r):
        if op in ('&&',):
            return ast.BoolOp(op=ast.And(), values=(l.values if isinstance(l, ast.BoolOp) and isinstance(l.op, ast.And) else [l]) + [r])
        if op == '||':
            return ast.BoolOp(op=ast.Or(), values=(l.values if isinstance(l, ast.BoolOp) and isinstance(l.op, ast.Or) else [l]) + [r])
        if op in CMP_OPS:
            if isinstance(l, ast.Call) and getattr(l.func, 'id', '') == '_indexof':
                ok, v = cval(r)
                if isinstance(r, ast.Attribute) and r.attr == 'npos':
                    ok, v = True, -1
                found = (op in ('>=',) and ok and v == 0) or (op in ('>', '!=', '!==') and ok and v == -1) or (op in ('!==', '!=') and ok and v is False)
                missing = (op in ('<',) and ok and v == 0) or (op in ('==', '===') and ok and (v == -1 or v is False))
                if found or missing:
                    c2 = CALL(MEMBER(l.args[0], 'contains'), l.args[1])
                    return c2 if found else ast.UnaryOp(op=ast.Not(), operand=c2)
            if isinstance(l, ast.Call) and getattr(l.func, 'id', '') == 'strcmp' and cval(r) == (True, 0):
                a, b = l.args
                return ast.Compare(left=a, ops=[CMP_OPS[op]()], comparators=[b])
            return ast.Compare(left=l, ops=[CMP_OPS[op]()], comparators=[r])
        if op in ('??', '?:'):
            return l
        if op == '+':
            return BIN(ast.Add, l, r)
        if op == '-':
            return BIN(ast.Sub, l, r)
        if op == '*':
            return BIN(ast.Mult, l, r)
        if op == '/':
            b = BIN(ast.Div, l, r)
            if self.lang in TYPED_DIV:
                b._cdiv = True
            return b
        if op == '%':
            if isinstance(l, ast.Call) and getattr(l.func, 'id', '') == 'rand':
                return CALL(MEMBER(NM('random'), 'randrange'), r)
            return BIN(ast.Mod, l, r)
        if op == '**':
            return BIN(ast.Pow, l, r)
        if op == '.':
            return BIN(ast.BitAnd, l, r)
        self.err("operator '{0}' is not supported (bitwise operators have no flowchart equivalent)".format(op))

    def unary(self):
        t = self.tk()
        if t[0] == 'op':
            op = t[1]
            if op == '!':
                self.adv()
                return ast.UnaryOp(op=ast.Not(), operand=self.unary())
            if op == '-':
                self.adv()
                o = self.unary()
                ok, v = cval(o)
                if ok and isinstance(v, (int, float)) and not isinstance(v, bool):
                    return K(-v)
                return ast.UnaryOp(op=ast.USub(), operand=o)
            if op == '+':
                self.adv()
                o = self.unary()
                return CALL('float', o) if self.lang in ('JavaScript', 'TypeScript') else o
            if op in ('++', '--'):
                self.adv()
                return IncrExpr(target=self.unary(), delta=1 if op == '++' else -1, prefix=True)
            if op == '&' and self.lang in ('C', 'C++', 'Go', 'Swift'):
                self.adv()
                o = self.unary()
                o._addr = True
                return o
            if op == '*' and self.lang in ('C', 'C++', 'Go'):
                self.err('pointers are not supported')
            if op == '~':
                self.err('bitwise operators have no flowchart equivalent')
            if op == '(' and self.lang in ('C', 'C++', 'Java', 'C#', 'PHP'):
                save = self.i
                self.adv()
                ti = self.parse_type()
                if ti is not None and self.is_op(')') and (ti['ir'] in ('Integer', 'Real', 'String', 'Boolean') or ti['name'] in CAST_NAMES) \
                        and not ti['array'] and self.tk(1)[0] in ('id', 'num', 'str', 'tpl') or (
                        ti is not None and self.is_op(')') and self.tk(1)[0] == 'op' and self.tk(1)[1] in ('(', '!', '-')
                        and ti['ir'] in ('Integer', 'Real', 'String', 'Boolean') and ti['known']):
                    self.adv()
                    return self.cast(ti, self.unary())
                self.i = save
        if t[0] == 'id' and t[1] == 'new':
            return self.postfix(self.p_new())
        return self.postfix(self.primary())

    def cast(self, ti, operand):
        ir = ti['ir']
        if ir == 'Integer' and isinstance(operand, ast.Call) and getattr(operand.func, 'id', '') in ('len', 'int'):
            return operand
        if ir == 'Integer' and cval(operand)[0] and isinstance(cval(operand)[1], int):
            return operand
        name = CAST_NAMES.get(ti['name'])
        if ir == 'Integer' or name == 'int':
            return CALL('int', operand)
        if ir == 'Real' or name == 'float':
            return CALL('float', operand)
        if ir == 'String' or name == 'str':
            return CALL('str', operand)
        return operand

    def p_new(self):
        self.adv()
        ti = self.parse_type_name_only()
        name = ti
        if self.is_op('['):
            self.adv()
            self.depth += 1
            size = None if self.is_op(']') else self.expr()
            self.depth -= 1
            self.expect(']')
            if self.is_op('['):
                self.err('two-dimensional arrays are not supported')
            ir = self.ir_of(name)
            if self.is_op('{'):
                return self.brace_list()
            return ArrayNew(size=size, default=default_node(ir))
        if self.is_op('('):
            args = self.call_args()
            if name == 'Array' and self.lang in ('JavaScript', 'TypeScript'):
                return ArrayNew(size=args[0][1], default=K(0))
            if name in ('Scanner', 'BufferedReader', 'InputStreamReader', 'Random', 'StringReader', 'Object', 'StreamReader'):
                return SkipExpr(id='_obj')
            self.err('objects of type {0} are not supported'.format(name))
        self.err('cannot understand this new-expression')

    def parse_type_name_only(self):
        name = self.adv()[1]
        while self.is_op('.') or self.is_op('::'):
            self.adv()
            name = self.adv()[1]
        if self.is_op('<'):
            depth = 0
            while not self.at_end():
                if self.is_op('<'):
                    depth += 1
                elif self.is_op('>'):
                    depth -= 1
                elif self.is_op('>>'):
                    depth -= 2
                self.adv()
                if depth <= 0:
                    break
        return name

    def postfix(self, node):
        lang = self.lang
        while True:
            t = self.tk()
            if t[0] != 'op':
                break
            op = t[1]
            if self.nlsens and t[3] and self.depth == 0 and op in ('(', '[', '++', '--', '!'):
                break
            if op == '(':
                if lang == 'Go' and isinstance(node, ast.Name) and node.id == 'make':
                    node = self.go_make()
                    continue
                line = t[2]
                args = self.call_args()
                node = self.make_call(node, args, line)
                if lang == 'Kotlin' and isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'Array' and self.is_op('{'):
                    self.adv()
                    d = self.expr()
                    self.expect('}')
                    node = ArrayNew(size=node.args[0], default=d)
                continue
            if op == '[':
                self.adv()
                self.depth += 1
                idx = self.expr()
                self.depth -= 1
                self.expect(']')
                node = SUBS(node, idx)
                continue
            if (op == '.' and lang != 'PHP') or op in ('->', '?.', '::'):
                if op == '->' and lang not in ('PHP', 'C', 'C++'):
                    break
                self.adv()
                name = self.adv()[1]
                if op == '::' and isinstance(node, ast.Name) and node.id == 'std':
                    node = OutExpr(items=[]) if name in ('cout', 'cerr', 'clog') else InExpr(targets=[]) if name == 'cin' else NM(name)
                    if name in ('max', 'min', 'abs', 'pow') and self.is_op('<'):
                        save = self.i
                        self.adv()
                        ti = self.parse_type()
                        if ti is not None and self.is_op('>') and self.is_op('(', 1):
                            self.adv()
                        else:
                            self.i = save
                    continue
                node = MEMBER(node, name)
                if name in SIZE_PROPS and not self.is_op('('):
                    node = CALL('len', node.value)
                elif dotted(node) in ('Math.PI', 'math.pi', 'Double.pi', 'math.Pi', 'M_PI', 'Math.Pi') or (
                        isinstance(node, ast.Attribute) and node.attr in ('PI', 'pi', 'Pi') and dotted(node.value) in MATH_NS | set(['math'])):
                    node = MEMBER(NM('math'), 'pi')
                continue
            if op in ('++', '--'):
                self.adv()
                node = IncrExpr(target=node, delta=1 if op == '++' else -1, prefix=False)
                continue
            if op in ('!!', '!') and lang in ('Kotlin', 'Swift', 'TypeScript'):
                if op == '!' and self.tk(1)[0] == 'op' and self.tk(1)[1] == '=':
                    break
                self.adv()
                continue
            break
        return node

    def go_make(self):
        self.expect('(')
        ti = self.parse_type()
        if ti is None or not ti['array']:
            self.err('make() is supported for slices only')
        self.expect(',')
        size = self.expr()
        if self.accept(','):
            self.expr()
        self.expect(')')
        return ArrayNew(size=size, default=default_node(ti['ir']))

    def call_args(self):
        self.expect('(')
        self.depth += 1
        args = []
        while not self.is_op(')'):
            kw = None
            t, t1 = self.tk(), self.tk(1)
            if t[0] == 'id' and t1[0] == 'op' and ((t1[1] == ':' and self.lang in ('Swift', 'Kotlin')) or (t1[1] == '=' and self.lang in ('Kotlin', 'C#'))):
                kw = t[1]
                self.adv()
                self.adv()
            if self.lang == 'Go' and self.is_op('['):
                ti = self.parse_type()
                if ti and self.is_op('{'):
                    lst = self.brace_list()
                    args.append((kw, lst))
                    if not self.accept(','):
                        break
                    continue
            if self.lang in ('Swift',) and self.is_id('in') is False and kw == 'in':
                pass
            e = self.range_expr() if self.lang in ('Swift', 'Kotlin') else self.expr()
            args.append((kw, e))
            if not self.accept(','):
                break
        self.depth -= 1
        self.expect(')')
        return args

    def primary(self):
        t = self.adv()
        k, v = t[0], t[1]
        lang = self.lang
        if k == 'num' or k == 'str':
            return K(v)
        if k == 'tpl':
            return self.template(v)
        if k == 'op':
            if v == '(':
                self.depth += 1
                e = self.range_expr() if lang in ('Kotlin', 'Swift') else self.expr()
                self.depth -= 1
                self.expect(')')
                return e
            if v == '[':
                if lang == 'Go':
                    self.i -= 1
                    ti = self.parse_type()
                    if ti is None:
                        self.err('cannot understand this array type')
                    if self.is_op('{'):
                        return self.brace_list()
                    self.err('cannot understand this array expression')
                if lang == 'Swift' and self.tk()[0] == 'id':
                    save = self.i
                    ti = self.parse_type()
                    if ti is not None and self.accept(']') and self.is_op('('):
                        args = dict((k2, a) for k2, a in self.call_args())
                        return ArrayNew(size=args.get('count'), default=args.get('repeating'))
                    self.i = save
                self.depth += 1
                items = []
                while not self.is_op(']'):
                    items.append(self.expr())
                    if not self.accept(','):
                        break
                self.depth -= 1
                self.expect(']')
                return ast.List(elts=items)
            if v == '{':
                self.i -= 1
                return self.brace_list()
            if v == '.' and lang == 'Swift' and self.tk()[0] == 'id':
                return NM(self.adv()[1])
            self.i -= 1
            self.err("unexpected '{0}'".format(v))
        if k == 'id':
            if v in ('true', 'True', 'TRUE'):
                return K(True)
            if v in ('false', 'False', 'FALSE'):
                return K(False)
            if v in ('null', 'nullptr', 'NULL', 'nil', 'undefined', 'None'):
                return SkipExpr(id='_obj')
            if v in self.defines:
                sub = CFront(lang, self.defines[v])
                sub.scopes = self.scopes
                return sub.expr()
            if self.lang == 'C++' and v in ('max', 'min', 'abs', 'pow') and self.is_op('<'):
                save = self.i
                self.adv()
                ti = self.parse_type()
                if ti is not None and self.is_op('>') and self.is_op('(', 1):
                    self.adv()
                else:
                    self.i = save
            if v in ('static_cast', 'reinterpret_cast', 'const_cast') and self.is_op('<'):
                self.adv()
                ti = self.parse_type()
                self.expect('>')
                self.expect('(')
                self.depth += 1
                inner = self.expr()
                self.depth -= 1
                self.expect(')')
                return self.cast(ti, inner) if ti else inner
            if v == 'sizeof' and self.is_op('('):
                depth = 0
                while not self.at_end():
                    if self.is_op('('):
                        depth += 1
                    elif self.is_op(')'):
                        depth -= 1
                        if depth == 0:
                            self.adv()
                            break
                    self.adv()
                return K(1)
            if v in ('cout', 'cerr', 'clog'):
                return OutExpr(items=[])
            if v == 'cin':
                return InExpr(targets=[])
            if v in ('function', 'lambda', 'func') and self.is_op('('):
                self.err('anonymous functions are not supported')
            if lang in ('Kotlin',) and v == 'if':
                c = self.paren_expr()
                a = self.expr()
                self.expect('else')
                b = self.expr()
                return ast.IfExp(test=c, body=a, orelse=b)
            if lang == 'PHP':
                if v == 'array' and self.is_op('('):
                    self.adv()
                    items = []
                    while not self.is_op(')'):
                        items.append(self.expr())
                        if not self.accept(','):
                            break
                    self.expect(')')
                    return ast.List(elts=items)
                return NM(v.lstrip('$'))
            return NM(v)
        self.err('unexpected end of file' if k == 'eof' else 'unexpected token')

    def template(self, parts):
        nodes = []
        for p in parts:
            if isinstance(p, str):
                if p:
                    nodes.append(K(p))
            else:
                sub = CFront(self.lang, p[1])
                sub.scopes = self.scopes
                nodes.append(sub.expr())
        if not nodes:
            return K('')
        out = nodes[0]
        if len(nodes) == 1:
            return CALL('str', out) if cval(out)[0] is False else out
        for n in nodes[1:]:
            out = BIN(ast.BitAnd, out, n)
        return out

    # ------------------------------------------------------------ output / input helpers
    def print_call(self, items, newline, sep=None):
        kw = {}
        if not newline:
            kw['end'] = K('')
        if sep is not None:
            kw['sep'] = K(sep)
        return CALL('print', *items, **kw)

    def out_call(self, e):
        items = list(e.items)
        newline = False
        while items and isinstance(items[-1], ast.Name) and items[-1].id in ('endl', 'flush', 'ends'):
            newline = newline or items[-1].id == 'endl'
            items.pop()
        if items:
            ok, c = cval(items[-1])
            if ok and isinstance(c, str) and c.endswith('\n'):
                newline = True
                items[-1] = K(c[:-1])
                if c[:-1] == '':
                    items.pop()
        items = [x for x in items if not (isinstance(x, ast.Call) and getattr(x.func, 'id', '') in ('setprecision', 'setw', 'fixed')) and not (isinstance(x, ast.Name) and x.id in ('fixed', 'left', 'right'))]
        items = [x for x in items if not getattr(x, 'skip', False)]
        if not items and not newline:
            return SkipExpr(id='_obj')
        return self.print_call(items, newline, sep='')

    def typed_input(self, target):
        base = target
        while isinstance(base, ast.Subscript):
            base = base.value
        ir = self.var_ir(base.id) if isinstance(base, ast.Name) else None
        return self.input_of(ir)

    def input_of(self, ir):
        src = CALL('input')
        if ir == 'Integer':
            return CALL('int', src)
        if ir == 'Real':
            return CALL('float', src)
        if ir == 'Boolean':
            return self.bool_parse(src)
        return src

    def bool_parse(self, src):
        low = CALL(MEMBER(src, 'lower'))
        if isinstance(src, ast.Call) and getattr(src.func, 'id', '') == 'input':
            return ast.Compare(left=CALL(MEMBER(CALL(MEMBER(src, 'strip')), 'lower')), ops=[ast.In()],
                               comparators=[ast.Tuple(elts=[K('true'), K('1')])])
        return ast.Compare(left=CALL(MEMBER(src, 'lower')), ops=[ast.Eq()], comparators=[K('true')])

    def fmt_expr(self, fmt, args, csharp=False):
        pieces, ai, buf = [], 0, ''

        def flush():
            if buf:
                pieces.append(K(buf))

        if csharp:
            parts = re.split(r'(\{\d+(?::[^}]*)?\})', fmt)
            for p in parts:
                m = re.match(r'\{(\d+)(?::([^}]*))?\}', p)
                if m:
                    idx = int(m.group(1))
                    if idx >= len(args):
                        self.err('format placeholder {{{0}}} has no argument'.format(idx))
                    a = args[idx]
                    spec = m.group(2) or ''
                    mm = re.match(r'[FfNn](\d+)', spec)
                    if mm:
                        a = self.round_to(a, int(mm.group(1)))
                    pieces.append(a)
                elif p:
                    pieces.append(K(p))
        else:
            i = 0
            rx = re.compile(r'%([-+ 0#]*)(\d+|\*)?(?:\.(\d+))?(hh|h|ll|l|L|z|j|t)?([diuoxXfFeEgGcsvtqpn%])')
            while i < len(fmt):
                m = rx.match(fmt, i) if fmt[i] == '%' else None
                if m:
                    conv = m.group(5)
                    if conv == '%':
                        buf += '%'
                    elif conv == 'n':
                        buf += '\n'
                    else:
                        flush()
                        buf = ''
                        if ai >= len(args):
                            self.err('format string needs more arguments')
                        a = args[ai]
                        ai += 1
                        if conv in 'fFeEgG':
                            self.warn('number formatting like %.2f is approximated by rounding')
                            if m.group(3) is not None:
                                a = self.round_to(a, int(m.group(3)))
                        elif conv in 'xXo':
                            self.err('hexadecimal/octal output is not supported')
                        pieces.append(a)
                    i = m.end()
                else:
                    buf += fmt[i]
                    i += 1
            flush()
        if not pieces:
            return K(''), False
        newline = False
        last = pieces[-1]
        ok, c = cval(last)
        if ok and isinstance(c, str) and c.endswith('\n'):
            newline = True
            if c[:-1]:
                pieces[-1] = K(c[:-1])
            else:
                pieces.pop()
        if not pieces:
            return K(''), newline
        out = pieces[0]
        for p in pieces[1:]:
            out = BIN(ast.BitAnd, out, p)
        return out, newline

    def round_to(self, a, p):
        scale = K(10 ** p)
        return BIN(ast.Div, CALL('round', BIN(ast.Mult, a, scale)), scale)

    def str_lit(self, n):
        ok, c = cval(n)
        return c if ok and isinstance(c, str) else None

    def make_call(self, callee, args, line):
        lang = self.lang
        pos = [a for k, a in args if k is None]
        kwd = dict((k, a) for k, a in args if k)
        allargs = [a for k, a in args if k not in ('separator', 'terminator')]
        dn = dotted(callee) or ''
        last = callee.attr if isinstance(callee, ast.Attribute) else (callee.id if isinstance(callee, ast.Name) else '')
        recv = callee.value if isinstance(callee, ast.Attribute) else None
        if last in ('push', 'push_back') and recv is not None and getattr(self, 'fill_ctx', False):
            return CALL('_fill', recv, pos[0])
        if last in ('push', 'push_back', 'append', 'add', 'Add', 'Push', 'insert', 'pop', 'remove', 'Append') and recv is not None \
                and not dn.startswith(('System', 'Console')):
            self.err('dynamic lists ({0}) are not supported; create a fixed-size array and assign elements'.format(last))
        # ---- output
        if dn in PRINTF or (dn in ('Console.WriteLine', 'Console.Write') and pos and (self.str_lit(pos[0]) or '').find('{0') >= 0) \
                or (dn in ('Console.WriteLine', 'Console.Write') and False):
            f = self.str_lit(pos[0]) if pos else None
            if f is None:
                self.err('the format string of printf must be a literal')
            cs = dn.startswith('Console') 
            e, nl = self.fmt_expr(f, pos[1:], csharp=cs)
            if dn == 'Console.Write':
                nl = False
            elif dn == 'Console.WriteLine':
                nl = True
            return self.print_call([e], nl)
        if dn in SPRINTF:
            f = self.str_lit(pos[0]) if pos else None
            if f is None:
                self.err('the format string must be a literal')
            return self.fmt_expr(f, pos[1:], csharp=dn in ('string.Format', 'String.Format'))[0]
        if dn in PRINTLN or (dn == 'print' and lang == 'Swift') or (last in ('println', 'Println') and lang in ('Java', 'Kotlin', 'Go')):
            term = kwd.get('terminator')
            sep = self.str_lit(kwd['separator']) if 'separator' in kwd else None
            nl = term is None or self.str_lit(term) == '\n'
            items = allargs
            if term is not None and self.str_lit(term) not in ('\n', ''):
                items = items + [term]
            return self.print_call(items, nl, sep)
        if dn in PRINTNL or (dn == 'print' and lang in ('Kotlin', 'PHP')) or (last in ('Print',) and lang == 'Go'):
            return self.print_call(allargs, False, '' if lang == 'Go' else None)
        if dn == 'puts' or dn == 'fputs':
            return self.print_call(pos[:1], dn == 'puts')
        if lang == 'PHP' and dn == 'print':
            return self.print_call(allargs, False)
        # ---- input
        if dn in ('scanf', 'fmt.Scan', 'fmt.Scanln', 'fmt.Scanf', 'sscanf', 'fscanf', 'cin.get'):
            targets = [a for a in pos if getattr(a, '_addr', False) or isinstance(a, (ast.Name, ast.Subscript))]
            f = self.str_lit(pos[0]) if pos and self.str_lit(pos[0]) is not None else ''
            convs = re.findall(r'%\*?(?:hh|h|ll|l|L)?([diufeEgGsc])', f)
            stmts = []
            for j, tg in enumerate(targets):
                if isinstance(tg, ast.Name) and tg.id == 'stdin':
                    continue
                if j < len(convs):
                    ir = {'d': 'Integer', 'i': 'Integer', 'u': 'Integer', 'f': 'Real', 'e': 'Real', 'g': 'Real', 'E': 'Real', 'G': 'Real'}.get(convs[j], 'String')
                else:
                    ir = self.var_ir(tg.id) if isinstance(tg, ast.Name) else None
                stmts.append(ast.Assign(targets=[tg], value=self.input_of(ir) if j >= len(convs) or True else None))
            return StmtList(stmts=stmts)
        if dn in ('getline', 'std.getline') or (last == 'getline' and recv is None):
            return StmtList(stmts=[ast.Assign(targets=[pos[1]], value=CALL('input'))])
        if dn in ('fgets', 'gets', 'fgets_s') and len(pos) >= 2 and isinstance(pos[0], ast.Name):
            return StmtList(stmts=[ast.Assign(targets=[pos[0]], value=CALL('input'))])
        if dn in ('fgets', 'readline') and lang == 'PHP' or dn in INPUT_NAMES or last in INPUT_NAMES or last in ('ReadLine',):
            if not (last == 'question' and not pos):
                return CALL('input')
        if last in ('nextInt', 'nextLong', 'nextShort', 'nextByte', 'ReadInt', 'readInt') and not pos:
            return CALL('int', CALL('input'))
        if last in ('nextDouble', 'nextFloat') and not pos:
            return CALL('float', CALL('input'))
        if last in ('nextLine', 'next', 'readLine', 'Text', 'ReadString') and recv is not None and (not pos or last == 'ReadString'):
            return CALL('input')
        if last == 'nextBoolean':
            return self.bool_parse(CALL('input'))
        if last in ('nextInt', 'Intn', 'Int63n', 'Int31n', 'randrange', 'next_int', 'nextLong') and pos and recv is not None and last != 'nextInt' or (last == 'nextInt' and pos):
            return CALL(MEMBER(NM('random'), 'randrange'), pos[0])
        if dn in ('flowRandom', 'rand.Int63n', 'rand.Intn') and pos:
            return CALL(MEMBER(NM('random'), 'randrange'), pos[0])
        if dn in ('mt_rand', 'random_int', 'rand', 'Random.nextInt') and len(pos) == 2:
            return CALL(MEMBER(NM('random'), 'randint'), pos[0], pos[1])
        if dn == 'rand' and not pos:
            return CALL('rand')
        if last == 'random' and 'in' in kwd and isinstance(kwd['in'], RangeExpr):
            r = kwd['in']
            hi = r.stop if not r.inclusive else BIN(ast.Add, r.stop, K(1))
            return CALL(MEMBER(NM('random'), 'randint' if r.inclusive else 'randrange'), *([r.start, r.stop] if r.inclusive else [r.stop]))
        # ---- ignored calls and exits
        if last in IGNORED_CALLS or dn in IGNORED_CALLS or last in ('Scanner', 'BufferedReader', 'InputStreamReader', 'NewReader', 'NewScanner', 'NewWriter', 'Random', 'StringBuilder'):
            return SkipExpr(id='_obj')
        if dn in EXIT_NAMES or last in EXIT_NAMES:
            return StmtList(stmts=[ast.Return(value=None)])
        # ---- conversions
        if dn in INT_CONV or (last in INT_CONV and recv is not None and last.startswith('to')) or (recv is None and last in INT_CONV):
            src = recv if (recv is not None and last.startswith('to') and not pos) else (pos[0] if pos else None)
            if src is None:
                self.err('missing argument for ' + dn)
            return CALL('int', src)
        if dn in REAL_CONV or (last in REAL_CONV and recv is not None and last.startswith('to')) or (recv is None and last in REAL_CONV):
            src = recv if (recv is not None and last.startswith('to') and not pos) else (pos[0] if pos else None)
            if src is None:
                self.err('missing argument for ' + dn)
            return CALL('float', src)
        if dn in ('Boolean.parseBoolean', 'bool.Parse', 'strconv.ParseBool', 'flowBool', 'flow_bool', 'toBoolean', 'Boolean.valueOf') or (last in ('toBoolean',) and recv is not None):
            return self.bool_parse(pos[0] if pos else recv)
        if dn in STR_CONV or (last in ('toString', 'ToString', 'to_string') and recv is not None):
            src = recv if (recv is not None and last in ('toString', 'ToString') and not pos) else pos[0]
            return CALL('str', src)
        if recv is None and last in INT_T and len(pos) == 1:
            return CALL('int', pos[0])
        if recv is None and last in REAL_T and len(pos) == 1:
            return CALL('float', pos[0])
        if recv is None and last in ('String', 'string', 'str') and len(pos) == 1:
            return CALL('str', pos[0])
        if lang == 'C++' and recv is None and last == 'string' and len(pos) == 2 and cval(pos[0]) == (True, 1):
            # std::string(1, character) wraps a single indexed character. The
            # shared IR already represents a string index as a one-letter string.
            return CALL('str', pos[1])
        if recv is None and last in ('static_cast', ) :
            return pos[0]
        # ---- containers
        if recv is None and last == 'Array' and ('repeating' in kwd or 'count' in kwd):
            return ArrayNew(size=kwd.get('count'), default=kwd.get('repeating'))
        if lang == 'Swift' and recv is None and last == 'Array' and len(pos) == 1:
            # Swift needs Array(text)[index] for character access; the IR can
            # index text directly, preserving the same character value.
            return pos[0]
        if last in ('IntArray', 'LongArray', 'DoubleArray', 'BooleanArray', 'ShortArray', 'FloatArray') and pos:
            return ArrayNew(size=pos[0], default=default_node(ARRAY_T[last]))
        if last in ('arrayOf', 'listOf', 'intArrayOf', 'doubleArrayOf', 'longArrayOf', 'mutableListOf', 'booleanArrayOf'):
            return ast.List(elts=pos)
        if last == 'array_fill' and len(pos) == 3:
            return ArrayNew(size=pos[1], default=pos[2])
        if recv is not None and last == 'fill' and isinstance(recv, ArrayNew):
            recv.default = pos[0] if pos else K(0)
            return recv
        if recv is None and last == 'Array' and lang in ('JavaScript', 'TypeScript') and pos:
            return ArrayNew(size=pos[0], default=K(0))
        if last in ('indexOf', 'IndexOf', 'strpos', 'find') and (pos if recv is None else pos[:1]):
            return CALL('_indexof', *(([recv] if recv is not None else []) + pos[:2 if recv is None else 1]))
        if last in ('count', 'sizeof') and recv is None and pos:
            return CALL('len', pos[0])
        if recv is None and last in HELPER_FUNCS:
            kind = HELPER_FUNCS[last]
            if kind == 'cat' and len(pos) == 2:
                return BIN(ast.BitAnd, pos[0], pos[1])
            if kind in ('upper', 'lower', 'strip'):
                return CALL(MEMBER(pos[0], kind))
            if kind == 'contains':
                return CALL(MEMBER(pos[0], 'contains'), pos[1])
            if kind == 'char':
                return SUBS(pos[0], pos[1])
            if kind == 'int':
                return CALL('int', pos[0])
            if kind == 'abs':
                return CALL('abs', pos[0])
        if last in ('calloc', 'malloc', 'realloc') and recv is None and pos:
            size = pos[0]
            if last == 'calloc' and len(pos) == 2:
                size = pos[0]
            elif isinstance(size, ast.BinOp) and isinstance(size.op, ast.Mult):
                size = size.right if cval(size.left) == (True, 1) else size.left
            while isinstance(size, ast.Call) and getattr(size.func, 'id', '') == 'int' and len(size.args) == 1:
                size = size.args[0]
            return ArrayNew(size=size, default=None)
        if last == 'fill' and dn.endswith('Arrays.fill') and len(pos) == 2:
            return StmtList(stmts=[ArrayFill(name=pos[0].id, size=None, default=pos[1])])
        if last in ('push', 'push_back') and recv is not None and isinstance(recv, ast.Name) and getattr(self, 'fill_ctx', False):
            return CALL('_fill', recv, pos[0])
        # ---- strings
        if recv is not None and not (dn.split('.')[0] in MATH_NS and last in MATH_FUNCS):
            if last in ('length', 'Length', 'size', 'count', 'Count') and not pos:
                return CALL('len', recv)
            if last in ('toUpperCase', 'ToUpper', 'uppercase', 'uppercased', 'upper', 'toUpper') and not pos:
                return CALL(MEMBER(recv, 'upper'))
            if last in ('toLowerCase', 'ToLower', 'lowercase', 'lowercased', 'lower', 'toLower') and not pos:
                return CALL(MEMBER(recv, 'lower'))
            if last in ('trim', 'Trim', 'strip', 'trimmingCharacters', 'TrimEnd', 'TrimStart', 'trimEnd', 'trimStart'):
                return CALL(MEMBER(recv, 'strip'))
            if last in ('contains', 'Contains', 'includes') and len(pos) == 1:
                return CALL(MEMBER(recv, 'contains'), pos[0])
            if last in ('charAt', 'at', 'CharAt') and len(pos) == 1:
                return SUBS(recv, pos[0])
            if last in ('substring', 'Substring', 'substr') and len(pos) == 2:
                a, b = pos
                if isinstance(b, ast.BinOp) and isinstance(b.op, ast.Add) and ast.dump(b.left) == ast.dump(a) and cval(b.right) == (True, 1):
                    return SUBS(recv, a)
                if cval(b) == (True, 1):
                    return SUBS(recv, a)
                self.err('only single-character substrings are supported')
            if last in ('equals', 'Equals', 'equalsIgnoreCase') and len(pos) == 1:
                return ast.Compare(left=recv, ops=[ast.Eq()], comparators=[pos[0]])
        # ---- math
        ns = dn.rsplit('.', 1)[0] if '.' in dn else ''
        lname = last.lower()
        if (ns in MATH_NS or ns.endswith('Math') or (recv is None and lname in MATH_FUNCS and True)) and lname in MATH_FUNCS and pos:
            return CALL(MEMBER(NM('math'), MATH_FUNCS[lname]), *pos[:1])
        if (ns in MATH_NS or recv is None) and lname in ('floor', 'ceil') and pos:
            return CALL(MEMBER(NM('math'), lname), pos[0])
        if (ns in MATH_NS or ns.endswith('Math') or recv is None) and lname in ('abs', 'fabs', 'labs', 'llabs') and pos:
            return CALL('abs', pos[0])
        if (ns in MATH_NS or ns.endswith('Math') or recv is None) and lname == 'pow' and len(pos) == 2:
            return BIN(ast.Pow, pos[0], pos[1])
        if (ns in MATH_NS or ns.endswith('Math') or recv is None) and lname in ('max', 'min') and len(pos) == 2:
            return CALL(lname, *pos)
        if (ns in MATH_NS or ns.endswith('Math') or recv is None) and lname in ('round', 'llround', 'lround', 'rint', 'roundtoeven') and len(pos) == 1:
            return CALL('round', pos[0])
        if (ns in MATH_NS or ns.endswith('Math') or recv is None) and lname in ('trunc', 'truncate') and len(pos) == 1:
            return CALL('int', pos[0])
        if last == 'strlen' or (recv is None and last == 'len' and len(pos) == 1) or last in ('mb_strlen', 'strlen'):
            return CALL('len', pos[0])
        if last in ('strtoupper', 'toupper') and len(pos) == 1 and recv is None:
            return CALL(MEMBER(pos[0], 'upper'))
        if last in ('strtolower', 'tolower') and len(pos) == 1 and recv is None:
            return CALL(MEMBER(pos[0], 'lower'))
        if last in ('ToUpper', 'ToLower', 'TrimSpace', 'Contains') and ns == 'strings':
            m = {'ToUpper': 'upper', 'ToLower': 'lower', 'TrimSpace': 'strip', 'Contains': 'contains'}[last]
            return CALL(MEMBER(pos[0], m), *pos[1:])
        if last == 'trim' and recv is None and pos:
            return CALL(MEMBER(pos[0], 'strip'))
        if last == 'strpos' and False:
            pass
        if last == 'intdiv' and len(pos) == 2:
            return CALL('int', BIN(ast.Div, pos[0], pos[1]))
        if last == 'strcpy' and len(pos) == 2:
            return StmtList(stmts=[ast.Assign(targets=[pos[0]], value=pos[1])])
        if last == 'strcat' and len(pos) == 2:
            return StmtList(stmts=[ast.Assign(targets=[pos[0]], value=BIN(ast.BitAnd, pos[0], pos[1]))])
        if last == 'strcmp' and len(pos) == 2:
            return CALL('strcmp', *pos)
        if last == 'stride' and recv is None and kwd:
            return CALL('stride', **kwd)
        if last == 'swap' and len(pos) == 2 and (recv is None or dn in ('std.swap',)):
            return StmtList(stmts=[ast.Assign(targets=[ast.Tuple(elts=[pos[0], pos[1]])], value=ast.Tuple(elts=[pos[1], pos[0]]))])
        if last == 'reversed' and isinstance(recv, RangeExpr) and not pos:
            hi = recv.stop if recv.inclusive else BIN(ast.Sub, recv.stop, K(1))
            return RangeExpr(start=hi, stop=recv.start, step='down', inclusive=True)
        if last == 'rounded' and recv is not None and not pos:
            return CALL('round', recv)
        if last in ('compareTo', 'CompareTo', 'compare') and recv is not None and len(pos) == 1:
            return CALL('strcmp', recv, pos[0])
        if last in ('CompareOrdinal', 'Compare') and len(pos) == 2:
            return CALL('strcmp', *pos)
        if last in ('substr', 'mb_substr') and recv is None and len(pos) == 3 and cval(pos[2]) == (True, 1):
            return SUBS(pos[0], pos[1])
        # ---- user function (or unknown)
        if isinstance(callee, ast.Name):
            return CALL(callee.id, *allargs)
        if isinstance(callee, ast.Attribute) and recv is not None and dotted(recv) in ('this', 'self', 'Program', 'Main', 'main', 'Solution'):
            return CALL(callee.attr, *allargs)
        self.err('the call {0}(...) is not supported'.format(dn or last or 'expression'))


TYPED_DIV = ('C', 'C++', 'C#', 'Java', 'Go', 'Kotlin', 'Swift')
CMP_OPS = {'==': ast.Eq, '===': ast.Eq, '!=': ast.NotEq, '!==': ast.NotEq, '<>': ast.NotEq,
           '<': ast.Lt, '<=': ast.LtE, '>': ast.Gt, '>=': ast.GtE}
BIN_PREC = {'??': 3, '||': 4, '&&': 5, '|': 6, '^': 7, '&': 8, '==': 9, '!=': 9, '===': 9, '!==': 9, '<>': 9,
            '<': 10, '<=': 10, '>': 10, '>=': 10, '<<': 11, '>>': 11,
            '+': 12, '-': 12, '*': 13, '/': 13, '%': 13, '**': 14}
ASSIGN_OPS = {'=', '.=', '+=', '-=', '*=', '/=', '%=', ':=', '&=', '|=', '^=', '<<=', '>>=', '>>>='}
AUG = {'+=': ast.Add, '-=': ast.Sub, '*=': ast.Mult, '%=': ast.Mod}
LAST_WARNINGS = []


def default_node(ir):
    return K({'Integer': 0, 'Real': 0.0, 'String': '', 'Boolean': False}.get(ir, 0))


def dotted(n):
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Attribute):
        d = dotted(n.value)
        return None if d is None else d + '.' + n.attr
    return None


class StmtList(ast.AST):
    _fields = ('stmts',)


class ArrayNew(ast.AST):
    _fields = ('size', 'default')


class ArrayFill(ast.AST):
    _fields = ('name', 'size', 'default')


class CFront(CExprMixin):
    def __init__(self, lang, text):
        self.lang = lang
        self.toks, self.comments, self.defines = tokenize_clike(text, lang)
        self.i = 0
        self.ci = 0
        self.depth = 0
        self.nlsens = lang in ('Go', 'Kotlin', 'Swift', 'JavaScript', 'TypeScript')
        self.scopes = [{'name': 'Main', 'seed': {}}]
        self.funcs = []
        self.main_body = []
        self.warnings = []
        self.objects = set()
        self.tmp = 0

    # ----------------------------------------------------------------- tokens
    def tk(self, k=0):
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def adv(self):
        t = self.toks[self.i]
        if self.i < len(self.toks) - 1:
            self.i += 1
        return t

    def is_op(self, v, k=0):
        t = self.tk(k)
        return t[0] == 'op' and t[1] == v

    def is_id(self, v, k=0):
        t = self.tk(k)
        return t[0] == 'id' and t[1] == v

    def accept(self, v):
        t = self.tk()
        if t[0] in ('op', 'id') and t[1] == v:
            self.adv()
            return True
        return False

    def expect(self, v):
        if not self.accept(v):
            self.err("expected '{0}' but found '{1}'".format(v, self.tk()[1] or 'end of file'))

    def err(self, msg):
        raise ParseError('Line {0}: {1}'.format(self.tk()[2], msg))

    def warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)

    def at_end(self):
        return self.tk()[0] == 'eof'

    def eos(self):
        """Optional statement terminator."""
        if self.accept(';'):
            return
        t = self.tk()
        if t[0] == 'eof' or (t[0] == 'op' and t[1] == '}') or (self.nlsens and t[3]):
            return
        if self.lang == 'PHP' and t[1] == '?>':
            return
        self.err("expected ';' but found '{0}'".format(t[1]))

    def comments_before(self, line):
        out = []
        while self.ci < len(self.comments) and self.comments[self.ci][0] < line:
            out.append(AT(ast.Expr(value=K(self.comments[self.ci][1])), self.comments[self.ci][0]))
            self.ci += 1
        return out

    @property
    def scope(self):
        return self.scopes[-1]

    def seed(self, name, ir, arr=False):
        if ir is not None or arr:
            self.scope['seed'][name] = (ir, arr)

    def var_ir(self, name):
        s = self.scope['seed'].get(name)
        return s[0] if s else None

    # ----------------------------------------------------------------- types
    def ir_of(self, name):
        if name in INT_T:
            return 'Integer'
        if name in REAL_T:
            return 'Real'
        if name in STR_T:
            return 'String'
        if name in BOOL_T:
            return 'Boolean'
        if name in VOID_T:
            return 'None'
        return None

    def parse_type(self):
        """Try to parse a type; returns dict or None (position restored by caller)."""
        lang = self.lang
        info = {'name': None, 'ir': None, 'array': False, 'ptr': False, 'known': False, 'void': False}
        while self.tk()[0] == 'id' and self.tk()[1] in MODIFIERS:
            self.adv()
        if lang == 'Go' and self.is_op('['):
            self.adv()
            if self.tk()[0] == 'num':
                self.adv()
            if not self.accept(']'):
                return None
            sub = self.parse_type()
            if sub is None:
                return None
            sub['array'] = True
            return sub
        if lang == 'Swift' and self.is_op('['):
            self.adv()
            sub = self.parse_type()
            if sub is None or not self.accept(']'):
                return None
            sub['array'] = True
            return sub
        if self.is_op('*') and lang == 'Go':
            self.adv()
        t = self.tk()
        if t[0] != 'id':
            return None
        name = t[1]
        self.adv()
        while (self.is_op('::') or (self.is_op('.') and lang in ('Java', 'C#', 'Kotlin', 'Swift', 'TypeScript'))) and self.tk(1)[0] == 'id':
            self.adv()
            name = self.adv()[1]
        if name in ('long', 'short', 'unsigned', 'signed'):
            while self.tk()[0] == 'id' and self.tk()[1] in ('long', 'int', 'double', 'short', 'char', 'unsigned', 'signed'):
                if self.tk()[1] == 'double':
                    name = 'double'
                elif self.tk()[1] == 'char':
                    name = 'char'
                elif name in ('unsigned', 'signed', 'short'):
                    name = 'int'
                self.adv()
            if name in ('unsigned', 'signed'):
                name = 'int'
        info['name'] = name
        ir = self.ir_of(name)
        if ir == 'None':
            info['void'] = True
            ir = None
        info['ir'] = ir
        info['known'] = ir is not None or info['void'] or name in ANY_T
        if name in ARRAY_T:
            info.update(ir=ARRAY_T[name], array=True, known=True)
        if self.is_op('<') and (name[:1].isupper() or name in ('vector', 'array', 'list', 'map', 'set', 'unique_ptr', 'span')):
            j, depth = 0, 0
            while True:
                t = self.tk(j)
                if t[0] == 'eof' or (t[0] == 'op' and t[1] in (';', '{', '}', '(', ')')):
                    return None
                if t[0] == 'op' and t[1] == '<':
                    depth += 1
                elif t[0] == 'op' and t[1] == '>':
                    depth -= 1
                elif t[0] == 'op' and t[1] == '>>':
                    depth -= 2
                j += 1
                if depth <= 0:
                    break
            inner = [self.tk(k) for k in range(1, j - 1)]
            self.i += j
            ids = [x[1] for x in inner if x[0] == 'id']
            if name in ('vector', 'List', 'ArrayList', 'Array', 'array', 'list', 'MutableList', 'span', 'IntArray'):
                info['array'] = True
                info['known'] = True
                info['ir'] = self.ir_of(ids[0]) if ids else None
        while True:
            if (self.is_op('*') or self.is_op('**')) and lang in ('C', 'C++'):
                # The shared lexer keeps ** as one token for languages with
                # exponentiation. In a C type it denotes two pointer levels.
                pointer = self.adv()[1]
                info['stars'] = info.get('stars', 0) + len(pointer)
                info['ptr'] = True
            elif self.is_op('&') and lang in ('C++',):
                self.adv()
            elif self.is_op('?') and lang in ('Kotlin', 'Swift', 'C#', 'TypeScript'):
                self.adv()
            elif self.is_op('[') and self.is_op(']', 1) and lang in ('Java', 'C#', 'TypeScript', 'JavaScript'):
                self.adv()
                self.adv()
                info['array'] = True
            elif self.is_op('...') and lang in ('Java',):
                self.adv()
                info['array'] = True
            else:
                break
        if name == 'char' and info.get('stars', 0) >= 2:
            info.update(ptr=False, array=True, ir='String')
        elif name == 'char' and (info['ptr'] or info['array']):
            info.update(ptr=False, array=False, ir='String')
        elif info['ptr'] and info['ir'] is not None and lang == 'C':
            info['array'] = True
            info['ptr'] = False
        elif info['ptr']:
            return None
        return info

    # ------------------------------------------------------------ program
    def parse_program(self):
        body = []
        while not self.at_end():
            body.extend(self.parse_top())
        body.extend(self.comments_before(10 ** 9))
        body = self.merge_fills(body)
        self.main_body = self.merge_fills(self.main_body)
        mod = ast.Module(body=self.funcs + self.main_body + body)
        mod._seed = self.scopes[0]['seed']
        return mod

    def skip_stmt(self):
        depth = 0
        while not self.at_end():
            if self.is_op('('):
                depth += 1
            elif self.is_op(')'):
                depth -= 1
            elif self.accept(';') or (self.nlsens and self.tk(1)[3] and depth <= 0 and not self.is_op(',')):
                if self.tk(-1)[1] != ';' and not self.is_op(';'):
                    self.adv()
                return
            if depth <= 0 and self.tk()[1] == ';' and self.tk()[0] == 'op':
                self.adv()
                return
            self.adv()

    def parse_top(self):
        t = self.tk()
        line = t[2]
        v = t[1] if t[0] == 'id' else None
        if v in ('package', 'import', 'using', 'namespace', 'use', 'declare', 'extern', 'typedef') or (v == 'from' and self.lang == 'Python'):
            if v == 'import' and self.is_op('(', 1):
                self.adv()
                depth = 0
                while not self.at_end():
                    if self.is_op('('):
                        depth += 1
                    elif self.is_op(')'):
                        depth -= 1
                        if depth == 0:
                            self.adv()
                            break
                    self.adv()
                return []
            if v == 'namespace' and self.tk(2)[1] == '{' or (v == 'namespace' and self.tk(1)[0] == 'id' and self.is_op('{', 2)):
                self.adv()
                while not self.is_op('{'):
                    self.adv()
                return self.parse_members()
            self.skip_stmt()
            return []
        if v in ('class', 'struct', 'interface', 'object', 'enum', 'record') or (
                v in MODIFIERS and self.tk(1)[1] in ('class', 'struct', 'interface', 'object', 'record')) or (
                v in MODIFIERS and self.tk(2)[1] in ('class', 'struct', 'interface')):
            while not self.is_op('{') and not self.at_end():
                self.adv()
            return self.parse_members()
        if v == 'template' and self.is_op('<', 1):
            depth = 0
            while not self.at_end():
                if self.is_op('<'):
                    depth += 1
                elif self.is_op('>'):
                    depth -= 1
                    if depth == 0:
                        self.adv()
                        break
                self.adv()
            return self.parse_top()
        if self.lang == 'PHP' and v in ('namespace',):
            self.skip_stmt()
            return []
        if self.try_function():
            return []
        return self.parse_statement()

    def parse_members(self):
        """Inside class { ... }: methods become functions; fields are rejected."""
        self.expect('{')
        out = []
        while not self.is_op('}') and not self.at_end():
            save = self.i
            if self.try_function():
                continue
            if self.accept(';'):
                continue
            t = self.tk()
            if t[0] == 'id' and t[1] in ('class', 'struct', 'object'):
                while not self.is_op('{') and not self.at_end():
                    self.adv()
                out.extend(self.parse_members())
                continue
            out.extend(self.parse_statement())
        self.expect('}')
        return out

    # ------------------------------------------------------------ functions
    def fn_start(self):
        """Return ('kind', name_index_offset) if a function definition starts here."""
        lang = self.lang
        t = self.tk()
        k = 0
        while self.tk(k)[0] == 'id' and self.tk(k)[1] in MODIFIERS | set(['async', 'export', 'default']):
            k += 1
        w = self.tk(k)[1]
        if lang in ('JavaScript', 'TypeScript', 'PHP') and w == 'function' and self.tk(k + 1)[0] == 'id' and self.is_op('(', k + 2):
            return k + 1, 'js'
        if lang == 'Kotlin' and w == 'fun':
            return (k + 1 if self.tk(k + 1)[0] == 'id' else k + 5), 'kt'
        if lang == 'Swift' and w == 'func' and self.tk(k + 1)[0] == 'id':
            return k + 1, 'swift'
        if lang == 'Go' and w == 'func' and self.tk(k + 1)[0] == 'id' and self.is_op('(', k + 2):
            return k + 1, 'go'
        if lang in ('C', 'C++', 'C#', 'Java'):
            save = self.i
            self.i += k
            try:
                info = self.parse_type()
                if info is None or self.tk()[0] != 'id' or not self.is_op('(', 1):
                    return None
                if lang == 'C++' and self.tk()[1] in ('operator',):
                    return None
                name_off = self.i - save
                # find matching ) and check for { or ;
                j, depth = 1, 0
                while True:
                    tt = self.tk(j)
                    if tt[0] == 'eof':
                        return None
                    if tt[0] == 'op' and tt[1] == '(':
                        depth += 1
                    elif tt[0] == 'op' and tt[1] == ')':
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                j += 1
                while self.tk(j)[0] == 'id' and self.tk(j)[1] in ('const', 'throws', 'override', 'noexcept', 'final'):
                    j += 1
                    while self.tk(j)[0] == 'id' and self.tk(j - 1)[1] == 'throws':
                        j += 1
                        if self.is_op(',', j):
                            j += 1
                nxt = self.tk(j)
                if nxt[1] == '{' and nxt[0] == 'op':
                    return name_off, 'c'
                if nxt[1] == ';' and nxt[0] == 'op':
                    # prototype or constructor-call declaration: prototype if first token is a type or empty
                    first = self.tk(2)
                    if first[0] == 'op' and first[1] == ')':
                        return name_off, 'proto'
                    save2 = self.i
                    self.i += 2
                    isproto = self.parse_type() is not None and self.tk()[0] in ('id',) or (first[0] == 'id' and (first[1] in ('void',)))
                    self.i = save2
                    if isproto:
                        return name_off, 'proto'
                return None
            finally:
                self.i = save
        return None

    def try_function(self):
        fs = self.fn_start()
        if fs is None:
            return False
        off, kind = fs
        if kind == 'proto':
            self.skip_stmt()
            return True
        lang = self.lang
        line = self.tk()[2]
        rettype = None
        if kind == 'c':
            while self.tk()[0] == 'id' and self.tk()[1] in MODIFIERS:
                self.adv()
            rettype = self.parse_type()
            name = self.adv()[1]
        else:
            while self.tk()[1] not in ('function', 'fun', 'func'):
                self.adv()
            self.adv()
            if lang == 'Kotlin' and self.is_op('<'):
                while not self.is_op('>'):
                    self.adv()
                self.adv()
            name = self.adv()[1]
        self.expect('(')
        params = self.parse_params()
        ret_ir, ret_void = None, False
        if rettype is not None:
            ret_ir, ret_void = rettype['ir'], rettype['void']
            if rettype['array']:
                self.err('functions that return arrays are not supported')
        else:
            if (lang in ('TypeScript', 'Kotlin', 'PHP') and self.accept(':')):
                rt = self.parse_type()
                if rt:
                    ret_ir, ret_void = rt['ir'], rt['void'] or rt['name'] in ('void', 'Unit')
            elif lang == 'Swift' and self.accept('->'):
                rt = self.parse_type()
                if rt:
                    ret_ir, ret_void = rt['ir'], rt['void']
            elif lang == 'Go' and not self.is_op('{'):
                rt = self.parse_type()
                if rt:
                    ret_ir = rt['ir']
            if ret_ir is None and lang in ('Kotlin', 'Swift', 'Go', 'TypeScript', 'PHP') and rettype is None:
                ret_void = ret_void or not self.had_ret_type if False else ret_void
        while self.tk()[0] == 'id' and self.tk()[1] in ('const', 'throws', 'override', 'noexcept', 'final'):
            self.adv()
        scope = {'name': name, 'seed': {}}
        for p in params:
            if p[1] is not None or p[2]:
                scope['seed'][p[0]] = (p[1], p[2])
        self.scopes.append(scope)
        self.expect('{')
        body = self.parse_stmts_until_close()
        self.scopes.pop()
        if name.lower() == 'main' and name in ('main', 'Main'):
            while body and isinstance(body[-1], ast.Return) and (body[-1].value is None or cval(body[-1].value)[0]):
                body.pop()
            self.main_body = body
            for k2, v2 in scope['seed'].items():
                self.scopes[0]['seed'].setdefault(k2, v2)
            return True
        if name.startswith('flow') or name.startswith('_') or name.startswith('.'):
            return True
        args = ast.arguments(args=[ast.arg(arg=p[0], annotation=None) for p in params], vararg=None, kwarg=None,
                             defaults=[], kwonlyargs=[], kw_defaults=[])
        fd = AT(ast.FunctionDef(name=name, args=args, body=body or [AT(ast.Pass(), line)], decorator_list=[], returns=None), line)
        fd._ptypes = [(p[1], p[2]) if (p[1] is not None or p[2]) else None for p in params]
        if ret_void:
            fd._ret = 'None'
        elif ret_ir is not None:
            fd._ret = ret_ir
        elif lang in ('C', 'C++', 'C#', 'Java', 'Go', 'Kotlin', 'Swift') and rettype is not None:
            fd._ret = 'None'
        fd._seed = {k: v for k, v in scope['seed'].items() if k not in [p[0] for p in params]}
        self.funcs.append(fd)
        return True

    def parse_params(self):
        params = []
        lang = self.lang
        while not self.is_op(')') and not self.at_end():
            if self.is_id('void') and self.is_op(')', 1):
                self.adv()
                break
            ptype, name = None, None
            if lang in ('C', 'C++', 'C#', 'Java'):
                while self.tk()[0] == 'id' and self.tk()[1] in ('final', 'ref', 'out', 'in', 'params', 'const'):
                    self.adv()
                ptype = self.parse_type()
                if ptype is None or self.tk()[0] != 'id':
                    self.err('cannot understand this parameter')
                name = self.adv()[1]
                while self.is_op('['):
                    self.adv()
                    while not self.is_op(']'):
                        self.adv()
                    self.adv()
                    ptype['array'] = True
            elif lang in ('JavaScript', 'TypeScript', 'Kotlin', 'PHP', 'Swift'):
                if lang == 'PHP':
                    ptype = None
                    save = self.i
                    if self.tk()[0] == 'id' and not self.tk()[1].startswith('$'):
                        ptype = self.parse_type()
                    if self.is_op('&'):
                        self.adv()
                    if self.tk()[0] != 'id':
                        self.err('cannot understand this parameter')
                    name = self.adv()[1]
                    if ptype and ptype['name'] == 'array':
                        ptype['array'] = True
                else:
                    if lang == 'Kotlin' and self.tk()[0] == 'id' and self.tk()[1] in ('val', 'var', 'vararg'):
                        self.adv()
                    name = self.adv()[1]
                    if lang == 'Swift' and self.tk()[0] == 'id':
                        name = self.adv()[1]
                    self.accept('?')
                    if self.accept(':'):
                        if lang == 'Swift':
                            self.accept('inout')
                        ptype = self.parse_type()
                        if ptype is None:
                            self.err('cannot understand the parameter type')
            elif lang == 'Go':
                names = [self.adv()[1]]
                while self.accept(','):
                    names.append(self.adv()[1])
                ptype = self.parse_type()
                if ptype is None:
                    self.err('cannot understand the parameter type')
                for nm in names[:-1]:
                    params.append((nm, ptype['ir'], ptype['array']))
                name = names[-1]
            if self.accept('=') :
                self.expr()
            params.append((name.lstrip('$'), ptype['ir'] if ptype else None, bool(ptype and ptype['array'])))
            if not self.accept(','):
                break
        self.expect(')')
        return params

    def parse_stmts_until_close(self):
        """Parse statements after '{' up to and including the matching '}'."""
        out = []
        while not self.is_op('}'):
            if self.at_end():
                self.err("missing '}'")
            out.extend(self.parse_statement())
        out.extend(self.comments_before(self.tk()[2]))
        self.adv()
        return self.merge_fills(out)

    # ------------------------------------------------------------ statements
    def parse_block_or_stmt(self):
        if self.is_op('{'):
            self.adv()
            return self.parse_stmts_until_close()
        return self.parse_statement()

    def parse_statement(self):
        line = self.tk()[2]
        out = self.comments_before(line)
        for s in self.collapse_fill(self._statement()):
            if not hasattr(s, 'lineno'):
                AT(s, line)
            out.append(s)
        return out

    def collapse_fill(self, stmts):
        """Recognise the array-initialisation loops our generators emit (for _k ... a[_k] = v)."""
        out = []
        for s in stmts:
            if isinstance(s, ast.For) and isinstance(s.target, ast.Name) and s.target.id.startswith('_k') and len(s.body) == 1:
                b = s.body[0]
                size = None
                if isinstance(s.iter, ast.Call) and getattr(s.iter.func, 'id', '') == 'range':
                    a = s.iter.args
                    size = a[0] if len(a) == 1 else a[1]
                if isinstance(b, ast.Assign) and isinstance(b.targets[0], ast.Subscript) and isinstance(b.targets[0].value, ast.Name):
                    out.append(ArrayFill(name=b.targets[0].value.id, size=size, default=b.value))
                    continue
                if isinstance(b, ast.Expr) and isinstance(b.value, ast.Call) and getattr(b.value.func, 'id', '') == '_fill':
                    out.append(ArrayFill(name=b.value.args[0].id, size=size, default=b.value.args[1]))
                    continue
            out.append(s)
        return out

    def merge_fills(self, stmts):
        out = []
        for s in stmts:
            if isinstance(s, StmtList):
                out.extend(self.merge_fills(s.stmts))
                continue
            if isinstance(s, ArrayFill):
                prev = out[-1] if out else None
                if isinstance(prev, ast.Assign) and isinstance(prev.targets[0], ast.Name) and prev.targets[0].id == s.name:
                    if isinstance(prev.value, ast.List) and not prev.value.elts and s.size is not None:
                        prev.value = BIN(ast.Mult, ast.List(elts=[s.default]), s.size)
                    continue
                continue
            for field in ('body', 'orelse'):
                if hasattr(s, field) and isinstance(getattr(s, field), list):
                    setattr(s, field, self.merge_fills(getattr(s, field)))
            out.append(s)
        return out

    def _statement(self):
        t = self.tk()
        v = t[1] if t[0] == 'id' else None
        lang = self.lang
        if self.accept(';'):
            return []
        if self.is_op('{'):
            self.adv()
            return self.parse_stmts_until_close()
        if v == 'if':
            return self.p_if()
        if v == 'while':
            self.adv()
            c = self.paren_expr()
            return [ast.While(test=c, body=self.parse_block_or_stmt() or [ast.Pass()], orelse=[])]
        if v == 'do' and self.is_op('{', 1):
            self.adv()
            body = self.parse_block_or_stmt()
            self.expect('while')
            c = self.paren_expr()
            self.eos()
            return [ast.While(test=K(True), body=body + [ast.If(test=ast.UnaryOp(op=ast.Not(), operand=c), body=[ast.Break()], orelse=[])], orelse=[])]
        if v == 'repeat' and lang == 'Swift':
            self.adv()
            body = self.parse_block_or_stmt()
            self.expect('while')
            c = self.expr()
            return [ast.While(test=K(True), body=body + [ast.If(test=ast.UnaryOp(op=ast.Not(), operand=c), body=[ast.Break()], orelse=[])], orelse=[])]
        if v == 'for':
            return self.p_for()
        if v == 'foreach':
            return self.p_foreach()
        if v == 'switch' or (v == 'when' and lang == 'Kotlin'):
            return self.p_switch()
        if v == 'return':
            self.adv()
            val = None
            if not (self.is_op(';') or self.is_op('}') or (self.nlsens and self.tk()[3])):
                val = self.expr()
            self.eos()
            return [ast.Return(value=val)]
        if v == 'break':
            self.adv()
            self.eos()
            return [ast.Break()]
        if v == 'continue':
            self.adv()
            self.eos()
            return [ast.Continue()]
        if v in ('try', 'catch', 'throw', 'goto', 'delete', 'lambda'):
            self.err('{0} is not supported by flowchart shapes'.format(v))
        if lang == 'PHP' and v in ('echo', 'print') and not self.is_op('(', 1) or (lang == 'PHP' and v == 'echo'):
            self.adv()
            items = [self.expr()]
            while self.accept(','):
                items.append(self.expr())
            self.eos()
            return self.expr_to_stmts(OutExpr(items=items))
        if lang in ('JavaScript', 'TypeScript') and self.is_op('(') and self.is_id('function', 1):
            # (function () { ... })();   -> main body
            self.adv()
            self.adv()
            self.expect('(')
            self.expect(')')
            self.expect('{')
            body = self.parse_stmts_until_close()
            self.expect(')')
            if self.accept('('):
                self.expect(')')
            self.eos()
            return body
        d = self.try_declaration()
        if d is not None:
            return d
        e = self.expr()
        # In C++, the comma operator sequences expressions and evaluates each
        # from left to right.  Preserve this as a sequence of flowchart
        # statements when it appears at statement level, e.g.
        #   std::cout << x, x = x + 1;
        # Do not apply this to other languages, where commas usually delimit
        # arguments or declarations and are handled by their own grammar.
        if lang == 'C++' and self.accept(','):
            seq = [e]
            while True:
                seq.append(self.expr())
                if not self.accept(','):
                    break
            self.eos()
            out = []
            for item in seq:
                out.extend(self.expr_to_stmts(item))
            return out
        self.eos()
        return self.expr_to_stmts(e)

    def paren_expr(self):
        if self.is_op('('):
            self.adv()
            self.depth += 1
            e = self.expr()
            self.depth -= 1
            self.expect(')')
            return e
        return self.expr()

    def p_if(self):
        self.adv()
        c = self.paren_expr()
        body = self.parse_block_or_stmt()
        orelse = []
        if self.is_id('else') or (self.lang == 'PHP' and self.is_id('elseif')):
            if self.is_id('elseif'):
                self.toks[self.i] = ('id', 'if', self.tk()[2], self.tk()[3])
                orelse = self.p_if()
            else:
                self.adv()
                if self.is_id('if'):
                    orelse = self.p_if()
                else:
                    orelse = self.parse_block_or_stmt()
        return [ast.If(test=c, body=body or [ast.Pass()], orelse=orelse)]

    # ---- declarations
    def try_declaration(self):
        lang = self.lang
        t = self.tk()
        v = t[1] if t[0] == 'id' else None
        save = self.i
        line = t[2]
        if lang in ('JavaScript', 'TypeScript', 'Kotlin', 'Swift', 'Go') and v in ('let', 'const', 'var', 'val'):
            self.adv()
            out = []
            while True:
                if self.tk()[0] != 'id':
                    self.err('expected a variable name')
                names = [self.adv()[1]]
                while lang == 'Go' and self.accept(','):
                    names.append(self.adv()[1])
                ti = None
                if lang == 'Go':
                    if not (self.is_op('=') or self.is_op(';') or self.tk()[3]):
                        ti = self.parse_type()
                elif self.accept(':'):
                    ti = self.parse_type()
                    if ti is None:
                        self.err('cannot understand the type')
                init = None
                if self.accept('='):
                    init = self.initializer(ti)
                for nm in names:
                    out.extend(self.declare(nm, ti, init, None))
                if not (lang in ('JavaScript', 'TypeScript') and self.accept(',')):
                    break
            self.eos()
            return out
        if lang in ('C', 'C++', 'C#', 'Java'):
            ti = self.parse_type()
            if ti is None or self.tk()[0] != 'id' or self.tk()[1] in ('in', 'is', 'as', 'instanceof'):
                self.i = save
                return None
            nxt = self.tk(1)
            if not (nxt[0] == 'op' and nxt[1] in ('=', ';', ',', '[', '(', '{', ':')):
                self.i = save
                return None
            if not (ti['known'] or ti['name'] in ('Scanner', 'BufferedReader', 'Random') or ti['name'][:1].isupper() or ti['name'] in ('vector', 'string')):
                self.i = save
                return None
            out = []
            while True:
                name = self.adv()[1]
                size = None
                while self.is_op('['):
                    self.adv()
                    if not self.is_op(']'):
                        size = self.expr()
                    self.expect(']')
                    ti = dict(ti, array=True) if not (ti['name'] == 'char' and ti['ir'] == 'String') else ti
                    if ti['name'] == 'char' and ti['ir'] == 'String':
                        size = None
                init = None
                if self.accept('='):
                    init = self.initializer(ti)
                elif self.is_op('(') and lang == 'C++':
                    self.adv()
                    args = []
                    if not self.is_op(')'):
                        args.append(self.expr())
                        while self.accept(','):
                            args.append(self.expr())
                    self.expect(')')
                    if ti['array']:
                        init = ArrayNew(size=args[0], default=args[1] if len(args) > 1 else None)
                    elif args:
                        init = args[0]
                elif self.is_op('{') and lang == 'C++':
                    init = self.brace_list()
                out.extend(self.declare(name, ti, init, size))
                if not self.accept(','):
                    break
            self.eos()
            return out
        return None

    def brace_list(self):
        self.expect('{')
        items = []
        while not self.is_op('}'):
            items.append(self.brace_list() if self.is_op('{') else self.expr())
            if not self.accept(','):
                break
        self.expect('}')
        return ast.List(elts=items)

    def initializer(self, ti):
        if self.is_op('{'):
            return self.brace_list()
        return self.expr()

    def declare(self, name, ti, init, size):
        """Build assignments for a declaration and remember the declared type."""
        name = name.lstrip('$')
        ir = ti['ir'] if ti else None
        arr = bool(ti and ti['array'])
        if ti and ti.get('void'):
            self.err('a variable cannot be void')
        if ti and not ti['known'] and not ti['name'][:1].islower() and init is not None and isinstance(init, ast.AST) \
                and (getattr(init, 'skip', False) or init is SKIP):
            self.objects.add(name)
            return []
        if init is SKIP or (init is not None and getattr(init, 'skip', False)):
            self.objects.add(name)
            return []
        if arr or isinstance(init, (ArrayNew, ast.List)) and not (ti and ti['name'] == 'char'):
            if isinstance(init, ArrayNew):
                value = self.make_array(init, ir)
            elif isinstance(init, ast.List):
                value = init
                if size is not None and ir is not None:
                    ok, n = cval(size)
                    if ok and len(init.elts) < n:
                        value = BIN(ast.Add, init, BIN(ast.Mult, ast.List(elts=[default_node(ir)]), K(n - len(init.elts))))
                    elif ok and len(init.elts) == 1 and n > 1:
                        value = BIN(ast.Mult, init, K(n))
            elif init is None and size is not None:
                value = self.make_array(ArrayNew(size=size, default=None), ir)
            elif init is not None:
                value = init
            else:
                self.err('array {0} needs a size'.format(name))
            if isinstance(value, ast.List) and ir is None and value.elts:
                pass
            self.seed(name, ir, True)
            return [ast.Assign(targets=[NM(name)], value=value)]
        if init is None:
            val = default_node(ir)
        else:
            val = init
            if ir == 'Real':
                ok, c = cval(val)
                if ok and isinstance(c, int) and not isinstance(c, bool):
                    val = K(float(c))
        if ti and ti['name'] in ANY_T and ti['ir'] is None:
            pass
        self.seed(name, ir, False)
        return [ast.Assign(targets=[NM(name)], value=val)]

    def make_array(self, an, ir):
        while isinstance(an.size, ast.Call) and getattr(an.size.func, 'id', '') == 'int' and len(an.size.args) == 1:
            an.size = an.size.args[0]
        d = an.default if an.default is not None else default_node(ir)
        ok, c = cval(d)
        if ir == 'Real' and ok and isinstance(c, int) and not isinstance(c, bool):
            d = K(float(c))
        return BIN(ast.Mult, ast.List(elts=[d]), an.size)

    # ---- assignment-like expressions to statements
    def expr_to_stmts(self, e):
        if e is SKIP or getattr(e, 'skip', False):
            return []
        if isinstance(e, StmtList):
            return e.stmts
        if isinstance(e, AssignExpr):
            return self.assign_stmts(e)
        if isinstance(e, IncrExpr):
            return [ast.AugAssign(target=e.target, op=(ast.Add if e.delta > 0 else ast.Sub)(), value=K(1))]
        if isinstance(e, OutExpr):
            r = self.out_call(e)
            return [] if getattr(r, 'skip', False) else [ast.Expr(value=r)]
        if isinstance(e, InExpr):
            return [ast.Assign(targets=[t], value=self.typed_input(t)) for t in e.targets]
        if isinstance(e, ast.Call) or isinstance(e, ast.Attribute) or isinstance(e, ast.Name):
            return [ast.Expr(value=e)]
        if isinstance(e, ast.Constant if _AST_CONSTANT else ast.Str):
            return []
        return [ast.Expr(value=e)]

    def assign_stmts(self, e):
        if isinstance(e.target, ast.Name) and e.target.id == '_':
            return []
        if isinstance(e.target, ast.Tuple):
            vals = e.value.elts if isinstance(e.value, ast.Tuple) else [e.value]
            names = e.target.elts
            if len(names) == 2 and isinstance(names[1], ast.Name) and names[1].id in ('_', 'err', 'ok') and len(vals) == 1:
                return self.assign_stmts(AssignExpr(op=e.op, target=names[0], value=vals[0]))
            return [ast.Assign(targets=[e.target], value=e.value if isinstance(e.value, ast.Tuple) else ast.Tuple(elts=vals))]
        value = e.value
        if isinstance(value, AssignExpr):
            inner = self.assign_stmts(value)
            return inner + self.assign_stmts(AssignExpr(op=e.op, target=e.target, value=value.target))
        if isinstance(value, ArrayNew):
            ir = self.var_ir(e.target.id) if isinstance(e.target, ast.Name) else None
            value = self.make_array(value, ir)
        if e.op in ('=', ':='):
            if isinstance(e.target, ast.Name):
                ir = self.var_ir(e.target.id)
                if ir == 'Real':
                    ok, c = cval(value)
                    if ok and isinstance(c, int) and not isinstance(c, bool):
                        value = K(float(c))
            return [ast.Assign(targets=[e.target], value=value)]
        if e.op == '.=':
            return [ast.Assign(targets=[e.target], value=BIN(ast.BitAnd, e.target, value))]
        if e.op == '/=':
            b = BIN(ast.Div, e.target, value)
            if self.lang in TYPED_DIV:
                b._cdiv = True
            return [ast.Assign(targets=[e.target], value=b)]
        if e.op in AUG:
            return [ast.AugAssign(target=e.target, op=AUG[e.op](), value=value)]
        self.err('operator {0} is not supported'.format(e.op))

    # ---- loops
    def p_for(self):
        lang = self.lang
        self.adv()
        if lang == 'Go':
            return self.p_for_go()
        if lang == 'Swift':
            return self.p_for_swift()
        if lang == 'Kotlin':
            return self.p_for_kotlin()
        self.expect('(')
        self.depth += 1
        save = self.i
        # for-each forms: Java/C++ (T x : xs), JS (const x of xs), JS (x in xs), PHP handled by foreach
        fe = self.spec_foreach()
        if fe is not None:
            self.depth -= 1
            self.expect(')')
            body = self.parse_block_or_stmt()
            return self.lower_foreach(fe[0], fe[1], body)
        self.i = save
        init = []
        if not self.is_op(';'):
            d = self.try_declaration_noeos()
            if d is not None:
                init = d
            else:
                init = self.expr_to_stmts_list()
        self.expect(';')
        cond = None if self.is_op(';') else self.expr()
        self.expect(';')
        steps = []
        while not self.is_op(')'):
            steps.extend(self.expr_to_stmts(self.expr()))
            if not self.accept(','):
                break
        self.depth -= 1
        self.expect(')')
        self.fill_ctx = bool(init and isinstance(init[0], ast.Assign) and isinstance(init[0].targets[0], ast.Name) and init[0].targets[0].id.startswith('_k'))
        try:
            body = self.parse_block_or_stmt()
        finally:
            self.fill_ctx = False
        return self.lower_for(init, cond, steps, body)

    def try_declaration_noeos(self):
        save_eos = self.eos
        self.eos = lambda: None
        try:
            return self.try_declaration()
        finally:
            self.eos = save_eos

    def expr_to_stmts_list(self):
        out = []
        while True:
            out.extend(self.expr_to_stmts(self.expr()))
            if not self.accept(','):
                break
        return out

    def spec_foreach(self):
        save = self.i
        lang = self.lang
        if lang in ('JavaScript', 'TypeScript'):
            if self.tk()[1] in ('const', 'let', 'var') and self.tk(1)[0] == 'id' and self.tk(2)[1] in ('of', 'in'):
                self.adv()
                name = self.adv()[1]
                kind = self.adv()[1]
                return name, (self.expr(), kind)
            return None
        ti = self.parse_type()
        if ti is not None and self.tk()[0] == 'id' and self.is_op(':', 1):
            name = self.adv()[1]
            self.adv()
            self.seed(name, ti['ir'], False)
            return name, (self.expr(), 'of')
        self.i = save
        return None

    def lower_foreach(self, name, seqinfo, body):
        seq, kind = seqinfo
        self.tmp += 1
        idx = 'idx' if self.tmp == 1 else 'idx' + str(self.tmp)
        if kind == 'in':
            self.seed(name, 'Integer')
            return [ast.For(target=NM(name), iter=CALL('range', CALL('len', seq)), body=body or [ast.Pass()], orelse=[])]
        return [ast.For(target=NM(name), iter=seq, body=body or [ast.Pass()], orelse=[])]

    def p_foreach(self):
        self.adv()
        if self.lang == 'PHP':
            self.expect('(')
            seq = self.expr()
            self.expect('as')
            k = None
            v = self.adv()[1].lstrip('$')
            if self.accept('=>'):
                k, v = v, self.adv()[1].lstrip('$')
            self.expect(')')
            body = self.parse_block_or_stmt()
            if k:
                return [ast.For(target=ast.Tuple(elts=[NM(k), NM(v)]), iter=CALL('enumerate', seq), body=body or [ast.Pass()], orelse=[])]
            return [ast.For(target=NM(v), iter=seq, body=body or [ast.Pass()], orelse=[])]
        self.expect('(')
        ti = self.parse_type()
        name = self.adv()[1]
        self.expect('in')
        seq = self.expr()
        self.expect(')')
        if ti:
            self.seed(name, ti['ir'], False)
        body = self.parse_block_or_stmt()
        return [ast.For(target=NM(name), iter=seq, body=body or [ast.Pass()], orelse=[])]

    def p_for_go(self):
        if self.is_op('{'):
            return [ast.While(test=K(True), body=self.parse_block_or_stmt(), orelse=[])]
        # for cond { }   |   for init; cond; post { }   |   for i, v := range xs { }
        save = self.i
        if self.tk()[0] == 'id' and (self.is_op(',', 1) or self.is_op(':=', 1)):
            names = [self.adv()[1]]
            if self.accept(','):
                names.append(self.adv()[1])
            if self.accept(':='):
                if self.accept('range'):
                    seq = self.expr_no_brace()
                    body = self.parse_block_or_stmt()
                    return self.go_range(names, seq, body)
        self.i = save
        init = []
        if not self.is_op(';'):
            e = self.expr_no_brace()
            if self.is_op('{'):
                return [ast.While(test=e, body=self.parse_block_or_stmt() or [ast.Pass()], orelse=[])]
            init = self.expr_to_stmts(e)
        self.expect(';')
        cond = None if self.is_op(';') else self.expr_no_brace()
        self.expect(';')
        steps = [] if self.is_op('{') else self.expr_to_stmts(self.expr_no_brace())
        body = self.parse_block_or_stmt()
        return self.lower_for(init, cond, steps, body)

    def expr_no_brace(self):
        return self.expr()

    def go_range(self, names, seq, body):
        if len(names) == 1 or names[0] == '_':
            if len(names) == 2:
                return [ast.For(target=NM(names[1]), iter=seq, body=body or [ast.Pass()], orelse=[])]
            ok, c = cval(seq)
            if isinstance(seq, ast.Name) and self.var_ir(seq.id) == 'Integer' or ok:
                return [ast.For(target=NM(names[0]), iter=CALL('range', seq), body=body or [ast.Pass()], orelse=[])]
            return [ast.For(target=NM(names[0]), iter=CALL('range', CALL('len', seq)), body=body or [ast.Pass()], orelse=[])]
        return [ast.For(target=ast.Tuple(elts=[NM(names[0]), NM(names[1])]), iter=CALL('enumerate', seq), body=body or [ast.Pass()], orelse=[])]

    def range_expr(self):
        """Kotlin/Swift ranges: a..b, a until b, a downTo b step s, a..<b, a...b (else a plain expression)."""
        a = self.expr()
        if self.is_op('..') or self.is_op('...'):
            self.adv()
            return RangeExpr(start=a, stop=self.expr(), step=None, inclusive=True)
        if self.is_op('..<'):
            self.adv()
            return RangeExpr(start=a, stop=self.expr(), step=None, inclusive=False)
        if self.is_id('until'):
            self.adv()
            return RangeExpr(start=a, stop=self.binary(12), step=None, inclusive=False)
        if self.is_id('downTo'):
            self.adv()
            return RangeExpr(start=a, stop=self.binary(12), step='down', inclusive=True)
        return a

    def finish_range(self, r):
        if self.accept('step') if self.is_id('step') else False:
            r.step = self.binary(12) if r.step != 'down' else ('down', self.binary(12))
        return r

    def range_to_call(self, r):
        step = r.step
        down = step == 'down' or (isinstance(step, tuple))
        stepnode = None
        if isinstance(step, tuple):
            stepnode = step[1]
        elif step not in (None, 'down'):
            stepnode = step
        if down:
            stop = BIN(ast.Sub, r.stop, K(1)) if r.inclusive else r.stop
            neg = ast.UnaryOp(op=ast.USub(), operand=stepnode if stepnode is not None else K(1))
            return CALL('range', r.start, stop, neg)
        stop = BIN(ast.Add, r.stop, K(1)) if r.inclusive else r.stop
        return CALL('range', r.start, stop, *([stepnode] if stepnode is not None else []))

    def p_for_kotlin(self):
        self.expect('(')
        name = self.adv()[1]
        self.expect('in')
        e = self.range_expr()
        if isinstance(e, RangeExpr):
            e = self.range_to_call(self.finish_range(e))
        elif self.is_id('step'):
            pass
        self.expect(')')
        self.seed(name, 'Integer' if isinstance(e, ast.Call) and getattr(e.func, 'id', '') == 'range' else self.var_ir(name))
        body = self.parse_block_or_stmt()
        if isinstance(e, ast.Call) and getattr(e.func, 'id', '') == 'range':
            return [ast.For(target=NM(name), iter=e, body=body or [ast.Pass()], orelse=[])]
        return [ast.For(target=NM(name), iter=e, body=body or [ast.Pass()], orelse=[])]

    def p_for_swift(self):
        if self.is_id('_') or self.tk()[0] == 'id':
            name = self.adv()[1]
        self.expect('in')
        e = self.range_expr()
        if isinstance(e, RangeExpr):
            e = self.range_to_call(self.finish_range(e))
        elif isinstance(e, ast.Call) and getattr(e.func, 'id', '') == 'stride':
            e = self.stride(e)
        body = self.parse_block_or_stmt()
        if isinstance(e, ast.Call) and getattr(e.func, 'id', '') == 'range':
            self.seed(name, 'Integer')
        return [ast.For(target=NM(name), iter=e, body=body or [ast.Pass()], orelse=[])]

    def stride(self, c):
        kw = dict((k.arg, k.value) for k in c.keywords)
        start, stop, by = kw.get('from'), kw.get('to') or kw.get('through'), kw.get('by')
        through = 'through' in kw
        ok, bv = cval(by) if by is not None else (False, None)
        neg = isinstance(by, ast.UnaryOp) and isinstance(by.op, ast.USub)
        if neg:
            step = by
            stop = BIN(ast.Sub, stop, K(1)) if through else stop
        else:
            step = by
            stop = BIN(ast.Add, stop, K(1)) if through else stop
        return CALL('range', start, stop, step)

    def lower_for(self, init, cond, steps, body):
        pat = self.range_pattern(init, cond, steps, body)
        if pat is not None:
            return pat
        test = cond if cond is not None else K(True)
        last = max([getattr(x, 'lineno', 0) for s in body for x in ast.walk(s)] + [0])
        for s in steps:
            AT(s, last)
        newbody = self.inject_steps(body, steps) + steps
        return init + [ast.While(test=test, body=newbody or [ast.Pass()], orelse=[])]

    def inject_steps(self, body, steps):
        if not steps:
            return body
        out = []
        for s in body:
            if isinstance(s, ast.Continue):
                for st in copy.deepcopy(steps):
                    out.append(AT(st, getattr(s, 'lineno', 0)))
                out.append(s)
            elif isinstance(s, ast.If):
                s.body = self.inject_steps(s.body, steps)
                s.orelse = self.inject_steps(s.orelse, steps)
                out.append(s)
            else:
                out.append(s)
        return out

    def range_pattern(self, init, cond, steps, body):
        if len(init) != 1 or len(steps) != 1 or cond is None:
            return None
        a, st = init[0], steps[0]
        if not (isinstance(a, ast.Assign) and isinstance(a.targets[0], ast.Name)):
            return None
        v = a.targets[0].id
        if not (isinstance(cond, ast.Compare) and len(cond.ops) == 1 and isinstance(cond.left, ast.Name)
                and cond.left.id == v and type(cond.ops[0]) in (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
            return None
        stop = cond.comparators[0]
        if any(isinstance(x, ast.Name) and x.id == v for x in ast.walk(stop)):
            return None
        if not (isinstance(st, ast.AugAssign) and isinstance(st.target, ast.Name) and st.target.id == v and type(st.op) in (ast.Add, ast.Sub)):
            return None
        ok, k = cval(st.value)
        if not (ok and isinstance(k, int) and not isinstance(k, bool) and k > 0):
            return None
        for x in body:
            for y in ast.walk(x):
                if isinstance(y, ast.Assign) and any(isinstance(t, ast.Name) and t.id == v for t in y.targets):
                    return None
                if isinstance(y, ast.AugAssign) and isinstance(y.target, ast.Name) and y.target.id == v:
                    return None
                if isinstance(y, (ast.While, ast.For)):
                    pass
        up = isinstance(st.op, ast.Add)
        op = type(cond.ops[0])
        if up and op not in (ast.Lt, ast.LtE) or (not up and op not in (ast.Gt, ast.GtE)):
            return None
        if up:
            stopn = stop if op is ast.Lt else BIN(ast.Add, stop, K(1))
            args = [a.value, stopn] + ([K(k)] if k != 1 else [])
        else:
            stopn = stop if op is ast.Gt else BIN(ast.Sub, stop, K(1))
            args = [a.value, stopn, ast.UnaryOp(op=ast.USub(), operand=K(k))]
        if self.var_ir(v) == 'Real':
            return None
        self.seed(v, 'Integer')
        return [ast.For(target=NM(v), iter=CALL('range', *args), body=body or [ast.Pass()], orelse=[])]

    # ---- switch / when
    def p_switch(self):
        lang = self.lang
        self.adv()
        subject = None
        if not (lang in ('Go', 'Kotlin') and self.is_op('{')):
            subject = self.paren_expr()
        self.expect('{')
        cases = []
        while not self.is_op('}'):
            labels = None
            if lang == 'Kotlin':
                if self.accept('else'):
                    labels = None
                else:
                    labels = [self.expr()]
                    while self.accept(','):
                        labels.append(self.expr())
                self.expect('->')
                body = self.parse_block_or_stmt()
            else:
                if self.accept('default'):
                    labels = None
                else:
                    self.expect('case')
                    labels = [self.expr()]
                    while self.accept(','):
                        labels.append(self.expr())
                self.expect(':')
                body = []
                while not (self.is_id('case') or self.is_id('default') or self.is_op('}')):
                    body.extend(self.parse_statement())
            cases.append((labels, body))
        self.expect('}')
        return self.lower_switch(subject, cases)

    def lower_switch(self, subject, cases):
        pre = []
        if subject is not None and not isinstance(subject, (ast.Name,)) and not cval(subject)[0]:
            self.tmp += 1
            name = 'sw' if self.tmp == 1 else 'sw' + str(self.tmp)
            pre.append(ast.Assign(targets=[NM(name)], value=subject))
            subject = NM(name)
        implicit = self.lang in ('Go', 'Swift', 'Kotlin')
        merged, carry = [], []
        for labels, body in cases:
            if not body and labels is not None and not implicit:
                carry.extend(labels)
                continue
            if labels is not None:
                labels = carry + labels
                carry = []
            if body and isinstance(body[-1], ast.Break):
                body = body[:-1]
            elif body and isinstance(body[-1], (ast.Return, ast.Continue)):
                pass
            elif not implicit and (labels is not None or merged):
                if cases[-1][1] is not body:
                    self.err('switch case falls through to the next one; add break')
            merged.append((labels, body))
        chain, default = None, []
        for labels, body in reversed(merged):
            if labels is None:
                default = body
                continue
            tests = []
            for lb in labels:
                if subject is None:
                    tests.append(lb)
                elif isinstance(lb, RangeExpr):
                    r = self.finish_range(lb)
                    hi = r.stop if r.inclusive else BIN(ast.Sub, r.stop, K(1))
                    tests.append(ast.BoolOp(op=ast.And(), values=[ast.Compare(left=subject, ops=[ast.GtE()], comparators=[r.start]),
                                                                  ast.Compare(left=subject, ops=[ast.LtE()], comparators=[hi])]))
                else:
                    tests.append(ast.Compare(left=subject, ops=[ast.Eq()], comparators=[lb]))
            test = tests[0] if len(tests) == 1 else ast.BoolOp(op=ast.Or(), values=tests)
            orelse = [chain] if chain is not None else default
            chain = ast.If(test=test, body=body or [ast.Pass()], orelse=orelse)
            default = []
        if chain is None:
            return pre + default
        return pre + [chain]


def strip_helpers(text):
    """Remove generated runtime-helper blocks (they are scaffolding, not program logic)."""
    return re.sub(r'(?s)[^\n]*' + HELP_BEGIN + r'.*?' + HELP_END + r'[^\n]*', lambda m: '\n' * m.group(0).count('\n'), text)


def fix_locations(tree):
    def walk_fix(node, line):
        line = getattr(node, 'lineno', None) or line
        if isinstance(node, (ast.stmt, ast.expr)) or hasattr(node, 'lineno') or True:
            if not hasattr(node, 'lineno') or node.lineno is None:
                try:
                    node.lineno = line
                except AttributeError:
                    pass
            if not hasattr(node, 'col_offset'):
                node.col_offset = 0
        for child in ast.iter_child_nodes(node):
            walk_fix(child, line)
    walk_fix(tree, 1)


def parse_clike(lang, text):
    fe = CFront(lang, strip_helpers(text))
    tree = fe.parse_program()
    fix_locations(tree)
    for k in list(LAST_WARNINGS):
        LAST_WARNINGS.remove(k)
    LAST_WARNINGS.extend(fe.warnings)
    imp = PyImporter('')
    return imp.run(tree)


CLIKE = ('C', 'C++', 'C#', 'Java', 'JavaScript', 'TypeScript', 'Go', 'Kotlin', 'Swift', 'PHP')


def parse_code(language, text, name=None):
    """Turn source code in any supported language back into a flowchart document."""
    del LAST_WARNINGS[:]
    if language == 'Python':
        doc = parse_python(text)
    elif language == 'Pseudocode':
        doc = parse_pseudocode(text)
    elif language in CLIKE:
        doc = parse_clike(language, text)
    elif language == 'R':
        doc = parse_r(text)
    elif language == 'MATLAB':
        doc = parse_matlab(text)
    else:
        raise ParseError('Unknown language: ' + language)
    if name:
        doc['name'] = name
    return doc


# ----------------------------------------------------------------------------
# R and MATLAB front-ends
# ----------------------------------------------------------------------------
def tokenize_rm(src, lang):
    toks, comments = [], []
    i, n, line = 0, len(src), 1
    prev_nl = True
    r = lang == 'R'
    cc = '#' if r else '%'

    def push(kind, val):
        toks.append([kind, val, line, False])

    while i < n:
        c = src[i]
        if c == '\n':
            toks.append(['nl', '\n', line, False])
            line += 1
            i += 1
            continue
        if c in ' \t\r\f':
            i += 1
            continue
        if c == cc:
            if not r and src.startswith('%{', i) and src[i:src.find('\n', i) if src.find('\n', i) >= 0 else n].strip() == '%{':
                j = src.find('%}', i)
                j = n if j < 0 else j
                line += src.count('\n', i, j)
                i = j + 2
                continue
            j = src.find('\n', i)
            j = n if j < 0 else j
            comments.append((line, src[i + 1:j].strip()))
            i = j
            continue
        if not r and src.startswith('...', i):
            j = src.find('\n', i)
            j = n if j < 0 else j
            line += 1
            i = j + 1
            continue
        m = re.compile(r'0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?').match(src, i) if (c.isdigit() or (c == '.' and src[i + 1:i + 2].isdigit())) else None
        if m:
            body = m.group(0)
            i = m.end()
            if r and src[i:i + 1] == 'L':
                i += 1
            push('num', int(body, 16) if body[:2] in ('0x', '0X') else (float(body) if ('.' in body or 'e' in body.lower()) else int(body)))
            continue
        if c == '"' or (c == "'" and (r or not toks or toks[-1][0] in ('nl', 'op') and toks[-1][1] not in (')', ']', '}', "'") or (toks[-1][0] == 'op' and toks[-1][1] in (',', '(', '[', '=', ';')))):
            j, buf = i + 1, []
            while j < n and src[j] != c:
                if src[j] == '\\' and r and j + 1 < n:
                    buf.append(src[j:j + 2])
                    j += 2
                elif not r and c == "'" and src[j] == "'" :
                    break
                else:
                    buf.append(src[j])
                    j += 1
            if not r and c == "'":
                # MATLAB single-quoted: '' is an escaped quote
                j, buf = i + 1, []
                while j < n:
                    if src[j] == "'":
                        if src[j + 1:j + 2] == "'":
                            buf.append("'")
                            j += 2
                            continue
                        break
                    buf.append(src[j])
                    j += 1
                push('str', ''.join(buf))
            else:
                push('str', unescape(''.join(buf), 'R', c) if r else ''.join(buf).replace('\\n', '\n').replace('\\t', '\t'))
            line += 0
            i = j + 1
            continue
        m = re.compile(r'[A-Za-z_.][A-Za-z0-9_.]*' if r else r'[A-Za-z_][A-Za-z0-9_]*').match(src, i)
        if m:
            push('id', m.group(0))
            i = m.end()
            continue
        for op in (['<<-', '->>', '%/%', '%in%', '%%', '<-', '->', '==', '!=', '<=', '>=', '&&', '||', '::'] if r else
                   ['==', '~=', '<=', '>=', '&&', '||', '.*', './', '.^', '!=']):
            if src.startswith(op, i):
                push('op', op)
                i += len(op)
                break
        else:
            push('op', c)
            i += 1
    toks.append(['nl', '\n', line, False])
    toks.append(['eof', '', line, False])
    return toks, comments


class RMBase(CExprMixin):
    """Shared plumbing for the R and MATLAB parsers (statements end at newlines)."""
    nlsens = True

    def __init__(self, text, lang):
        self.lang = lang
        self.defines = {}
        self.toks, self.comments = tokenize_rm(strip_helpers(text), lang)
        self.i = 0
        self.ci = 0
        self.depth = 0
        self.warnings = []
        self.funcs = []
        self.main_body = []
        self.scopes = [{'name': 'Main', 'seed': {}}]
        self.known = [set()]
        self.fn_names = set()
        self.tmp = 0

    def tk(self, k=0):
        return self.toks[min(self.i + k, len(self.toks) - 1)]

    def adv(self):
        t = self.toks[self.i]
        if self.i < len(self.toks) - 1:
            self.i += 1
        return t

    def is_op(self, v, k=0):
        t = self.tk(k)
        return t[0] == 'op' and t[1] == v

    def is_id(self, v, k=0):
        t = self.tk(k)
        return t[0] == 'id' and t[1] == v

    def accept(self, v):
        t = self.tk()
        if t[0] in ('op', 'id') and t[1] == v:
            self.adv()
            return True
        return False

    def expect(self, v):
        if not self.accept(v):
            self.err("expected '{0}' but found '{1}'".format(v, self.tk()[1].strip() or 'end of line'))

    def err(self, msg):
        raise ParseError('Line {0}: {1}'.format(self.tk()[2], msg))

    def warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)

    def at_end(self):
        return self.tk()[0] == 'eof'

    def skip_nl(self):
        while self.tk()[0] == 'nl' or self.is_op(';') or (self.lang == 'MATLAB' and self.is_op(',') and False):
            self.adv()

    def comments_before(self, line):
        out = []
        while self.ci < len(self.comments) and self.comments[self.ci][0] < line:
            out.append(AT(ast.Expr(value=K(self.comments[self.ci][1])), self.comments[self.ci][0]))
            self.ci += 1
        return out

    @property
    def scope(self):
        return self.scopes[-1]

    def end_stmt(self):
        t = self.tk()
        if t[0] == 'nl' or t[0] == 'eof' or (t[0] == 'op' and t[1] in (';', ',')) or (t[0] == 'op' and t[1] == '}') or (
                self.lang == 'MATLAB' and t[0] == 'id' and t[1] in ('end', 'else', 'elseif', 'case', 'otherwise', 'endif', 'endwhile', 'endfor', 'endfunction')):
            return
        self.err("unexpected '{0}'".format(t[1]))

    def idx_minus_one(self, idx):
        if isinstance(idx, ast.BinOp) and isinstance(idx.op, ast.Add) and cval(idx.right) == (True, 1):
            return idx.left
        ok, v = cval(idx)
        if ok and isinstance(v, int) and not isinstance(v, bool):
            return K(v - 1)
        return BIN(ast.Sub, idx, K(1))

    def finish(self, funcs, main):
        main = self.merge_fills(main) if hasattr(self, 'merge_fills') else main
        mod = ast.Module(body=funcs + main)
        mod._seed = self.scopes[0]['seed']
        fix_locations(mod)
        return mod


class RFront(RMBase):
    def __init__(self, text):
        RMBase.__init__(self, text, 'R')

    def parse_program(self):
        body = []
        while not self.at_end():
            self.skip_nl()
            if self.at_end():
                break
            body.extend(self.parse_statement())
        body.extend(self.comments_before(10 ** 9))
        return self.finish(self.funcs, body)

    def skip_blank(self):
        while self.tk()[0] == 'nl' or self.is_op(';'):
            self.adv()

    def parse_block(self):
        """After '{'."""
        out = []
        while True:
            self.skip_blank()
            if self.is_op('}'):
                out.extend(self.comments_before(self.tk()[2]))
                self.adv()
                return out
            if self.at_end():
                self.err("missing '}'")
            out.extend(self.parse_statement())

    def parse_body(self):
        while self.tk()[0] == 'nl':
            self.adv()
        if self.is_op('{'):
            self.adv()
            return self.parse_block()
        return self.parse_statement()

    def parse_statement(self):
        line = self.tk()[2]
        out = self.comments_before(line)
        for s in self._stmt():
            if not hasattr(s, 'lineno'):
                AT(s, line)
            out.append(s)
        return out

    def peek_else(self):
        j = 0
        while self.tk(j)[0] == 'nl':
            j += 1
        if self.is_id('else', j):
            self.i += j
            return True
        return False

    def _stmt(self):
        t = self.tk()
        v = t[1] if t[0] == 'id' else None
        if v == 'if':
            self.adv()
            self.expect('(')
            self.depth += 1
            c = self.expr()
            self.depth -= 1
            self.expect(')')
            body = self.parse_body()
            orelse = []
            if self.peek_else():
                self.adv()
                orelse = self.parse_body()
            return [ast.If(test=c, body=body or [ast.Pass()], orelse=orelse)]
        if v == 'while':
            self.adv()
            self.expect('(')
            self.depth += 1
            c = self.expr()
            self.depth -= 1
            self.expect(')')
            return [ast.While(test=c, body=self.parse_body() or [ast.Pass()], orelse=[])]
        if v == 'repeat':
            self.adv()
            return [ast.While(test=K(True), body=self.parse_body() or [ast.Pass()], orelse=[])]
        if v == 'for':
            self.adv()
            self.expect('(')
            self.depth += 1
            var = self.adv()[1]
            self.expect('in')
            seq = self.expr()
            self.depth -= 1
            self.expect(')')
            body = self.parse_body()
            return [ast.For(target=NM(var), iter=self.r_iter(seq), body=body or [ast.Pass()], orelse=[])]
        if v == 'break':
            self.adv()
            return [ast.Break()]
        if v == 'next':
            self.adv()
            return [ast.Continue()]
        if v in ('library', 'require', 'suppressWarnings', 'set.seed', 'options', 'rm', 'invisible', 'flush', 'setwd', 'source') and self.is_op('(', 1):
            self.skip_call()
            return []
        if self.is_op('{'):
            self.adv()
            return self.parse_block()
        e = self.expr_stmt()
        self.end_stmt()
        return e

    def skip_call(self):
        self.adv()
        depth = 0
        while not self.at_end():
            if self.is_op('('):
                depth += 1
            elif self.is_op(')'):
                depth -= 1
                if depth == 0:
                    self.adv()
                    return
            self.adv()

    def r_iter(self, seq):
        if isinstance(seq, RangeExpr):
            if seq.step == 'down':
                return CALL('range', seq.start, BIN(ast.Sub, seq.stop, K(1)), K(-1))
            return CALL('range', seq.start, BIN(ast.Add, seq.stop, K(1)))
        if isinstance(seq, ast.Call) and getattr(seq.func, 'id', '') == '_seq_len':
            return CALL('range', K(1), BIN(ast.Add, seq.args[0], K(1)))
        return seq

    def expr_stmt(self):
        left = self.expr()
        t = self.tk()
        if t[0] == 'op' and t[1] in ('<-', '<<-', '=') and not self.depth:
            self.adv()
            while self.tk()[0] == 'nl':
                self.adv()
            if self.is_id('function'):
                return self.define_function(left)
            value = self.expr_stmt_value()
            return self.make_assign(left, value)
        if t[0] == 'op' and t[1] in ('->', '->>'):
            self.adv()
            target = self.expr()
            return self.make_assign(target, left)
        return self.to_stmts(left)

    def expr_stmt_value(self):
        v = self.expr()
        t = self.tk()
        if t[0] == 'op' and t[1] in ('<-', '=') and isinstance(v, (ast.Name, ast.Subscript)):
            self.adv()
            inner = self.expr_stmt_value()
            return ('chain', v, inner)
        return v

    def make_assign(self, target, value):
        if isinstance(value, tuple):
            _, t2, inner = value
            return self.make_assign(t2, inner) + self.make_assign(target, t2)
        if isinstance(target, ast.Name) and target.id.startswith('.'):
            return []
        if getattr(value, 'skip', False):
            return []
        if isinstance(value, ArrayNew):
            return [ast.Assign(targets=[target], value=BIN(ast.Mult, ast.List(elts=[value.default if value.default is not None else K(0)]), value.size))]
        return [ast.Assign(targets=[target], value=value)]

    def to_stmts(self, e):
        if getattr(e, 'skip', False):
            return []
        if isinstance(e, StmtList):
            return e.stmts
        if isinstance(e, ast.Call):
            return [ast.Expr(value=e)]
        if isinstance(e, (ast.Name,)):
            return [ast.Expr(value=e)]
        return [ast.Expr(value=e)]

    def define_function(self, nameexpr):
        self.adv()
        self.expect('(')
        params = []
        while not self.is_op(')'):
            params.append(self.adv()[1])
            if self.accept('='):
                self.err('default parameter values are not supported')
            if not self.accept(','):
                break
        self.expect(')')
        name = nameexpr.id
        self.scopes.append({'name': name, 'seed': {}})
        body = self.parse_body()
        self.scopes.pop()
        if body and isinstance(body[-1], ast.Expr) and not (isinstance(body[-1].value, ast.Call) and getattr(body[-1].value.func, 'id', '') in ('print',) or getattr(body[-1].value, 'skip', False)) \
                and not (isinstance(body[-1].value, ast.Call) and getattr(body[-1].value.func, 'id', '') in self.fn_names and False):
            if not cval(body[-1].value)[0] or True:
                last = body[-1]
                if not (isinstance(last.value, ast.Call) and getattr(last.value.func, 'id', '') == 'print'):
                    body[-1] = AT(ast.Return(value=last.value), getattr(last, 'lineno', 0))
        args = ast.arguments(args=[ast.arg(arg=p, annotation=None) for p in params], vararg=None, kwarg=None,
                             defaults=[], kwonlyargs=[], kw_defaults=[])
        fd = AT(ast.FunctionDef(name=name, args=args, body=body or [ast.Pass()], decorator_list=[], returns=None), self.tk()[2])
        self.funcs.append(fd)
        return []

    # ---- expressions
    RPREC = {'||': 1, '|': 1, '&&': 2, '&': 2, '==': 4, '!=': 4, '<': 4, '>': 4, '<=': 4, '>=': 4,
             '+': 5, '-': 5, '*': 6, '/': 6, '%%': 7, '%/%': 7, '%in%': 7, ':': 8, '^': 10}

    def expr(self):
        return self.rbinary(1)

    def rbinary(self, minprec):
        left = self.runary()
        while True:
            t = self.tk()
            if t[0] != 'op':
                break
            op = t[1]
            prec = self.RPREC.get(op)
            if prec is None or prec < minprec:
                break
            self.adv()
            while self.tk()[0] == 'nl':
                self.adv()
            right = self.rbinary(prec if op == '^' else prec + 1)
            left = self.r_bin(op, left, right)
        return left

    def r_bin(self, op, l, r):
        if op in ('&&', '&'):
            return ast.BoolOp(op=ast.And(), values=[l, r])
        if op in ('||', '|'):
            return ast.BoolOp(op=ast.Or(), values=[l, r])
        if op in CMP_OPS:
            return ast.Compare(left=l, ops=[CMP_OPS[op]()], comparators=[r])
        if op == ':':
            return RangeExpr(start=l, stop=r, step=None, inclusive=True)
        m = {'+': ast.Add, '-': ast.Sub, '*': ast.Mult, '/': ast.Div, '%%': ast.Mod, '%/%': ast.FloorDiv, '^': ast.Pow}
        if op in m:
            return BIN(m[op], l, r)
        self.err('operator {0} is not supported'.format(op))

    def runary(self):
        t = self.tk()
        if t[0] == 'op':
            if t[1] == '!':
                self.adv()
                return ast.UnaryOp(op=ast.Not(), operand=self.rbinary(4))
            if t[1] == '-':
                self.adv()
                o = self.rbinary(9)
                ok, v = cval(o)
                return K(-v) if ok and isinstance(v, (int, float)) and not isinstance(v, bool) else ast.UnaryOp(op=ast.USub(), operand=o)
            if t[1] == '+':
                self.adv()
                return self.rbinary(9)
        return self.rpostfix(self.rprimary())

    def rprimary(self):
        t = self.adv()
        k, v = t[0], t[1]
        if k in ('num', 'str'):
            return K(v)
        if k == 'op' and v == '(':
            self.depth += 1
            e = self.expr()
            self.depth -= 1
            self.expect(')')
            return e
        if k == 'op' and v == '{':
            self.err('blocks are not supported inside expressions')
        if k == 'id':
            if v in ('TRUE', 'T'):
                return K(True)
            if v in ('FALSE', 'F'):
                return K(False)
            if v in ('NULL', 'NA', 'NaN'):
                return SkipExpr(id='_obj')
            if v == 'Inf':
                self.err('Inf is not supported')
            if v == 'pi':
                return MEMBER(NM('math'), 'pi')
            if v == 'function':
                self.err('anonymous functions are not supported')
            if v == 'if':
                self.expect('(')
                c = self.expr()
                self.expect(')')
                a = self.expr()
                self.expect('else')
                b = self.expr()
                return ast.IfExp(test=c, body=a, orelse=b)
            return NM(v)
        self.i -= 1
        self.err("unexpected '{0}'".format(v.strip() or 'end of line'))

    def rpostfix(self, node):
        while True:
            t = self.tk()
            if t[0] != 'op':
                break
            if t[1] == '(':
                self.adv()
                self.depth += 1
                args = []
                while not self.is_op(')'):
                    while self.tk()[0] == 'nl':
                        self.adv()
                    kw = None
                    if self.tk()[0] == 'id' and self.is_op('=', 1) and not self.is_op('==', 1):
                        kw = self.adv()[1]
                        self.adv()
                    args.append((kw, self.expr()))
                    while self.tk()[0] == 'nl':
                        self.adv()
                    if not self.accept(','):
                        break
                self.depth -= 1
                self.expect(')')
                node = self.r_call(node, args)
                continue
            if t[1] == '[':
                self.adv()
                dbl = self.accept('[')
                self.depth += 1
                idx = self.expr()
                self.depth -= 1
                self.expect(']')
                if dbl:
                    self.expect(']')
                node = SUBS(node, self.idx_minus_one(idx))
                continue
            if t[1] == '$':
                self.err('lists/data frames ($) are not supported')
            if t[1] == '::':
                self.adv()
                node = NM(self.adv()[1])
                continue
            break
        return node

    def r_call(self, callee, args):
        name = callee.id if isinstance(callee, ast.Name) else None
        pos = [a for k, a in args if k is None]
        kw = dict((k, a) for k, a in args if k)
        if name is None:
            self.err('this call is not supported')
        if name == 'cat':
            items = pos
            sep = self.str_lit(kw['sep']) if 'sep' in kw else ' '
            newline = False
            if items:
                ok, c = cval(items[-1])
                if ok and isinstance(c, str) and c.endswith('\n'):
                    newline = True
                    items = items[:-1] + ([K(c[:-1])] if c[:-1] else [])
            return self.print_call(items, newline, sep)
        if name == 'print':
            return self.print_call(pos[:1], True)
        if name in ('paste0', 'paste'):
            sep = '' if name == 'paste0' else (self.str_lit(kw['sep']) if 'sep' in kw else ' ')
            out = None
            for p in pos:
                if out is None:
                    out = p
                else:
                    if sep:
                        out = BIN(ast.BitAnd, out, K(sep))
                    out = BIN(ast.BitAnd, out, p)
            return out if out is not None else K('')
        if name == 'sprintf':
            f = self.str_lit(pos[0]) if pos else None
            if f is None:
                self.err('sprintf needs a literal format')
            return self.fmt_expr(f, pos[1:])[0]
        if name in ('readline', 'readLines', 'scan', 'readLines'):
            return CALL('input')
        if name in ('as.numeric', 'as.double'):
            return CALL('float', pos[0])
        if name in ('as.integer', 'as.numeric_int'):
            return CALL('int', pos[0])
        if name == 'as.character':
            return CALL('str', pos[0])
        if name in ('as.logical',):
            return pos[0]
        if name in ('nchar', 'length'):
            return CALL('len', pos[0])
        if name in ('toupper', 'tolower', 'trimws'):
            return CALL(MEMBER(pos[0], {'toupper': 'upper', 'tolower': 'lower', 'trimws': 'strip'}[name]))
        if name == 'grepl' and len(pos) >= 2:
            return CALL(MEMBER(pos[1], 'contains'), pos[0])
        if name == 'substr' and len(pos) == 3:
            return SUBS(pos[0], self.idx_minus_one(pos[1]))
        if name in ('rep',) and len(pos) == 2 or (name == 'rep' and 'times' in kw):
            return ArrayNew(size=pos[1] if len(pos) > 1 else kw['times'], default=pos[0])
        if name in ('numeric', 'double') and pos:
            return ArrayNew(size=pos[0], default=K(0.0))
        if name == 'integer' and pos:
            return ArrayNew(size=pos[0], default=K(0))
        if name == 'character' and pos:
            return ArrayNew(size=pos[0], default=K(''))
        if name == 'logical' and pos:
            return ArrayNew(size=pos[0], default=K(False))
        if name == 'c':
            return ast.List(elts=pos)
        if name == 'seq_len':
            return CALL('_seq_len', pos[0])
        if name == 'seq_along':
            return CALL('_seq_len', CALL('len', pos[0]))
        if name == 'seq':
            step = kw.get('by')
            if len(pos) == 2 and step is None:
                return RangeExpr(start=pos[0], stop=pos[1], step=None, inclusive=True)
            if len(pos) == 2 and step is not None:
                neg = isinstance(step, ast.UnaryOp) or (cval(step)[0] and cval(step)[1] < 0)
                stp = step.operand if isinstance(step, ast.UnaryOp) else (K(-cval(step)[1]) if neg else step)
                stop = BIN(ast.Sub, pos[1], K(1)) if neg else BIN(ast.Add, pos[1], K(1))
                return CALL('range', pos[0], stop, ast.UnaryOp(op=ast.USub(), operand=stp) if neg else stp)
            self.err('seq() is supported as seq(a, b) or seq(a, b, by = s)')
        if name in ('round',) and len(pos) == 2:
            ok, p = cval(pos[1])
            if ok and isinstance(p, int):
                return self.round_to(pos[0], p)
        if name in ('format', 'formatC') and pos:
            return pos[0]
        if name in ('quit', 'q', 'stop'):
            return StmtList(stmts=[ast.Return(value=None)])
        if name == 'return':
            return StmtList(stmts=[ast.Return(value=pos[0] if pos else None)])
        if name in ('invisible', 'message', 'flush', 'file', 'close', 'suppressWarnings', 'Sys.sleep'):
            return SkipExpr(id='_obj')
        if name in ('abs', 'sqrt', 'sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'log', 'log10', 'floor', 'ceiling', 'trunc'):
            if name == 'abs':
                return CALL('abs', pos[0])
            if name == 'trunc':
                return CALL('int', pos[0])
            return CALL(MEMBER(NM('math'), {'ceiling': 'ceil'}.get(name, name)), pos[0])
        if name == 'round' and len(pos) == 1:
            return CALL('round', pos[0])
        if name in ('max', 'min') and len(pos) == 2:
            return CALL(name, *pos)
        if name == 'sign' and pos:
            self.err('sign() is not supported')
        if name == 'floor' and pos:
            return CALL(MEMBER(NM('math'), 'floor'), pos[0])
        if name == 'runif' and False:
            pass
        if name == 'sample' or name == 'runif':
            self.err('random numbers: use floor(runif(1) * n)')
        return CALL(name, *pos)

    def prescan(self):
        pass


class MatlabFront(RMBase):
    def __init__(self, text):
        RMBase.__init__(self, text, 'MATLAB')
        self.known = [set()]
        j = 0
        toks = self.toks
        for k, t in enumerate(toks):
            if t[0] == 'id' and t[1] == 'function':
                m = k + 1
                while m < len(toks) and toks[m][0] != 'nl':
                    if toks[m][0] == 'id' and m + 1 < len(toks) and toks[m + 1][0] == 'op' and toks[m + 1][1] == '(':
                        self.fn_names.add(toks[m][1])
                        break
                    if toks[m][0] == 'id' and (m + 1 >= len(toks) or toks[m + 1][0] == 'nl'):
                        self.fn_names.add(toks[m][1])
                        break
                    m += 1

    END_WORDS = ('end', 'endif', 'endwhile', 'endfor', 'endfunction', 'endswitch')

    def parse_program(self):
        body = []
        while not self.at_end():
            self.skip_blank()
            if self.at_end():
                break
            if self.is_id('function'):
                self.parse_function()
                continue
            body.extend(self.parse_statement())
        body.extend(self.comments_before(10 ** 9))
        return self.finish(self.funcs, body)

    def skip_blank(self):
        while self.tk()[0] == 'nl' or self.is_op(';') or self.is_op(','):
            self.adv()

    def at_block_end(self):
        t = self.tk()
        return t[0] == 'id' and t[1] in self.END_WORDS + ('else', 'elseif', 'case', 'otherwise')

    def parse_block(self):
        out = []
        while True:
            self.skip_blank()
            if self.at_end() or self.at_block_end():
                return out
            if self.is_id('function'):
                self.parse_function()
                continue
            out.extend(self.parse_statement())

    def end_kw(self):
        if self.tk()[0] == 'id' and self.tk()[1] in self.END_WORDS:
            self.adv()
        else:
            self.err("missing 'end'")

    def parse_statement(self):
        line = self.tk()[2]
        out = self.comments_before(line)
        for s in self._stmt():
            if not hasattr(s, 'lineno'):
                AT(s, line)
            out.append(s)
        return out

    def parse_function(self):
        self.adv()
        outs = []
        if self.is_op('['):
            self.adv()
            while not self.is_op(']'):
                outs.append(self.adv()[1])
                self.accept(',')
            self.adv()
            self.expect('=')
        elif self.tk(1)[0] == 'op' and self.tk(1)[1] == '=':
            outs.append(self.adv()[1])
            self.adv()
        name = self.adv()[1]
        params = []
        if self.accept('('):
            while not self.is_op(')'):
                params.append(self.adv()[1])
                if not self.accept(','):
                    break
            self.expect(')')
        if len(outs) > 1:
            self.err('functions with several outputs are not supported')
        self.known.append(set(params) | set(outs))
        self.scopes.append({'name': name, 'seed': {}})
        body = self.parse_block()
        self.known.pop()
        self.scopes.pop()
        if self.tk()[0] == 'id' and self.tk()[1] in self.END_WORDS:
            self.adv()
        if outs:
            body = self.fix_returns(body, outs[0])
        args = ast.arguments(args=[ast.arg(arg=p, annotation=None) for p in params], vararg=None, kwarg=None,
                             defaults=[], kwonlyargs=[], kw_defaults=[])
        fd = AT(ast.FunctionDef(name=name, args=args, body=body or [ast.Pass()], decorator_list=[], returns=None), self.tk()[2])
        self.funcs.append(fd)

    def fix_returns(self, body, res):
        def walk_block(stmts, top):
            out = []
            i = 0
            while i < len(stmts):
                s = stmts[i]
                nxt = stmts[i + 1] if i + 1 < len(stmts) else None
                if isinstance(s, ast.Assign) and isinstance(s.targets[0], ast.Name) and s.targets[0].id == res \
                        and isinstance(nxt, ast.Return) and nxt.value is None:
                    out.append(AT(ast.Return(value=s.value), getattr(s, 'lineno', 0)))
                    i += 2
                    continue
                if isinstance(s, ast.Return) and s.value is None:
                    out.append(AT(ast.Return(value=NM(res)), getattr(s, 'lineno', 0)))
                    i += 1
                    continue
                for f in ('body', 'orelse'):
                    if hasattr(s, f) and isinstance(getattr(s, f), list):
                        setattr(s, f, walk_block(getattr(s, f), False))
                out.append(s)
                i += 1
            return out
        body = walk_block(body, True)
        if body and isinstance(body[-1], ast.Assign) and isinstance(body[-1].targets[0], ast.Name) and body[-1].targets[0].id == res:
            last = body.pop()
            body.append(AT(ast.Return(value=last.value), getattr(last, 'lineno', 0)))
        elif not (body and isinstance(body[-1], (ast.Return, ast.If))):
            body.append(ast.Return(value=NM(res)))
        return body

    def _stmt(self):
        t = self.tk()
        v = t[1] if t[0] == 'id' else None
        if v == 'if':
            return [self.p_if()]
        if v == 'while':
            self.adv()
            c = self.expr()
            body = self.parse_block()
            self.end_kw()
            return [ast.While(test=c, body=body or [ast.Pass()], orelse=[])]
        if v == 'for':
            return self.p_for()
        if v == 'switch':
            return self.p_switch()
        if v == 'break':
            self.adv()
            return [ast.Break()]
        if v == 'continue':
            self.adv()
            return [ast.Continue()]
        if v == 'return':
            self.adv()
            return [ast.Return(value=None)]
        if v in ('clc', 'clear', 'close', 'format', 'hold', 'warning', 'rng', 'clearvars', 'more') :
            while self.tk()[0] not in ('nl', 'eof') and not self.is_op(';'):
                self.adv()
            return []
        return self.simple_stmt()

    def p_if(self):
        self.adv()
        c = self.expr()
        body = self.parse_block()
        orelse = []
        if self.is_id('elseif'):
            self.toks[self.i][1] = 'if'
            orelse = [self.p_if_nested()]
            return ast.If(test=c, body=body or [ast.Pass()], orelse=orelse)
        if self.is_id('else'):
            self.adv()
            orelse = self.parse_block()
        self.end_kw()
        return ast.If(test=c, body=body or [ast.Pass()], orelse=orelse)

    def p_if_nested(self):
        return self.p_if()

    def p_for(self):
        self.adv()
        paren = self.accept('(')
        var = self.adv()[1]
        self.expect('=')
        a = self.expr()
        if paren:
            self.expect(')')
        if isinstance(a, RangeExpr):
            def flat(r):
                return flat(r.start) + [r.stop] if isinstance(r.start, RangeExpr) else [r.start, r.stop]
            parts = flat(a)
            if len(parts) == 2:
                it = CALL('range', parts[0], BIN(ast.Add, parts[1], K(1)))
            else:
                step = parts[1]
                neg = isinstance(step, ast.UnaryOp) or (cval(step)[0] and cval(step)[1] < 0)
                if neg:
                    stp = step.operand if isinstance(step, ast.UnaryOp) else K(-cval(step)[1])
                    it = CALL('range', parts[0], BIN(ast.Sub, parts[2], K(1)), ast.UnaryOp(op=ast.USub(), operand=stp))
                else:
                    it = CALL('range', parts[0], BIN(ast.Add, parts[2], K(1)), step)
        else:
            it = a
        self.known[-1].add(var)
        body = self.parse_block()
        self.end_kw()
        return [ast.For(target=NM(var), iter=it, body=body or [ast.Pass()], orelse=[])]

    def p_switch(self):
        self.adv()
        subject = self.expr()
        self.skip_blank()
        cases = []
        while self.is_id('case') or self.is_id('otherwise'):
            if self.accept('otherwise'):
                labels = None
            else:
                self.adv()
                if self.is_op('{'):
                    self.adv()
                    labels = []
                    while not self.is_op('}'):
                        labels.append(self.expr())
                        self.accept(',')
                    self.adv()
                else:
                    labels = [self.expr()]
            cases.append((labels, self.parse_block()))
        self.end_kw()
        return CFront.lower_switch(self, subject, cases)

    def simple_stmt(self):
        # assignment: name = expr   |   name(idx) = expr
        save = self.i
        if self.tk()[0] == 'id':
            target = self.mat_primary_target()
            if self.is_op('=') and not self.is_op('==') and target is not None:
                self.adv()
                value = self.expr()
                self.end_stmt()
                name = target.id if isinstance(target, ast.Name) else target.value.id
                self.known[-1].add(name)
                if getattr(value, 'skip', False):
                    return []
                if isinstance(value, ArrayNew):
                    value = BIN(ast.Mult, ast.List(elts=[value.default if value.default is not None else K(0)]), value.size)
                return [ast.Assign(targets=[target], value=value)]
            self.i = save
        e = self.expr()
        self.end_stmt()
        if getattr(e, 'skip', False):
            return []
        if isinstance(e, StmtList):
            return e.stmts
        if isinstance(e, ast.Constant if _AST_CONSTANT else ast.Num):
            return []
        return [ast.Expr(value=e)]

    def mat_primary_target(self):
        name = self.adv()[1]
        node = NM(name)
        if self.is_op('(') and name in self.known[-1]:
            self.adv()
            self.depth += 1
            idx = self.expr()
            self.depth -= 1
            if not self.accept(')'):
                return None
            return SUBS(node, self.idx_minus_one(idx))
        if self.is_op('{'):
            self.adv()
            idx = self.expr()
            self.expect('}')
            return SUBS(node, self.idx_minus_one(idx))
        return node

    # ---- expressions
    MPREC = {'||': 1, '|': 1, '&&': 2, '&': 2, '==': 4, '~=': 4, '!=': 4, '<': 4, '>': 4, '<=': 4, '>=': 4,
             ':': 5, '+': 6, '-': 6, '*': 7, '/': 7, '.*': 7, './': 7, '^': 9, '.^': 9}

    def expr(self):
        return self.mbinary(1)

    def mbinary(self, minprec):
        left = self.munary()
        while True:
            t = self.tk()
            if t[0] != 'op':
                break
            op = t[1]
            prec = self.MPREC.get(op)
            if prec is None or prec < minprec:
                break
            if self.depth and False:
                break
            self.adv()
            if op == ':':
                right = self.mbinary(prec + 1)
                left = RangeExpr(start=left, stop=right, step=None, inclusive=True)
                continue
            right = self.mbinary(prec if op in ('^', '.^') else prec + 1)
            left = self.m_bin(op, left, right)
        return left

    def m_bin(self, op, l, r):
        if op in ('&&', '&'):
            return ast.BoolOp(op=ast.And(), values=[l, r])
        if op in ('||', '|'):
            return ast.BoolOp(op=ast.Or(), values=[l, r])
        if op in ('==', '~=', '!=', '<', '>', '<=', '>='):
            return ast.Compare(left=l, ops=[CMP_OPS['!=' if op == '~=' else op]()], comparators=[r])
        m = {'+': ast.Add, '-': ast.Sub, '*': ast.Mult, '.*': ast.Mult, '/': ast.Div, './': ast.Div, '^': ast.Pow, '.^': ast.Pow}
        return BIN(m[op], l, r)

    def munary(self):
        t = self.tk()
        if t[0] == 'op':
            if t[1] in ('~', '!'):
                self.adv()
                o = self.mbinary(4)
                if isinstance(o, ast.Call) and getattr(o.func, 'id', '') == 'isempty' and isinstance(o.args[0], ast.Call) \
                        and getattr(o.args[0].func, 'id', '') == '_indexof':
                    a = o.args[0].args
                    return CALL(MEMBER(a[0], 'contains'), a[1])
                return ast.UnaryOp(op=ast.Not(), operand=o)
            if t[1] == '-':
                self.adv()
                o = self.mbinary(8)
                ok, v = cval(o)
                return K(-v) if ok and isinstance(v, (int, float)) and not isinstance(v, bool) else ast.UnaryOp(op=ast.USub(), operand=o)
            if t[1] == '+':
                self.adv()
                return self.mbinary(8)
        return self.mpostfix(self.mprimary())

    def mprimary(self):
        t = self.adv()
        k, v = t[0], t[1]
        if k in ('num', 'str'):
            return K(v)
        if k == 'op' and v == '(':
            self.depth += 1
            e = self.expr()
            self.depth -= 1
            self.expect(')')
            return e
        if k == 'op' and v == '[':
            self.depth += 1
            items = []
            while not self.is_op(']'):
                items.append(self.expr())
                if not self.accept(','):
                    pass
                while self.tk()[0] == 'nl' or self.is_op(';'):
                    self.adv()
            self.depth -= 1
            self.expect(']')
            stringy = any(isinstance(x, ast.Call) and getattr(x.func, 'id', '') in ('str', 'sprintf') or (
                cval(x)[0] and isinstance(cval(x)[1], str)) or (isinstance(x, ast.BinOp) and isinstance(x.op, ast.BitAnd)) for x in items)
            if stringy and items:
                out = items[0]
                for x in items[1:]:
                    out = BIN(ast.BitAnd, out, x)
                return out
            return ast.List(elts=items)
        if k == 'op' and v == '{':
            items = []
            while not self.is_op('}'):
                items.append(self.expr())
                self.accept(',')
            self.adv()
            return ast.List(elts=items)
        if k == 'id':
            if v == 'true' and not self.is_op('('):
                return K(True)
            if v == 'false' and not self.is_op('('):
                return K(False)
            if v == 'pi':
                return MEMBER(NM('math'), 'pi')
            if v == 'end':
                return NM('_end')
            return NM(v)
        self.i -= 1
        self.err("unexpected '{0}'".format(v.strip() or 'end of line'))

    def mpostfix(self, node):
        while True:
            t = self.tk()
            if t[0] == 'op' and t[1] == '(':
                self.adv()
                self.depth += 1
                args = []
                while not self.is_op(')'):
                    if self.is_op(':'):
                        self.err('slices are not supported')
                    args.append(self.expr())
                    if not self.accept(','):
                        break
                self.depth -= 1
                self.expect(')')
                if isinstance(node, ast.Name) and node.id in self.known[-1] and node.id not in self.fn_names:
                    idx = args[0]
                    idx = self.subst_end(idx, node)
                    node = SUBS(node, self.idx_minus_one(idx))
                else:
                    node = self.m_call(node, args)
                continue
            if t[0] == 'op' and t[1] == '{' and isinstance(node, ast.Name):
                self.adv()
                idx = self.expr()
                self.expect('}')
                node = SUBS(node, self.idx_minus_one(self.subst_end(idx, node)))
                continue
            if t[0] == 'op' and t[1] == "'":
                self.err('transpose is not supported')
            break
        return node

    def subst_end(self, idx, arr):
        for n in ast.walk(idx):
            pass
        def sub(n):
            if isinstance(n, ast.Name) and n.id == '_end':
                return CALL('len', arr)
            for f in ('left', 'right', 'operand'):
                if hasattr(n, f):
                    setattr(n, f, sub(getattr(n, f)))
            return n
        return sub(idx)

    def m_call(self, callee, args):
        name = callee.id if isinstance(callee, ast.Name) else None
        if name is None:
            self.err('this call is not supported')
        if name in ('disp', 'display'):
            return self.print_call(args[:1], True)
        if name in ('fprintf', 'printf'):
            if args and isinstance(cval(args[0])[1], str) and cval(args[0])[0]:
                e, nl = self.fmt_expr(unescape(cval(args[0])[1], 'MATLAB', "'"), args[1:])
                return self.print_call([e], nl)
            self.err('fprintf needs a literal format string')
        if name == 'sprintf':
            return self.fmt_expr(unescape(cval(args[0])[1], 'MATLAB', "'"), args[1:])[0]
        if name == 'input':
            if len(args) == 2:
                return CALL('input')
            return CALL('float', CALL('input'))
        if name in ('str2double', 'str2num'):
            return CALL('float', args[0])
        if name == 'num2str':
            return CALL('str', args[0])
        if name == 'mat2str':
            a = args[0]
            if isinstance(a, ast.Call) and getattr(a.func, 'id', '') == 'logical':
                a = a.args[0]
            return CALL('str', a)
        if name == 'logical':
            return args[0]
        if name == 'issorted' and isinstance(args[0], ast.List) and len(args[0].elts) == 2:
            return ast.Compare(left=args[0].elts[0], ops=[ast.LtE()], comparators=[args[0].elts[1]])
        if name in ('numel', 'length'):
            return CALL('len', args[0])
        if name in ('upper', 'lower', 'strtrim'):
            return CALL(MEMBER(args[0], {'upper': 'upper', 'lower': 'lower', 'strtrim': 'strip'}[name]))
        if name in ('strcmp', 'strcmpi'):
            return ast.Compare(left=args[0], ops=[ast.Eq()], comparators=[args[1]])
        if name == 'strfind':
            return CALL('_indexof', args[0], args[1])
        if name in ('zeros', 'ones', 'false', 'true', 'cell'):
            size = args[1] if len(args) >= 2 else args[0]
            default = {'zeros': K(0), 'ones': K(1), 'false': K(False), 'true': K(True), 'cell': K('')}[name]
            return ArrayNew(size=size, default=default)
        if name == 'repmat' and len(args) == 3:
            d = args[0].elts[0] if isinstance(args[0], ast.List) and args[0].elts else K(0)
            return ArrayNew(size=args[2], default=d)
        if name in ('mod', 'rem') and len(args) == 2:
            return BIN(ast.Mod, args[0], args[1])
        if name == 'power' and len(args) == 2:
            return BIN(ast.Pow, args[0], args[1])
        if name in ('abs',):
            return CALL('abs', args[0])
        if name in ('fix',):
            a0 = args[0]
            if isinstance(a0, ast.Call) and getattr(a0.func, 'id', '') == 'float' and len(a0.args) == 1:
                return CALL('int', a0.args[0])
            return CALL('int', a0)
        if name in ('sqrt', 'sin', 'cos', 'tan', 'asin', 'acos', 'atan', 'log', 'log10', 'floor', 'ceil'):
            if name == 'floor' and isinstance(args[0], ast.BinOp) and isinstance(args[0].op, ast.Mult) and \
                    isinstance(args[0].left, ast.Call) and getattr(args[0].left.func, 'id', '') == 'rand':
                return CALL(MEMBER(NM('random'), 'randrange'), args[0].right)
            return CALL(MEMBER(NM('math'), name), args[0])
        if name == 'round':
            return CALL('round', args[0])
        if name in ('max', 'min') and len(args) == 2:
            return CALL(name, *args)
        if name in ('exit', 'quit'):
            return StmtList(stmts=[ast.Return(value=None)])
        if name == 'rand':
            return CALL('rand')
        if name in ('fflush', 'fclose', 'pause', 'drawnow', 'stdout', 'tic', 'toc'):
            return SkipExpr(id='_obj')
        return CALL(name, *args)


def parse_r(text):
    fe = RFront(text)
    tree = fe.parse_program()
    for k in list(LAST_WARNINGS):
        LAST_WARNINGS.remove(k)
    LAST_WARNINGS.extend(fe.warnings)
    return PyImporter('').run(tree)


def parse_matlab(text):
    fe = MatlabFront(text)
    tree = fe.parse_program()
    for k in list(LAST_WARNINGS):
        LAST_WARNINGS.remove(k)
    LAST_WARNINGS.extend(fe.warnings)
    return PyImporter('').run(tree)


CAPABILITIES = """Flowchart Studio is an independent educational desktop editor.
It is not an official Flowgorithm application or a universal Python compiler.

PYTHON PROGRAMS
Python source is parsed with Python's AST and compiled to editable chart nodes.
A dedicated restricted interpreter preserves Python values and operators rather
than forcing everything into four scalar types. It never uses eval or exec.
Supported: strings, numbers, Booleans, None; lists, tuples, dictionaries, sets;
collection literals and constructors; nested values, indexing and slices;
assignment/unpacking and augmented assignment; if/else; while/for, break,
continue and loop else; input inside expressions; print sep/end; common safe
string/collection methods; comprehensions, generator expressions and f-strings;
range, enumerate, zip, map/filter, sorted, sum and other common built-ins;
functions, positional/default arguments, recursion; math/random imports.
For loops evaluate their iterable once and retain Python's empty-loop and
last-value behavior. Dictionaries iterate over keys, and items()/values() work.
Python source export is rebuilt from chart nodes; JSON saves retain these values
and iterable loops. A dynamic Python chart cannot be saved as .fprg without
losing information, so that export is rejected explicitly.

Unsupported Python: classes, arbitrary libraries, exceptions/try, with, async,
lambda, nested functions, decorators, file/network I/O, global/nonlocal
statements, positional-only/keyword-only parameters and *args/**kwargs function
signatures. Unsafe/private attributes are rejected. Some valid Python therefore
cannot be represented; the error should identify the unsupported construct.
This interpreter is an educational subset, not a security sandbox for hostile
code. Execution and sequence-allocation limits help catch runaway programs.

PORTABLE CHARTS AND OTHER LANGUAGES
The original portable model remains available: Integer/Real/String/Boolean,
fixed-size arrays, functions, branches and loops. It generates and parses
Python, Pseudocode, C, C++, C#, Java, JavaScript, TypeScript, Go, Kotlin, Swift,
PHP, R and MATLAB. Conversion uses a finite subset of each language. Python
charts lower nested input, snapshotted range bounds and signed steps into
explicit portable operations. Homogeneous list/tuple/string iteration, enumerate,
and fixed dictionaries represented by parallel key/value arrays are supported.
Named and inline dictionary lookups accept runtime keys. Dictionary entries are
evaluated eagerly in source order, including repeated keys, inside their original
loop or branch; a missing lookup key stops execution with an error. Dictionary
keys must be scalar literals, and array element types must fit the portable
scalar model. Python and/or retain operand values and short-circuit evaluation.
Dynamic map resizing, heterogeneous collections,
and unsupported library features still report a conversion error. Target-parser validation
does not prove external-compiler acceptance or semantic equivalence. Compiler
and runtime availability varies by machine; no external compiler is bundled.

EDITOR
Flowchart editing, symbol insertion and dragging, undo/redo, functions,
run/step/pause, breakpoints, source editing, console/variables, zoom, JSON saves,
and vector PDF export. User-function calls execute atomically while stepping.
The UI follows familiar desktop flowchart-editor conventions without copying
proprietary assets.

VALIDATION
Run --self-test for the bundled portable-model checks and available toolchains.
The separate test_programs.py compares chart execution, Python export and
re-import with CPython, including collection loops, input expressions, iterator
bounds, mutation, source-order defaults and JSON persistence. A passing suite
covers its fixtures, not every possible Python program or external language.

Requires Python 3.3+ and only the standard library. The desktop interface needs
Tkinter/Tk and a graphical display; headless CLI operation does not import Tk.
"""
def label(n):
    k = n['kind']
    if k == 'Declare':
        return n['type'] + ' ' + n['name'] + ('[' + n['size'] + ']' if n['array'] else '')
    if k == 'Assign':
        return n['variable'] + ' = ' + n['expression']
    if k == 'Input':
        return 'Input ' + n['variable']
    if k == 'Output':
        return 'Output ' + n['expression']
    if k == 'For':
        if n.get('iterable'):
            return n['variable'] + ' in ' + n['iterable']
        return n['variable'] + ' = ' + n['start'] + ' to ' + n['end'] + ' step ' + ('-' if n['direction'] == 'dec' else '') + n['step']
    if k == 'Comment':
        return n['text']
    if k in ('Break', 'Continue'):
        return k
    return k + ' ' + n.get('expression', '')


# --- Compact, standard-library vector PDF exporter --------------------------------
# No PIL, Ghostscript, reportlab or font file is required. Drawing stays as
# PDF paths, so a 25 MB native chart need not become a huge raster image.
import zlib

class _FlowPDF(object):
    def __init__(self):
        self.objects = [None]

    def reserve(self):
        self.objects.append(None)
        return len(self.objects) - 1

    def put(self, ref, data):
        if isinstance(data, str):
            data = data.encode('latin-1', 'replace')
        self.objects[ref] = data

    def stream(self, instructions):
        data = zlib.compress(('\n'.join(instructions) + '\n').encode('latin-1', 'replace'), 6)
        ref = self.reserve()
        self.put(ref, ('<< /Length %d /Filter /FlateDecode >>\nstream\n' % len(data)).encode('ascii')
                 + data + b'\nendstream')
        return ref

    def write(self, pathname, catalog):
        out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
        positions = [0]
        for i in range(1, len(self.objects)):
            positions.append(len(out))
            out.extend(('%d 0 obj\n' % i).encode('ascii'))
            if self.objects[i] is None:
                raise ValueError('Unassigned PDF object ' + str(i))
            out.extend(self.objects[i])
            out.extend(b'\nendobj\n')
        xref = len(out)
        out.extend(('xref\n0 %d\n' % len(self.objects)).encode('ascii'))
        out.extend(b'0000000000 65535 f \n')
        for pos in positions[1:]:
            out.extend(('%010d 00000 n \n' % pos).encode('ascii'))
        out.extend(('trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n'
                    % (len(self.objects), catalog, xref)).encode('ascii'))
        with open(pathname, 'wb') as f:
            f.write(out)
        return len(out)


def _pdf_str(value):
    # Standard PDF fonts cover WinAnsi only; unavailable glyphs use '?'.
    text = str(value).encode('cp1252', 'replace').decode('latin-1')
    return '(' + text.replace('\\','\\\\').replace('(','\\(').replace(')','\\)') + ')'


def _pdf_color(rgb):
    if not rgb:
        return None
    return '%.4f %.4f %.4f' % tuple(max(0., min(1., float(v))) for v in rgb)


def _pdf_pages_for_scene(scene):
    box = scene['bounds']
    lo_x, lo_y, hi_x, hi_y = [float(v) for v in box]
    # Coordinate units are Tk world coordinates (at zoom 100%).
    lo_x -= 20
    lo_y -= 20
    hi_x += 20
    hi_y += 20
    width, height = hi_x-lo_x, hi_y-lo_y
    scale = 0.94
    if width*scale <= 13000 and height*scale <= 13000:
        w = max(550., width*scale+80)
        h = max(200., height*scale+105)
        return [(w,h,(lo_x,lo_y,hi_x,hi_y),1,1,1,1,scale)]
    # Beyond the safe PDF-page geometry, split into complete vector sheets.
    # Avoid cutting through the body of a shape when positioning page seams.
    page_w, page_h = 1190.55,841.89  # A3 landscape, in PDF points
    span_x = (page_w-84)/scale
    span_y = (page_h-100)/scale
    nodes = [it['bbox'] for it in scene['items']
             if it['type'] in ('rectangle','oval','polygon') and it.get('fill') is not None]
    def partitions(start,stop,span,axis):
        cuts = [start]
        while cuts[-1] < stop-0.001:
            low = cuts[-1]
            high = min(stop,low+span)
            if high < stop:
                for bb in nodes:
                    a,b = float(bb[axis]),float(bb[axis+2])
                    if a < high < b and (b-a) < span*0.4 and a-12 > low+span*0.40:
                        high = a-12
            high = max(low+min(70,span/3),high)
            high = min(stop,high)
            cuts.append(high)
            if len(cuts) > 1000000:
                raise ValueError('Diagram page count exceeds feasible PDF limits')
        return list(zip(cuts[:-1],cuts[1:]))
    xs = partitions(lo_x,hi_x,span_x,0)
    ys = partitions(lo_y,hi_y,span_y,1)
    pages=[]
    for ry,(y0,y1) in enumerate(ys):
        for rx,(x0,x1) in enumerate(xs):
            pages.append((page_w,page_h,(x0,y0,x1,y1),rx+1,len(xs),ry+1,len(ys),scale))
    return pages


def _pdf_draw_item(it, window, sheet_width, sheet_height, scale):
    x0,y0,x1,y1 = window
    bb = it.get('bbox')
    if bb and (bb[2] < x0 or bb[0] > x1 or bb[3] < y0 or bb[1] > y1):
        return []
    left,top = 40., sheet_height-65.
    X = lambda v: left+(v-x0)*scale
    Y = lambda v: top-(v-y0)*scale
    coords=it['coords']
    typ=it['type']
    fill=_pdf_color(it.get('fill'))
    outline=_pdf_color(it.get('outline'))
    thickness=max(0.5,float(it.get('width',1))*scale)
    cmds=[]
    if typ=='text':
        value=it.get('text','')
        if not value: return []
        size=max(5.,float(it.get('fontsize',10))*scale)
        maxlen=float(it.get('textwidth',0))/max(1.,float(it.get('fontsize',10))*0.54)
        lines=[]
        for para in value.split('\n'):
            if maxlen < 3 or len(para) <= maxlen:
                lines.append(para)
            else:
                words=para.split(' ')
                buf=''
                for word in words:
                    if buf and len(buf)+1+len(word)>maxlen:
                        lines.append(buf)
                        buf=word
                    else:
                        buf=(buf+' '+word).strip()
                lines.append(buf)
        if not lines:lines=['']
        color=fill or '0 0 0'
        h=size*1.16
        first=Y(coords[1])+(len(lines)-1)*h/2-size*0.33
        for j,line in enumerate(lines):
            tx=X(coords[0])-len(line)*size*0.255
            ty=first-j*h
            cmds.append('q %s rg BT /F1 %.3f Tf 1 0 0 1 %.3f %.3f Tm %s Tj ET Q'
                        % (color,size,tx,ty,_pdf_str(line)))
        return cmds
    if typ not in ('line','polygon','rectangle','oval'):
        return []
    cmds.append('q 1 J 1 j %.3f w' % thickness)
    if fill:cmds.append(fill+' rg')
    if outline:cmds.append(outline+' RG')
    if typ=='line':
        pts=list(zip(coords[0::2],coords[1::2]))
        if len(pts)<2:return []
        cmds.append('%.3f %.3f m' % (X(pts[0][0]),Y(pts[0][1])))
        for px,py in pts[1:]:
            cmds.append('%.3f %.3f l' % (X(px),Y(py)))
        cmds.append('S')
        if it.get('arrow') in ('last','both'):
            import math as _m
            px,py=pts[-2]
            qx,qy=pts[-1]
            dx,dy=qx-px,qy-py
            mag=_m.sqrt(dx*dx+dy*dy)
            if mag>0.1:
                dx,dy=dx/mag,dy/mag
                ax,ay=-dy,dx
                length=10
                aw=4.2
                points=[(qx,qy),(qx-dx*length+ax*aw,qy-dy*length+ay*aw),
                        (qx-dx*length-ax*aw,qy-dy*length-ay*aw)]
                cc=outline or fill or '0.3 0.3 0.3'
                cmds.append(cc+' rg')
                cmds.append('%.3f %.3f m' % (X(points[0][0]),Y(points[0][1])))
                for a,b in points[1:]:cmds.append('%.3f %.3f l' % (X(a),Y(b)))
                cmds.append('h f')
        cmds.append('Q')
        return cmds
    if typ=='rectangle':
        xx,yy=coords[0],coords[1]
        ww,hh=coords[2]-coords[0],coords[3]-coords[1]
        cmds.append('%.3f %.3f %.3f %.3f re' % (X(xx),Y(yy+hh),ww*scale,hh*scale))
    elif typ=='polygon':
        pts=list(zip(coords[0::2],coords[1::2]))
        if not pts:return []
        cmds.append('%.3f %.3f m' % (X(pts[0][0]),Y(pts[0][1])))
        for x,y in pts[1:]:cmds.append('%.3f %.3f l' % (X(x),Y(y)))
        cmds.append('h')
    elif typ=='oval':
        xa,ya,xb,yb=coords
        cx,cy=(xa+xb)/2.,(ya+yb)/2.
        rx,ry=(xb-xa)/2.,(yb-ya)/2.
        v=0.5522847498
        def p(x,y):return '%.3f %.3f' % (X(x),Y(y))
        cmds.append(p(cx+rx,cy)+' m')
        cmds.append(p(cx+rx,cy+v*ry)+' '+p(cx+v*rx,cy+ry)+' '+p(cx,cy+ry)+' c')
        cmds.append(p(cx-v*rx,cy+ry)+' '+p(cx-rx,cy+v*ry)+' '+p(cx-rx,cy)+' c')
        cmds.append(p(cx-rx,cy-v*ry)+' '+p(cx-v*rx,cy-ry)+' '+p(cx,cy-ry)+' c')
        cmds.append(p(cx+v*rx,cy-ry)+' '+p(cx+rx,cy-v*ry)+' '+p(cx+rx,cy)+' c')
        cmds.append('h')
    cmds.append('B' if fill and outline else ('f' if fill else 'S'))
    cmds.append('Q')
    return cmds


def export_vector_flowchart_pdf(scenes, pathname):
    """Export all functions, preserving every diagram region as vectors.

    Small/medium diagrams use one uninterrupted page per function. Overlong
    charts are tiled with shape-safe page boundaries and row/column labels.
    There is no artificial PDF file size limit.
    """
    if not scenes:
        raise ValueError('No flowchart functions to export')
    pdf=_FlowPDF()
    catalog=pdf.reserve()
    pagesref=pdf.reserve()
    fontref=pdf.reserve()
    pdf.put(fontref,'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>')
    refs=[]
    for scene in scenes:
        sheets=_pdf_pages_for_scene(scene)
        for index,(w,h,window,col,cols,row,rows,scale) in enumerate(sheets):
            text='Function: '+scene['name']
            if cols>1 or rows>1:
                text+='  |  Sheet %d/%d  |  Column %d/%d  Row %d/%d' % (index+1,len(sheets),col,cols,row,rows)
            instr=['1 1 1 rg 0 0 %.3f %.3f re f' % (w,h),
                   '0.11 0.17 0.28 rg BT /F1 15 Tf 1 0 0 1 40 %.3f Tm %s Tj ET' % (h-30,_pdf_str(text)),
                   '0.82 0.86 0.91 RG 0.8 w 40 %.3f m %.3f %.3f l S' % (h-42,w-40,h-42),
                   'q 40 35 %.3f %.3f re W n' % (w-80,h-88)]
            for it in scene['items']:
                instr.extend(_pdf_draw_item(it,window,w,h,scale))
            instr.append('Q')
            content=pdf.stream(instr)
            pref=pdf.reserve()
            refs.append(pref)
            pdf.put(pref,'<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.3f %.3f] /Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>'
                    % (pagesref,w,h,fontref,content))
    pdf.put(pagesref,'<< /Type /Pages /Count %d /Kids [%s] >>'
            % (len(refs),' '.join('%d 0 R' % r for r in refs)))
    pdf.put(catalog,'<< /Type /Catalog /Pages %d 0 R >>' % pagesref)
    return pdf.write(pathname,catalog),len(refs)



def launch_gui(initial_path=None):
    # Delayed import means CLI works on systems without Tk.
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox, simpledialog
    except ImportError:
        sys.stderr.write('The desktop editor needs Tkinter, which is not included in this Python installation.\nNo pip packages are used. The headless --run / --generate CLI still works.\n')
        return 1

    class ShapeDialog(simpledialog.Dialog):
        def __init__(self, parent, n, python_mode=False):
            self.python_mode = python_mode
            self.original = copy.deepcopy(n)
            if python_mode:
                if n['kind'] == 'For':
                    self.original.setdefault('iterable', 'range(1, 11)')
                elif n['kind'] == 'Input':
                    self.original.setdefault('expression', 'input()')
                elif n['kind'] == 'Output' and not n.get('python_call'):
                    self.original['expression'] = 'print(' + n['expression'] + (')' if n.get('newline', True) else ", end='')")
                    self.original['python_call'] = True
            self.values = {}
            simpledialog.Dialog.__init__(self, parent, 'Edit ' + n['kind'])

        def body(self, master):
            hint = ('Python expressions and collections. Indices start at zero.\nFor iterable: range(int(input())+1), a list, string, tuple or dictionary.' if self.python_mode else
                    'Expressions: =, <>, +, -, *, /, ^, &, And, Or, Not.\nArrays use zero-based indices: values[0].')
            ttk.Label(master, text=symbol_help_text(self.original['kind'], self.python_mode),
                      justify='left', wraplength=530, padding=(8, 6)).grid(
                          row=0, column=0, columnspan=2, sticky='ew', pady=(4, 6))
            ttk.Label(master, text=hint, justify='left', wraplength=530).grid(
                row=1, column=0, columnspan=2, sticky='w', pady=(0, 8))
            row = 2
            control = None
            fields = list(DEFAULTS[self.original['kind']])
            if self.python_mode:
                if self.original['kind'] == 'For': fields = ['variable', 'iterable']
                elif self.original['kind'] in ('Input', 'Output'):
                    fields = ['variable', 'expression'] if self.original['kind'] == 'Input' else ['expression']
                if self.original.get('augmented'): fields.append('augmented')
                if self.original.get('python_import'): fields = ['python_import']
            for key in fields:
                title = 'Python print call' if self.python_mode and self.original['kind']=='Output' and key=='expression' else key.replace('_', ' ').title()
                ttk.Label(master, text=title + ':').grid(row=row, column=0, sticky='w', padx=5, pady=5)
                val = self.original[key]
                if key == 'variable' and self.python_mode and len(self.original.get('targets', [])) > 1:
                    val = ' = '.join(self.original['targets'])
                var = tk.BooleanVar(value=val) if isinstance(val, bool) else tk.StringVar(value=str(val))
                self.values[key] = var
                if isinstance(val, bool):
                    control = ttk.Checkbutton(master, variable=var)
                elif key == 'augmented':
                    control = ttk.Combobox(master, textvariable=var, values=('Add','Sub','Mult','Div','FloorDiv','Mod','Pow','BitAnd','BitOr','BitXor','LShift','RShift'), state='readonly', width=44)
                elif key in ('type', 'direction'):
                    opts = ('Integer', 'Real', 'String', 'Boolean') if key == 'type' else ('inc', 'dec')
                    control = ttk.Combobox(master, textvariable=var, values=opts, state='readonly', width=44)
                else:
                    control = ttk.Entry(master, textvariable=var, width=48)
                control.grid(row=row, column=1, sticky='ew', padx=5, pady=5)
                row += 1
            return control

        def validate(self):
            result = copy.deepcopy(self.original)
            for k, v in self.values.items():
                result[k] = v.get()
            try:
                d = empty_document()
                if self.python_mode:
                    d['python'] = True
                    if result['kind'] in ('Assign', 'Input') and not result.get('augmented'):
                        assignment = ast.parse(result['variable'] + ' = None').body[0]
                        result['targets'] = [ast_source(t) for t in assignment.targets]
                        result['variable'] = result['targets'][0]
                if result.get('python_import'):
                    result['text'] = result['python_import']
                d['functions'][0]['body'] = ([node('While', expression='True', body=[result])] if result['kind'] in ('Break', 'Continue') else [result])
                validate(d)
                self.result = result
                return True
            except Exception as e:
                messagebox.showerror('Invalid shape', str(e), parent=self)
                return False

        def apply(self):
            pass

    class FunctionDialog(simpledialog.Dialog):
        def __init__(self, parent, f, python_mode=False):
            self.python_mode = python_mode
            self.original = f
            simpledialog.Dialog.__init__(self, parent, 'Function properties')

        def body(self, master):
            self.name = tk.StringVar(value=self.original['name'])
            self.typ = tk.StringVar(value=self.original['type'])
            self.ret = tk.StringVar(value=self.original['variable'])
            self.params = tk.StringVar(value=', '.join(p['name'] + ':' + p['type'] + ('[]' if p['array'] else '') for p in self.original['parameters']))
            for row, pair in enumerate([('Name', self.name), ('Return type', self.typ), ('Return variable (optional)', self.ret), ('Parameters', self.params)]):
                ttk.Label(master, text=pair[0]).grid(row=row, column=0, padx=5, pady=5, sticky='w')
                if row == 1:
                    w = ttk.Combobox(master, textvariable=pair[1], values=(('None', 'Python', 'Integer', 'Real', 'String', 'Boolean') if self.python_mode else ('None', 'Integer', 'Real', 'String', 'Boolean')), state='readonly')
                else:
                    w = ttk.Entry(master, textvariable=pair[1], width=48)
                w.grid(row=row, column=1, padx=5, pady=5, sticky='ew')
            ttk.Label(master, text='Parameters: x:Integer, text:String, values:Real[]\nUse a Return shape or set the optional return variable.').grid(row=4, column=0, columnspan=2, pady=8)
            return w

        def validate(self):
            try:
                name = self.name.get().strip()
                if not valid_name(name):
                    raise FlowError('Invalid function name.')
                params = []
                for text in self.params.get().split(','):
                    if not text.strip():
                        continue
                    bits = text.strip().split(':')
                    if len(bits) != 2 or not valid_name(bits[0].strip()):
                        raise FlowError('Parameter format: name:Type or name:Type[]')
                    typ = bits[1].strip()
                    array = typ.endswith('[]')
                    typ = typ[:-2] if array else typ
                    if typ not in (('Python', 'Integer', 'Real', 'String', 'Boolean') if self.python_mode else ('Integer', 'Real', 'String', 'Boolean')):
                        raise FlowError('Unknown parameter type: ' + typ)
                    param = {'name': bits[0].strip(), 'type': typ, 'array': array}
                    prior = next((p for p in self.original['parameters'] if p['name']==param['name']), {})
                    if self.python_mode and 'default' in prior:
                        param['default'] = prior['default']
                    params.append(param)
                if len(set(p['name'] for p in params)) != len(params):
                    raise FlowError('Duplicate parameter names.')
                self.result = copy.deepcopy(self.original)
                self.result.update(name=name, type=self.typ.get(), variable=self.ret.get().strip(), parameters=params)
                return True
            except Exception as e:
                messagebox.showerror('Invalid function', str(e), parent=self)
                return False

        def apply(self):
            pass

    class Editor(object):
        def __init__(self, root):
            self.root = root
            self.doc = empty_document()
            self.path = None
            self.saved_state = json.dumps(self.doc, sort_keys=True)
            self.undo_stack = []
            self.redo_stack = []
            self.clipboard = None
            self.function_index = 0
            self.mapping = {}
            self.node_iids = {}
            self.breakpoints = set()
            self.engine = None
            self.iterator = None
            self.current_node = None
            self.running = False
            self.timer = None
            self.zoom = 1.0
            self.source = None
            self.code_timer = None
            self.code_busy = False
            self.code_language = 'Python'
            self.code_status = tk.StringVar(value='')
            self.language = tk.StringVar(value='Python')
            self.function_var = tk.StringVar(value='Main')
            self.status = tk.StringVar(value='Ready. Hover over a connector to open the symbol picker.')
            self.speed = tk.IntVar(value=250)
            self.speed_choice = tk.StringVar(value='0.25 seconds per instruction')
            self.palette_filter = tk.StringVar(value='')
            self.dark_theme = False
            self.palette_buttons = []
            self.palette_drag_kind = None
            self.palette_drag_origin = None
            self.palette_drag_moved = False
            self.drag_preview = None
            self.drag_poll = None
            self.drop_sites = []
            self.pending_insert = None
            self.insert_hit_targets = {}
            self.connector_paths = {}
            self.hover_connector = None
            self.connector_hover_point = None
            self.connector_hover_timer = None
            self.connector_close_timer = None
            self.shape_picker = None
            self.canvas_drag_iid = None
            self.canvas_drag_origin = None
            self.canvas_drag_moved = False
            root.geometry('1280x820')
            root.minsize(960, 640)
            self.build_ui()
            self.refresh()
            root.protocol('WM_DELETE_WINDOW', self.close)

        def build_ui(self):
            # Use a compact, native desktop layout; keep the diagram primary.
            from tkinter import font as tkfont
            families = {f.lower(): f for f in tkfont.families(self.root)}
            ui_font = next((families[f.lower()] for f in ('Segoe UI', 'DejaVu Sans', 'Arial', 'Helvetica') if f.lower() in families), 'Helvetica')
            mono_font = next((families[f.lower()] for f in ('Cascadia Code', 'Consolas', 'DejaVu Sans Mono', 'Courier') if f.lower() in families), 'Courier')
            for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
                tkfont.nametofont(name).configure(family=ui_font, size=10)
            self.ui_font, self.mono_font = ui_font, mono_font
            style = ttk.Style(self.root)
            try:
                style.theme_use('clam')
            except tk.TclError:
                pass
            style.configure('.', background='#f1f3f6', foreground='#253247', font=(ui_font, 10))
            style.configure('TFrame', background='#f1f3f6')
            style.configure('TLabel', background='#f1f3f6')
            style.configure('TButton', padding=(8, 5), background='#fafbfc', borderwidth=1)
            style.map('TButton', background=[('active', '#e3edfa')])
            style.configure('Tool.TButton', padding=(5, 4), relief='flat', borderwidth=0, background='#f1f3f6')
            style.configure('TNotebook', borderwidth=0)
            style.configure('TNotebook.Tab', padding=(13, 6))
            style.configure('Treeview', rowheight=26, background='white', fieldbackground='white')
            style.map('Treeview', background=[('selected', '#d8e9ff')], foreground=[('selected', '#12345a')])
            self.root.configure(background='#f1f3f6')
            menu = tk.Menu(self.root)
            self.root.config(menu=menu)
            filemenu = tk.Menu(menu, tearoff=False)
            for text, cmd in [('New', self.new), ('Open...', self.open), ('Import source code...', self.import_source), ('Save', self.save), ('Save As...', lambda: self.save(True)), ('Load example', self.example), ('Export generated source...', self.export_code), ('Export full flowchart (PDF)...', self.export_diagram), ('Exit', self.close)]:
                filemenu.add_command(label=text, command=cmd)
            menu.add_cascade(label='File', menu=filemenu)
            editmenu = tk.Menu(menu, tearoff=False)
            for text, cmd in [('Undo', self.undo), ('Redo', self.redo), ('Edit shape', self.edit_shape), ('Delete', self.delete), ('Cut', self.cut), ('Copy', self.copy), ('Paste', self.paste), ('Move up', lambda: self.move(-1)), ('Move down', lambda: self.move(1)), ('Toggle breakpoint', self.toggle_breakpoint)]:
                editmenu.add_command(label=text, command=cmd)
            menu.add_cascade(label='Edit', menu=editmenu)
            funmenu = tk.Menu(menu, tearoff=False)
            for text, cmd in [('Add function', self.add_function), ('Edit function', self.edit_function), ('Delete function', self.delete_function)]:
                funmenu.add_command(label=text, command=cmd)
            menu.add_cascade(label='Functions', menu=funmenu)
            runmenu = tk.Menu(menu, tearoff=False)
            for text, cmd in [('Run / Continue', self.run), ('Step', self.step), ('Pause', self.pause), ('Stop / Reset', self.stop), ('Toggle breakpoint', self.toggle_breakpoint)]:
                runmenu.add_command(label=text, command=cmd)
            menu.add_cascade(label='Debug', menu=runmenu)
            toolmenu = tk.Menu(menu, tearoff=False)
            toolmenu.add_command(label='Convert code between languages...', command=self.convert_dialog)
            menu.add_cascade(label='Tools', menu=toolmenu)
            viewmenu = tk.Menu(menu, tearoff=False)
            viewmenu.add_command(label='Zoom in', command=lambda: self.set_zoom(1.15))
            viewmenu.add_command(label='Zoom out', command=lambda: self.set_zoom(1 / 1.15))
            viewmenu.add_command(label='Reset zoom (100%)', command=self.reset_zoom)
            viewmenu.add_command(label='Fit diagram to window', command=self.fit_diagram)
            viewmenu.add_separator()
            viewmenu.add_command(label='Toggle light / dark theme', command=self.toggle_theme)
            viewmenu.add_separator()
            viewmenu.add_command(label='Symbols and outline', command=self.toggle_symbols, accelerator='Ctrl+Shift+B')
            viewmenu.add_command(label='Generated code', command=self.show_generated_code, accelerator='Ctrl+L')
            viewmenu.add_command(label='Console and variables', command=lambda: self.show_tools(1, True))
            menu.add_cascade(label='View', menu=viewmenu)
            helpmenu = tk.Menu(menu, tearoff=False)
            helpmenu.add_command(label='Capabilities and limitations', command=self.help)
            helpmenu.add_command(label='Symbol guide', command=self.symbol_guide)
            helpmenu.add_command(label='Expression reference', command=self.expression_help)
            helpmenu.add_command(label='About', command=lambda: messagebox.showinfo('About', 'Flowchart Studio ' + VERSION + '\nIndependent standard-library Python 3.3+ application.\nNot affiliated with Flowgorithm.', parent=self.root))
            menu.add_cascade(label='Help', menu=helpmenu)
            toolbar = ttk.Frame(self.root, padding=(10, 5))
            toolbar.pack(fill='x')
            self.toolbar_images = []
            def tool(icon, hint, command):
                image = self.toolbar_icon(icon)
                self.toolbar_images.append(image)
                button = ttk.Button(toolbar, image=image, command=command, style='Tool.TButton', takefocus=True)
                button.pack(side='left', padx=2)
                self.tooltip(button, hint)
                return button
            def separator():
                ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=9, pady=3)
            for icon, hint, cmd in [('new', 'New (Ctrl+N)', self.new), ('open', 'Open chart (Ctrl+O)', self.open), ('save', 'Save (Ctrl+S)', self.save)]:
                tool(icon, hint, cmd)
            separator()
            tool('undo', 'Undo (Ctrl+Z)', self.undo)
            tool('redo', 'Redo (Ctrl+Y)', self.redo)
            separator()
            tool('run', 'Run / continue (F5)', self.run)
            tool('step', 'Single step (F6)', self.step)
            tool('pause', 'Pause (Escape)', self.pause)
            tool('stop', 'Stop / reset', self.stop)
            ttk.Label(toolbar, text='Speed').pack(side='left', padx=(12, 5))
            self.speed_box = ttk.Combobox(toolbar, textvariable=self.speed_choice, state='readonly', width=12,
                values=('Instant', 'Fast', 'Normal', 'Slow', 'Very slow'))
            self.speed_choice.set('Normal')
            self.speed_box.pack(side='left')
            self.speed_box.bind('<<ComboboxSelected>>', self.change_speed)
            separator()
            tool('source', 'Generate and show code (Ctrl+L)', self.show_generated_code)
            ttk.Button(toolbar, text='Generate code', command=self.show_generated_code, style='Tool.TButton').pack(side='left')
            tool('console', 'Console and variables', lambda: self.show_tools(1, True))
            ttk.Button(toolbar, text='Symbols', command=self.toggle_symbols, style='Tool.TButton').pack(side='left', padx=(5, 0))
            ttk.Button(toolbar, text='Import code...', command=self.import_source, style='Tool.TButton').pack(side='right')
            ttk.Separator(self.root).pack(fill='x')
            document_bar = ttk.Frame(self.root, padding=(14, 7))
            document_bar.pack(fill='x')
            ttk.Label(document_bar, text='Function', foreground='#64748b').pack(side='left', padx=(0, 8))
            self.function_box = ttk.Combobox(document_bar, textvariable=self.function_var, state='readonly', width=20)
            self.function_box.pack(side='left')
            self.function_box.bind('<<ComboboxSelected>>', self.switch_function)
            ttk.Button(document_bar, text='+', width=3, command=self.add_function, style='Tool.TButton').pack(side='left', padx=3)
            ttk.Label(document_bar, text='Hover arrows to add  |  Double-click symbols to edit', foreground='#65748a').pack(side='left', padx=18)
            self.zoom_label = tk.StringVar(value='100%')
            ttk.Button(document_bar, text='-', width=3, command=lambda: self.set_zoom(1 / 1.15), style='Tool.TButton').pack(side='right')
            ttk.Button(document_bar, textvariable=self.zoom_label, width=6, command=self.reset_zoom, style='Tool.TButton').pack(side='right')
            ttk.Button(document_bar, text='+', width=3, command=lambda: self.set_zoom(1.15), style='Tool.TButton').pack(side='right')
            ttk.Button(document_bar, text='Fit', command=self.fit_diagram, style='Tool.TButton').pack(side='right', padx=5)
            self.panes = ttk.Panedwindow(self.root, orient='horizontal')
            self.panes.pack(fill='both', expand=True)
            self.left_panel = left = ttk.Frame(self.panes, padding=8, width=260)
            self.center_panel = center = ttk.Frame(self.panes)
            self.right_panel = right = ttk.Frame(self.panes, padding=(7, 0, 7, 7), width=400)
            self.panes.add(center, weight=4)
            self.symbols_visible = False
            self.tools_visible = False
            header = ttk.Frame(left)
            header.pack(fill='x', pady=(0, 7))
            ttk.Label(header, text='Symbols & outline', font=(ui_font, 10, 'bold')).pack(side='left')
            ttk.Button(header, text='x', width=2, style='Tool.TButton', command=self.toggle_symbols).pack(side='right')
            self.palette_entry = ttk.Entry(left, textvariable=self.palette_filter)
            self.palette_entry.pack(fill='x', pady=(0, 6))
            if hasattr(self.palette_filter, 'trace_add'):
                self.palette_filter.trace_add('write', self.render_palette)
            else:
                self.palette_filter.trace('w', self.render_palette)
            palette_tabs = ttk.Notebook(left)
            palette_tabs.pack(fill='both', expand=True)
            palette_page, outline_page = ttk.Frame(palette_tabs), ttk.Frame(palette_tabs)
            palette_tabs.add(palette_page, text='Symbols')
            palette_tabs.add(outline_page, text='Outline')
            palette_canvas = tk.Canvas(palette_page, width=244, highlightthickness=0, bg='#f1f3f6')
            palette_scroll = ttk.Scrollbar(palette_page, orient='vertical', command=palette_canvas.yview)
            palette_canvas.configure(yscrollcommand=palette_scroll.set)
            palette_scroll.pack(side='right', fill='y')
            palette_canvas.pack(fill='both', expand=True)
            self.palette = ttk.Frame(palette_canvas)
            palette_canvas.create_window(0, 0, anchor='nw', window=self.palette)
            self.palette.bind('<Configure>', lambda e: palette_canvas.configure(scrollregion=palette_canvas.bbox('all')))
            self.render_palette()
            self.tree = ttk.Treeview(outline_page, show='tree', selectmode='browse')
            self.tree.pack(fill='both', expand=True)
            self.tree.bind('<<TreeviewSelect>>', lambda e: self.draw())
            self.tree.bind('<Double-1>', lambda e: self.edit_shape())
            row = ttk.Frame(outline_page)
            row.pack(fill='x', pady=4)
            for text, cmd in [('Edit', self.edit_shape), ('Delete', self.delete), ('↑', lambda: self.move(-1)), ('↓', lambda: self.move(1))]:
                ttk.Button(row, text=text, width=4, command=cmd).pack(side='left', padx=1)
            area = ttk.Frame(center)
            area.pack(fill='both', expand=True)
            self.canvas = tk.Canvas(area, bg='white', highlightthickness=0, cursor='arrow')
            ys = ttk.Scrollbar(area, orient='vertical', command=lambda *args: self.scroll_canvas('y', *args))
            xs = ttk.Scrollbar(area, orient='horizontal', command=lambda *args: self.scroll_canvas('x', *args))
            self.canvas.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
            ys.pack(side='right', fill='y')
            xs.pack(side='bottom', fill='x')
            self.canvas.pack(fill='both', expand=True)
            self.canvas.bind('<Button-1>', self.canvas_select)
            self.canvas.bind('<ButtonPress-1>', self.canvas_drag_start, add='+')
            self.canvas.bind('<B1-Motion>', self.canvas_drag_motion, add='+')
            self.canvas.bind('<ButtonRelease-1>', self.canvas_drag_drop, add='+')
            self.canvas.bind('<Double-1>', self.canvas_edit)
            self.canvas.bind('<Button-3>', self.canvas_menu)
            self.canvas.bind('<MouseWheel>', self.mousewheel)
            self.canvas.bind('<Button-4>', lambda e: self.scroll_canvas('y', 'scroll', -3, 'units'))
            self.canvas.bind('<Button-5>', lambda e: self.scroll_canvas('y', 'scroll', 3, 'units'))
            self.canvas.bind('<Configure>', self.resize_canvas)
            self.canvas.bind('<Motion>', self.connector_motion, add='+')
            self.canvas.bind('<Leave>', self.connector_leave, add='+')
            self.root.bind_all('<ButtonRelease-1>', self.global_drag_release, add='+')
            tools_header = ttk.Frame(right)
            tools_header.pack(fill='x')
            ttk.Label(tools_header, text='Program tools', font=(ui_font, 10, 'bold')).pack(side='left', padx=5)
            ttk.Button(tools_header, text='x', width=2, style='Tool.TButton', command=self.hide_tools).pack(side='right')
            self.notebook = ttk.Notebook(right)
            self.notebook.pack(fill='both', expand=True)
            sourcepage, consolepage = ttk.Frame(self.notebook), ttk.Frame(self.notebook)
            self.notebook.add(sourcepage, text='Generated code')
            self.notebook.add(consolepage, text='Console & variables')
            language_row = ttk.Frame(sourcepage, padding=(0, 7))
            language_row.pack(fill='x')
            ttk.Label(language_row, text='Language').pack(side='left', padx=(0, 6))
            self.language_box = ttk.Combobox(language_row, textvariable=self.language, values=LANGUAGES, state='readonly', width=15)
            self.language_box.pack(side='left', fill='x', expand=True)
            self.language_box.bind('<<ComboboxSelected>>', self.language_changed)
            ttk.Button(language_row, text='Export', width=7, command=self.export_code).pack(side='left', padx=4)
            ttk.Button(language_row, text='Copy', width=5, command=self.copy_code).pack(side='left')
            sync_row = ttk.Frame(sourcepage)
            sync_row.pack(fill='x', side='bottom', pady=(6, 0))
            ttk.Button(sync_row, text='Apply to chart', command=self.apply_code).pack(side='left')
            ttk.Button(sync_row, text='Reset', command=self.update_code).pack(side='left', padx=4)
            ttk.Label(sourcepage, textvariable=self.code_status, wraplength=360, justify='left', foreground='#526780').pack(fill='x', side='bottom', pady=5)
            code_area = ttk.Frame(sourcepage)
            code_area.pack(fill='both', expand=True)
            self.code = tk.Text(code_area, wrap='none', font=(mono_font, 11), bg='#ffffff', fg='#183452',
                insertbackground='#183452', selectbackground='#cfe3ff', padx=12, pady=12,
                relief='flat', highlightthickness=1, highlightbackground='#d8dfe8', undo=True, maxundo=200, tabs=('1c',))
            code_scroll = ttk.Scrollbar(code_area, orient='horizontal', command=self.code.xview)
            vertical = ttk.Scrollbar(code_area, orient='vertical', command=self.code.yview)
            code_scroll.pack(side='bottom', fill='x')
            vertical.pack(side='right', fill='y')
            self.code.pack(fill='both', expand=True)
            self.code.configure(xscrollcommand=code_scroll.set, yscrollcommand=vertical.set)
            self.code.bind('<<Modified>>', self.code_modified)
            output_header = ttk.Frame(consolepage, padding=(4, 7))
            output_header.pack(fill='x')
            ttk.Label(output_header, text='Program output').pack(side='left')
            ttk.Button(output_header, text='Clear', command=self.clear_console, style='Tool.TButton').pack(side='right')
            debug_panes = ttk.Panedwindow(consolepage, orient='vertical')
            debug_panes.pack(fill='both', expand=True)
            console_area = ttk.Frame(debug_panes)
            self.console = tk.Text(console_area, wrap='word', height=12, font=(mono_font, 11), state='disabled',
                bg='white', fg='#253247', relief='flat', padx=10, pady=10)
            console_scroll = ttk.Scrollbar(console_area, command=self.console.yview)
            console_scroll.pack(side='right', fill='y')
            self.console.configure(yscrollcommand=console_scroll.set)
            self.console.pack(fill='both', expand=True)
            variables_area = ttk.Frame(debug_panes)
            ttk.Label(variables_area, text='Variables', padding=(5, 7)).pack(anchor='w')
            self.variables = ttk.Treeview(variables_area, columns=('type', 'value'), show='tree headings', height=8)
            for col, title, width in [('#0', 'Name', 95), ('type', 'Type', 75), ('value', 'Value', 170)]:
                self.variables.heading(col, text=title)
                self.variables.column(col, width=width, minwidth=45)
            self.variables.pack(fill='both', expand=True)
            debug_panes.add(console_area, weight=3)
            debug_panes.add(variables_area, weight=2)
            self.status_label = ttk.Label(self.root, textvariable=self.status, anchor='w', padding=(12, 6))
            self.status_label.pack(fill='x')
            for binding, cmd in [('<Control-n>', self.new), ('<Control-o>', self.open), ('<Control-s>', self.save), ('<Control-l>', self.show_generated_code), ('<Control-Shift-B>', self.toggle_symbols), ('<F5>', self.run), ('<F6>', self.step), ('<Escape>', self.pause), ('<Control-plus>', lambda: self.set_zoom(1.15)), ('<Control-equal>', lambda: self.set_zoom(1.15)), ('<Control-minus>', lambda: self.set_zoom(1 / 1.15)), ('<Control-0>', self.reset_zoom)]:
                self.root.bind(binding, lambda e, c=cmd: c())
            for widget in (self.tree, self.canvas):
                for binding, cmd in [('<Delete>', self.delete), ('<Control-z>', self.undo), ('<Control-y>', self.redo), ('<Control-c>', self.copy), ('<Control-v>', self.paste), ('<Control-x>', self.cut), ('<F9>', self.toggle_breakpoint)]:
                    widget.bind(binding, lambda e, c=cmd: c())

        def toolbar_icon(self, name):
            image = tk.PhotoImage(width=24, height=24, master=self.root)
            def rect(x0, y0, x1, y1, color):
                image.put(color, to=(x0, y0, x1, y1))
            def line(x0, y0, x1, y1, color, thick=2):
                steps = max(abs(x1-x0), abs(y1-y0), 1)
                for i in range(steps+1):
                    x, y = int(x0+(x1-x0)*i/steps), int(y0+(y1-y0)*i/steps)
                    rect(x, y, min(24,x+thick), min(24,y+thick), color)
            if name == 'new':
                rect(5, 2, 19, 22, '#56728f'); rect(7, 4, 17, 20, '#ffffff')
                rect(10, 8, 20, 10, '#3c94df'); rect(14, 4, 16, 14, '#3c94df')
            elif name == 'open':
                rect(2, 6, 11, 10, '#be8b29'); rect(2, 9, 22, 21, '#e7b951'); rect(4, 11, 22, 20, '#f4cb70')
            elif name == 'save':
                rect(3, 3, 21, 22, '#417bac'); rect(7, 3, 17, 10, '#dcebf5'); rect(7, 14, 17, 21, '#ffffff'); rect(14, 4, 16, 9, '#417bac')
            elif name in ('run', 'step'):
                for x in range(5, 18):
                    half = max(1, int((18-x)*0.65))
                    rect(x, 12-half, x+1, 13+half, '#2f974c')
                if name == 'step': rect(19, 4, 22, 21, '#537a9f')
            elif name == 'pause':
                rect(5, 4, 10, 21, '#d4982b'); rect(14, 4, 19, 21, '#d4982b')
            elif name == 'stop': rect(4, 4, 21, 21, '#c85b5b')
            elif name in ('undo', 'redo'):
                def flip(x): return 22-x if name=='redo' else x
                for x0,y0,x1,y1 in [(6,7,15,7),(15,7,19,12),(19,12,19,18),(6,7,10,3),(6,7,10,11)]:
                    line(flip(x0),y0,flip(x1),y1,'#6383a5')
            elif name == 'source':
                for coords in [(8,5,3,12),(3,12,8,19),(16,5,21,12),(21,12,16,19),(14,3,10,21)]: line(*coords, color='#417bac')
            elif name == 'console':
                rect(2, 3, 23, 21, '#526b83'); rect(4, 6, 21, 19, '#ffffff')
                line(6,9,9,12,'#319252'); line(9,12,6,15,'#319252'); rect(12,14,18,16,'#526b83')
            return image

        def tooltip(self, widget, text):
            state = {'timer': None, 'window': None}
            def hide(event=None):
                if state['timer'] is not None:
                    try:
                        self.root.after_cancel(state['timer'])
                    except tk.TclError:
                        pass
                    state['timer'] = None
                if state['window'] is not None:
                    window, state['window'] = state['window'], None
                    try:
                        window.destroy()
                    except tk.TclError:
                        pass
            def show():
                state['timer'] = None
                if not widget.winfo_exists():
                    return
                win = state['window'] = tk.Toplevel(self.root)
                win.wm_overrideredirect(True)
                tk.Label(win, text=text, bg='#fffde9', fg='#253247', padx=8, pady=4,
                         wraplength=480, justify='left', relief='solid', borderwidth=1).pack()
                win.update_idletasks()
                width, height = win.winfo_reqwidth(), win.winfo_reqheight()
                x = min(widget.winfo_rootx(), max(10, self.root.winfo_screenwidth()-width-10))
                y = widget.winfo_rooty()+widget.winfo_height()+5
                if y+height > self.root.winfo_screenheight()-10:
                    y = widget.winfo_rooty()-height-5
                win.geometry('+%d+%d' % (max(10, x), max(10, y)))
            def later(event):
                hide(); state['timer'] = self.root.after(550, show)
            widget.bind('<Enter>', later, add='+')
            widget.bind('<Leave>', hide, add='+')
            widget.bind('<ButtonPress>', hide, add='+')
            widget.bind('<Destroy>', lambda e: hide() if e.widget is widget else None, add='+')

        def show_generated_code(self):
            self.show_tools(0)
            if not self.sync_source():
                return False
            self.update_code()
            if self.source is None:
                self.status.set('Cannot generate ' + self.language.get() + ' code. See the error in the code panel.')
                return False
            self.status.set('Generated ' + self.language.get() + ' code. Use Copy or Export to save it.')
            return True

        def show_tools(self, tab=0, toggle=False):
            if toggle and self.tools_visible and self.notebook.index('current') == tab:
                self.hide_tools()
                return
            if not self.tools_visible:
                self.panes.add(self.right_panel, weight=2)
                self.tools_visible = True
                self.root.update_idletasks()
                self.panes.sashpos(len(self.panes.panes())-2, max(350, self.panes.winfo_width()-430))
            self.notebook.select(tab)
            if tab == 0:
                self.code.focus_set()

        def hide_tools(self):
            if self.tools_visible:
                self.panes.forget(self.right_panel)
                self.tools_visible = False

        def toggle_symbols(self):
            if self.symbols_visible:
                self.panes.forget(self.left_panel)
            else:
                self.panes.insert(0, self.left_panel, weight=0)
                self.root.update_idletasks()
                self.panes.sashpos(0, 270)
            self.symbols_visible = not self.symbols_visible

        def resize_canvas(self, event=None):
            if hasattr(self, 'tree') and self.tree.get_children():
                self.draw()

        def import_source(self):
            path = filedialog.askopenfilename(parent=self.root, title='Import source code',
                filetypes=[('Python', '*.py'), ('All supported source files', '*')])
            if not path:
                return
            language = detect_language(path)
            if not language:
                messagebox.showerror('Unknown source language', 'Choose a supported source file, or paste code into the Generated code panel.', parent=self.root)
                return
            try:
                with open(path, 'r', encoding='utf-8-sig') as stream:
                    text = stream.read()
                document = parse_code(language, text, os.path.splitext(os.path.basename(path))[0])
                if not self.check_discard():
                    return
                self.replace_doc(document)
                self.language.set(language)
                self.update_code()
                self.show_tools(0)
                self.status.set('Imported ' + os.path.basename(path))
            except Exception as exc:
                messagebox.showerror('Import failed', str(exc), parent=self.root)

        def render_palette(self, *unused):
            """Canvas-based palette: clicking and dragging have no ttk.Button conflict."""
            if not hasattr(self, 'palette'):
                return
            for child in self.palette.winfo_children():
                child.destroy()
            query = self.palette_filter.get().strip().lower()
            visible = [kind for kind in KINDS if query in kind.lower()]
            if not visible:
                ttk.Label(self.palette, text='No matching symbols').grid(row=0, column=0)
                return
            for i, kind in enumerate(visible):
                tile = tk.Canvas(self.palette, height=71, width=115, bg='#ffffff',
                                 highlightbackground='#cbd5e1', highlightthickness=1,
                                 cursor='hand2', relief='flat')
                tile.grid(row=i // 2, column=i % 2, padx=3, pady=3, sticky='ew')
                center = 57
                fill = {'If':'#fef3c7','For':'#ffedd5', 'While':'#fef3c7',
                        'Do':'#fef3c7','Input':'#dcfce7','Output':'#dcfce7',
                        'Call':'#f3e8ff','Return':'#f3e8ff'}.get(kind,'#dbeafe')
                if kind in ('If','While','Do'):
                    tile.create_polygon(center,5,99,26,center,47,15,26,
                                        fill=fill,outline='#334155',width=2)
                elif kind == 'For':
                    tile.create_polygon(23,8,91,8,100,26,91,44,23,44,14,26,
                                        fill=fill,outline='#334155',width=2)
                elif kind in ('Input','Output'):
                    tile.create_polygon(24,8,102,8,90,44,12,44,
                                        fill=fill,outline='#334155',width=2)
                elif kind in ('Call','Return'):
                    tile.create_rectangle(15,8,101,44,fill=fill,outline='#334155',width=2)
                    tile.create_line(23,8,23,44,fill='#334155')
                    tile.create_line(93,8,93,44,fill='#334155')
                else:
                    tile.create_rectangle(14,8,101,44,fill=fill,outline='#334155',width=2)
                tile.create_text(center,57,text=kind,fill='#0f172a',
                                 font=(self.ui_font,9,'bold'))
                tile.bind('<ButtonPress-1>',lambda e,k=kind:self.palette_drag_start(e,k))
                tile.bind('<B1-Motion>',self.palette_drag_motion)
                tile.bind('<ButtonRelease-1>',lambda e,k=kind:self.palette_drag_release(e,k))
                tile.bind('<Enter>',lambda e,w=tile:w.configure(highlightbackground='#3b82f6'))
                tile.bind('<Leave>',lambda e,w=tile:w.configure(highlightbackground='#cbd5e1'))
                self.tooltip(tile, symbol_help_text(kind, self.doc.get('python', False)))
            for col in range(2):
                self.palette.grid_columnconfigure(col,weight=1)

        def toggle_theme(self):
            """Toggle a restrained light/dark editor theme without changing the document."""
            self.dark_theme = not self.dark_theme
            style = ttk.Style(self.root)
            try:
                style.theme_use('clam')
            except tk.TclError:
                pass
            if self.dark_theme:
                bg, panel, fg, field, select = '#17212f', '#202c3b', '#e5edf6', '#111a26', '#36516f'
                canvas_bg, code_bg, code_fg = '#111a26', '#111a26', '#dbeafe'
            else:
                bg, panel, fg, field, select = '#f1f3f6', '#ffffff', '#1f2937', '#ffffff', '#cfe3ff'
                canvas_bg, code_bg, code_fg = '#ffffff', '#ffffff', '#183452'
            self.root.configure(background=bg)
            style.configure('.', background=bg, foreground=fg)
            style.configure('TFrame', background=bg)
            style.configure('TLabel', background=bg, foreground=fg)
            style.configure('TButton', background=panel, foreground=fg, padding=(7, 4))
            style.configure('TEntry', fieldbackground=field, foreground=fg)
            style.configure('TCombobox', fieldbackground=field, foreground=fg, background=panel)
            style.configure('Treeview', background=field, fieldbackground=field, foreground=fg, rowheight=24)
            style.configure('Treeview.Heading', background=panel, foreground=fg)
            style.map('Treeview', background=[('selected', select)], foreground=[('selected', fg)])
            self.canvas.configure(background=canvas_bg)
            self.code.configure(background=code_bg, foreground=code_fg, insertbackground=fg)
            self.console.configure(background=field, foreground=fg, insertbackground=fg)
            self.status_label.configure(background=panel, foreground=fg)
            self.draw()
            self.status.set('Dark theme enabled.' if self.dark_theme else 'Light theme enabled.')

        def reset_zoom(self):
            self.zoom = 1.0
            self.draw()
            self.status.set('Diagram zoom reset to 100%.')

        def fit_diagram(self):
            """Scale the current diagram to fit the visible canvas area."""
            self.root.update_idletasks()
            width = max(100, self.canvas.winfo_width() - 36)
            height = max(100, self.canvas.winfo_height() - 36)
            old_zoom = self.zoom
            self.zoom = 1.0
            self.draw()
            bounds = self.canvas.bbox('all')
            if not bounds:
                return
            diagram_width = max(1, bounds[2] - bounds[0])
            diagram_height = max(1, bounds[3] - bounds[1])
            factor = min(float(width) / diagram_width, float(height) / diagram_height, 2.2)
            self.zoom = max(0.4, min(2.2, factor))
            self.draw()
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)
            self.status.set('Diagram fitted to window (previous zoom {0:.0f}%).'.format(old_zoom * 100))

        def state(self):
            return json.dumps(self.doc, sort_keys=True)

        def source_modified(self):
            return (self.source is not None and self.code_language in TWO_WAY and
                    self.code.get('1.0', 'end-1c').rstrip() != self.source.rstrip())

        def sync_source(self):
            if self.source_modified() or self.code_timer is not None:
                if not self.apply_code():
                    self.show_tools(0)
                    self.status.set('Fix the source error or use Reset before continuing.')
                    return False
            return True

        def modified(self):
            return self.state() != self.saved_state or self.source_modified()

        def remember(self):
            self.stop()
            self.undo_stack.append(copy.deepcopy(self.doc))
            self.undo_stack = self.undo_stack[-100:]
            self.redo_stack = []
            self.breakpoints.clear()

        def undo(self):
            if self.undo_stack:
                self.stop()
                self.redo_stack.append(copy.deepcopy(self.doc))
                self.doc = self.undo_stack.pop()
                self.breakpoints.clear()
                self.refresh()

        def redo(self):
            if self.redo_stack:
                self.stop()
                self.undo_stack.append(copy.deepcopy(self.doc))
                self.doc = self.redo_stack.pop()
                self.breakpoints.clear()
                self.refresh()

        def refresh(self, select_node=None, keep_code=False):
            self.function_index = min(self.function_index, len(self.doc['functions']) - 1)
            self.function_box.configure(values=[f['name'] for f in self.doc['functions']])
            self.function_var.set(self.doc['functions'][self.function_index]['name'])
            self.root.title((' *' if self.modified() else '') + self.doc['name'] + ' - Flowchart Studio')
            for iid in self.tree.get_children():
                self.tree.delete(iid)
            self.mapping = {}
            self.node_iids = {}
            body = self.doc['functions'][self.function_index]['body']
            def add_block(parent, title, block):
                iid = self.tree.insert(parent, 'end', text=title, open=True)
                self.mapping[iid] = ('block', block, None)
                for i, n in enumerate(block):
                    ni = self.tree.insert(iid, 'end', text=n['kind'] + ': ' + label(n)[:60], open=True)
                    self.mapping[ni] = ('node', block, i)
                    self.node_iids[id(n)] = ni
                    for b in BRANCHES.get(n['kind'], []):
                        add_block(ni, b.title(), n[b])
                return iid
            rootid = add_block('', 'Function body', body)
            self.tree.selection_set(self.node_iids.get(id(select_node), rootid))
            self.draw()
            if not keep_code:
                self.update_code()
                self.show_tools(0)

        def selection(self):
            items = self.tree.selection()
            return self.mapping.get(items[0]) if items else None

        def selected_node(self):
            s = self.selection()
            return s[1][s[2]] if s and s[0] == 'node' else None

        def location(self):
            s = self.selection()
            if s is None:
                body = self.doc['functions'][self.function_index]['body']
                return body, len(body)
            return (s[1], s[2] + 1) if s[0] == 'node' else (s[1], len(s[1]))

        def add_shape(self, kind):
            insertion_doc = self.doc if self.pending_insert is not None else None
            if not self.sync_source():
                return
            if insertion_doc is not None and self.doc is not insertion_doc:
                self.status.set('The diagram was updated from source. Hover over a connector to choose the insertion point again.')
                return
            self.pause()
            insertion = self.pending_insert
            self.pending_insert = None  # canceled dialogs cannot leave stale targets
            d = ShapeDialog(self.root, node(kind), self.doc.get('python', False))
            if d.result is not None:
                if insertion is not None:
                    block, idx = insertion
                else:
                    block, idx = self.location()
                self.remember()
                block.insert(idx, d.result)
                self.refresh(d.result)

        def edit_shape(self):
            if not self.sync_source():
                return
            n = self.selected_node()
            if n is None:
                return
            if n.get('python_definition'):
                self.function_index = next(i for i, f in enumerate(self.doc['functions']) if f['name']==n['python_definition'])
                self.refresh()
                self.edit_function()
                return
            self.pause()
            d = ShapeDialog(self.root, n, self.doc.get('python', False))
            if d.result is not None:
                self.remember()
                n.clear()
                n.update(d.result)
                self.refresh(n)

        def delete(self):
            if not self.sync_source():
                return
            s = self.selection()
            if s and s[0] == 'node':
                self.remember()
                del s[1][s[2]]
                self.refresh()

        def copy(self):
            n = self.selected_node()
            if n:
                self.clipboard = copy.deepcopy(n)
                self.status.set('Shape and its nested blocks copied.')

        def cut(self):
            self.copy()
            self.delete()

        def paste(self):
            if not self.sync_source():
                return
            if self.clipboard:
                block, idx = self.location()
                self.remember()
                n = copy.deepcopy(self.clipboard)
                block.insert(idx, n)
                self.refresh(n)

        def move(self, delta):
            if not self.sync_source():
                return
            s = self.selection()
            if s and s[0] == 'node':
                block, i = s[1], s[2]
                if 0 <= i + delta < len(block):
                    self.remember()
                    n = block.pop(i)
                    block.insert(i + delta, n)
                    self.refresh(n)

        def switch_function(self, event=None):
            name = self.function_var.get()
            if not self.sync_source():
                self.function_var.set(self.doc['functions'][self.function_index]['name'])
                return
            self.function_index = next(i for i, f in enumerate(self.doc['functions']) if f['name'] == name)
            self.refresh()

        def add_function(self):
            if not self.sync_source():
                return
            f = {'name': 'MyFunction', 'type': 'None', 'variable': '', 'parameters': [], 'body': []}
            d = FunctionDialog(self.root, f, self.doc.get('python', False))
            if d.result is not None:
                if any(x['name'] == d.result['name'] for x in self.doc['functions']):
                    messagebox.showerror('Function', 'That name already exists.', parent=self.root)
                    return
                self.remember()
                self.doc['functions'].append(d.result)
                self.function_index = len(self.doc['functions']) - 1
                self.refresh()

        def edit_function(self):
            if not self.sync_source():
                return
            if self.function_index == 0:
                messagebox.showinfo('Main', 'Main has no parameters or return type.', parent=self.root)
                return
            f = self.doc['functions'][self.function_index]
            d = FunctionDialog(self.root, f, self.doc.get('python', False))
            if d.result is not None:
                if any(x is not f and x['name'] == d.result['name'] for x in self.doc['functions']):
                    messagebox.showerror('Function', 'That name already exists.', parent=self.root)
                    return
                self.remember()
                self.doc['functions'][self.function_index] = d.result
                if self.doc.get('python'):
                    for function in self.doc['functions']:
                        for marker in walk(function['body']):
                            if marker.get('python_definition') == f['name']:
                                marker['python_definition'] = d.result['name']
                                marker['text'] = 'Define ' + d.result['name']
                self.refresh()
                self.status.set('Function changed. Update call expressions if you renamed it.')

        def delete_function(self):
            if not self.sync_source():
                return
            if self.function_index == 0:
                return
            if messagebox.askyesno('Delete function', 'Delete this function and its entire body?', parent=self.root):
                self.remember()
                removed = self.doc['functions'].pop(self.function_index)['name']
                if self.doc.get('python'):
                    for function in self.doc['functions']:
                        for marker in walk(function['body']):
                            if marker.get('python_definition') == removed:
                                del marker['python_definition']
                                marker['text'] = 'Removed function ' + removed
                self.function_index = 0
                self.refresh()

        def check_discard(self):
            if not self.sync_source():
                if not messagebox.askyesno('Unapplied source',
                    'The source contains an error and cannot be saved as a chart. Discard the unapplied text?', parent=self.root):
                    return False
                self.update_code()
            if not self.modified():
                return True
            answer = messagebox.askyesnocancel('Unsaved chart', 'Save your changes first?', parent=self.root)
            if answer is None:
                return False
            if answer:
                return self.save()
            return True

        def replace_doc(self, d, path=None):
            self.stop()
            self.doc = d
            self.path = path
            self.saved_state = self.state()
            self.undo_stack, self.redo_stack = [], []
            self.function_index = 0
            self.breakpoints.clear()
            self.refresh()

        def new(self):
            if self.check_discard():
                self.replace_doc(empty_document())

        def example(self):
            if self.check_discard():
                self.replace_doc(sample_document())

        def open(self):
            if not self.check_discard():
                return
            path = filedialog.askopenfilename(parent=self.root, filetypes=[('Editable flowcharts (JSON)', '*.json'), ('All files', '*')])
            if path:
                try:
                    self.replace_doc(load_document(path), path)
                except Exception as e:
                    messagebox.showerror('Open failed', str(e), parent=self.root)

        def save(self, saveas=False):
            if not self.sync_source():
                return False
            path = self.path
            # Keep PDF as presentation/export and JSON as editable source.
            # Legacy imported charts must not silently save to .fprg.
            if path and os.path.splitext(path)[1].lower() != '.json':
                path = None
            if saveas or not path:
                path = filedialog.asksaveasfilename(parent=self.root, defaultextension='.json', initialfile=self.doc['name'] + '.json', filetypes=[('Editable flowchart (JSON)', '*.json')])
            if not path:
                return False
            try:
                save_document(self.doc, path)
                self.path = path
                self.saved_state = self.state()
                self.root.title(self.doc['name'] + ' - Flowchart Studio')
                self.status.set('Saved: ' + path)
                return True
            except Exception as e:
                messagebox.showerror('Save failed', str(e), parent=self.root)
                return False

        def update_code(self):
            """Regenerate the source panel from the chart (chart -> code)."""
            if self.code_timer is not None:
                self.root.after_cancel(self.code_timer)
                self.code_timer = None
            lang = self.language.get()
            self.code_language = lang
            try:
                self.source = GENERATORS[lang](lang).generate(self.doc)
                text = self.source
                error = None
            except Exception as e:
                self.source = None
                text = 'SOURCE NOT GENERATED\n\n' + str(e) + '\n\nSee Help > Capabilities for limitations.'
                error = str(e)
            editable = lang in TWO_WAY and self.source is not None
            self.code_busy = True
            self.code.configure(state='normal')
            self.code.delete('1.0', 'end')
            self.code.insert('1.0', text)
            self.code.edit_reset()
            self.code.edit_modified(False)
            self.code.configure(state='normal' if editable else 'disabled')
            self.code_busy = False
            if error:
                self.code_status.set('Cannot generate ' + lang + ': ' + error)
                self.status.set('Cannot generate ' + lang + ': ' + error)
            elif editable:
                self.code_status.set('Editable: changes here update the flowchart.')
            else:
                self.code_status.set('Read-only. Choose Python or Pseudocode to edit the code and change the flowchart.')

        def language_changed(self, event=None):
            if not self.sync_source():
                self.language.set(self.code_language)
                return
            self.update_code()

        def code_modified(self, event=None):
            if self.code_busy or not self.code.edit_modified():
                return
            self.code.edit_modified(False)
            if self.language.get() not in TWO_WAY:
                return
            if self.code_timer is not None:
                self.root.after_cancel(self.code_timer)
            self.code_status.set('Typing...')
            self.code_timer = self.root.after(700, self.apply_code)

        def apply_code(self, quiet=False):
            """Parse the edited source and replace the flowchart (code -> chart)."""
            if self.code_timer is not None:
                self.root.after_cancel(self.code_timer)
                self.code_timer = None
            lang = self.code_language
            if lang not in TWO_WAY:
                return False
            text = self.code.get('1.0', 'end-1c')
            try:
                newdoc = parse_code(lang, text, self.doc['name'])
            except FlowError as e:
                self.code_status.set('Not applied - ' + str(e))
                return False
            except Exception as e:
                self.code_status.set('Not applied - ' + type(e).__name__ + ': ' + str(e))
                return False
            if json.dumps(newdoc, sort_keys=True) == self.state():
                self.source = text
                self.code_status.set('In sync with the flowchart.')
                return True
            current = self.doc['functions'][self.function_index]['name']
            self.remember()
            self.doc = newdoc
            self.function_index = 0
            for i, f in enumerate(newdoc['functions']):
                if f['name'] == current:
                    self.function_index = i
            self.source = text
            self.refresh(keep_code=True)
            self.code_status.set('Applied: the flowchart now matches the code.' + (' Note: ' + '; '.join(LAST_WARNINGS) if LAST_WARNINGS else ''))
            self.status.set('Flowchart updated from edited ' + lang + ' code.')
            return True

        def shown_source(self):
            if self.language.get() in TWO_WAY and self.source is not None:
                return self.code.get('1.0', 'end-1c') + '\n'
            return self.source

        def copy_code(self):
            text = self.shown_source()
            if text is None:
                messagebox.showerror('No source', 'Resolve the generation error before copying.', parent=self.root)
                return
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status.set('Source copied.')

        def export_code(self):
            if not self.sync_source():
                return
            if self.language.get() not in TWO_WAY:
                self.update_code()
            text = self.shown_source()
            if text is None:
                messagebox.showerror('Export blocked', 'This chart cannot be exported to the selected language. See the live source panel.', parent=self.root)
                return
            extension = GENERATORS[self.language.get()].ext
            filename = 'main' + extension
            if self.language.get() == 'Java':
                filename = 'Main.java'
            path = filedialog.asksaveasfilename(parent=self.root, initialfile=filename, defaultextension=extension)
            if path:
                try:
                    with open(path, 'w', encoding='utf-8') as h:
                        h.write(text)
                    self.status.set('Exported ' + self.language.get() + ' source: ' + path)
                except Exception as e:
                    messagebox.showerror('Export failed', str(e), parent=self.root)

        def convert_dialog(self):
            """Translate code from any supported language to any other, through the flowchart model."""
            win = tk.Toplevel(self.root)
            win.title('Convert code between languages')
            win.geometry('1150x680')
            src_lang = tk.StringVar(value=self.language.get())
            dst_lang = tk.StringVar(value='Java' if self.language.get() != 'Java' else 'Python')
            msg = tk.StringVar(value='Paste code on the left, choose the languages, and press Convert.')
            top = ttk.Frame(win, padding=6)
            top.pack(fill='x')
            ttk.Label(top, text='From:').pack(side='left')
            ttk.Combobox(top, textvariable=src_lang, values=LANGUAGES, state='readonly', width=14).pack(side='left', padx=4)
            ttk.Label(top, text='To:').pack(side='left', padx=(10, 0))
            ttk.Combobox(top, textvariable=dst_lang, values=LANGUAGES, state='readonly', width=14).pack(side='left', padx=4)
            panes = ttk.PanedWindow(win, orient='horizontal')
            panes.pack(fill='both', expand=True, padx=6, pady=4)
            left = tk.Text(panes, wrap='none', font=('Courier', 10), undo=True, tabs=('1c',))
            right = tk.Text(panes, wrap='none', font=('Courier', 10), bg='#192535', fg='#d8e8f6')
            panes.add(left, weight=1)
            panes.add(right, weight=1)
            state = {'timer': None}

            def convert(*_):
                if state['timer'] is not None:
                    win.after_cancel(state['timer'])
                    state['timer'] = None
                text = left.get('1.0', 'end-1c')
                right.configure(state='normal')
                right.delete('1.0', 'end')
                if not text.strip():
                    msg.set('Paste code on the left.')
                    return
                try:
                    code, warns = convert_code(src_lang.get(), text, dst_lang.get())
                except FlowError as e:
                    msg.set('Cannot convert: ' + str(e))
                    return
                except Exception as e:
                    msg.set('Cannot convert: ' + type(e).__name__ + ': ' + str(e))
                    return
                right.insert('1.0', code)
                msg.set('Converted ' + src_lang.get() + ' -> ' + dst_lang.get() + '.' + (' Note: ' + '; '.join(warns) if warns else ''))

            def later(event=None):
                if left.edit_modified():
                    left.edit_modified(False)
                    if state['timer'] is not None:
                        win.after_cancel(state['timer'])
                    state['timer'] = win.after(700, convert)

            def swap():
                a, b = src_lang.get(), dst_lang.get()
                text = right.get('1.0', 'end-1c')
                src_lang.set(b)
                dst_lang.set(a)
                if text.strip():
                    left.delete('1.0', 'end')
                    left.insert('1.0', text)
                convert()

            def from_editor():
                src_lang.set(self.language.get())
                left.delete('1.0', 'end')
                left.insert('1.0', self.shown_source() or '')
                convert()

            def to_editor():
                try:
                    doc = parse_code(src_lang.get(), left.get('1.0', 'end-1c'), self.doc['name'])
                except FlowError as e:
                    messagebox.showerror('Cannot open', str(e), parent=win)
                    return
                self.remember()
                self.doc = doc
                self.function_index = 0
                self.refresh()
                self.status.set('Chart replaced by the converted program.')
                win.destroy()

            def copy_result():
                win.clipboard_clear()
                win.clipboard_append(right.get('1.0', 'end-1c'))
                msg.set('Result copied.')

            for text, cmd in [('Convert', convert), ('Swap', swap), ('Take code from editor', from_editor),
                              ('Open as flowchart', to_editor), ('Copy result', copy_result)]:
                ttk.Button(top, text=text, command=cmd).pack(side='left', padx=3)
            ttk.Label(win, textvariable=msg, wraplength=1100, justify='left').pack(fill='x', padx=8, pady=4)
            left.bind('<<Modified>>', later)
            from_editor()

        def capture_diagram_scene(self, name):
            """Snapshot full canvas world coordinates; ignore invisible drop hotspots."""
            cv=self.canvas
            def rgb(value):
                if not value or value == '{}':
                    return None
                try:
                    r,g,b=self.root.winfo_rgb(value)
                    return (r/65535.,g/65535.,b/65535.)
                except tk.TclError:
                    return None
            items=[]
            for obj in cv.find_all():
                tags=cv.gettags(obj)
                if 'drop_hint' in tags or 'connector_halo' in tags or any(t.startswith('insert_at_') for t in tags):
                    continue
                typ=cv.type(obj)
                if typ not in ('line','rectangle','oval','polygon','text'):
                    continue
                coords=[float(x)/self.zoom for x in cv.coords(obj)]
                bbox=cv.bbox(obj)
                if bbox is None:
                    continue
                one={'type':typ,'coords':coords,
                     'bbox':[float(x)/self.zoom for x in bbox]}
                if typ=='text':
                    one['text']=cv.itemcget(obj,'text')
                    one['fill']=rgb(cv.itemcget(obj,'fill'))
                    one['textwidth']=float(cv.itemcget(obj,'width') or 0)/self.zoom
                    font=cv.itemcget(obj,'font')
                    match=re.search(r'(-?[0-9]+)',font)
                    one['fontsize']=abs(float(match.group(1))) / self.zoom if match else 10.
                else:
                    one['fill']=rgb(cv.itemcget(obj,'fill')) if typ!='line' else None
                    one['outline']=rgb(cv.itemcget(obj,'outline')) if typ!='line' else rgb(cv.itemcget(obj,'fill'))
                    one['width']=float(cv.itemcget(obj,'width') or 1)/self.zoom
                    if 'flow_connector' in tags:
                        one['outline']=rgb('#65758a')
                        one['width']=1.5/self.zoom
                    if typ=='line':
                        one['arrow']=cv.itemcget(obj,'arrow')
                items.append(one)
            bb=cv.bbox('all')
            if not bb:
                bb=(0,0,400,600)
            return {'name':name, 'items':items,
                    'bounds':tuple(float(x)/self.zoom for x in bb)}

        def export_diagram(self):
            if not self.sync_source():
                return
            # PDF is for viewing/printing; save editable files as .json.
            pathname=filedialog.asksaveasfilename(parent=self.root,defaultextension='.pdf',
                initialfile=self.doc['name']+'.pdf',filetypes=[('Vector PDF flowchart','*.pdf')])
            if not pathname:
                return
            old_index=self.function_index
            old_selection=self.selected_node()
            old_zoom=self.zoom
            scenes=[]
            try:
                self.pause()
                self.zoom=1.0
                for i,function in enumerate(self.doc['functions']):
                    self.function_index=i
                    self.refresh(keep_code=True)
                    scenes.append(self.capture_diagram_scene(function['name']))
                bytecount,pages=export_vector_flowchart_pdf(scenes,pathname)
                self.status.set('PDF exported: %d complete page(s), %s bytes.' % (pages,format(bytecount,',')))
            except Exception as exc:
                messagebox.showerror('PDF export failed',str(exc),parent=self.root)
            finally:
                self.zoom=old_zoom
                self.function_index=old_index
                self.refresh(select_node=old_selection,keep_code=True)

        def selected_iid(self):
            return self.tree.selection()[0] if self.tree.selection() else None

        def draw(self):
            self.close_shape_picker()
            self.canvas.delete('all')
            self.connector_paths = {}
            self.canvas_hits = {}
            self.insert_hit_targets = {}
            self.drop_sites = []
            z = self.zoom
            if hasattr(self, 'zoom_label'):
                self.zoom_label.set('{0:.0f}%'.format(z*100))
            selected = self.selected_node()
            body = self.doc['functions'][self.function_index]['body']
            # Layout uses recursive subtree widths, keeping nested branches apart.
            def width(block):
                w = 210
                for n in block:
                    if n['kind'] == 'If':
                        w = max(w, width(n['true']) + width(n['false']) + 50)
                    elif n['kind'] in ('While', 'Do', 'For'):
                        w = max(w, width(n['body']) + 90)
                return w
            def line(coords, arrow=True, dash=None, target=None):
                opts = {'fill': '#65758a', 'width': 1.5, 'arrow': 'last' if arrow else 'none'}
                if dash:
                    opts['dash'] = dash
                scaled = [v*z for v in coords]
                if target is not None:
                    block, index = target
                    key = (id(block), index)
                    tag = connector_keys.get(key)
                    if tag is None:
                        tag = 'connector_' + str(len(self.connector_paths)+1)
                        connector_keys[key] = tag
                        self.insert_hit_targets[tag] = (block, index)
                        self.connector_paths[tag] = {'target': (block, index), 'parts': [], 'coords': scaled, 'segments': []}
                    opts['tags'] = ('flow_connector', tag)
                item = self.canvas.create_line(*scaled, **opts)
                if target is not None:
                    record = self.connector_paths[tag]
                    record['parts'].append(item)
                    record['segments'].append(scaled)
                    self.canvas.tag_bind(tag, '<Button-1>', lambda e, t=tag: self.connector_clicked(e, t))
                    self.canvas.tag_bind(tag, '<Button-3>', lambda e, t=tag: self.connector_menu(e, t))
                    self.canvas.tag_bind(tag, '<Double-1>', lambda e, t=tag: self.connector_menu(e, t))
                return item
            connector_keys = {}
            def insert_target(x, y, block, index):
                # Drop sites share the full edge mapping; no tiny overlay line.
                self.drop_sites.append((x*z, y*z, block, index))
            def text(x, y, value, **kwargs):
                self.canvas.create_text(x*z, y*z, text=value, font=(self.ui_font, max(8, int(11*z))), **kwargs)
            def shape(n, x, y, terminal=None):
                k = n['kind'] if n else 'Terminal'
                w, h = 176, 62
                coords = [(x-w/2)*z, y*z, (x+w/2)*z, (y+h)*z]
                color = {'Terminal': '#cce1f7', 'Declare': '#dce9fa', 'Assign': '#fff2bd', 'Input': '#d8efcf', 'Output': '#f5d5d5', 'If': '#fef3c7', 'While': '#fef3c7', 'Do': '#fef3c7', 'For': '#fef3c7', 'Call': '#f3e8ff', 'Return': '#f3e8ff', 'Comment': '#f1f5f9', 'Break': '#fee2e2', 'Continue': '#fee2e2'}.get(k, '#fff')
                outline = '#2b78c8' if n is selected and n is not None else '#526d8d'
                active = n is self.current_node and self.engine is not None
                if active:
                    color, outline = '#ffec99', '#ea580c'
                tags = ()
                if n:
                    iid = self.node_iids.get(id(n))
                    if iid:
                        tags = ('hit_' + iid,)
                        self.canvas_hits[tags[0]] = iid
                opts = {'fill': color, 'outline': outline,
                        'width': max(2.5,3.5*z) if active else (3 if n is selected else 1.5),
                        'tags': tags}
                # Tk Canvas has no blurred shadow. Concentric, matching contours
                # create a bright whole-border halo without substituting an oval
                # for a hexagon, diamond or parallelogram.
                def glow_polygon(*points, **options):
                    if active:
                        for glow_width, glow_color in ((13,'#fed7aa'),(8,'#fb923c')):
                            halo = dict(options)
                            halo.update(fill='',outline=glow_color,width=glow_width*z,tags=())
                            self.canvas.create_polygon(*points,**halo)
                    return self.canvas.create_polygon(*points,**options)
                def glow_rectangle(*points, **options):
                    if active:
                        for glow_width,glow_color in ((13,'#fed7aa'),(8,'#fb923c')):
                            halo=dict(options)
                            halo.update(fill='',outline=glow_color,width=glow_width*z,tags=())
                            self.canvas.create_rectangle(*points,**halo)
                    return self.canvas.create_rectangle(*points,**options)
                def glow_oval(*points, **options):
                    if active:
                        for glow_width,glow_color in ((13,'#fed7aa'),(8,'#fb923c')):
                            halo=dict(options)
                            halo.update(fill='',outline=glow_color,width=glow_width*z,tags=())
                            self.canvas.create_oval(*points,**halo)
                    return self.canvas.create_oval(*points,**options)
                if k == 'If':
                    # Decision: classic diamond.
                    glow_polygon(x*z, y*z, (x+w/2)*z, (y+h/2)*z,
                                               x*z, (y+h)*z, (x-w/2)*z, (y+h/2)*z, **opts)
                elif k == 'For':
                    # For-loop initialization/step: a distinct preparation hexagon.
                    glow_polygon((x-w/2+17)*z, y*z, (x+w/2-17)*z, y*z,
                                               (x+w/2)*z, (y+h/2)*z,
                                               (x+w/2-17)*z, (y+h)*z,
                                               (x-w/2+17)*z, (y+h)*z,
                                               (x-w/2)*z, (y+h/2)*z, **opts)
                elif k in ('While', 'Do'):
                    # Loop condition: diamond with an inset loop marker.
                    glow_polygon(x*z, y*z, (x+w/2)*z, (y+h/2)*z,
                                               x*z, (y+h)*z, (x-w/2)*z, (y+h/2)*z, **opts)
                elif k in ('Input', 'Output'):
                    # I/O: parallelogram.
                    glow_polygon((x-w/2+16)*z, y*z, (x+w/2)*z, y*z,
                                               (x+w/2-16)*z, (y+h)*z, (x-w/2)*z, (y+h)*z, **opts)
                elif k == 'Terminal':
                    # Start/end: pill-shaped terminal.
                    glow_oval(*coords, **opts)
                elif k == 'Declare':
                    # Declaration: process rectangle with a left accent rail.
                    glow_rectangle(*coords, **opts)
                    self.canvas.create_line((x-w/2+7)*z, (y+8)*z, (x-w/2+7)*z, (y+h-8)*z,
                                            fill=outline, width=2)
                elif k == 'Call':
                    glow_rectangle(*coords, **opts)
                    self.canvas.create_line((x-w/2+10)*z, y*z, (x-w/2+10)*z, (y+h)*z,
                                            fill=outline, width=2)
                    self.canvas.create_line((x+w/2-10)*z, y*z, (x+w/2-10)*z, (y+h)*z,
                                            fill=outline, width=2)
                elif k == 'Return':
                    glow_polygon((x-w/2+14)*z, y*z, (x+w/2-14)*z, y*z,
                                               (x+w/2)*z, (y+h/2)*z,
                                               (x+w/2-14)*z, (y+h)*z,
                                               (x-w/2+14)*z, (y+h)*z,
                                               (x-w/2)*z, (y+h/2)*z, **opts)
                elif k in ('Break', 'Continue'):
                    glow_polygon((x-w/2+12)*z, y*z, (x+w/2)*z, y*z,
                                               (x+w/2-12)*z, (y+h)*z, (x-w/2)*z, (y+h)*z, **opts)
                else:
                    glow_rectangle(*coords, **opts)
                caption = terminal if terminal else label(n)
                if len(caption) > 100:
                    caption = caption[:97] + '...'
                text(x, y+h/2, caption, width=150*z, tags=tags, fill='#183452')
                if n and id(n) in self.breakpoints:
                    self.canvas.create_oval((x-w/2-15)*z, (y+5)*z, (x-w/2-3)*z, (y+17)*z, fill='#dc2626', outline='')
                return y+h
            def block_draw(block, x, y, block_iid):
                if not block:
                    tag = 'hit_' + block_iid
                    self.canvas_hits[tag] = block_iid
                    line([x, y, x, y+35], target=(block, 0))
                    insert_target(x, y+18, block, 0)
                    line([x, y+35, x, y+58], False, target=(block, 0))
                    self.canvas.create_oval((x-10)*z, (y+38)*z, (x+10)*z, (y+58)*z, fill='white', outline='#94a3b8', tags=(tag,))
                    text(x, y+48, '+', tags=(tag,))
                    line([x, y+58, x, y+80], target=(block, 0))
                    return y+80
                for sequence_index, n in enumerate(block):
                    if n['kind'] == 'Do':
                        insert_target(x, y+12, block, sequence_index)
                        ni = self.node_iids[id(n)]
                        child = self.tree.get_children(ni)[0]
                        entry_y = y + 25
                        line([x, y, x, entry_y], target=(block, sequence_index))
                        text(x+55, entry_y-5, 'Do body', fill='#7c3aed')
                        by = block_draw(n['body'], x, entry_y, child)
                        line([x, by, x, by+25], target=(n['body'], len(n['body'])))
                        top = by+25
                        bottom = shape(n, x, top)
                        loopx = x-width(n['body'])/2-35
                        line([x-88, top+31, loopx, top+31, loopx, entry_y, x, entry_y], target=(n['body'], 0))
                        text(loopx+22, top+16, 'True', fill='#15803d')
                        text(x+30, bottom+14, 'False', fill='#b91c1c')
                        y = bottom+25
                        line([x, bottom, x, y], target=(block, sequence_index+1))
                        continue
                    line([x, y, x, y+25], target=(block, sequence_index))
                    if n is self.current_node and self.engine is not None:
                        self.canvas.create_line(x*z,y*z,x*z,(y+25)*z,fill='#fb923c',width=max(3,5*z),arrow='last')
                    insert_target(x, y+12, block, sequence_index)
                    y += 25
                    top = y
                    y = shape(n, x, y)
                    ni = self.node_iids[id(n)]
                    children = self.tree.get_children(ni)
                    if n['kind'] == 'If':
                        wl, wr = width(n['true']), width(n['false'])
                        lx, rx = x-(wr/2+25), x+(wl/2+25)
                        line([x-88, top+31, lx, top+31, lx, y+20], target=(n['true'], 0))
                        line([x+88, top+31, rx, top+31, rx, y+20], target=(n['false'], 0))
                        text(lx, y+8, 'True', fill='#15803d')
                        text(rx, y+8, 'False', fill='#b91c1c')
                        ly = block_draw(n['true'], lx, y+20, children[0])
                        ry = block_draw(n['false'], rx, y+20, children[1])
                        y = max(ly, ry)+25
                        line([lx, ly, lx, y, x, y], False, target=(n['true'], len(n['true'])))
                        line([rx, ry, rx, y, x, y], False, target=(n['false'], len(n['false'])))
                    elif n['kind'] in ('While', 'For'):
                        text(x+28, y+12, 'True / body', fill='#15803d')
                        start = y
                        line([x, y, x, y+25], target=(n['body'], 0))
                        by = block_draw(n['body'], x, y+25, children[0])
                        bw = width(n['body'])/2+25
                        line([x, by, x, by+18, x-bw, by+18, x-bw, top+31, x-88, top+31], target=(n['body'], len(n['body'])))
                        outx = x+bw+20
                        line([x+88, top+31, outx, top+31, outx, by+35, x, by+35], False, target=(block, sequence_index+1))
                        text(outx-20, top+18, 'False', fill='#b91c1c')
                        y = by+35
                # Allow insertion after the last node as well as before nodes.
                insert_target(x, y+12, block, len(block))
                return y
            total_width = width(body)
            x = max(total_width/2+80, self.canvas.winfo_width()/(2*z))
            y = shape(None, x, 25, self.function_var.get())
            rootid = self.tree.get_children()[0]
            y = block_draw(body, x, y, rootid)
            line([x, y, x, y+30], target=(body, len(body)))
            shape(None, x, y+30, 'End')
            bounds = self.canvas.bbox('all')
            if bounds:
                self.canvas.configure(scrollregion=(min(0,bounds[0]-30), 0, max(self.canvas.winfo_width(),bounds[2]+30), max(self.canvas.winfo_height(),bounds[3]+30)))

        def palette_drag_start(self, event, kind):
            self.close_shape_picker()
            self.palette_drag_kind = kind
            self.palette_drag_origin = (event.x_root, event.y_root)
            self.palette_drag_moved = False
            self._cancel_drag_poll()

        def _cancel_drag_poll(self):
            if self.drag_poll is not None:
                try:
                    self.root.after_cancel(self.drag_poll)
                except tk.TclError:
                    pass
                self.drag_poll = None

        def _clear_drag_preview(self):
            self._cancel_drag_poll()
            if self.drag_preview is not None:
                try:
                    self.drag_preview.destroy()
                except tk.TclError:
                    pass
                self.drag_preview = None
            self.canvas.delete('drop_hint')

        def _over_diagram(self, root_x, root_y):
            # Root-coordinate geometry is reliable even while Tk has grabbed
            # the pressed palette tile and even with a drag-ghost on top.
            return (self.canvas.winfo_rootx() <= root_x < self.canvas.winfo_rootx()+self.canvas.winfo_width()
                    and self.canvas.winfo_rooty() <= root_y < self.canvas.winfo_rooty()+self.canvas.winfo_height())

        def _nearest_drop(self, root_x, root_y):
            if not self._over_diagram(root_x, root_y):
                return None
            cx = self.canvas.canvasx(root_x - self.canvas.winfo_rootx())
            cy = self.canvas.canvasy(root_y - self.canvas.winfo_rooty())
            tag = self._connector_at(cx, cy)
            if tag is not None:
                block, index = self.connector_paths[tag]['target']
                return (cx, cy, block, index)
            if not self.drop_sites:
                return None
            return min(self.drop_sites,
                       key=lambda site:(site[0]-cx)**2+(site[1]-cy)**2)

        def _update_drag_preview(self):
            if not self.palette_drag_kind:
                self._clear_drag_preview()
                return
            rx, ry = self.root.winfo_pointerxy()
            if self.drag_preview is not None:
                try:
                    self.drag_preview.geometry('+%d+%d' % (rx+18,ry+18))
                except tk.TclError:
                    pass
            self.canvas.delete('drop_hint')
            site = self._nearest_drop(rx,ry)
            if site is not None:
                cx, cy = site[0], site[1]
                self.canvas.create_oval(cx-16,cy-16,cx+16,cy+16,
                    fill='#fde68a',outline='#f97316',width=3,tags=('drop_hint',))
                self.canvas.create_text(cx,cy,text='+',fill='#9a3412',
                    font=(self.ui_font,15,'bold'),tags=('drop_hint',))
            self.drag_poll = self.root.after(45,self._update_drag_preview)

        def palette_drag_motion(self, event):
            if self.palette_drag_origin and self.palette_drag_kind:
                dx = event.x_root-self.palette_drag_origin[0]
                dy = event.y_root-self.palette_drag_origin[1]
                if dx*dx+dy*dy >= 64 and not self.palette_drag_moved:
                    self.palette_drag_moved = True
                    ghost = tk.Toplevel(self.root)
                    ghost.overrideredirect(True)
                    ghost.configure(bg='#1e293b')
                    tk.Label(ghost,text='  +  '+self.palette_drag_kind+'  ',
                             bg='#1e293b',fg='#ffffff',padx=12,pady=9,
                             font=(self.ui_font,10,'bold')).pack()
                    self.drag_preview = ghost
                    self.status.set('Release on a connector or branch to insert '+self.palette_drag_kind)
                    self._update_drag_preview()

        def global_drag_release(self, event):
            # Fallback for platforms that route the release outside the tile.
            if self.palette_drag_kind is not None:
                self.palette_drag_release(event, self.palette_drag_kind)
            self.canvas_drag_iid = None
            self.canvas_drag_origin = None
            self.canvas_drag_moved = False

        def palette_drag_release(self, event, kind):
            if self.palette_drag_kind is None:
                return
            moved = self.palette_drag_moved
            rx, ry = event.x_root, event.y_root
            site = self._nearest_drop(rx,ry) if moved else None
            self.palette_drag_kind = None
            self.palette_drag_origin = None
            self.palette_drag_moved = False
            self._clear_drag_preview()
            if not moved:
                self.add_shape(kind)
            elif site is None:
                self.status.set('Drag cancelled. Drop onto the flowchart canvas.')
            else:
                self.pending_insert = (site[2],site[3])
                self.add_shape(kind)
            return 'break'

        def _canvas_hit_iid(self, event):
            x = self.canvas.canvasx(event.x)
            y = self.canvas.canvasy(event.y)
            items = self.canvas.find_overlapping(x-3, y-3, x+3, y+3)
            for item in reversed(items):
                for tag in self.canvas.gettags(item):
                    if tag in self.canvas_hits:
                        return self.canvas_hits[tag]
            return None

        def canvas_drag_start(self, event):
            # Record a flowchart node as a possible drag source; palette drags
            # take precedence and are handled on release below.
            if self.palette_drag_kind:
                return
            iid = self._canvas_hit_iid(event)
            if iid and iid in self.mapping and self.mapping[iid][0] == 'node':
                self.canvas_drag_iid = iid
                self.canvas_drag_origin = (event.x_root, event.y_root)
                self.canvas_drag_moved = False

        def canvas_drag_motion(self, event):
            if self.canvas_drag_iid and self.canvas_drag_origin:
                dx = event.x_root - self.canvas_drag_origin[0]
                dy = event.y_root - self.canvas_drag_origin[1]
                if dx * dx + dy * dy > 100:
                    self.canvas_drag_moved = True
                    self.status.set('Drag the block onto another block to change its order.')

        def canvas_drag_drop(self, event):
            # Palette drag/drop: a drop on the diagram opens the normal editor
            # for that shape and inserts it at the selected insertion point.
            if self.palette_drag_kind:
                self.palette_drag_release(event,self.palette_drag_kind)
                return
            # Reorder nodes by dropping on another node in the same sequence.
            if self.canvas_drag_iid and self.canvas_drag_moved:
                source = self.mapping.get(self.canvas_drag_iid)
                target_iid = self._canvas_hit_iid(event)
                target = self.mapping.get(target_iid) if target_iid else None
                if source and target and source[0] == 'node' and target[0] == 'node':
                    src_block, src_index = source[1], source[2]
                    dst_block, dst_index = target[1], target[2]
                    if src_block is dst_block and src_index != dst_index:
                        self.remember()
                        src_block[src_index], src_block[dst_index] = src_block[dst_index], src_block[src_index]
                        self.refresh(src_block[dst_index])
                        self.status.set('Blocks swapped by drag-and-drop.')
                    else:
                        self.status.set('Blocks can be reordered within the same branch.')
            self.canvas_drag_iid = None
            self.canvas_drag_origin = None
            self.canvas_drag_moved = False

        def _cancel_connector_timer(self, attribute):
            timer = getattr(self, attribute, None)
            if timer is not None:
                try:
                    self.root.after_cancel(timer)
                except tk.TclError:
                    pass
                setattr(self, attribute, None)

        def _clear_connector_glow(self):
            try:
                if not self.canvas.winfo_exists():
                    return
            except tk.TclError:
                return
            self.canvas.delete('connector_halo')
            for record in self.connector_paths.values():
                for part in record['parts']:
                    if self.canvas.type(part):
                        self.canvas.itemconfigure(part, fill='#65758a', width=1.5)

        def close_shape_picker(self, clear_hover=True, keep_target=False):
            self._cancel_connector_timer('connector_hover_timer')
            self._cancel_connector_timer('connector_close_timer')
            window = self.shape_picker
            self.shape_picker = None
            if window is not None:
                try:
                    if window.winfo_exists():
                        window.destroy()
                except tk.TclError:
                    pass
            if not keep_target:
                self.pending_insert = None
            if clear_hover:
                self._clear_connector_glow()
                self.hover_connector = None
                self.connector_hover_point = None

        def _connector_distance(self, coords, x, y):
            best = float('inf')
            for offset in range(0, len(coords)-2, 2):
                ax, ay, bx, by = coords[offset:offset+4]
                dx, dy = bx-ax, by-ay
                fraction = max(0.0, min(1.0, ((x-ax)*dx+(y-ay)*dy)/(dx*dx+dy*dy))) if dx or dy else 0.0
                best = min(best, math.hypot(x-(ax+fraction*dx), y-(ay+fraction*dy)))
            return best

        def _connector_at(self, x, y):
            best, distance = None, 8.0
            candidates = list(self.connector_paths)
            if self.hover_connector in candidates:
                candidates.remove(self.hover_connector)
                candidates.insert(0, self.hover_connector)
            for tag in candidates:
                record = self.connector_paths[tag]
                found = min(self._connector_distance(path, x, y) for path in record['segments'])
                if found < distance:
                    best, distance = tag, found
            return best

        def _glow_connector(self, tag):
            self._clear_connector_glow()
            record = self.connector_paths.get(tag)
            if record is None:
                return
            for coords in record['segments']:
                for width, color in ((max(9, 12*self.zoom), '#ffe2ba'), (max(5, 7*self.zoom), '#ffc67d')):
                    item = self.canvas.create_line(*coords, fill=color, width=width,
                                                   capstyle='round', joinstyle='round',
                                                   tags=('connector_halo',))
                    self.canvas.tag_lower(item)
            for part in record['parts']:
                self.canvas.itemconfigure(part, fill='#ef7d00', width=max(2.5, 3*self.zoom))

        def connector_motion(self, event):
            if self.running or self.palette_drag_kind or self.canvas_drag_iid:
                return
            # Actual symbols take precedence over the generous wire hit radius.
            hit = self._canvas_hit_iid(event)
            if hit and self.mapping.get(hit, (None,))[0] == 'node':
                self.connector_leave(event)
                return
            tag = self._connector_at(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
            if tag is None:
                self.connector_leave(event)
                return
            self._cancel_connector_timer('connector_close_timer')
            self.connector_hover_point = (event.x_root, event.y_root)
            if tag == self.hover_connector:
                if self.shape_picker is None and self.connector_hover_timer is None:
                    self.connector_hover_timer = self.root.after(250, lambda t=tag: self._open_hover_picker(t))
                return
            self.close_shape_picker()
            self.hover_connector = tag
            self.connector_hover_point = (event.x_root, event.y_root)
            self._glow_connector(tag)
            self.connector_hover_timer = self.root.after(250, lambda t=tag: self._open_hover_picker(t))

        def _open_hover_picker(self, tag):
            self.connector_hover_timer = None
            if tag != self.hover_connector or tag not in self.connector_paths or self.running:
                return
            if self.palette_drag_kind or self.canvas_drag_iid:
                return
            self.pending_insert = self.connector_paths[tag]['target']
            x, y = self.connector_hover_point
            self.show_shape_picker(x+14, y+14)

        def connector_leave(self, event=None):
            self._cancel_connector_timer('connector_hover_timer')
            if self.hover_connector is not None or self.shape_picker is not None:
                self._cancel_connector_timer('connector_close_timer')
                self.connector_close_timer = self.root.after(180, self._close_picker_if_outside)

        def picker_enter(self, event=None):
            self._cancel_connector_timer('connector_close_timer')

        def picker_leave(self, event=None):
            self.connector_leave(event)

        def _close_picker_if_outside(self):
            self.connector_close_timer = None
            try:
                rx, ry = self.root.winfo_pointerxy()
                window = self.shape_picker
                if window is not None and window.winfo_exists():
                    wx, wy = window.winfo_rootx(), window.winfo_rooty()
                    if wx <= rx < wx+window.winfo_width() and wy <= ry < wy+window.winfo_height():
                        return
                    # A short corridor lets the pointer reach the popup without
                    # requiring a perfectly straight or instant mouse movement.
                    if self.connector_hover_point is not None:
                        ax, ay = self.connector_hover_point
                        nearest_x = max(wx, min(ax, wx+window.winfo_width()))
                        nearest_y = max(wy, min(ay, wy+window.winfo_height()))
                        if min(ax, nearest_x)-7 <= rx <= max(ax, nearest_x)+7 and min(ay, nearest_y)-7 <= ry <= max(ay, nearest_y)+7:
                            return
                if self._over_diagram(rx, ry) and self.hover_connector is not None:
                    x = self.canvas.canvasx(rx-self.canvas.winfo_rootx())
                    y = self.canvas.canvasy(ry-self.canvas.winfo_rooty())
                    if self._connector_at(x, y) == self.hover_connector:
                        return
            except tk.TclError:
                pass
            self.close_shape_picker()

        def connector_clicked(self, event, tag):
            target = self.insert_hit_targets.get(tag)
            if target is None:
                return
            self.pending_insert = target
            self.show_shape_picker(event.x_root, event.y_root)
            # Clicking a connector selects its insertion point; the palette can
            # now be clicked normally to insert directly at that exact location.
            return 'break'

        def connector_menu(self, event, tag):
            target = self.insert_hit_targets.get(tag)
            if target is None:
                return 'break'
            self.pending_insert = target
            self.show_shape_picker(event.x_root, event.y_root)
            return 'break'

        def show_shape_picker(self, x_root, y_root):
            """Flowgorithm-style visual Add Shape palette, anchored at a connector."""
            self.close_shape_picker(clear_hover=False, keep_target=True)
            # Finish pending pane/canvas geometry before publishing a popup.
            # A Configure redraw closes old pickers, including during idles.
            insertion, document = self.pending_insert, self.doc
            hovered, hover_point = self.hover_connector, self.connector_hover_point
            self.root.update_idletasks()
            if self.doc is not document:
                return None
            self.pending_insert = insertion
            if hovered is not None and insertion is not None:
                for tag, record in self.connector_paths.items():
                    block, index = record['target']
                    if block is insertion[0] and index == insertion[1]:
                        self.hover_connector = tag
                        self.connector_hover_point = hover_point
                        self._glow_connector(tag)
                        break
            win = tk.Toplevel(self.root)
            self.shape_picker = win
            win.title('Add Shape')
            win.transient(self.root)
            win.resizable(False, False)
            win.configure(bg='#f8fafc')
            win.protocol('WM_DELETE_WINDOW', self.close_shape_picker)
            win.bind('<Escape>', lambda e: self.close_shape_picker())
            win.bind('<Enter>', self.picker_enter, add='+')
            win.bind('<Leave>', self.picker_leave, add='+')
            def destroyed(event):
                if event.widget is win and self.shape_picker is win:
                    self.shape_picker = None
                    self.pending_insert = None
                    self._cancel_connector_timer('connector_close_timer')
                    self._cancel_connector_timer('connector_hover_timer')
                    self._clear_connector_glow()
                    self.hover_connector = None
            win.bind('<Destroy>', destroyed, add='+')
            header = tk.Frame(win, bg='#f8fafc', padx=12, pady=9)
            header.pack(fill='x')
            tk.Label(header, text='Add a shape', bg='#f8fafc', fg='#0f172a',
                     font=(self.ui_font, 12, 'bold')).pack(side='left')
            tk.Label(header, text='Choose a symbol to insert here', bg='#f8fafc',
                     fg='#64748b').pack(side='left', padx=12)
            grid = tk.Frame(win, bg='#e2e8f0', padx=1, pady=1)
            grid.pack(padx=10, pady=(0, 8))
            help_panel = tk.Frame(win, bg='#edf4fc', padx=10, pady=8,
                                  width=540, height=184)
            help_panel.pack(fill='x', padx=10, pady=(0, 10))
            help_panel.pack_propagate(False)
            win.symbol_help_kind = tk.StringVar(master=win)
            win.symbol_help_text = tk.StringVar(master=win)
            win.symbol_cards = {}
            tk.Label(help_panel, textvariable=win.symbol_help_kind, bg='#edf4fc',
                     fg='#183452', font=(self.ui_font, 10, 'bold'),
                     anchor='w').pack(fill='x')
            tk.Label(help_panel, textvariable=win.symbol_help_text, bg='#edf4fc',
                     fg='#334155', font=(self.ui_font, 9), wraplength=520,
                     justify='left', anchor='nw').pack(fill='both', expand=True, pady=(4, 0))
            def preview(kind):
                win.symbol_help_kind.set(kind)
                body = symbol_help_text(kind, self.doc.get('python', False)).split('\n', 1)[1]
                win.symbol_help_text.set(body)
            preview('Assign')
            styles = {
                'Declare': ('#e0e7ff', 'rectangle'), 'Assign': ('#dbeafe', 'rectangle'),
                'Input': ('#dcfce7', 'io'), 'Output': ('#dcfce7', 'io'),
                'If': ('#fef3c7', 'diamond'), 'While': ('#fef3c7', 'diamond'),
                'Do': ('#fef3c7', 'diamond'), 'For': ('#ffedd5', 'hex'),
                'Call': ('#f3e8ff', 'subroutine'), 'Return': ('#f3e8ff', 'subroutine'),
                'Comment': ('#f1f5f9', 'rectangle'), 'Break': ('#fee2e2', 'rectangle'),
                'Continue': ('#fee2e2', 'rectangle')
            }
            choices = [k for k in KINDS if k not in ('Terminal',)]
            for idx, kind in enumerate(choices):
                bg, shape_kind = styles.get(kind, ('#e2e8f0', 'rectangle'))
                card = tk.Frame(grid, bg='#ffffff', width=132, height=80,
                                highlightbackground='#cbd5e1', highlightthickness=1,
                                takefocus=True)
                card.grid(row=idx // 4, column=idx % 4, padx=1, pady=1, sticky='nsew')
                card.grid_propagate(False)
                win.symbol_cards[kind] = card
                icon = tk.Canvas(card, width=116, height=53, bg='#ffffff',
                                highlightthickness=0, cursor='hand2')
                icon.pack(pady=(4, 0))
                fill = bg
                if shape_kind == 'diamond':
                    icon.create_polygon(58, 5, 105, 26, 58, 47, 11, 26,
                                        fill=fill, outline='#475569', width=1.5)
                elif shape_kind == 'io':
                    icon.create_polygon(24, 9, 105, 9, 92, 43, 11, 43,
                                        fill=fill, outline='#475569', width=1.5)
                elif shape_kind == 'hex':
                    icon.create_polygon(22, 9, 94, 9, 105, 26, 94, 43,
                                        22, 43, 11, 26, fill=fill,
                                        outline='#475569', width=1.5)
                elif shape_kind == 'subroutine':
                    icon.create_rectangle(16, 8, 100, 45, fill=fill,
                                          outline='#475569', width=1.5)
                    icon.create_line(23, 8, 23, 45, fill='#475569', width=1.5)
                    icon.create_line(93, 8, 93, 45, fill='#475569', width=1.5)
                else:
                    icon.create_rectangle(13, 8, 103, 45, fill=fill,
                                          outline='#475569', width=1.5)
                caption = tk.Label(card, text=kind, bg='#ffffff', fg='#0f172a',
                         font=(self.ui_font, 9, 'bold'), cursor='hand2')
                caption.pack()
                def choose(k=kind):
                    self.close_shape_picker(keep_target=True)
                    self.add_shape(k)
                for widget in (card, icon, caption):
                    widget.bind('<Button-1>', lambda e, fn=choose: fn())
                    widget.bind('<Enter>', lambda e, w=card, k=kind: (w.configure(bg='#eff6ff'), preview(k)))
                    widget.bind('<Leave>', lambda e, w=card: w.configure(bg='#ffffff'))
                    widget.bind('<FocusIn>', lambda e, k=kind: preview(k))
                # A button-like hover/click target across the entire card.
                card.bind('<Double-Button-1>', lambda e, fn=choose: fn())
                card.bind('<Return>', lambda e, fn=choose: fn())
                card.bind('<space>', lambda e, fn=choose: fn())
            win.update_idletasks()
            if not win.winfo_exists():
                return None
            sw, sh = win.winfo_reqwidth(), win.winfo_reqheight()
            x = min(max(10, x_root), max(10, self.root.winfo_screenwidth() - sw - 10))
            y = min(max(10, y_root), max(10, self.root.winfo_screenheight() - sh - 10))
            win.geometry('+%d+%d' % (x, y))
            return win

        def change_speed(self, event=None):
            values = {
                'Instant': 0, 'Fast': 100, 'Normal': 250, 'Slow': 750, 'Very slow': 1500,
                'Instant (as fast as possible)': 0,
                '0.1 seconds per instruction': 100,
                '0.25 seconds per instruction': 250,
                '0.5 seconds per instruction': 500,
                '1 second per instruction': 1000,
                '1.5 seconds per instruction': 1500,
                '2 seconds per instruction': 2000,
            }
            self.speed.set(values.get(self.speed_choice.get(), 250))
            self.status.set('Execution speed: ' + self.speed_choice.get())

        def canvas_select(self, event):
            items = self.canvas.find_overlapping(self.canvas.canvasx(event.x)-2, self.canvas.canvasy(event.y)-2, self.canvas.canvasx(event.x)+2, self.canvas.canvasy(event.y)+2)
            for item in reversed(items):
                for tag in self.canvas.gettags(item):
                    if tag in self.canvas_hits:
                        iid = self.canvas_hits[tag]
                        self.tree.selection_set(iid)
                        self.tree.see(iid)
                        return

        def canvas_edit(self, event):
            self.canvas_select(event)
            self.edit_shape()

        def canvas_menu(self, event):
            self.canvas_select(event)
            menu = tk.Menu(self.root, tearoff=False)
            for text, cmd in [('Edit', self.edit_shape), ('Delete', self.delete), ('Copy', self.copy), ('Paste after', self.paste), ('Toggle breakpoint', self.toggle_breakpoint)]:
                menu.add_command(label=text, command=cmd)
            menu.tk_popup(event.x_root, event.y_root)

        def scroll_canvas(self, axis, *args):
            self.close_shape_picker()
            getattr(self.canvas, axis + 'view')(*args)

        def mousewheel(self, event):
            if event.state & 0x0004:
                self.set_zoom(1.1 if event.delta > 0 else 1 / 1.1)
            else:
                self.scroll_canvas('y', 'scroll', -1 if event.delta > 0 else 1, 'units')

        def set_zoom(self, factor):
            self.zoom = max(0.4, min(2.2, self.zoom * factor))
            self.draw()

        def clear_console(self):
            self.console.configure(state='normal')
            self.console.delete('1.0', 'end')
            self.console.configure(state='disabled')

        def log(self, value, nl=True):
            self.console.configure(state='normal')
            self.console.insert('end', value + ('\n' if nl else ''))
            self.console.see('end')
            self.console.configure(state='disabled')

        def read_input(self, name):
            self.show_tools(1)
            value = simpledialog.askstring('Input', 'Value for ' + name + ':', parent=self.root)
            if value is not None:
                self.log('> ' + value)
            return value

        def inspect_variables(self):
            for iid in self.variables.get_children():
                self.variables.delete(iid)
            if self.engine:
                for name in sorted(self.engine.env):
                    typ, array = self.engine.types.get(name, (type(self.engine.env[name]).__name__, False))
                    value = repr(self.engine.env[name])
                    self.variables.insert('', 'end', text=name, values=(typ + ('[]' if array else ''), value[:500]))

        def start_engine(self):
            if not self.sync_source():
                return False
            if self.iterator is not None:
                return True
            try:
                self.engine = Interpreter(self.doc, self.read_input, self.log)
                self.iterator = self.engine.steps()
                self.clear_console()
                self.log('--- Execution started ---')
                self.show_tools(1)
                return True
            except Exception as e:
                messagebox.showerror('Cannot run', str(e), parent=self.root)
                return False

        def advance(self, render=True):
            try:
                self.current_node = next(self.iterator)
                if render:
                    self.inspect_variables()
                    iid = self.node_iids.get(id(self.current_node))
                    if iid:
                        self.tree.selection_set(iid)
                        self.tree.see(iid)
                    self.draw()
                    self.status.set('About to execute: ' + label(self.current_node))
                return True
            except StopIteration:
                self.pause()
                self.iterator = None
                self.current_node = None
                self.inspect_variables()
                self.draw()
                self.log('--- Execution finished ---')
                self.status.set('Finished. Variables contain final values.')
            except Exception as e:
                self.pause()
                self.iterator = None
                self.inspect_variables()
                self.log('ERROR: ' + str(e))
                self.status.set('Execution error: ' + str(e))
                self.draw()
            return False

        def step(self):
            self.pause()
            if self.start_engine():
                self.advance()

        def run(self):
            if self.running:
                return
            if not self.start_engine():
                return
            self.running = True
            self.status.set('Running...')
            self.schedule_tick()

        def schedule_tick(self):
            self.timer = None
            if not self.running:
                return
            try:
                delay = max(0,int(self.speed.get()))
            except Exception:
                delay = 250
            if delay == 0:
                # Batch enough for fast execution, then return to Tk so that
                # Pause/Stop and other interactions can be handled.
                for count in range(120):
                    if not self.running or not self.advance(render=False):
                        return
                    if id(self.current_node) in self.breakpoints:
                        self.pause()
                        self.inspect_variables()
                        self.draw()
                        self.status.set('Breakpoint: '+label(self.current_node))
                        return
                self.inspect_variables()
                self.draw()
                self.timer = self.root.after(1,self.schedule_tick)
                return
            if not self.advance():
                return
            if id(self.current_node) in self.breakpoints:
                self.pause()
                self.status.set('Breakpoint before: '+label(self.current_node))
                return
            self.timer = self.root.after(delay,self.schedule_tick)

        def pause(self):
            self.running = False
            if self.timer is not None:
                self.root.after_cancel(self.timer)
                self.timer = None

        def stop(self):
            self._clear_drag_preview()
            self.palette_drag_kind = None
            self.pause()
            if self.iterator:
                self.iterator.close()
            self.iterator = None
            self.engine = None
            self.current_node = None
            if hasattr(self, 'variables'):
                self.inspect_variables()
                self.draw()
            self.status.set('Stopped / reset.')

        def toggle_breakpoint(self):
            n = self.selected_node()
            if n:
                ident = id(n)
                if ident in self.breakpoints:
                    self.breakpoints.remove(ident)
                else:
                    self.breakpoints.add(ident)
                self.draw()

        def show_text(self, title, value):
            win = tk.Toplevel(self.root)
            win.title(title)
            win.geometry('760x600')
            text = tk.Text(win, wrap='word', padx=12, pady=12)
            text.pack(fill='both', expand=True)
            text.insert('1.0', value)
            text.configure(state='disabled')
            ttk.Button(win, text='Close', command=win.destroy).pack(pady=5)

        def help(self):
            self.show_text('Capabilities and honest limitations', CAPABILITIES)

        def symbol_guide(self):
            self.show_text('Symbol guide', '\n\n'.join(
                symbol_help_text(kind, self.doc.get('python', False))
                for kind in ['Terminal'] + KINDS))

        def expression_help(self):
            self.show_text('Expressions and usage', '''Python source uses normal Python syntax and dynamic values: no declarations needed.
Use ** for powers, ^ for bitwise XOR, == for equality.
Lists, tuples, dictionaries, sets, slices and iterable for loops are supported.
The Generated code panel opens automatically. Use Generate code (Ctrl+L)
to reopen or refresh it, or Import code to load a program.
Native Python collection charts save as JSON; advanced constructs may not
convert to the portable subset used by other language exporters.

For hand-built typed charts, declare variables before assigning or reading them.
Types: Integer, Real, String, Boolean. Arrays are zero-based.
Declare x, y, total together, or declare an array with its size.

Operators:
+ - * / (real division), ^ (power), % (remainder), & (concatenation)
= or == (equality), <> or !=, < <= > >=
And / Or / Not (also &&, ||, !)
Strings in double quotes; Boolean literals true / false.
Example: "Total: " & ToString(total)

Interpreter built-ins:
Abs, Sqrt, Sin, Cos, Tan, ArcSin, ArcCos, ArcTan,
Log (natural), Log10, Floor, Ceiling, Round, Int,
ToString, ToInteger, ToReal, ToBoolean, Len, Length,
Size, Char(string, index), Random(exclusive_upper), Min, Max, Sgn.
Math angles are in radians. Pi is a constant.
Built-ins are case-insensitive. Variables/functions are case-sensitive.
Exports support a subset; unsupported built-ins show an error.

For loops include the end value. Step must be positive;
choose direction dec to count down. Declare the loop variable first.
Do loops always run the body once, then repeat while condition is true.

Hover any part of a connector to highlight its complete path and open
the symbol picker. Move over a symbol to read its definition and example.
Help > Symbol guide lists every symbol, including Main and End.
Select a block in the outline to append inside it. Select a shape to
insert after it. Click a canvas shape to select; double-click to edit.
Use cut/paste to move a shape between branches. Delete removes its
nested blocks too. Edits, undo, redo and function changes regenerate
source immediately. Select the source language above the source panel.

Two-way code editing: with Python or Pseudocode selected, the source
panel is editable. Type (or paste) code and the flowchart updates after a
short pause; syntax or unsupported-feature problems are shown under the
panel and the chart is left untouched. Plain top-level scripts work - no
functions or main() are needed. Pseudocode is the lossless format: every
shape maps to exactly one line.

F5 Run/Continue; F6 Step; F9 toggle breakpoint on selected shape.
Ctrl+Plus / Ctrl+Minus zoom the diagram; Ctrl+0 resets zoom. Ctrl+mouse-wheel zooms.
Use View > Fit diagram to window to fit the current diagram, or search the shape palette by name.
Stepping pauses BEFORE the highlighted shape; the next step executes it.
User-defined function calls execute as one debugger step.
Execution is capped at 100000 operations. Stop resets execution state.
Edits reset the debugger and clear breakpoints, but not the chart.

Save editable flowcharts as .json and export all functions as a vector PDF.
PDFs can use very large pages or multiple pages when the chart is enormous.
''')

        def close(self):
            if self.check_discard():
                self.close_shape_picker()
                self.pause()
                self.root.destroy()

    try:
        root = tk.Tk()
    except tk.TclError as e:
        sys.stderr.write('Cannot open desktop window: ' + str(e) + '\nUse --help for headless commands.\n')
        return 1
    app = Editor(root)
    if initial_path:
        try:
            app.replace_doc(load_document(initial_path), initial_path)
        except Exception as e:
            messagebox.showerror('Open failed', str(e), parent=root)
    root.mainloop()
    return 0




def kitchen_sink():
    """A chart that touches every shape; used by the self-test."""
    d = empty_document()
    d['name'] = 'Everything'
    d['functions'][0]['body'] = [
        node('Declare', name='n, i, total'), node('Declare', type='Real', name='avg'),
        node('Declare', type='String', name='name, msg'), node('Declare', type='Boolean', name='flag'),
        node('Declare', name='arr', array=True, size='5'),
        node('Output', expression='"Enter n and name:"'),
        node('Input', variable='n'), node('Input', variable='name'),
        node('Assign', variable='total', expression='0'),
        node('For', variable='i', start='1', end='n', body=[node('Assign', variable='total', expression='total + i * 2')]),
        node('If', expression='total > 10', true=[node('Assign', variable='msg', expression='"big " & ToString(total)')],
             false=[node('Assign', variable='msg', expression='"small"')]),
        node('Assign', variable='avg', expression='total / 4'),
        node('While', expression='n > 0', body=[node('Assign', variable='n', expression='n - 1')]),
        node('Assign', variable='i', expression='3'),
        node('Do', expression='i > 0', body=[node('Assign', variable='i', expression='i - 1')]),
        node('Assign', variable='arr[2]', expression='Square(4) + 1'),
        node('Output', expression='arr[2]'),
        node('Assign', variable='flag', expression='total >= 5 And Not (name = "bob")'),
        node('Output', expression='msg & " " & ToString(avg) & " " & ToString(flag)'),
        node('Output', expression='Length(name)'),
        node('Output', expression='Sqrt(16) + 1'),
        node('Call', expression='Greet(name)'),
        node('Output', expression='Fact(5)'),
        node('For', variable='i', start='3', end='1', direction='dec', body=[node('Output', expression='i')]),
        node('Output', expression='"tail"', newline=False), node('Output', expression='"!"'),
        node('Declare', name='t2'),
        node('For', variable='i', start='1', end='10', body=[
            node('If', expression='i % 2 = 0', true=[node('Continue')]),
            node('If', expression='i > 7', true=[node('Break')]),
            node('Assign', variable='t2', expression='t2 + i')]),
        node('Output', expression='t2'),
        node('Output', expression='ToUpper("abc") & Trim("  x ") & ToString(Contains("hello", "ell")) & ToLower("QQ")'),
        node('If', expression='total = 30', true=[node('Output', expression='"thirty"')], false=[
            node('If', expression='total = 31', true=[node('Output', expression='"thirtyone"')],
                 false=[node('Output', expression='"other"')])]),
        node('Comment', text='done')]
    d['functions'].append({'name': 'Square', 'type': 'Integer', 'variable': '', 'parameters': [
        {'name': 'v', 'type': 'Integer', 'array': False}], 'body': [node('Return', expression='v ^ 2')]})
    d['functions'].append({'name': 'Greet', 'type': 'None', 'variable': '', 'parameters': [
        {'name': 'who', 'type': 'String', 'array': False}], 'body': [node('Output', expression='"Hello " & who')]})
    d['functions'].append({'name': 'Fact', 'type': 'Integer', 'variable': '', 'parameters': [
        {'name': 'k', 'type': 'Integer', 'array': False}], 'body': [
        node('If', expression='k <= 1', true=[node('Return', expression='1')],
             false=[node('Return', expression='k * Fact(k - 1)')])]})
    return d


def generate_source(language, doc):
    return GENERATORS[language](language).generate(doc)


EXT_LANG = {'.py': 'Python', '.txt': 'Pseudocode', '.pseudo': 'Pseudocode', '.c': 'C', '.cpp': 'C++', '.cc': 'C++',
            '.cxx': 'C++', '.cs': 'C#', '.java': 'Java', '.js': 'JavaScript', '.mjs': 'JavaScript',
            '.ts': 'TypeScript', '.go': 'Go', '.kt': 'Kotlin', '.swift': 'Swift', '.php': 'PHP', '.r': 'R',
            '.m': 'MATLAB'}


def detect_language(path):
    return EXT_LANG.get(os.path.splitext(path)[1].lower())


def convert_code(src_language, text, dst_language):
    """Translate source via the flowchart model and reject invalid generated output.

    This validates the generated text with the target language's own parser before
    returning it. It is a syntax/representability check, not a proof of semantic
    equivalence or a substitute for the target compiler/runtime.
    Returns (code, warnings).
    """
    doc = parse_code(src_language, text)
    warnings = list(LAST_WARNINGS)
    generated = generate_source(dst_language, doc)
    try:
        parse_code(dst_language, generated)
    except FlowError as exc:
        raise FlowError('Generated {0} code failed validation: {1}'.format(dst_language, exc))
    # Parsing the generated code updates this module-level list; restore the
    # source-front-end warnings so callers see warnings about the actual input.
    del LAST_WARNINGS[:]
    LAST_WARNINGS.extend(warnings)
    return generated, warnings


PLAIN_SCRIPT = '''# plain script: no functions, no main()
n = int(input("How many? "))
total = 0
for i in range(1, n + 1):
    total += i * i
print("Sum of squares:", total)
if total > 50:
    print("big")
else:
    print("small")
'''


SELF_PROGRAMS = {
    'Python': """n = int(input())
total = 0
for i in range(1, n + 1):
    if i % 2 == 1:
        continue
    if i > 8:
        break
    total += i
a, b = 3, 4
a, b = b, a
label = "big" if total > 10 else "small"
sq = [k * k for k in range(4)]
print(total, a, b, label, sq[3], "ok".upper())
""",
    'C': """#include <stdio.h>
int is_prime(int k) {
    if (k < 2) return 0;
    for (int d = 2; d * d <= k; d++) { if (k % d == 0) return 0; }
    return 1;
}
int main(void) {
    int n;
    scanf("%d", &n);
    int count = 0;
    for (int i = 2; i <= n; i++) {
        if (!is_prime(i)) continue;
        count++;
    }
    printf("%d primes, half=%d\n", count, n / 4);
    return 0;
}
""",
    'Java': """import java.util.Scanner;
public class Main {
    static int fact(int k) { return k <= 1 ? 1 : k * fact(k - 1); }
    public static void main(String[] args) {
        Scanner sc = new Scanner(System.in);
        int n = sc.nextInt();
        int[] a = new int[n];
        for (int i = 0; i < n; i++) a[i] = fact(i + 1);
        System.out.println(a[n - 1] + " " + a.length);
    }
}
""",
    'JavaScript': """const n = parseInt(_readLine(), 10);
let s = "";
for (let i = n; i > 0; i--) { s += i + ","; }
console.log(`down: ${s}`);
""",
    'Go': """package main
import "fmt"
func main() {
	var n int
	fmt.Scan(&n)
	sum := 0
	for i := 1; i <= n; i++ {
		sum += i
	}
	fmt.Println("sum", sum)
}
""",
    'R': """n <- as.integer(readLines(file("stdin"), n = 1))
t <- 0
for (i in 1:n) { t <- t + i }
cat("t =", t, "\n")
""",
    'MATLAB': """n = str2double(input('', 's'));
t = 0;
for i = 1:n
  t = t + i;
end
fprintf('t = %d\\n', t);
""",
}
SELF_EXPECT = {'Python': '20 4 3 big 9 OK', 'C': '4 primes, half=2', 'Java': '3628800 10', 'JavaScript': 'down: 10,9,8,7,6,5,4,3,2,1,',
               'Go': 'sum 55', 'R': 't = 55', 'MATLAB': 't = 55'}


def self_test():
    """Headless regression suite, bundled so no testing dependency is needed."""
    import tempfile
    import shutil
    import subprocess
    tests = [0]

    def check(value, message):
        if not value:
            raise AssertionError(message)
        tests[0] += 1

    def run_chart(d, inputs=None):
        output = []
        inputs = iter(inputs or [])
        engine = Interpreter(d, lambda name: next(inputs), lambda value, nl: output.append(value + ('\n' if nl else '')))
        engine.run()
        return engine, ''.join(output)

    d = sample_document()
    e, out = run_chart(d, ['5'])
    check(e.env['total'] == 15 and out.endswith('Sum = 15\n'), 'Sample sum')
    d = empty_document()
    d['functions'][0]['body'] = [node('Declare', name='i, total'),
        node('Assign', variable='total', expression='0'),
        node('For', start='5', end='1', direction='dec', body=[node('Assign', variable='total', expression='total + i')]),
        node('If', expression='total = 15 And Not false', true=[node('Output', expression='"yes"')], false=[node('Output', expression='"no"')]),
        node('Do', expression='i < 2', body=[node('Assign', variable='i', expression='i + 1')])]
    e, out = run_chart(d)
    check(out == 'yes\n' and e.env['i'] == 2, 'For/if/do')
    d = empty_document()
    d['functions'][0]['body'] = [node('Declare', name='a', array=True, size='3'),
        node('Declare', name='x'), node('Assign', variable='a[1]', expression='Square(4)'),
        node('Assign', variable='x', expression='a[1]'), node('Output', expression='x')]
    d['functions'].append({'name': 'Square', 'type': 'Integer', 'variable': '',
        'parameters': [{'name': 'v', 'type': 'Integer', 'array': False}],
        'body': [node('Return', expression='v ^ 2')]})
    e, out = run_chart(d)
    check(e.env['a'] == [0, 16, 0] and out == '16\n', 'Arrays/functions')
    e.env['x'] = 1
    check(e.evaluate('"a=b & c" & ToString(x)') == 'a=b & c1', 'String operator preservation')
    check(e.evaluate('1 < 2 < 3') is True, 'Chained comparisons')
    for expr in ['__import__("os")', 'x.__class__', '[1, 2]', 'open("bad")']:
        try:
            e.evaluate(expr)
        except (FlowError, TypeError):
            tests[0] += 1
        else:
            raise AssertionError('Unsafe expression accepted: ' + expr)
    inf = empty_document()
    inf['functions'][0]['body'] = [node('While', expression='true')]
    try:
        Interpreter(inf, limit=30).run()
    except FlowError:
        tests[0] += 1
    else:
        raise AssertionError('No execution limit')
    brk = empty_document()
    brk['functions'][0]['body'] = [node('Declare', name='i, s'), node('For', variable='i', start='1', end='9', body=[
        node('If', expression='i = 3', true=[node('Continue')]), node('If', expression='i > 5', true=[node('Break')]),
        node('Assign', variable='s', expression='s + i')]), node('Output', expression='s')]
    check(run_chart(brk)[1] == '12\n', 'Break/Continue in the interpreter')
    bad = empty_document()
    bad['functions'][0]['body'] = [node('Break')]
    try:
        validate(bad)
    except FlowError:
        tests[0] += 1
    else:
        raise AssertionError('Break outside a loop accepted')

    sink = kitchen_sink()
    inputs = ['5', 'alice']
    _, want = run_chart(sink, inputs)
    check('thirty' in want and 'Hello alice' in want and 'ABCxtrueqq' in want and '\n16\n' in want, 'Kitchen sink runs')
    # every language generates the whole chart, and every language parses its own output back
    for language in LANGUAGES:
        source = generate_source(language, sink)
        check(len(source) > 200, 'Target ' + language)
        back = parse_code(language, source)
        _, got = run_chart(back, inputs)
        check(got.split() == want.split(), 'Round trip behaviour ' + language + ': ' + repr(got[:80]))
    for language in ('Python', 'Pseudocode'):
        source = generate_source(language, sink)
        canonical = generate_source(language, parse_code(language, source))
        check(generate_source(language, parse_code(language, canonical)) == canonical, 'Round trip text is stable ' + language)
    # hand-written programs in several languages convert to every other language and keep their meaning
    for language, program in sorted(SELF_PROGRAMS.items()):
        doc = parse_code(language, program)
        _, out = run_chart(doc, ['10'] if language not in ('Java',) else ['10'])
        check(out.strip().replace('\n', ' ') == SELF_EXPECT[language] or SELF_EXPECT[language] in out.replace('\n', ' '),
              'Hand-written ' + language + ' program: ' + repr(out))
        for target in LANGUAGES:
            code, warns = convert_code(language, program, target)
            back = parse_code(target, code)
            _, out2 = run_chart(back, ['10'])
            check(out2.split() == out.split(), 'Convert {0} -> {1}: {2!r} vs {3!r}'.format(language, target, out2, out))
    # Conversion validates generated target syntax before returning it.
    checked_code, checked_warnings = convert_code('Python', 'x = 2 + 3\nprint(x)\n', 'JavaScript')
    check('console.log' in checked_code and parse_code('JavaScript', checked_code) is not None,
          'Generated target code passes its target parser')
    check(isinstance(checked_warnings, list), 'Conversion warnings are returned')
    plain = parse_code('Python', PLAIN_SCRIPT)
    _, out = run_chart(plain, ['5'])
    check(out.endswith('Sum of squares: 55\nbig\n'), 'Plain Python script imported')
    check(len(plain['functions']) == 1, 'No function wrapper needed')
    text = generate_source('Python', plain)
    check('def ' not in text and '__main__' not in text, 'Generated Python is plain code')
    for lang, bad_src in (('Python', 'with open("data") as f: pass\n'), ('Python', 'class A: pass\n'), ('Python', 'x = (\n'), ('Python', 'print((1).__class__)\n'),
                          ('Java', 'class A { int x = 1; void f() { try { } catch (Exception e) { } } }'),
                          ('C', 'int main() { int *p; return 0; }'), ('Go', 'func main() { x := ( }'),
                          ('PHP', '<?php $x = ;'), ('R', 'x <- (1 +'), ('MATLAB', 'x = 1 +;'), ('Pseudocode', 'If x > 1 Then\nOutput 1\n')):
        try:
            parse_code(lang, bad_src)
        except ParseError:
            tests[0] += 1
        else:
            raise AssertionError('Bad {0} code accepted: {1!r}'.format(lang, bad_src))
    temp = tempfile.mkdtemp(prefix='flowchart_studio_test_')
    try:
        for ext in ('.json', '.fprg'):
            path = os.path.join(temp, 'roundtrip' + ext)
            save_document(brk, path)
            loaded = load_document(path)
            loaded['name'] = brk['name']
            check(loaded == brk, 'Roundtrip ' + ext)
        path = os.path.join(temp, 'program.py')
        with io.open(path, 'w', encoding='utf-8') as h:
            h.write(generate_source('Python', sink))
        p = subprocess.Popen([sys.executable, path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = p.communicate(b'5\nalice\n')
        check(p.returncode == 0, 'Python generated execution: ' + stderr.decode('utf-8'))
        check(stdout.decode('utf-8').split() == want.split(), 'Python generated output matches interpreter')

        # Where toolchains are installed, compile/run a tiny generated program
        # instead of trusting only this application's own parser.
        probe = 'x = 2 + 3\nprint(x)\n'
        toolchains = [
            ('C', 'gcc', 'probe.c', lambda src, exe: [shutil.which('gcc'), src, '-std=c99', '-lm', '-o', exe],
             lambda exe: [exe]),
            ('C++', 'g++', 'probe.cpp', lambda src, exe: [shutil.which('g++'), src, '-std=c++11', '-o', exe],
             lambda exe: [exe]),
            ('Java', 'javac', 'Main.java', lambda src, exe: [shutil.which('javac'), src],
             lambda exe: [shutil.which('java'), '-cp', temp, 'Main']),
            ('JavaScript', 'node', 'probe.js', lambda src, exe: None,
             lambda exe: [shutil.which('node'), os.path.join(temp, 'probe.js')]),
            ('Go', 'go', 'main.go', lambda src, exe: None,
             lambda exe: [shutil.which('go'), 'run', os.path.join(temp, 'main.go')]),
        ]
        for lang, tool, filename, build_cmd, run_cmd in toolchains:
            if not shutil.which(tool):
                print('SKIP: {0} external compiler/runtime is unavailable.'.format(lang))
                continue
            if tool == 'go':
                version = subprocess.Popen([shutil.which(tool), 'version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                version_output, version_error = version.communicate()
                if version.returncode or not version_output.startswith(b'go version go'):
                    print('SKIP: executable named go is not a Go compiler.')
                    continue
            generated, unused_warnings = convert_code('Python', probe, lang)
            source_path = os.path.join(temp, filename)
            with io.open(source_path, 'w', encoding='utf-8') as h:
                h.write(generated)
            exe_path = os.path.join(temp, 'probe.exe' if os.name == 'nt' else 'probe')
            cmd = build_cmd(source_path, exe_path)
            if cmd:
                proc = subprocess.Popen(cmd, cwd=temp, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                out_build, err_build = proc.communicate()
                check(proc.returncode == 0, '{0} generated code compiles: {1}'.format(lang, err_build.decode('utf-8', 'replace')))
            proc = subprocess.Popen(run_cmd(exe_path), cwd=temp, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            out_run, err_run = proc.communicate()
            check(proc.returncode == 0 and out_run.decode('utf-8', 'replace').strip() == '5',
                  '{0} generated code executes: {1}'.format(lang, err_run.decode('utf-8', 'replace')))
    finally:
        shutil.rmtree(temp)
    print('PASS: {0} headless regression checks; {1} languages, all generated and parsed.'.format(tests[0], len(LANGUAGES)))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Single-file Python 3.3+ flowchart editor and code converter. Standard library only; GUI needs preinstalled Tkinter.')
    parser.add_argument('file', nargs='?', help='Open a saved editable .json flowchart')
    parser.add_argument('--self-test', action='store_true', help='Run bundled headless tests')
    parser.add_argument('--list-languages', action='store_true', help='List supported languages')
    parser.add_argument('--capabilities', action='store_true', help='Print honest feature/support limitations')
    parser.add_argument('--run', metavar='CHART', help='Interpret a chart in the terminal')
    parser.add_argument('--generate', metavar='CHART', help='Generate source from a chart (see --language)')
    parser.add_argument('--convert', metavar='SOURCE', help='Convert a source file to another language (needs --to)')
    parser.add_argument('--from-code', metavar='SOURCE', help='Turn source code into a chart file (use -o to save it)')
    parser.add_argument('--from', dest='src_language', choices=LANGUAGES, help='language of the input (default: from the file extension)')
    parser.add_argument('--to', dest='dst_language', choices=LANGUAGES, help='target language for --convert')
    parser.add_argument('--language', default=None, choices=LANGUAGES, help='language for --generate')
    parser.add_argument('-o', '--output', help='Write the result to this file instead of stdout')
    args = parser.parse_args(argv)

    def emit(text):
        if args.output:
            with io.open(args.output, 'w', encoding='utf-8') as h:
                h.write(text)
        else:
            sys.stdout.write(text)

    def read(path):
        with io.open(path, encoding='utf-8') as h:
            return h.read()
    try:
        if args.self_test:
            return self_test()
        if args.list_languages:
            print('\n'.join(LANGUAGES))
            return 0
        if args.capabilities:
            print(CAPABILITIES)
            return 0
        if args.run:
            Interpreter(load_document(args.run)).run()
            return 0
        if args.generate:
            emit(generate_source(args.language or 'Python', load_document(args.generate)))
            return 0
        if args.convert:
            src = args.src_language or detect_language(args.convert)
            if src is None or not args.dst_language:
                raise FlowError('Use --convert FILE --to LANGUAGE [--from LANGUAGE] (the input language is taken from the file extension).')
            code, warns = convert_code(src, read(args.convert), args.dst_language)
            for w in warns:
                sys.stderr.write('Note: ' + w + '\n')
            emit(code)
            return 0
        if args.from_code:
            src = args.src_language or args.language or detect_language(args.from_code) or 'Python'
            doc = parse_code(src, read(args.from_code), os.path.splitext(os.path.basename(args.from_code))[0])
            if args.output:
                save_document(doc, args.output)
            else:
                sys.stdout.write(json.dumps(doc, indent=2) + '\n')
            return 0
        return launch_gui(args.file)
    except (FlowError, ValueError, TypeError, IndexError, KeyError, OSError, ArithmeticError, RuntimeError, ET.ParseError) as e:
        sys.stderr.write('Error: ' + str(e) + '\n')
        return 1
    except KeyboardInterrupt:
        sys.stderr.write('\nExecution interrupted.\n')
        return 130


if __name__ == '__main__':
    sys.exit(main())
