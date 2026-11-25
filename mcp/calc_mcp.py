#!/usr/bin/env python3
"""calculator MCP for the GED tutor (stdlib only).

The tutor is told never to do arithmetic in its head: it calls `calc`, and the
answer comes from Python, so a wrong number can only come from a wrong
expression - and the expression is returned with the result so it can be
checked.

Tools:
  calc(expression, exact=False)  evaluate an arithmetic expression
  percent(part, whole)           part/whole as a percent, plus the two other forms
  solve_linear(a, b)             solve a*x + b = 0

`calc` is a whitelisted AST walker, not eval: numbers, + - * / // % **, unary
minus, comparisons, and a fixed set of math functions and constants. Anything
else is refused with a message saying what is allowed.
"""
from __future__ import annotations

import ast
import json
import math
import statistics
import sys
from fractions import Fraction

FUNCS = {
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "sqrt": math.sqrt, "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x),
    "pow": pow, "exp": math.exp, "log": math.log, "log10": math.log10, "log2": math.log2,
    "ln": math.log, "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "degrees": math.degrees, "radians": math.radians, "hypot": math.hypot,
    "floor": math.floor, "ceil": math.ceil, "trunc": math.trunc,
    "factorial": math.factorial, "gcd": math.gcd, "lcm": math.lcm,
    "mean": statistics.mean, "median": statistics.median, "mode": statistics.mode,
    "stdev": statistics.pstdev, "variance": statistics.pvariance,
    "comb": math.comb, "perm": math.perm, "fabs": math.fabs, "copysign": math.copysign,
}
CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}

BIN_OPS = {
    ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a ** b,
}
CMP_OPS = {
    ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
}


class CalcError(Exception):
    pass


def _eval(node, exact: bool):
    if isinstance(node, ast.Expression):
        return _eval(node.body, exact)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return Fraction(node.value) if exact else node.value
        raise CalcError(f"not a number: {node.value!r}")
    if isinstance(node, ast.UnaryOp):
        val = _eval(node.operand, exact)
        if isinstance(node.op, ast.USub):
            return -val
        if isinstance(node.op, ast.UAdd):
            return val
        raise CalcError("only unary + and - are allowed")
    if isinstance(node, ast.BinOp):
        op = BIN_OPS.get(type(node.op))
        if not op:
            raise CalcError("that operator is not allowed")
        a, b = _eval(node.left, exact), _eval(node.right, exact)
        try:
            return op(a, b)
        except ZeroDivisionError:
            raise CalcError("division by zero")
    if isinstance(node, ast.Compare):
        left = _eval(node.left, exact)
        values = [_eval(c, exact) for c in node.comparators]
        result = True
        for op, right in zip(node.ops, values):
            fn = CMP_OPS.get(type(op))
            if not fn:
                raise CalcError("that comparison is not allowed")
            result = result and fn(left, right)
            left = right
        return result
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS:
            raise CalcError(f"unknown function; allowed: {', '.join(sorted(FUNCS))}")
        if node.keywords:
            raise CalcError("keyword arguments are not allowed")
        args = [_eval(a, False) for a in node.args]
        return FUNCS[node.func.id](*args)
    if isinstance(node, ast.Name):
        if node.id in CONSTS:
            return CONSTS[node.id]
        raise CalcError(f"unknown name {node.id!r}; allowed constants: pi, e, tau")
    if isinstance(node, (ast.List, ast.Tuple)):
        vals = [_eval(e, False) for e in node.elts]
        return vals if isinstance(node, ast.List) else tuple(vals)
    raise CalcError(f"{type(node).__name__} is not allowed in a calculation")


def _fmt(value) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, Fraction):
        if value.denominator == 1:
            return str(value.numerator)
        mixed = f"{float(value):.10g}"
        return f"{value.numerator}/{value.denominator} = {mixed}"
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return f"{value:.1f}".rstrip("0").rstrip(".") or "0"
        return f"{value:.10g}"
    return str(value)


def calc(expression: str, exact: bool = False) -> str:
    raw = str(expression or "").strip()
    if not raw:
        return "error: empty expression"
    expr = raw.replace("^", "**").replace("×", "*").replace("÷", "/").replace("−", "-")
    expr = expr.replace(",", "") if expr.count(",") and "(" not in expr else expr
    try:
        tree = ast.parse(expr, mode="eval")
        value = _eval(tree, exact)
    except CalcError as exc:
        return f"error: {exc}"
    except SyntaxError:
        return ("error: that is not a plain expression - use numbers and operators, "
                "e.g. (3/4) * 240 or sqrt(2)*10")
    except Exception as exc:  # noqa: BLE001
        return f"error: {exc}"
    shown = _fmt(value)
    return (f"{raw}  =  {shown}\n"
            f"python: {expr}\n"
            f"exact: {_fmt(Fraction(value)) if isinstance(value, (int, float, Fraction)) and not isinstance(value, bool) else shown}")


TOOLS = [
    {
        "name": "calc",
        "description": ("Run a calculation in Python. Use this for EVERY arithmetic step in an "
                        "explanation - never compute in your head. Accepts + - * / // % **, "
                        "parentheses, comparisons, and sqrt, log, ln, log10, exp, sin, cos, tan, "
                        "factorial, gcd, lcm, comb, perm, floor, ceil, round, abs, min, max, sum, "
                        "mean, median, mode, stdev, pi, e. Returns the value, the python expression "
                        "that produced it, and the exact fraction when it is exact."),
        "inputSchema": {"type": "object", "properties": {
            "expression": {"type": "string", "description": "e.g. (3/4)*240 or 100*1.07**5"},
            "exact": {"type": "boolean", "description": "keep fractions exact instead of floats"}},
            "required": ["expression"]},
    },
    {
        "name": "percent",
        "description": "Percent trio: what percent is part of whole, plus the multiplier and the remainder.",
        "inputSchema": {"type": "object", "properties": {
            "part": {"type": "number"}, "whole": {"type": "number"}},
            "required": ["part", "whole"]},
    },
    {
        "name": "solve_linear",
        "description": "Solve a*x + b = 0 exactly (the common GED algebra shape).",
        "inputSchema": {"type": "object", "properties": {
            "a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]},
    },
]


def call(name: str, args: dict) -> str:
    if name == "calc":
        return calc(args.get("expression", ""), bool(args.get("exact")))
    if name == "percent":
        part, whole = float(args.get("part") or 0), float(args.get("whole") or 0)
        if whole == 0:
            return "error: whole cannot be zero"
        pct = part / whole * 100
        return (f"{part:g} of {whole:g} = {pct:.4g}%\n"
                f"python: {part}/{whole}*100\n"
                f"remainder: {whole - part:g} ({100 - pct:.4g}%)")
    if name == "solve_linear":
        a, b = Fraction(str(args.get("a") or 0)), Fraction(str(args.get("b") or 0))
        if a == 0:
            return "no unique solution (a is 0)"
        x = -b / a
        return f"x = -b/a = -({_fmt(b)})/({_fmt(a)}) = {_fmt(x)}\npython: -({b})/({a})"
    raise KeyError(name)


def handle(msg: dict):
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": params.get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ged-calc", "version": "1.0.0"}}}
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        try:
            out = call(params.get("name"), params.get("arguments") or {})
        except Exception as exc:  # noqa: BLE001
            out = f"error: {exc}"
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": out}]}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if mid is None:
        return None
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        out = handle(msg)
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
