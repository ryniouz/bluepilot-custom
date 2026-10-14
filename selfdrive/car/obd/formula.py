"""
Custom: safe evaluator for OBD PID formulas (stream B).

Formulas use the common scanner-app dialect: response bytes are A..H, helpers INT16(a, b), SIGNED(a),
and if(cond; then; else) with a single `=` for equality. They are parsed into a Python AST and only
arithmetic, comparisons, byte names and the helpers are allowed, so a catalog file cannot run code.
"""
import ast
import re

_BARE_EQ = re.compile(r"(?<![=<>!])=(?!=)")
_ALLOWED_NODES = (
  ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load, ast.Call, ast.Compare,
  ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.USub, ast.UAdd,
  ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.BitAnd, ast.BitOr, ast.RShift, ast.LShift,
)
BYTE_NAMES = "ABCDEFGH"


def _sbyte(a):
  return a - 256 if a > 127 else a


FUNCS = {
  "INT16": lambda a, b: a * 256 + b,
  "UINT16": lambda a, b: a * 256 + b,
  "SIGNED": _sbyte,
  "INT8": _sbyte,
  "_if": lambda c, a, b: a if c else b,
}


_FUNC_NAMES = {k.upper() for k in FUNCS}


class FormulaError(ValueError):
  pass


def _translate(formula: str) -> str:
  out = formula.strip()
  if "if(" in out or ";" in out:
    out = out.replace("if(", "_if(").replace(";", ",")
    out = _BARE_EQ.sub("==", out)
  return out


class Formula:
  def __init__(self, text: str):
    self.text = text
    try:
      tree = ast.parse(_translate(text), mode="eval")
    except SyntaxError as e:
      raise FormulaError(f"bad formula {text!r}: {e.msg}") from None
    for node in ast.walk(tree):
      if not isinstance(node, _ALLOWED_NODES):
        raise FormulaError(f"formula {text!r} uses {type(node).__name__}, which is not allowed")
      if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id.upper() not in _FUNC_NAMES:
          raise FormulaError(f"formula {text!r} calls an unknown function")
      elif isinstance(node, ast.Name) and node.id.upper() not in _FUNC_NAMES and node.id not in BYTE_NAMES:
        raise FormulaError(f"formula {text!r} uses unknown name {node.id!r}")
    self._code = compile(tree, "<pid formula>", "eval")

  def __call__(self, data: bytes) -> float:
    env = {n: (data[i] if i < len(data) else 0) for i, n in enumerate(BYTE_NAMES)}
    for k, f in FUNCS.items():
      env[k] = env[k.lower()] = f
    return float(eval(self._code, {"__builtins__": {}}, env))
