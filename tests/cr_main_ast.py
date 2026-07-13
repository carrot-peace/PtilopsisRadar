"""AST helpers for CR dispatch-hook structure checks in ``__main__.py``."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


MAIN_PATH = Path(__file__).resolve().parent.parent / "trendradar" / "__main__.py"


def call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and call_name(child) == name
    ]


def import_from_nodes(node: ast.AST, module: str) -> list[ast.ImportFrom]:
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.ImportFrom) and child.module == module
    ]


def assigned_name(statement: ast.stmt) -> str | None:
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        target = statement.targets[0]
        return target.id if isinstance(target, ast.Name) else None
    return None


def _is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _is_comparison(
    node: ast.AST,
    left_name: str,
    operator: type[ast.cmpop],
    right_name: str,
) -> bool:
    if not (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], operator)
        and len(node.comparators) == 1
    ):
        return False
    left = node.left
    right = node.comparators[0]
    return (
        _is_name(left, left_name) and _is_name(right, right_name)
    ) or (
        _is_name(left, right_name) and _is_name(right, left_name)
    )


def _find_main_pipeline(tree: ast.Module) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "NewsAnalyzer":
            for child in node.body:
                if (
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name == "_run_analysis_pipeline"
                ):
                    return child
    raise AssertionError("NewsAnalyzer._run_analysis_pipeline not found")


@dataclass(frozen=True)
class CRDispatchHook:
    tree: ast.Module
    function: ast.FunctionDef
    resolve_assignment: ast.Assign
    off_gate: ast.If
    live_gate: ast.If
    runtime_call: ast.Call


def load_cr_dispatch_hook() -> CRDispatchHook:
    tree = ast.parse(MAIN_PATH.read_text(encoding="utf-8"))
    function = _find_main_pipeline(tree)

    resolve_assignment = next(
        (
            node
            for node in ast.walk(function)
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and _is_name(node.targets[0], "_cr_mode")
            and isinstance(node.value, ast.Call)
            and call_name(node.value) == "resolve_cr_dispatch_mode"
        ),
        None,
    )
    if resolve_assignment is None:
        raise AssertionError("dispatch mode resolver assignment not found")

    off_gate = next(
        (
            node
            for node in ast.walk(function)
            if isinstance(node, ast.If)
            and _is_comparison(
                node.test, "_cr_mode", ast.NotEq, "CR_DISPATCH_OFF"
            )
        ),
        None,
    )
    if off_gate is None:
        raise AssertionError("off dispatch gate not found")

    live_gate = next(
        (
            node
            for node in ast.walk(off_gate)
            if isinstance(node, ast.If)
            and _is_comparison(
                node.test, "_cr_mode", ast.Eq, "CR_DISPATCH_LIVE"
            )
        ),
        None,
    )
    if live_gate is None:
        raise AssertionError("live dispatch gate not found inside off gate")

    runtime_calls = calls(off_gate, "build_and_write_cr_runtime_dry_run")
    if len(runtime_calls) != 1:
        raise AssertionError(
            "expected exactly one build_and_write_cr_runtime_dry_run call "
            f"inside dispatch hook, found {len(runtime_calls)}"
        )

    return CRDispatchHook(
        tree=tree,
        function=function,
        resolve_assignment=resolve_assignment,
        off_gate=off_gate,
        live_gate=live_gate,
        runtime_call=runtime_calls[0],
    )
