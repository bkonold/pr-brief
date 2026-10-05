"""Tests for the chunks each chunk is followed by (`next` in review.json) and the edge parser behind them. All data
here is invented. Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render import Chunk, assign_following, count_diagram_edges, parse_diagram_edges, review_json  # noqa: E402


def diagram(*lines: str) -> str:
    return "```mermaid\nflowchart TD\n" + "\n".join(f"  {line}" for line in lines) + "\n```"


def chunks_of(*node_lists: list[str]) -> list[Chunk]:
    return [Chunk(f"c{index}", "read", "w", [f"f{index}"], nodes=list(nodes), number=index)
            for index, nodes in enumerate(node_lists, 1)]


def following(text: str, *node_lists: list[str]) -> list[list[int]]:
    chunks = chunks_of(*node_lists)
    assign_following(text, chunks)
    return [chunk.following for chunk in chunks]


class Following(unittest.TestCase):
    def test_a_linear_path_leads_each_chunk_to_the_next_and_the_last_to_nothing(self) -> None:
        text = diagram('a["A"] --> b["B"]', 'b --> c["C"]')
        self.assertEqual(following(text, ["a"], ["b"], ["c"]), [[2], [3], []])

    def test_a_branch_gives_every_chunk_it_reaches_in_diagram_order(self) -> None:
        text = diagram('a["A"] --> b["B"]', 'a -->|no match| c["C"]', 'a --> d["D"]')
        self.assertEqual(following(text, ["a"], ["b"], ["c"], ["d"]), [[2, 3, 4], [3], [4], []])

    def test_a_branch_is_capped_at_three(self) -> None:
        text = diagram('a["A"] --> b["B"]', 'a --> c["C"]', 'a --> d["D"]', 'a --> e["E"]')
        self.assertEqual(following(text, ["a"], ["b"], ["c"], ["d"], ["e"])[0], [2, 3, 4])

    def test_a_box_of_the_same_chunk_is_walked_through(self) -> None:
        text = diagram('a["A"] --> a2["A2"]', 'a2 --> b["B"]')
        self.assertEqual(following(text, ["a", "a2"], ["b"]), [[2], []])

    def test_a_context_box_is_walked_through(self) -> None:
        text = diagram('a["A"] --> ctx["Context"]', 'ctx --> b["B"]')
        self.assertEqual(following(text, ["a"], ["b"]), [[2], []])

    def test_a_walk_stops_at_the_first_other_chunk_on_each_branch(self) -> None:
        text = diagram('a["A"] --> b["B"]', 'b --> c["C"]')
        self.assertEqual(following(text, ["a"], ["b"], ["c"])[0], [2])

    def test_a_loop_ends_and_never_names_the_chunk_itself(self) -> None:
        text = diagram('a["A"] --> ctx1["X"]', 'ctx1 --> ctx2["Y"]', 'ctx2 --> ctx1', 'ctx2 --> a', 'ctx2 --> b["B"]')
        self.assertEqual(following(text, ["a"], ["b"]), [[2], []])

    def test_a_cycle_through_context_alone_falls_back_to_the_next_number(self) -> None:
        text = diagram('a["A"] --> x["X"]', 'x --> y["Y"]', 'y --> x', 'b["B"]')
        self.assertEqual(following(text, ["a"], ["b"]), [[2], []])

    def test_a_box_owned_by_two_chunks_gives_both(self) -> None:
        text = diagram('a["A"] --> shared["S"]')
        self.assertEqual(following(text, ["a"], ["shared"], ["shared"]), [[2, 3], [3], []])

    def test_a_box_shared_with_an_earlier_chunk_never_leads_backward(self) -> None:
        text = diagram('s["S"]', 'b["B"] --> s')
        self.assertEqual(following(text, ["s"], ["b"], ["s"])[1], [3])

    def test_a_chunk_that_reaches_only_earlier_chunks_falls_back_to_the_next_number(self) -> None:
        text = diagram('s["S"]', 'b["B"] --> s', 'c["C"]')
        self.assertEqual(following(text, ["s"], ["b"], ["c"])[1], [3])

    def test_a_return_arrow_is_not_a_step_forward(self) -> None:
        text = diagram('a["A"] --> b["B"]', 'b -.->|redirect back| a')
        self.assertEqual(following(text, ["a"], ["b"]), [[2], []])

    def test_a_chunk_off_the_diagram_is_followed_by_the_next_number_and_the_last_by_nothing(self) -> None:
        text = diagram('a["A"] --> b["B"]')
        self.assertEqual(following(text, ["a"], ["b"], []), [[2], [3], []])

    def test_a_missing_diagram_gives_the_next_number(self) -> None:
        self.assertEqual(following("", [], [], []), [[2], [3], []])

    def test_chained_arrows_and_fan_out_are_edges(self) -> None:
        text = diagram('a["A"] --> b["B"] --> c["C"]', 'c --> d["D"] & e["E"]')
        self.assertEqual(following(text, ["a"], ["b"], ["c"], ["d"], ["e"]), [[2], [3], [4, 5], [5], []])

    def test_chunks_are_ordered_by_where_their_box_is_declared_not_by_number(self) -> None:
        text = diagram('a["A"] --> y["Y"]', 'a --> x["X"]')
        self.assertEqual(following(text, ["a"], ["x"], ["y"])[0], [3, 2])


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


class ReviewJson(unittest.TestCase):
    def test_every_chunk_carries_next(self) -> None:
        chunks = chunks_of(["a"], ["b"])
        assign_following(diagram('a["A"] --> b["B"]'), chunks)
        run = {"repo": "r", "pr": 1, "pr_head_sha": "s", "variant": "v"}
        pr = {"files": [{"path": "f1", "additions": 1, "deletions": 0}, {"path": "f2", "additions": 1, "deletions": 0}]}
        out = review_json(run, pr, chunks, True, None)
        self.assertEqual([c["next"] for c in out["chunks"]], [[2], []])
        self.assertEqual(out["schema"], 2)


if __name__ == "__main__":
    unittest.main()
