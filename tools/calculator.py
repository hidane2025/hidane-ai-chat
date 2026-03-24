"""安全な計算ツール。
助成金の計算、経理計算等に使用。eval()は使わず、astで安全に評価。
"""

import ast
import operator

TOOL_DEF = {
    "name": "calculator",
    "description": "数式を安全に計算します。助成金額の概算、経費計算、売上集計などに使えます。四則演算と括弧に対応。",
    "input_schema": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "計算式（例: 40 * 0.75 * 8、(960 + 240) * 0.75）",
            },
            "description": {
                "type": "string",
                "description": "何の計算か（例: 8名×3コースの助成金額）",
            },
        },
        "required": ["expression"],
    },
}

# 許可する演算子
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}


def _safe_eval(node):
    """ASTノードを安全に評価する。"""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"許可されていない値: {node.value}")
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _OPS:
            raise ValueError(f"許可されていない演算子: {op_type.__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        return _OPS[op_type](left, right)
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _OPS:
            raise ValueError(f"許可されていない演算子: {op_type.__name__}")
        return _OPS[op_type](_safe_eval(node.operand))
    raise ValueError(f"許可されていないノード: {type(node).__name__}")


def execute(params: dict) -> str:
    """数式を安全に評価して結果を返す。"""
    expression = params.get("expression", "").strip()
    description = params.get("description", "")
    if not expression:
        return "計算式を指定してください。"

    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree)

        # 整数で表現できる場合は整数に
        if isinstance(result, float) and result == int(result):
            result = int(result)

        formatted = f"{result:,}" if isinstance(result, (int, float)) else str(result)
        desc_line = f"\n計算内容: {description}" if description else ""
        return f"計算式: {expression}\n結果: {formatted}{desc_line}"

    except (ValueError, SyntaxError, ZeroDivisionError) as e:
        return f"計算エラー: {str(e)}\n式: {expression}"
