"""Scores the chunks of a run against a hand-written grouping of the same PR.

    python scripts/eval_chunks.py <run dir> <expected.toml>

The run dir is a run's folder (`runs/<key>/<variant>/`): `review.json` says which chunk each hunk landed in and `prompt.txt`
holds the diff the model saw, whose hunks are numbered the way the model numbered them. The TOML has one table per expected
chunk, `[chunks."Name"]`, with `hunks`, a list of entries: a bare path is every hunk of that file, and `path:a-b` (or `path:a`)
is the hunks whose new-side lines overlap a to b, or whose old-side lines do when the hunk adds no lines (a deletion).

It prints the pair agreement (among the pairs of hunks that both groupings place, the share on which they agree about being
in the same chunk), where the hunks of each expected chunk landed, and the hunks the expected file does not mention. An entry
that matches no hunk, or a hunk in two expected chunks, is an error: it is printed to stderr and the exit status is 1.
"""
import argparse
import json
import re
import sys
import tomllib
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from contract_lines import plural  # noqa: E402
from hunks import Hunk, hunk_number, parse_hunks  # noqa: E402
from render import diff_from_prompt  # noqa: E402

RANGE_ENTRY = re.compile(r"^(?P<path>.+?):(?P<first>\d+)(?:-(?P<last>\d+))?$")
UNPLACED = "none"


class EvalError(Exception):
    pass


def adds_lines(hunk: Hunk) -> bool:
    return any(line.startswith("+") for line in hunk.lines)


def overlaps(hunk: Hunk, first: int, last: int) -> bool:
    """Whether the hunk's new lines, or its old lines when it adds none, include a line from `first` to `last`."""
    start, count = (hunk.new_start, hunk.new_count) if adds_lines(hunk) else (hunk.old_start, hunk.old_count)
    return count > 0 and start <= last and first < start + count


def resolve_entry(entry: str, hunks: list[Hunk]) -> list[str]:
    """The ids of the hunks an entry names, in diff order; empty when it names none."""
    found: re.Match[str] | None = RANGE_ENTRY.match(entry)
    if not found:
        return [hunk.id for hunk in hunks if hunk.path == entry]
    first: int = int(found.group("first"))
    last: int = int(found.group("last") or first)
    return [hunk.id for hunk in hunks if hunk.path == found.group("path") and overlaps(hunk, first, last)]


def resolve_expected(expected: dict[str, list[str]], hunks: list[Hunk]) -> tuple[dict[str, str], list[str]]:
    """Each hunk the expected chunks name, with the chunk that has it, and the errors found. A hunk named by two chunks stays
    with the first."""
    placed: dict[str, str] = {}
    errors: list[str] = []
    for name, entries in expected.items():
        for entry in entries:
            ids: list[str] = resolve_entry(entry, hunks)
            if not ids:
                errors.append(f'{name}: "{entry}" matches no hunk')
            for hunk_id in ids:
                if placed.setdefault(hunk_id, name) != name:
                    errors.append(f"{name}: {hunk_id} is already in {placed[hunk_id]}")
    return placed, errors


def pair_agreement(expected: dict[str, str], actual: dict[str, int]) -> tuple[int, int]:
    """Among the pairs of hunks both groupings place, how many pairs both say are in one chunk or both say are in different
    chunks, and how many pairs there are."""
    both: list[str] = sorted(set(expected) & set(actual), key=hunk_number)
    agree: int = sum(1 for a, b in combinations(both, 2) if (expected[a] == expected[b]) == (actual[a] == actual[b]))
    return agree, len(both) * (len(both) - 1) // 2


def landed(expected: dict[str, str], actual: dict[str, int]) -> dict[str, dict[str | int, int]]:
    """For each expected chunk, how many of its hunks are in each actual chunk (`none` for a hunk the run did not place)."""
    found: dict[str, dict[str | int, int]] = {}
    for hunk_id, name in expected.items():
        spread: dict[str | int, int] = found.setdefault(name, {})
        where: str | int = actual.get(hunk_id, UNPLACED)
        spread[where] = spread.get(where, 0) + 1
    return found


def report(expected: dict[str, list[str]], placed: dict[str, str], actual: dict[str, int], hunks: list[Hunk]) -> str:
    agree, total = pair_agreement(placed, actual)
    lines: list[str] = [f"Pair agreement: {100 * agree / total:.1f}% ({agree} of {plural(total, 'pair')})" if total
                        else "Pair agreement: no pairs to compare", ""]
    where: dict[str, dict[str | int, int]] = landed(placed, actual)
    for name in expected:
        spread: dict[str | int, int] = where.get(name, {})
        order: list[str | int] = sorted(spread, key=lambda key: (isinstance(key, str), key if isinstance(key, int) else 0))
        lines.append(f"{name} → " + (", ".join(f"{key} ({plural(spread[key], 'hunk')})" for key in order) if spread else "no hunks"))
    unmentioned: list[str] = [hunk.id for hunk in hunks if hunk.id not in placed]
    lines += ["", f"Hunks the expected file does not mention ({len(unmentioned)}): {', '.join(unmentioned) or 'none'}"]
    return "\n".join(lines)


def load_actual(run_dir: Path) -> tuple[list[Hunk], dict[str, int]]:
    """The hunks of the diff the model saw, and the number of the chunk each hunk landed in."""
    review: dict[str, Any] = json.loads((run_dir / "review.json").read_text())
    if "chunks" not in review:
        raise EvalError(f"{run_dir / 'review.json'} has no chunks")
    hunks: list[Hunk] = parse_hunks(diff_from_prompt((run_dir / "prompt.txt").read_text()))
    return hunks, {hunk["id"]: chunk["i"] for chunk in review["chunks"] for hunk in chunk["hunks"]}


def load_expected(path: Path) -> dict[str, list[str]]:
    chunks: Any = tomllib.loads(path.read_text()).get("chunks")
    if not isinstance(chunks, dict) or not chunks:
        raise EvalError(f"{path} has no [chunks.\"...\"] tables")
    return {str(name): [str(entry) for entry in table.get("hunks", [])] for name, table in chunks.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score a run's chunks against an expected grouping.")
    parser.add_argument("run_dir")
    parser.add_argument("expected")
    args = parser.parse_args(argv)
    try:
        hunks, actual = load_actual(Path(args.run_dir))
        expected: dict[str, list[str]] = load_expected(Path(args.expected))
    except (EvalError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    placed, errors = resolve_expected(expected, hunks)
    print(report(expected, placed, actual, hunks))
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
