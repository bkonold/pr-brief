"""Tests for the data lines of a migration. All data here is invented.
Run with `python3 -m unittest discover -s tests` from the tool's folder."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from diff_lines import file_diff_lines  # noqa: E402
from data_lines import (  # noqa: E402
    ADDITIVE, DATA_LEVELS, DESTRUCTIVE, REWRITES, classify_statement, data_lines, narrows, split_statements,
)
from test_contract_block import make_diff  # noqa: E402

PATH = "db/migration/V9__widgets.sql"


def diff_lines(sql: str, path: str = PATH) -> list:
    return file_diff_lines(make_diff(path, "", sql), path)


def lines_for(sql: str) -> list[tuple[str | None, str]]:
    return [(line.impact, line.text) for line in data_lines({PATH: diff_lines(sql)})]


def levels(statement: str) -> list[tuple[str | None, str]]:
    return [(action.level, action.text) for action in classify_statement(statement)]


class Splitting(unittest.TestCase):
    def test_statements_span_lines_and_drop_comments(self) -> None:
        sql = "-- header\nCREATE TABLE widget (\n  id bigint, -- the key\n  /* note; here */ name text\n);\nDROP TABLE old;\n"
        found = split_statements(diff_lines(sql))
        self.assertEqual([(" ".join(text.split()), line) for text, line in found],
                         [("CREATE TABLE widget ( id bigint, name text )", 2), ("DROP TABLE old", 6)])

    def test_semicolons_inside_strings_and_dollar_quotes_do_not_split(self) -> None:
        sql = "INSERT INTO t (a) VALUES ('x;y');\nDO $$ BEGIN\n  UPDATE t SET a = 1;\nEND $$;\nDROP TABLE z;\n"
        found = [" ".join(text.split()) for text, _ in split_statements(diff_lines(sql))]
        self.assertEqual(found, ["INSERT INTO t (a) VALUES ('x;y')", "DO $$ BEGIN UPDATE t SET a = 1; END $$", "DROP TABLE z"])

    def test_only_added_lines_count(self) -> None:
        before = "DROP TABLE kept;\n"
        diff = make_diff(PATH, before, before + "CREATE INDEX i ON t (a);\n")
        found = split_statements(file_diff_lines(diff, PATH))
        self.assertEqual([text for text, _ in found], ["CREATE INDEX i ON t (a)"])


class Levels(unittest.TestCase):
    def test_the_levels_run_from_destructive_to_additive(self) -> None:
        self.assertEqual(DATA_LEVELS, (DESTRUCTIVE, REWRITES, ADDITIVE))

    def test_destructive_statements(self) -> None:
        self.assertEqual(levels("DROP TABLE IF EXISTS old_stuff CASCADE"), [(DESTRUCTIVE, "drop table `old_stuff`")])
        self.assertEqual(levels("TRUNCATE TABLE a, b"), [(DESTRUCTIVE, "truncate `a`"), (DESTRUCTIVE, "truncate `b`")])
        self.assertEqual(levels("DELETE FROM widget WHERE x = 1"), [(DESTRUCTIVE, "delete rows from `widget`")])
        self.assertEqual(levels("ALTER TABLE widget DROP COLUMN legacy"), [(DESTRUCTIVE, "drop column `widget.legacy`")])

    def test_a_type_change_narrows_when_the_target_has_a_size_or_is_small(self) -> None:
        self.assertEqual(levels("ALTER TABLE w ALTER COLUMN n TYPE varchar(20)"), [(DESTRUCTIVE, "narrow `w.n` to `varchar(20)`")])
        self.assertEqual(levels("ALTER TABLE w ALTER COLUMN n TYPE integer USING n::integer")[0][0], DESTRUCTIVE)
        self.assertEqual(levels("ALTER TABLE w ALTER COLUMN n TYPE text"), [(REWRITES, "change type of `w.n` to `text`")])
        self.assertTrue(narrows("numeric(10, 2)"))
        self.assertFalse(narrows("bigint"))

    def test_statements_that_rewrite_rows(self) -> None:
        self.assertEqual(levels("UPDATE widget SET a = 1"), [(REWRITES, "update rows in `widget`")])
        self.assertEqual(levels("ALTER TABLE w ALTER COLUMN a SET NOT NULL"), [(REWRITES, "set `w.a` NOT NULL")])
        self.assertEqual(levels("ALTER TABLE w ADD CONSTRAINT w_fk FOREIGN KEY (a) REFERENCES b (id)"),
                         [(REWRITES, "add constraint `w_fk` on `w`")])
        self.assertEqual(levels("ALTER TABLE w ADD CHECK (a > 0)"), [(REWRITES, "add constraint CHECK on `w`")])

    def test_add_column_not_null_needs_a_default_to_be_additive(self) -> None:
        self.assertEqual(levels("ALTER TABLE w ADD COLUMN a text NOT NULL"),
                         [(REWRITES, "add column `w.a` NOT NULL without a default")])
        self.assertEqual(levels("ALTER TABLE w ADD COLUMN a text NOT NULL DEFAULT ''"), [(ADDITIVE, "add column `w.a`")])
        self.assertEqual(levels("ALTER TABLE w ADD COLUMN a text"), [(ADDITIVE, "add column `w.a`")])
        self.assertEqual(levels("ALTER TABLE w ADD a bigserial NOT NULL"), [(ADDITIVE, "add column `w.a`")])

    def test_additive_statements(self) -> None:
        self.assertEqual(levels("CREATE TABLE IF NOT EXISTS widget (id bigint)"), [(ADDITIVE, "create table `widget`")])
        self.assertEqual(levels("CREATE UNIQUE INDEX CONCURRENTLY w_idx ON widget (a)"), [(ADDITIVE, "create index `w_idx` on `widget`")])
        self.assertEqual(levels("INSERT INTO widget (a) VALUES (1)"), [(ADDITIVE, "insert rows into `widget`")])
        self.assertEqual(levels("CREATE OR REPLACE VIEW v AS SELECT 1"), [(ADDITIVE, "create view `v`")])

    def test_one_alter_table_with_several_actions_gives_each_its_own_level(self) -> None:
        found = levels("ALTER TABLE w ADD COLUMN a int, DROP COLUMN b, ALTER COLUMN c SET NOT NULL")
        self.assertEqual(found, [(ADDITIVE, "add column `w.a`"), (DESTRUCTIVE, "drop column `w.b`"), (REWRITES, "set `w.c` NOT NULL")])

    def test_commas_inside_parentheses_do_not_split_actions(self) -> None:
        found = levels("ALTER TABLE w ADD COLUMN a numeric(10, 2) NOT NULL DEFAULT 0, ADD COLUMN b text")
        self.assertEqual(found, [(ADDITIVE, "add column `w.a`"), (ADDITIVE, "add column `w.b`")])

    def test_a_cte_update_is_found(self) -> None:
        self.assertEqual(levels("WITH x AS (SELECT 1) UPDATE widget SET a = 1")[0][0], REWRITES)

    def test_unknown_statements_have_no_level(self) -> None:
        for sql in ("DO $$ BEGIN NULL; END $$", "CREATE PUBLICATION p FOR ALL TABLES", "GRANT SELECT ON w TO r"):
            self.assertEqual([action.level for action in classify_statement(sql)], [None], sql)


class Parts(unittest.TestCase):
    """The Change and Table of each kind of line, which fill a table row."""

    def parts(self, sql: str) -> list[tuple[str | None, str, str]]:
        return [(line.impact, line.change, line.on) for line in data_lines({PATH: diff_lines(sql)})]

    def test_columns_read_as_plus_minus_and_a_qualifier(self) -> None:
        self.assertEqual(self.parts("ALTER TABLE slides ADD COLUMN hidden_slide_keys text;"),
                         [(ADDITIVE, "`+ hidden_slide_keys` nullable", "`slides`")])
        self.assertEqual(self.parts("ALTER TABLE slides ADD COLUMN n int NOT NULL;"),
                         [(REWRITES, "`+ n` NOT NULL, no default", "`slides`")])
        self.assertEqual(self.parts("ALTER TABLE slides ADD COLUMN n int NOT NULL DEFAULT 0;"),
                         [(ADDITIVE, "`+ n` NOT NULL, default", "`slides`")])
        self.assertEqual(self.parts("ALTER TABLE slides DROP COLUMN kept_position;"),
                         [(DESTRUCTIVE, "`− kept_position`", "`slides`")])

    def test_defaults_constraints_and_types(self) -> None:
        self.assertEqual(self.parts("ALTER TABLE slides ALTER COLUMN position SET DEFAULT 0;"),
                         [(ADDITIVE, "`position` default 0", "`slides`")])
        self.assertEqual(self.parts("ALTER TABLE slides DROP CONSTRAINT uq_slides_key;"),
                         [(REWRITES, "constraint `uq_slides_key` dropped", "`slides`")])
        self.assertEqual(self.parts("ALTER TABLE slides ALTER COLUMN n TYPE bigint;"),
                         [(REWRITES, "`n` type → `bigint`", "`slides`")])
        self.assertEqual(self.parts("ALTER TABLE slides ALTER COLUMN n SET NOT NULL;"), [(REWRITES, "`n` set NOT NULL", "`slides`")])

    def test_statements_on_rows_and_tables(self) -> None:
        self.assertEqual(self.parts("UPDATE slides SET n = 1;"), [(REWRITES, "backfill (UPDATE)", "`slides`")])
        self.assertEqual(self.parts("INSERT INTO kinds VALUES (1);"), [(ADDITIVE, "seed (INSERT)", "`kinds`")])
        self.assertEqual(self.parts("CREATE TABLE a (id int);"), [(ADDITIVE, "new table", "`a`")])
        self.assertEqual(self.parts("DROP TABLE a;"), [(DESTRUCTIVE, "dropped", "`a`")])
        self.assertEqual(self.parts("ALTER TABLE a RENAME TO b;"), [(REWRITES, "renamed to `b`", "`a`")])

    def test_an_index_has_no_table_so_its_file_is_the_place(self) -> None:
        self.assertEqual(self.parts("DROP INDEX idx_a;"), [(REWRITES, "index `idx_a` dropped", "`V9__widgets.sql`")])

    def test_a_sweep_counts_tables(self) -> None:
        sql = "".join(f"ALTER TABLE t{i} ADD COLUMN archived_at timestamp;\n" for i in range(4))
        self.assertEqual(self.parts(sql), [(ADDITIVE, "`+ archived_at` nullable", "4 tables: `t0`, `t1`, `t2` +1")])

    def test_a_repeated_statement_shows_its_count(self) -> None:
        sql = "UPDATE slides SET a = 1;\nUPDATE slides SET b = 2;\n"
        self.assertEqual(self.parts(sql), [(REWRITES, "backfill (UPDATE) ×2", "`slides`")])

    def test_an_unclassified_statement_has_no_impact_and_names_its_file(self) -> None:
        self.assertEqual(self.parts("DO $$ BEGIN NULL; END $$;"), [(None, "DO block", "`V9__widgets.sql`")])


class Lines(unittest.TestCase):
    def test_lines_are_worst_first_with_their_file_and_table(self) -> None:
        sql = "CREATE TABLE a (id bigint);\nUPDATE b SET x = 1;\nDROP TABLE c;\n"
        found = data_lines({PATH: diff_lines(sql)})
        self.assertEqual([(line.impact, line.text) for line in found],
                         [(DESTRUCTIVE, "drop table `c`"), (REWRITES, "update rows in `b`"), (ADDITIVE, "create table `a`")])
        self.assertEqual((found[0].path, found[0].loc, found[0].members[0].file, found[0].members[0].table, found[0].group),
                         (PATH, ("R", 3), PATH, "c", "c"))

    def test_the_same_statement_on_a_table_is_one_line_with_a_count(self) -> None:
        sql = "INSERT INTO t (a) VALUES (1);\nINSERT INTO t (a) VALUES (2);\nINSERT INTO t (a) VALUES (3);\n"
        self.assertEqual(lines_for(sql), [(ADDITIVE, "insert rows into `t` (3 statements)")])

    def test_one_column_added_to_three_tables_is_one_line(self) -> None:
        sql = "".join(f"ALTER TABLE t{i} ADD COLUMN archived_at timestamptz;\n" for i in range(1, 5))
        found = data_lines({PATH: diff_lines(sql)})
        self.assertEqual([(line.impact, line.text) for line in found],
                         [(ADDITIVE, "add column `archived_at` on 4 tables · `t1`, `t2`, `t3` +1")])
        self.assertEqual([member.table for member in found[0].members], ["t1", "t2", "t3", "t4"])

    def test_two_tables_stay_separate_lines(self) -> None:
        sql = "ALTER TABLE a ADD COLUMN n int;\nALTER TABLE b ADD COLUMN n int;\n"
        self.assertEqual(lines_for(sql), [(ADDITIVE, "add column `a.n`"), (ADDITIVE, "add column `b.n`")])

    def test_unclassified_statements_are_named_by_kind_and_file_without_a_level(self) -> None:
        sql = "DO $$ BEGIN NULL; END $$;\nGRANT SELECT ON a TO reader;\nCREATE TABLE a (id bigint);\n"
        self.assertEqual(lines_for(sql), [(ADDITIVE, "create table `a`"), (None, "DO block in V9__widgets.sql"),
                                          (None, "GRANT SELECT `a` in V9__widgets.sql")])

    def test_repeated_unclassified_kind_in_one_file_is_one_line_with_its_count(self) -> None:
        sql = "DO $$ BEGIN NULL; END $$;\nDO $$ BEGIN NULL; END $$;\n"
        self.assertEqual(lines_for(sql), [(None, "DO block in V9__widgets.sql (2 statements)")])

    def test_an_unknown_alter_table_action_names_its_verb_and_both_targets(self) -> None:
        self.assertEqual(levels("ALTER TABLE w ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY"),
                         [(None, "ALTER COLUMN `id` on `w`")])
        self.assertEqual(levels("ALTER SEQUENCE IF EXISTS seq_a OWNED BY w.id"), [(None, "ALTER SEQUENCE `seq_a`")])
        self.assertEqual(levels("VACUUM"), [(None, "VACUUM statement")])

    def test_default_changes_are_additive_and_name_the_column_and_value(self) -> None:
        self.assertEqual(levels("ALTER TABLE slides ALTER COLUMN position SET DEFAULT 0;"),
                         [(ADDITIVE, "`slides.position` default set to 0")])
        self.assertEqual(levels("ALTER TABLE slides ALTER COLUMN position DROP DEFAULT;"),
                         [(ADDITIVE, "`slides.position` default dropped")])

    def test_long_default_expression_is_cut(self) -> None:
        text = levels("ALTER TABLE a ALTER COLUMN c SET DEFAULT " + "x" * 80 + ";")[0][1]
        self.assertTrue(text.endswith("…"))
        self.assertLess(len(text), 70)

    def test_dropped_constraint_and_index_rewrite_rows_and_are_named(self) -> None:
        self.assertEqual(levels("ALTER TABLE widgets DROP CONSTRAINT uq_widgets_name;"),
                         [(REWRITES, "constraint `uq_widgets_name` dropped on `widgets`")])
        self.assertEqual(levels("DROP INDEX IF EXISTS idx_a, idx_b;"),
                         [(REWRITES, "index `idx_a` dropped"), (REWRITES, "index `idx_b` dropped")])

    def test_renames_rewrite_rows_and_say_what_became_what(self) -> None:
        self.assertEqual(levels("ALTER TABLE widgets RENAME COLUMN old_name TO new_name;"),
                         [(REWRITES, "column `widgets.old_name` renamed to `new_name`")])
        self.assertEqual(levels("ALTER TABLE widgets RENAME TO gadgets;"), [(REWRITES, "`widgets` renamed to `gadgets`")])
        self.assertEqual(levels("ALTER TABLE widgets RENAME CONSTRAINT a TO b;"),
                         [(REWRITES, "constraint `a` renamed to `b` on `widgets`")])
        self.assertEqual(levels("ALTER INDEX idx_a RENAME TO idx_b;"), [(REWRITES, "index `idx_a` renamed to `idx_b`")])

    def test_two_constraints_dropped_on_one_table_stay_two_lines(self) -> None:
        sql = "ALTER TABLE a DROP CONSTRAINT c1;\nALTER TABLE a DROP CONSTRAINT c2;\n"
        self.assertEqual(lines_for(sql), [(REWRITES, "constraint `c1` dropped on `a`"), (REWRITES, "constraint `c2` dropped on `a`")])

    def test_each_file_is_its_own_source(self) -> None:
        other = "db/migration/V10__more.sql"
        found = data_lines({PATH: diff_lines("DROP TABLE a;\n"), other: diff_lines("DROP TABLE b;\n", other)})
        self.assertEqual([(line.path, line.text) for line in found], [(PATH, "drop table `a`"), (other, "drop table `b`")])

    def test_a_migration_with_no_added_statements_gives_no_lines(self) -> None:
        self.assertEqual(lines_for("-- only a comment\n"), [])


if __name__ == "__main__":
    unittest.main()
