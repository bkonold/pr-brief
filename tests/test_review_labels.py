"""Tests for the effort levels (verify, read, skim) and the check labels on each chunk. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from render import (  # noqa: E402
    LEVELS, Chunk, build_chunks, clean_checks, derive_labels, file_floor, generated_share, is_destructive_sql,
    normalize_level, review_json, style_levels,
)

SPEC = "api/openapi.json"
SDK = "web/sdk/generated.ts"
CONTROLLER = "api/controllers/ItemController.java"
DTO = "api/models/ItemRequest.java"
SERVICE = "api/services/ItemService.java"
MIGRATION = "api/db/migration/V9__items.sql"
FLOORS = {"tag": [{"name": "generated", "globs": [SPEC, SDK]}]}
CONTRACT = {"path": SPEC, "removals": ["removed operation GET /api/items/archive"],
            "newly_required": ["ItemRequest.owner (now required)"]}
PATHS = [SPEC, SDK, CONTROLLER, DTO, SERVICE, MIGRATION, "docs/notes.md"]
COUNTS = {path.lower(): (3, 1) for path in PATHS}
DIFF_LINES = {
    CONTROLLER: [("R", 4, '@GetMapping("/archive")'), ("R", 9, "return items.list();")],
    DTO: [("R", 2, "public record ItemRequest(String owner) {}")],
    SERVICE: [("R", 5, "return repository.findAll();")],
}


def raw(name: str, review: str, files: list[str], checks: list[str] | None = None) -> dict:
    return {"name": name, "review": review, "why": "w", "files": files, **({} if checks is None else {"checks": checks})}


def build(chunks: list[dict], contract: dict | None = None, migration_added: dict | None = None,
          notes: list[str] | None = None, paths: list[str] = PATHS, floors: dict = FLOORS) -> list[Chunk]:
    return build_chunks(chunks, COUNTS, paths, floors, [] if notes is None else notes, DIFF_LINES, contract,
                        review_labels=True, migration_added=migration_added)


class Levels(unittest.TestCase):
    def test_the_levels_run_from_skim_to_verify(self) -> None:
        self.assertEqual(LEVELS, ["skim", "read", "verify"])

    def test_legacy_read_carefully_is_verify(self) -> None:
        self.assertEqual(normalize_level("read carefully"), "verify")
        self.assertEqual(normalize_level(" Read  Carefully "), "verify")

    def test_the_new_words_map_to_themselves_and_others_to_none(self) -> None:
        for level in LEVELS:
            self.assertEqual(normalize_level(level.upper()), level)
        self.assertIsNone(normalize_level("careful"))
        self.assertIsNone(normalize_level(None))

    def test_a_legacy_model_answer_renders_as_verify(self) -> None:
        chunks = build_chunks([raw("A", "read carefully", [SERVICE])], COUNTS, [SERVICE], {}, [], {})
        self.assertEqual(chunks[0].review, "verify")

    def test_a_floor_may_use_a_legacy_level_word(self) -> None:
        floors = {"floor": [{"name": "schema", "level": "read carefully", "globs": ["**/*.sql"]}]}
        self.assertEqual(file_floor(floors, MIGRATION, 0), ("verify", "schema"))

    def test_an_unknown_level_falls_back_to_read_with_a_note(self) -> None:
        notes: list[str] = []
        chunks = build([raw("A", "careful", [SERVICE])], notes=notes, paths=[SERVICE])
        self.assertEqual(chunks[0].review, "read")
        self.assertEqual(notes, ["chunk 'A': unknown review level 'careful', using 'read'"])

    def test_the_catch_all_chunk_is_skim_for_labelled_variants_and_read_otherwise(self) -> None:
        self.assertEqual(build([raw("A", "read", [SERVICE])], paths=[SERVICE, "docs/notes.md"])[-1].review, "skim")
        legacy = build_chunks([raw("A", "read", [SERVICE])], COUNTS, [SERVICE, "docs/notes.md"], {}, [], {})
        self.assertEqual(legacy[-1].review, "read")


class Checks(unittest.TestCase):
    def test_only_the_models_four_checks_are_kept_in_display_order(self) -> None:
        notes: list[str] = []
        self.assertEqual(clean_checks(["access", "logic", "breaking", "logic"], "A", notes), ["logic", "access"])
        self.assertEqual(notes, ["chunk 'A': unknown check 'breaking', dropped"])

    def test_a_comma_separated_string_is_accepted_and_more_than_three_are_cut(self) -> None:
        notes: list[str] = []
        self.assertEqual(clean_checks("logic, contract, data, access", "A", notes), ["logic", "contract", "data"])
        self.assertEqual(notes, ["chunk 'A': 4 checks, kept the first 3"])

    def test_a_missing_list_is_empty(self) -> None:
        self.assertEqual(clean_checks(None, "A", []), [])


class DeriveLabels(unittest.TestCase):
    def test_labels_come_out_in_display_order(self) -> None:
        self.assertEqual(derive_labels(["access", "logic", "data", "contract"], False, False, False),
                         ["logic", "contract", "data", "access"])

    def test_breaking_replaces_contract_and_destructive_replaces_data(self) -> None:
        self.assertEqual(derive_labels(["logic", "contract", "data"], True, True, False), ["logic", "breaking", "destructive"])

    def test_breaking_and_destructive_appear_even_when_the_model_did_not_tag_them(self) -> None:
        self.assertEqual(derive_labels([], True, True, False), ["breaking", "destructive"])

    def test_generated_comes_last(self) -> None:
        self.assertEqual(derive_labels(["access"], False, False, True), ["access", "generated"])


class Destructive(unittest.TestCase):
    def test_statements_that_lose_or_narrow_data_are_destructive(self) -> None:
        for sql in ("DROP TABLE items;", "alter table items drop column legacy;", "DELETE FROM items WHERE x = 1;",
                    "TRUNCATE items;", "ALTER TABLE items ALTER COLUMN qty TYPE integer;",
                    "ALTER TABLE items ALTER COLUMN qty SET DATA TYPE integer;",
                    "ALTER TABLE items ALTER COLUMN qty SET NOT NULL;", "DROP INDEX idx_items;"):
            self.assertTrue(is_destructive_sql([sql]), sql)

    def test_additive_and_loosening_statements_are_not(self) -> None:
        for sql in ("ALTER TABLE items ADD COLUMN note text;", "CREATE INDEX idx ON items (id);",
                    "UPDATE items SET note = '';", "ALTER TABLE items ALTER COLUMN qty DROP NOT NULL;",
                    "ALTER TABLE items ALTER COLUMN qty DROP DEFAULT;",
                    "ALTER TABLE items ADD FOREIGN KEY (o) REFERENCES o (id) ON DELETE CASCADE;",
                    "ALTER TABLE items ADD COLUMN note text; -- DROP later"):
            self.assertFalse(is_destructive_sql([sql]), sql)

    def test_a_migration_with_a_destructive_line_marks_its_chunk_and_raises_it_to_verify(self) -> None:
        chunks = build([raw("Items table", "skim", [MIGRATION], ["data"]), raw("Service", "read", [SERVICE], ["logic"])],
                       migration_added={MIGRATION: ["ALTER TABLE items DROP COLUMN legacy;"]}, paths=[MIGRATION, SERVICE])
        self.assertEqual((chunks[0].labels, chunks[0].review, chunks[0].raised_by),
                         (["destructive"], "verify", ["destructive migration"]))
        self.assertEqual((chunks[1].labels, chunks[1].review), (["logic"], "read"))

    def test_an_additive_migration_keeps_data_and_its_level(self) -> None:
        chunks = build([raw("Items table", "read", [MIGRATION], ["data"])],
                       migration_added={MIGRATION: ["ALTER TABLE items ADD COLUMN note text;"]}, paths=[MIGRATION])
        self.assertEqual((chunks[0].labels, chunks[0].review, chunks[0].raised_by), (["data"], "read", []))


class Breaking(unittest.TestCase):
    CHUNKS = [
        raw("SDK", "skim", [SPEC, SDK]),
        raw("Endpoint", "read", [CONTROLLER], ["logic", "contract"]),
        raw("Request", "read", [DTO], ["contract"]),
        raw("Service", "read", [SERVICE], ["logic"]),
    ]
    PATHS = [SPEC, SDK, CONTROLLER, DTO, SERVICE]

    def labels(self, chunks: list[dict] = CHUNKS, contract: dict | None = CONTRACT) -> dict[str, list[str]]:
        return {c.name: c.labels for c in build(chunks, contract, paths=self.PATHS)}

    def test_breaking_lands_on_the_chunks_whose_code_names_the_change_not_on_the_generated_chunk(self) -> None:
        self.assertEqual(self.labels(), {"SDK": ["generated"], "Endpoint": ["logic", "breaking"],
                                         "Request": ["breaking"], "Service": ["logic"]})

    def test_a_breaking_chunk_is_raised_to_verify_and_says_why(self) -> None:
        chunks = {c.name: c for c in build(self.CHUNKS, CONTRACT, paths=self.PATHS)}
        self.assertEqual((chunks["Endpoint"].review, chunks["Endpoint"].raised_by), ("verify", ["breaking change"]))
        self.assertEqual(chunks["SDK"].review, "skim")

    def test_a_chunk_the_model_labelled_contract_wins_over_one_it_did_not(self) -> None:
        chunks = [raw("SDK", "skim", [SPEC, SDK]), raw("Endpoint", "read", [CONTROLLER], ["contract"]),
                  raw("Service", "read", [SERVICE], [])]
        diff = {**DIFF_LINES, SERVICE: [("R", 1, 'client.get("/archive")')]}
        built = build_chunks(chunks, COUNTS, [SPEC, SDK, CONTROLLER, SERVICE], FLOORS, [], diff,
                             {"path": SPEC, "removals": ["removed operation GET /api/items/archive"]}, review_labels=True)
        self.assertEqual({c.name: c.labels for c in built}, {"SDK": ["generated"], "Endpoint": ["breaking"], "Service": []})

    def test_with_no_code_naming_it_the_single_contract_chunk_gets_it_with_a_note(self) -> None:
        notes: list[str] = []
        chunks = [raw("SDK", "skim", [SPEC, SDK]), raw("Endpoint", "read", [CONTROLLER], ["contract"]),
                  raw("Service", "read", [SERVICE], ["logic"])]
        built = build(chunks, {"path": SPEC, "removals": ["Gone (schema removed)"]}, notes=notes, paths=[SPEC, SDK, CONTROLLER, SERVICE])
        self.assertEqual({c.name: c.labels for c in built}, {"SDK": ["generated"], "Endpoint": ["breaking"], "Service": ["logic"]})
        self.assertEqual(notes, ["breaking change: no hand-written file names it, placed on chunk 'Endpoint'"])

    def test_with_several_contract_chunks_and_no_match_it_goes_to_the_chunk_with_the_spec_when_that_is_hand_written(self) -> None:
        chunks = [raw("Spec and endpoint", "read", [SPEC, CONTROLLER], ["contract"]), raw("Request", "read", [DTO], ["contract"])]
        built = build_chunks(chunks, COUNTS, [SPEC, CONTROLLER, DTO], FLOORS, [], {},
                             {"path": SPEC, "removals": ["Gone (schema removed)"]}, review_labels=True)
        self.assertEqual({c.name: c.labels for c in built}, {"Spec and endpoint": ["breaking"], "Request": ["contract"]})

    def test_with_several_contract_chunks_and_a_generated_spec_chunk_it_goes_to_the_first_contract_chunk(self) -> None:
        notes: list[str] = []
        built = build(self.CHUNKS, {"path": SPEC, "removals": ["Gone (schema removed)"]}, notes=notes, paths=self.PATHS)
        self.assertEqual({c.name: c.labels for c in built}["Endpoint"], ["logic", "breaking"])
        self.assertIn("breaking change: no hand-written file names it, placed on chunk 'Endpoint'", notes)

    def test_test_files_do_not_attract_the_label(self) -> None:
        test_path = "api/test/ItemRequestTest.java"
        chunks = [raw("SDK", "skim", [SPEC, SDK]), raw("Endpoint", "read", [CONTROLLER], ["contract"]),
                  raw("Tests", "read", [test_path])]
        diff = {**DIFF_LINES, test_path: [("R", 1, "new ItemRequest(null)")]}
        built = build_chunks(chunks, {**COUNTS, test_path.lower(): (1, 0)}, [SPEC, SDK, CONTROLLER, test_path], FLOORS, [], diff,
                             {"path": SPEC, "newly_required": ["ItemRequest.owner (now required)"]}, review_labels=True)
        self.assertEqual({c.name: c.labels for c in built}["Tests"], [])

    def test_no_breaking_change_means_no_breaking_label(self) -> None:
        self.assertNotIn("breaking", sum(self.labels(contract={"path": SPEC, "removals": [], "newly_required": []}).values(), []))
        self.assertNotIn("breaking", sum(self.labels(contract=None).values(), []))


class Generated(unittest.TestCase):
    def test_a_chunk_of_only_generated_files_is_labelled_generated(self) -> None:
        self.assertEqual(build([raw("SDK", "skim", [SPEC, SDK])], paths=[SPEC, SDK])[0].labels, ["generated"])

    def test_a_mixed_chunk_gets_a_note_and_no_generated_label(self) -> None:
        notes: list[str] = []
        chunks = build([raw("Mix", "read", [SDK, SERVICE], ["logic"])], notes=notes, paths=[SDK, SERVICE])
        self.assertEqual(chunks[0].labels, ["logic"])
        self.assertEqual(notes, ["chunk 'Mix': mixes generated and hand-written files"])

    def test_the_share_of_generated_files(self) -> None:
        self.assertEqual(generated_share(FLOORS, [SPEC, SDK]), "all")
        self.assertEqual(generated_share(FLOORS, [SDK, SERVICE]), "mixed")
        self.assertEqual(generated_share(FLOORS, [SERVICE]), "none")


class Floors(unittest.TestCase):
    def test_the_highest_of_a_floor_and_a_label_raise_wins(self) -> None:
        floors = {**FLOORS, "floor": [{"name": "controller", "level": "read", "globs": ["**/controllers/**"]}]}
        chunks = build([raw("Endpoint", "skim", [CONTROLLER], ["contract"])], {"path": SPEC, "removals": ["removed operation GET /x/archive"]},
                       paths=[CONTROLLER], floors=floors)
        self.assertEqual((chunks[0].review, chunks[0].raised_by), ("verify", ["breaking change"]))

    def test_a_floor_alone_still_raises_and_names_itself(self) -> None:
        floors = {"floor": [{"name": "controller", "level": "read", "globs": ["**/controllers/**"]}]}
        chunks = build([raw("Endpoint", "skim", [CONTROLLER])], paths=[CONTROLLER], floors=floors)
        self.assertEqual((chunks[0].review, chunks[0].raised_by), ("read", ["controller"]))


class DiagramAndJson(unittest.TestCase):
    DIAGRAM = 'flowchart TD\n  a["1 · A<br/>x: y"]\n  b["2 · B<br/>x: y"]\n  c["3 · C<br/>x: y"]\n  a --> b --> c\n```'

    def chunks(self) -> list[Chunk]:
        a = Chunk("A", "verify", "w", [], ["a"], labels=["logic", "breaking"])
        b = Chunk("B", "skim", "w", [], ["b"], labels=["generated"])
        return [a, b, Chunk("C", "read", "w", [], ["c"])]

    def test_boxes_get_a_level_class_and_a_class_per_label_in_display_order(self) -> None:
        styled = style_levels(self.DIAGRAM, self.chunks(), []).split("\n")
        self.assertEqual(styled[-7:-1], ["  class a lv-verify", "  class c lv-read", "  class b lv-skim", "  class a chk-logic",
                                         "  class a chk-breaking", "  class b chk-generated"])

    def test_review_json_carries_labels_only_for_labelled_variants(self) -> None:
        run = {"repo": "o/r", "pr": 1, "pr_head_sha": "abc", "variant": "v"}
        pr = {"files": [{"path": SERVICE, "additions": 1, "deletions": 0}]}
        chunk = Chunk("A", "verify", "w", [SERVICE], ["a"], labels=["logic"], number=1)
        self.assertEqual(review_json(run, pr, [chunk], False, None, True)["chunks"][0]["labels"], ["logic"])
        self.assertNotIn("labels", review_json(run, pr, [chunk], False, None)["chunks"][0])


if __name__ == "__main__":
    unittest.main()
