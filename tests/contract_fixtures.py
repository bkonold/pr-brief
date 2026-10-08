"""Builders for the invented OpenAPI documents and diffs the contract tests share."""
import difflib

from context_pack import contract_breaks, contract_changes

SPEC = "api/openapi.json"


def make_diff(path: str, before: str, after: str) -> str:
    body = difflib.unified_diff(before.splitlines(), after.splitlines(), f"a/{path}", f"b/{path}", lineterm="", n=3)
    return f"diff --git a/{path} b/{path}\n" + "\n".join(body)


def operation(operation_id: str, parameters: list | None = None) -> dict:
    return {"operationId": operation_id, "parameters": parameters or [], "responses": {"200": {"description": "ok"}}}


def document(paths: dict, schemas: dict, parameters: dict | None = None) -> dict:
    return {"openapi": "3.0.1", "paths": paths, "components": {"schemas": schemas, "parameters": parameters or {}}}


def contract_of(base: dict, head: dict) -> dict:
    breaks = contract_breaks(base, head)
    return {"path": SPEC, **breaks, **contract_changes(base, head, breaks)}
