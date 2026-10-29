# Flowchart Studio 3.1.5

Run the updated desktop application:

```sh
python Flowchart_Studio.py
```

Requires Python **3.2 or newer** with Tkinter. The app uses only the Python standard library; no pip installation is needed. On Windows, use a Python installer that includes Tcl/Tk. On Linux, your Python distribution may require its `python3-tk` package. The command-line tools work without a display. Python source syntax follows the interpreter running the app: for example, f-strings need Python 3.6 or newer.

## Use the editor

- **Generated code** appears beside the diagram on launch and after chart edits. **Generate code** or **Ctrl+L** refreshes and reopens it. Paste a complete Python program and click **Apply to chart**, or choose **Import code...** to load a `.py` file.
- **F5** runs; **F6** steps; **Escape** pauses. The console and variables panel opens during execution. Input is requested in a dialog.
- Normal runs have no total operation cap. Pause/Stop remain responsive inside long expressions, comprehensions and function calls. Terminal runs can use Ctrl+C, or an explicit operation budget with `--run chart.json --max-operations 1000000`.
- Hover over any part of a connector to highlight its complete path and open the symbol picker. Hover a symbol for its definition, example and behavior notes, then click to insert. Double-click a symbol to edit it. **Symbols** opens the optional palette and outline; **Help > Symbol guide** explains every symbol.
- Save editable charts as **JSON**. File > Export full flowchart produces a vector **PDF**.
- Source errors block execution, chart saving, and export instead of running a previously parsed chart. Fix the text or use **Reset** to return to the chart's source.

## Python improvements

Python programs now retain normal Python expressions and collection values in their chart nodes. Supported cases include input nested in expressions, inline loop bodies, string/list/tuple/dictionary iteration, dictionary items, unpacking, enumerate, zip, dynamic positive or negative ranges, comprehensions, slices, ordinary functions, and common collection methods. Range arguments are evaluated once; empty loops and loop-variable values follow Python behavior. Editing chart nodes changes the exported Python too.

This remains an educational interpreter with an explicit supported subset, not every feature of CPython. Classes, arbitrary third-party modules, file I/O, exception statements, async code, and some advanced function constructs are unsupported. Imports are restricted to math and random. Unsupported statements fail explicitly. Call-depth and allocation limits remain. See Help > Capabilities for details.

The 14-language generators/front ends convert the portable chart subset. Python conversion lowers nested input and range operations, and represents homogeneous tuples/lists and fixed dictionaries using portable arrays. Named and inline dictionary lookups support runtime keys, including runtime values rebuilt inside loops. Dictionary entries evaluate eagerly in source order; repeated keys overwrite earlier entries. Missing keys stop execution with an error. Python `and`/`or` preserve their operand values and short-circuit behavior, including expressions such as `h = b // 2 or 1`. Programs needing dynamic map resizing, heterogeneous collections, or unsupported libraries still report a specific conversion error.

Shared conversion now includes scalar function defaults and keyword arguments, chained scalar assignments, dictionary `get(key, default)` and membership, negative list/tuple/string indexing, `bool()`, signed `%`/`%=`, and negative constant exponents. Defaults evaluate once when the function is defined; arguments keep Python's evaluation order. Invalid indexes stop before accessing memory. MATLAB string concatenation preserves spaces. Portable exports still have a supported subset: mutable defaults, slices, dynamic collections and general sorting/reversal are not covered.

The UI uses a Flowgorithm-inspired desktop layout, not Flowgorithm's original assets or an exact clone. The blank chart starts with a large white canvas. Generated code is visible by default; console, symbols and outline are available as optional tools.

## Checks

From this directory:

```sh
python -m unittest -q test_cross_language test_control_conversion test_expression_conversion
python -m unittest -q test_execution_limits
python -m unittest -q test_function_conversion test_collection_features test_scalar_features
python Flowchart_Studio.py --self-test
python test_language_switching.py
python test_connector_hover.py
python test_generated_code.py
python test_execution_gui.py
```

The app, bundled self-test and new function/collection checks support Python 3.2 and newer. Some older development harnesses use Python 3.3 APIs. On Python 3.2, run `test_execution_gui.py` with an external timeout because `faulthandler` was introduced in Python 3.3. GUI checks need a desktop display. Conversion checks compare generated-source round trips with CPython and compile/run C, C++ and JavaScript when available. The expression suite includes the complete alphabet program in `examples/alphabet_letters.py`. Unavailable compilers are explicit skips.

Example CLI workflow:

```sh
python Flowchart_Studio.py --from-code examples/alphabet_letters.py -o chart.json
python Flowchart_Studio.py --run chart.json
python Flowchart_Studio.py --generate chart.json --language Python -o generated.py
```
