"""Small, non-executable expression language for workflow variables."""

from __future__ import annotations

import ast
import math
import operator
from dataclasses import dataclass
from typing import Any, Mapping


MAX_EXPRESSION_LENGTH = 500
MAX_EXPRESSION_NODES = 128
MAX_VARIABLE_NAME_LENGTH = 64
MAX_STRING_LENGTH = 1024
MAX_NUMBER_MAGNITUDE = 1e15
MAX_POWER_EXPONENT = 12

BUILTIN_VARIABLE_NAMES = frozenset(
    {
        "loop",
        "step",
        "attempt",
        "success_count",
        "execution_count",
        "elapsed",
        "last_success",
    }
)


class ExpressionError(ValueError):
    pass


@dataclass(frozen=True)
class Assignment:
    name: str
    expression: str
    tree: ast.Expression


ALLOWED_NODES = (
    ast.Expression,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.BinOp,
    ast.UnaryOp,
    ast.BoolOp,
    ast.Compare,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.UAdd,
    ast.USub,
    ast.Not,
    ast.And,
    ast.Or,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)


def validate_variable_name(name: str, *, assignment_target: bool = True) -> str:
    normalized = str(name or "").strip()
    if not normalized or len(normalized) > MAX_VARIABLE_NAME_LENGTH:
        raise ExpressionError(
            f"变量名长度必须为 1 到 {MAX_VARIABLE_NAME_LENGTH} 个字符。"
        )
    if not normalized.isidentifier() or normalized.startswith("_"):
        raise ExpressionError("变量名只能使用文字、数字和下划线，不能以数字或下划线开头。")
    if assignment_target and normalized in BUILTIN_VARIABLE_NAMES:
        raise ExpressionError(f"“{normalized}”是只读运行变量，不能被覆盖。")
    return normalized


def compile_expression(text: Any) -> ast.Expression:
    source = str(text or "").strip()
    if not source:
        raise ExpressionError("表达式不能为空。")
    if len(source) > MAX_EXPRESSION_LENGTH:
        raise ExpressionError(f"表达式不能超过 {MAX_EXPRESSION_LENGTH} 个字符。")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as error:
        detail = error.msg or "语法错误"
        raise ExpressionError(f"表达式语法错误：{detail}") from error
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_EXPRESSION_NODES:
        raise ExpressionError(f"表达式过于复杂，最多允许 {MAX_EXPRESSION_NODES} 个语法节点。")
    for node in nodes:
        if not isinstance(node, ALLOWED_NODES):
            raise ExpressionError(
                f"表达式不允许使用 {type(node).__name__}；函数、属性、下标和导入均被禁止。"
            )
        if isinstance(node, ast.Name):
            validate_variable_name(node.id, assignment_target=False)
        if isinstance(node, ast.Constant):
            _bounded_value(node.value)
    return tree


def parse_assignment(text: Any) -> Assignment:
    source = str(text or "").strip()
    if not source:
        raise ExpressionError("变量赋值不能为空，例如：count = count + 1。")
    if len(source) > MAX_EXPRESSION_LENGTH:
        raise ExpressionError(f"变量赋值不能超过 {MAX_EXPRESSION_LENGTH} 个字符。")
    try:
        module = ast.parse(source, mode="exec")
    except SyntaxError as error:
        raise ExpressionError(f"变量赋值语法错误：{error.msg or '语法错误'}") from error
    if len(module.body) != 1 or not isinstance(module.body[0], ast.Assign):
        raise ExpressionError("请使用单个赋值，格式例如：count = count + 1。")
    statement = module.body[0]
    if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
        raise ExpressionError("赋值左侧必须是一个变量名，不能使用属性或下标。")
    name = validate_variable_name(statement.targets[0].id)
    expression = ast.get_source_segment(source, statement.value)
    if not expression:
        try:
            expression = ast.unparse(statement.value)
        except Exception as error:
            raise ExpressionError("无法读取赋值右侧的表达式。") from error
    tree = compile_expression(expression)
    return Assignment(name=name, expression=expression, tree=tree)


