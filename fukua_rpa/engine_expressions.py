"""Runtime variables and safe expression actions for the execution engine."""

from __future__ import annotations

import time

from .expressions import (
    BUILTIN_VARIABLE_NAMES,
    ExpressionError,
    compile_expression,
    evaluate_expression,
    parse_assignment,
    validate_variable_name,
)


MAX_RUNTIME_VARIABLES = 128


class ExpressionExecutionMixin:
    def reset_expression_runtime(self):
        self.runtime_variables = {}
        self.expression_cache = {}
        self.assignment_cache = {}
        self.run_started_monotonic = time.monotonic()
        self.last_step_success = False

    def expression_context(self, step_info):
        step = int(step_info.get("step", 0) or 0)
        values = dict(self.runtime_variables)
        values.update(
            {
                "loop": int(step_info.get("loop", 0) or 0),
                "step": step,
                "attempt": int(step_info.get("attempt", 1) or 1),
                "success_count": int(step_info.get("success_count", 0) or 0),
                "execution_count": int(self.step_execution_counts.get(step, 0)),
                "elapsed": max(0.0, time.monotonic() - self.run_started_monotonic),
                "last_success": bool(self.last_step_success),
            }
        )
        return values

    def evaluate_runtime_expression(self, expression, step_info):
        source = str(expression or "").strip()
        tree = self.expression_cache.get(source)
        if tree is None:
            tree = compile_expression(source)
            self.expression_cache[source] = tree
        return evaluate_expression(tree, self.expression_context(step_info))

    def evaluate_breakpoint_condition(self, expression, step_info):
        source = str(expression or "").strip()
        if not source:
            return True, ""
        try:
            return bool(self.evaluate_runtime_expression(source, step_info)), ""
        except ExpressionError as error:
            # A broken condition must never make a requested breakpoint vanish.
            return True, str(error)

    def set_runtime_variable(self, assignment_text, step_info):
        source = str(assignment_text or "").strip()
        assignment = self.assignment_cache.get(source)
        if assignment is None:
            assignment = parse_assignment(source)
            self.assignment_cache[source] = assignment
        if (
            assignment.name not in self.runtime_variables
            and len(self.runtime_variables) >= MAX_RUNTIME_VARIABLES
        ):
            raise ExpressionError(
                f"本次运行最多允许 {MAX_RUNTIME_VARIABLES} 个自定义变量。"
            )
        value = evaluate_expression(
            assignment.tree, self.expression_context(step_info)
        )
        self.runtime_variables[assignment.name] = value
        return assignment.name, value

    def store_runtime_variable(self, name, value):
        normalized = validate_variable_name(str(name or "").strip())
        if (
            normalized not in self.runtime_variables
            and len(self.runtime_variables) >= MAX_RUNTIME_VARIABLES
        ):
            raise ExpressionError(
                f"本次运行最多允许 {MAX_RUNTIME_VARIABLES} 个自定义变量。"
            )
        self.runtime_variables[normalized] = value
        return normalized, value

    def expression_debug_snapshot(self, step=0, loop=0):
        context = self.expression_context(
            {"step": int(step or 0), "loop": int(loop or 0)}
        )
        return {
            name: context[name]
            for name in sorted(context)
            if name in BUILTIN_VARIABLE_NAMES or name in self.runtime_variables
        }
