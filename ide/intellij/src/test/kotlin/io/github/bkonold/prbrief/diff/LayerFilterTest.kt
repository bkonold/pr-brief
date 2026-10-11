package io.github.bkonold.prbrief.diff

import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import io.github.bkonold.prbrief.Fixtures
import io.github.bkonold.prbrief.model.HunkRange
import java.nio.file.Files
import java.nio.file.Path
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Runs every case under `ide/fixtures/layer-filter`, which other editors' plugins run too. */
class LayerFilterTest {
    private class Case(val name: String, val head: String, val base: String, val hunks: List<HunkRange>, val selected: Set<String>, val expected: String?)

    private fun cases(): List<Case> {
        val dir: Path = Fixtures.dir.resolve("layer-filter")
        return Files.list(dir).use { files -> files.filter { it.toString().endsWith(".json") }.sorted().toList() }.map { file ->
            val json: JsonObject = JsonParser.parseString(Files.readString(file)).asJsonObject
            Case(
                name = file.fileName.toString().removeSuffix(".json"),
                head = json.get("head").asString,
                base = json.get("base").asString,
                hunks = json.getAsJsonArray("hunks").map { hunk(it.asJsonObject) },
                selected = json.getAsJsonArray("selected").map { it.asString }.toSet(),
                expected = json.get("expected").takeIf { !it.isJsonNull }?.asString,
            )
        }
    }

    private fun hunk(json: JsonObject): HunkRange {
        val old: JsonArray = json.getAsJsonArray("old")
        val new: JsonArray = json.getAsJsonArray("new")
        return HunkRange(
            json.get("id").asString, json.get("path").asString, json.get("change").asString,
            old[0].asInt, old[1].asInt, new[0].asInt, new[1].asInt, null, null,
        )
    }

    @Test
    fun everyFixtureGivesItsExpectedLeftText() {
        val all: List<Case> = cases()
        assertTrue("fixtures are missing", all.size >= 20)
        for (case in all) {
            assertEquals(case.name, case.expected, LayerFilter.leftText(case.head, case.base, case.hunks, case.selected))
        }
    }

    @Test
    fun theFixturesCoverTheCasesTheLayerFilterMustHandle() {
        val names: Set<String> = cases().map { it.name }.toSet()
        val required: List<String> = listOf(
            "one-hunk", "several-hunks-one-selected", "several-hunks-two-selected", "added-lines-only", "removed-lines-only",
            "hunk-at-start", "hunk-at-end", "missing-trailing-newline-in-head", "added-file", "deleted-file",
            "mismatch-local-line-added-above",
        )
        assertEquals(emptyList<String>(), required.filter { it !in names })
    }

    @Test
    fun aMismatchIsTheOnlyReasonForNull() {
        val matching: List<Case> = cases().filter { !it.name.startsWith("mismatch-") }
        assertTrue(matching.all { it.expected != null })
        assertTrue(cases().filter { it.name.startsWith("mismatch-") }.all { it.expected == null })
    }

    @Test
    fun splitsLinesKeepingTheirNewlines() {
        assertEquals(listOf("a\n", "b"), LayerFilter.splitLines("a\nb"))
        assertEquals(listOf("a\n", "\n"), LayerFilter.splitLines("a\n\n"))
        assertEquals(emptyList<String>(), LayerFilter.splitLines(""))
    }
}