def evaluate_expression(
    expression: str | ast.Expression, variables: Mapping[str, Any]
) -> Any:
    tree = compile_expression(expression) if isinstance(expression, str) else expression
    environment = {str(name): _bounded_value(value) for name, value in variables.items()}
    return _bounded_value(_evaluate_node(tree.body, environment))


def _bounded_value(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if abs(value) > MAX_NUMBER_MAGNITUDE:
            raise ExpressionError("计算结果数字过大。")
        return value
    if isinstance(value, float):
        if not math.isfinite(value) or abs(value) > MAX_NUMBER_MAGNITUDE:
            raise ExpressionError("计算结果必须是有限且大小合理的数字。")
        return value
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise ExpressionError(f"文本结果不能超过 {MAX_STRING_LENGTH} 个字符。")
        return value
    raise ExpressionError(f"表达式只允许数字、文本、布尔值和空值，不能使用 {type(value).__name__}。")


def _evaluate_node(node: ast.AST, variables: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return _bounded_value(node.value)
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise ExpressionError(f"变量“{node.id}”尚未设置。")
        return variables[node.id]
    if isinstance(node, ast.UnaryOp):
        value = _evaluate_node(node.operand, variables)
        if isinstance(node.op, ast.Not):
            return not bool(value)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ExpressionError("正负号只能用于数字。")
        return _bounded_value(+value if isinstance(node.op, ast.UAdd) else -value)
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result = True
            for item in node.values:
                result = _evaluate_node(item, variables)
                if not bool(result):
                    return result
            return result
        result = False
        for item in node.values:
            result = _evaluate_node(item, variables)
            if bool(result):
                return result
        return result
    if isinstance(node, ast.BinOp):
        left = _evaluate_node(node.left, variables)
        right = _evaluate_node(node.right, variables)
        return _binary_operation(node.op, left, right)
    if isinstance(node, ast.Compare):
        left = _evaluate_node(node.left, variables)
        for operation, comparator in zip(node.ops, node.comparators, strict=True):
            right = _evaluate_node(comparator, variables)
            try:
                matched = _compare_operation(operation, left, right)
            except TypeError as error:
                raise ExpressionError("比较两侧的值类型不兼容。") from error
            if not matched:
                return False
            left = right
        return True
    raise ExpressionError(f"不支持的表达式节点：{type(node).__name__}。")


def _binary_operation(operation: ast.operator, left: Any, right: Any) -> Any:
    if isinstance(operation, ast.Pow):
        if not isinstance(right, (int, float)) or isinstance(right, bool):
            raise ExpressionError("乘方指数必须是数字。")
        if abs(right) > MAX_POWER_EXPONENT:
            raise ExpressionError(f"乘方指数绝对值不能超过 {MAX_POWER_EXPONENT}。")
    if isinstance(operation, ast.Mult) and (
        isinstance(left, str) or isinstance(right, str)
    ):
        text, count = (left, right) if isinstance(left, str) else (right, left)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ExpressionError("文本只能乘以非负整数。")
        if len(text) * count > MAX_STRING_LENGTH:
            raise ExpressionError(f"文本结果不能超过 {MAX_STRING_LENGTH} 个字符。")
    functions = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    function = functions.get(type(operation))
    if function is None:
        raise ExpressionError(f"不支持的运算符：{type(operation).__name__}。")
    try:
        return _bounded_value(function(left, right))
    except ZeroDivisionError as error:
        raise ExpressionError("表达式不能除以 0。") from error
    except (TypeError, OverflowError, ValueError) as error:
        raise ExpressionError("运算两侧的值类型不兼容或结果超出限制。") from error


def _compare_operation(operation: ast.cmpop, left: Any, right: Any) -> bool:
    functions = {
        ast.Eq: operator.eq,
        ast.NotEq: operator.ne,
        ast.Lt: operator.lt,
        ast.LtE: operator.le,
        ast.Gt: operator.gt,
        ast.GtE: operator.ge,
    }
    function = functions.get(type(operation))
    if function is None:
        raise ExpressionError(f"不支持的比较符：{type(operation).__name__}。")
    return bool(function(left, right))
