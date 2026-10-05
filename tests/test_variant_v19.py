"""Tests that variant v19 parses and differs from v18 only in its one-box-per-chunk rule, and that the renderer notes
a box shared by chunks and a chunk without exactly one box. Run with `python3 -m unittest discover -s tests` from the
tool's folder."""
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import compare  # noqa: E402
from render import Chunk, note_box_sharing  # noqa: E402

VARIANTS = Path(__file__).resolve().parent.parent / "variants"


def load(name: str) -> dict:
    return tomllib.loads((VARIANTS / f"{name}.toml").read_text())


def diagram(*lines: str) -> str:
    return "```mermaid\nflowchart TD\n" + "\n".join(f"  {line}" for line in lines) + "\n```"


def noted(text: str, *node_lists: list[str]) -> list[str]:
    chunks = [Chunk(f"c{index}", "read", "w", [f"f{index}"], nodes=list(nodes), number=index)
              for index, nodes in enumerate(node_lists, 1)]
    notes: list[str] = []
    note_box_sharing(text, chunks, notes)
    return notes


class VariantV19(unittest.TestCase):
    def setUp(self) -> None:
        self.v18 = load("one_path_risk_chunked_v18")
        self.v19 = load("one_path_risk_chunked_v19")

    def test_it_keeps_every_v18_setting_except_the_description_the_prompt_text_and_one_render_option(self) -> None:
        for key in ("context", "example_additions", "context_options"):
            self.assertEqual(self.v19[key], self.v18[key], key)
        self.assertEqual({**self.v19["render"], "one_box_per_chunk": None}, {**self.v18["render"], "one_box_per_chunk": None})
        self.assertTrue(self.v19["render"]["one_box_per_chunk"])
        self.assertNotIn("one_box_per_chunk", self.v18["render"])
        self.assertNotEqual(self.v19["description"], self.v18["description"])

    def test_the_instructions_make_every_chunk_exactly_one_box(self) -> None:
        text = self.v19["extra_instructions"]
        self.assertIn("Each chunk is exactly one diagram box and each changed box is exactly one chunk", text)
        self.assertIn("the only id in the chunk's `nodes`", text)
        self.assertIn("A box for unchanged context belongs to no chunk", text)
        self.assertIn("merge those steps into one box rather than splitting the file across chunks", text)
        self.assertIn("at most 10 nodes", text)
        self.assertIn('subgraph also["Also in this PR"]', text)
        for gone in ("may be shared", "no chunk has an empty"):
            self.assertNotIn(gone, text)

    def test_the_instructions_differ_from_v18_only_in_the_box_rule(self) -> None:
        before = self.v18["extra_instructions"].split("\n")
        after = self.v19["extra_instructions"].split("\n")
        self.assertEqual(len(before), len(after))
        changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        self.assertEqual(len(changed), 1)
        self.assertTrue(before[changed[0]].startswith("- Every chunk must own at least one box"))

    def test_the_schema_asks_for_exactly_one_node_per_chunk(self) -> None:
        text = self.v19["schema_additions"]
        self.assertIn("exactly one id, the id of the changes_diagram box that is this chunk", text)
        self.assertIn("A file is listed under exactly one box", text)
        for gone in ("empty when nothing in the chunk is on the diagram", "several boxes"):
            self.assertNotIn(gone, text)
        self.assertIn("start (object", text)
        self.assertEqual(text[text.index("start (object"):], self.v18["schema_additions"][self.v18["schema_additions"].index("start (object"):]
                         .replace("A file may be listed under several boxes; test files go with the box whose code they test.",
                                  "A file is listed under exactly one box, the box of its chunk; test files go with the box whose code they test."))

    def test_the_comparison_page_labels_it(self) -> None:
        self.assertEqual(compare.VARIANT_LABELS["one_path_risk_chunked_v19"], "19: one box per chunk")


class BoxSharingNotes(unittest.TestCase):
    TEXT = diagram('a["A"] --> b["B"]', 'b --> c["C"]')

    def test_one_box_per_chunk_gives_no_notes(self) -> None:
        self.assertEqual(noted(self.TEXT, ["a"], ["b"], ["c"]), [])

    def test_a_box_of_unchanged_context_owned_by_no_chunk_gives_no_note(self) -> None:
        self.assertEqual(noted(self.TEXT, ["a"], ["c"]), [])

    def test_a_box_claimed_by_two_chunks_is_noted_once(self) -> None:
        self.assertEqual(noted(self.TEXT, ["a"], ["b"], ["b"]), ["box b is claimed by 2 chunks: 'c2', 'c3'"])

    def test_a_chunk_with_no_box_is_noted(self) -> None:
        self.assertEqual(noted(self.TEXT, ["a"], []), ["chunk 'c2': has no box"])

    def test_a_chunk_with_several_boxes_is_noted(self) -> None:
        self.assertEqual(noted(self.TEXT, ["a", "b"], ["c"]), ["chunk 'c1': has 2 boxes: a, b"])

    def test_a_node_id_that_is_not_in_the_diagram_is_dropped_and_leaves_the_chunk_without_a_box(self) -> None:
        self.assertEqual(noted(self.TEXT, ["a"], ["zzz"]),
                         ["chunk 'c2': ignored node id that is not in the diagram: zzz", "chunk 'c2': has no box"])


if __name__ == "__main__":
    unittest.main()
