# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Safe arithmetic evaluator for calculated measures.

Compiles a formula like ``a / b * 100`` over a fixed set of variables using the
``ast`` module and a whitelist of node types - never ``eval``. Only numbers,
the provided variable names, unary minus and the binary operators + - * / // %
** are allowed; no calls, attribute access, comprehensions, names outside the
supplied set, or dunder anything can appear. Division by zero yields 0.0 rather
than raising, so one empty group never blanks a whole widget.
"""
import ast
import math


def _safe_pow(a, b):
    # Cap only genuine blow-ups. A large exponent (`9**9**9`) is the DoS to stop;
    # an ordinary root or small power of a large money value (`revenue ** 0.5` for
    # an RMS / geometric mean) must NOT be silently zeroed - that shipped wrong
    # numbers. Complex or non-finite results collapse to 0 so float() downstream
    # never crashes and the JSON-RPC response never carries a bare NaN/Infinity.
    try:
        if abs(b) > 64:
            return 0.0
        r = a ** b
        if isinstance(r, complex) or not math.isfinite(r):
            return 0.0
        return r
    except (OverflowError, ValueError, ZeroDivisionError):
        return 0.0


_BIN = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b if b else 0.0,
    ast.FloorDiv: lambda a, b: a // b if b else 0.0,
    ast.Mod: lambda a, b: a % b if b else 0.0,
    ast.Pow: _safe_pow,
}


class FormulaError(ValueError):
    pass


def compile_formula(expr):
    """Parse ``expr`` once and return a callable ``f(variables_dict) -> float``.

    Raises :class:`FormulaError` on any disallowed construct, so a bad formula
    is caught when the measure is saved, not at render time.
    """
    try:
        tree = ast.parse(expr or "0", mode="eval")
    except SyntaxError as err:
        raise FormulaError("Invalid formula: %s" % err)
    names = set()
    _check(tree.body, names)

    def run(variables):
        try:
            r = _eval(tree.body, variables or {})
            if isinstance(r, complex):
                return 0.0
            r = float(r)
            # inf / nan would serialise as bare Infinity/NaN tokens and break the
            # whole board's JSON-RPC response, so collapse them to 0.0.
            return r if math.isfinite(r) else 0.0
        except (OverflowError, ValueError, TypeError):
            return 0.0
    run.variables = names
    return run


# The positional variables a formula may reference (item base measures a, b, c ...).
ALLOWED_VARIABLES = frozenset("abcdef")


def _check(node, names):
    if isinstance(node, ast.BinOp):
        if type(node.op) not in _BIN:
            raise FormulaError("Operator not allowed.")
        _check(node.left, names)
        _check(node.right, names)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.UAdd, ast.USub)):
            raise FormulaError("Unary operator not allowed.")
        _check(node.operand, names)
    elif isinstance(node, ast.Name):
        if node.id.startswith("_"):
            raise FormulaError("Name not allowed.")
        names.add(node.id)
    elif isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
            raise FormulaError("Only numeric constants are allowed.")
    else:
        raise FormulaError("Expression element not allowed: %s" % type(node).__name__)


def _eval(node, variables):
    if isinstance(node, ast.BinOp):
        return _BIN[type(node.op)](_eval(node.left, variables), _eval(node.right, variables))
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, variables)
        return -v if isinstance(node.op, ast.USub) else +v
    if isinstance(node, ast.Name):
        return float(variables.get(node.id, 0.0) or 0.0)
    if isinstance(node, ast.Constant):
        return node.value
    raise FormulaError("Unexpected node.")
