"""Tests for the diagram edge parser and the arrow counts. All data here is invented. Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render import count_diagram_edges, parse_diagram_edges  # noqa: E402


def diagram(*lines: str) -> str:
    return "```mermaid\nflowchart TD\n" + "\n".join(f"  {line}" for line in lines) + "\n```"


class ParseEdges(unittest.TestCase):
    def test_every_connector_form_is_an_edge_with_its_label_state(self) -> None:
        text = diagram('a["A"] --> b["B"]', 'b -- text --> c["C"]', 'c -->|text| d["D"]', 'd -. back .-> a',
                       'a == big ==> d', 'a & b --> e["E"]')
        edges = parse_diagram_edges(text)
        self.assertEqual([(e.source, e.target, e.labelled) for e in edges],
                         [("a", "b", False), ("b", "c", True), ("c", "d", True), ("d", "a", True), ("a", "d", True),
                          ("a", "e", False), ("b", "e", False)])
        self.assertEqual(count_diagram_edges(text), (4, 7))

    def test_style_and_subgraph_lines_are_not_edges(self) -> None:
        text = diagram('subgraph also["Also in this PR"]', 'x["X"]', 'end', 'classDef save fill:#fff', 'class a,b save')
        self.assertEqual(parse_diagram_edges(text), [])


if __name__ == "__main__":
    unittest.main()
