package io.github.bkonold.prbrief.model

import io.github.bkonold.prbrief.Fixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class ReviewParserTest {
    private val review: Review = ReviewParser.parse(Fixtures.read("demo-review.json"))

    @Test
    fun readsTheHeader() {
        assertEquals("bkonold/pr-brief-demo", review.repo)
        assertEquals(1, review.pr)
        assertEquals("e10b234727d7153f09aa9782d8de874ed6677ac2", review.headSha)
    }

    @Test
    fun readsStopsWithAndWithoutALine() {
        assertEquals(6, review.walkthrough.size)
        assertEquals(1, review.walkthrough[0].line)
        assertNull(review.walkthrough[4].line)
        assertEquals("R", review.walkthrough[0].side)
    }

    @Test
    fun readsLayersAndTheirHunkRanges() {
        assertEquals(6, review.layers.size)
        val first: Layer = review.layers[0]
        assertEquals("high", first.risk)
        assertEquals(listOf(1), review.layers[1].dependsOn)
        val added: HunkRange = review.allHunks.first { it.id == "h09" }
        assertEquals(HunkRange("h09", "api/src/main/java/dev/shelf/entities/HoldEntity.java", "added", 0, 0, 1, 93, 93, 0), added)
    }

    @Test
    fun groupsHunksByPathInFirstHunkOrder() {
        val loans: List<HunkRange> = review.hunksOf("api/src/main/java/dev/shelf/services/LoanService.java")
        assertEquals(listOf("h19", "h20", "h21", "h22", "h23"), loans.map { it.id })
        assertEquals(listOf("api/src/main/java/dev/shelf/services/LoanService.java"), review.layers[1].paths.filter { it.endsWith("LoanService.java") })
    }

    @Test
    fun readsFileSets() {
        assertEquals(setOf("api/openapi.json", "web/sdk/generated.ts"), review.fileSets.contract)
        assertEquals(setOf("api/src/main/resources/db/migration/V3__holds.sql"), review.fileSets.data)
    }

    @Test
    fun aBriefWithoutLayersListsTheFilesOfItsStopsAndSets() {
        val plain: Review = review.copy(layers = emptyList())
        assertEquals(true, "api/openapi.json" in plain.changedPaths)
        assertEquals(plain.changedPaths.size, plain.changedPaths.distinct().size)
    }

    @Test
    fun rejectsAnOlderSchema() {
        assertThrows(ReviewParser.InvalidReviewException::class.java) {
            ReviewParser.parse("""{"schema": 3, "walkthrough": []}""")
        }
    }
}
