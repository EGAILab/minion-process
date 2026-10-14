"""Fault-fired accounting for feasibility matrices and control recipes (Part F, contract revision 3 and
checkpoint revision 4).

A filled matrix is YAML:

    rows:
      - id: <row id>
        credited: true | false          # what the author claims for the row
        cells:
          - fault: <planned fault or selection>
            platform: <platform>
            binding: <binding or authority attribution>
            value: fired | unfired | not-applicable | setup-failure
            reason: <required for not-applicable: the authority's declared reason>

A row may be credited only when every planned cell `fired`, or is `not-applicable` with a declared reason.
`unfired` and `setup-failure` never credit a row: a setup or compile failure is never a kill. The kit only
checks the accounting. Whether a fault or an exception is semantically valid stays a reviewer judgment, and
the baseline and intended-witness rules of §9.7 still apply.
"""

from __future__ import annotations

from typing import Any

from .validate import Problem

VALUES = ("fired", "unfired", "not-applicable", "setup-failure")
CELL_KEYS = ("fault", "platform", "binding", "value")


def check(matrix: Any) -> list[Problem]:
    problems: list[Problem] = []
    if not isinstance(matrix, dict) or not isinstance(matrix.get("rows"), list) or not matrix["rows"]:
        return [Problem("error", "rows", "a matrix needs a non-empty list of rows")]
    for index, row in enumerate(matrix["rows"]):
        where = f"rows[{index}]"
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            problems.append(Problem("error", where, "a row needs an id"))
            continue
        where = f"rows[{row['id']}]"
        if not isinstance(row.get("credited"), bool):
            problems.append(Problem("error", where, "credited must be true or false"))
        cells = row.get("cells")
        if not isinstance(cells, list) or not cells:
            problems.append(Problem("error", where, "a row needs one cell per planned fault or selection"))
            continue
        creditable = True
        for c_index, cell in enumerate(cells):
            at = f"{where}.cells[{c_index}]"
            if not isinstance(cell, dict):
                problems.append(Problem("error", at, "a cell must be a mapping"))
                creditable = False
                continue
            missing = [k for k in CELL_KEYS if not isinstance(cell.get(k), str) or not cell.get(k)]
            if missing:
                problems.append(Problem("error", at, f"missing {missing}"))
                creditable = False
                continue
            value = cell["value"]
            if value not in VALUES:
                problems.append(Problem("error", at, f"value must be one of {VALUES}"))
                creditable = False
            elif value == "not-applicable" and not (
                isinstance(cell.get("reason"), str) and cell["reason"].strip()
            ):
                problems.append(Problem("error", at, "not-applicable needs the authority's declared reason"))
                creditable = False
            elif value in ("unfired", "setup-failure"):
                creditable = False
        if row.get("credited") is True and not creditable:
            problems.append(
                Problem(
                    "error",
                    where,
                    "credited, but not every planned cell fired or is a declared not-applicable",
                )
            )
    return problems
