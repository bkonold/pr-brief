package io.github.bkonold.prbrief.diff

import io.github.bkonold.prbrief.Fixtures
import io.github.bkonold.prbrief.model.Layer
import io.github.bkonold.prbrief.model.Review
import io.github.bkonold.prbrief.model.ReviewParser
import io.github.bkonold.prbrief.model.Stop
import org.junit.Assert.assertEquals
import org.junit.Test

class ReviewCaptionsTest {
    private val review: Review = ReviewParser.parse(Fixtures.read("demo-review.json"))
    private val path = "api/src/main/java/dev/shelf/services/LoanService.java"

    @Test
    fun namesAFilesTabByItsLastPathSegment() {
        assertEquals("LoanService.java", ReviewCaptions.tabName(null, path))
        assertEquals("pom.xml", ReviewCaptions.tabName(null, "pom.xml"))
    }

    @Test
    fun namesAStopsAndALayersTabWithTheirNumber() {
        val stop: Stop = review.walkthrough[2]
        assertEquals("Stop 3 · LoanService.java", ReviewCaptions.tabName(ReviewCaptions.stopHeading(stop), path))
        assertEquals("Layer 2 · LoanService.java", ReviewCaptions.tabName(ReviewCaptions.layerHeading(2), path))
    }

    @Test
    fun showsAStopsFileAndLine() {
        val withLine = Stop(1, "Title", "Why", path, "R", 41)
        assertEquals("LoanService.java:41", ReviewCaptions.location(withLine))
        assertEquals("LoanService.java", ReviewCaptions.location(withLine.copy(line = null)))
    }

    @Test
    fun writesAStopBannerWithItsPlaceTitleAndReason() {
        val stop = Stop(3, "Placing a hold", "The queue is decided here", path, "R", 41)
        assertEquals("<html><b>3 of 6 · Placing a hold</b>&nbsp;&nbsp;The queue is decided here</html>", ReviewCaptions.stopBanner(stop, 6))
    }

    @Test
    fun escapesMarkupInTheBanners() {
        val stop = Stop(1, "Compare <T> & more", "Use a < b", path, "R", null)
        assertEquals("<html><b>1 of 2 · Compare &lt;T&gt; &amp; more</b>&nbsp;&nbsp;Use a &lt; b</html>", ReviewCaptions.stopBanner(stop, 2))
    }

    @Test
    fun leavesOutAnEmptyReason() {
        val stop = Stop(2, "Title", "  ", path, "R", null)
        assertEquals("<html><b>2 of 4 · Title</b></html>", ReviewCaptions.stopBanner(stop, 4))
    }

    @Test
    fun writesALayerBannerWithItsSummary() {
        val layer: Layer = review.layers[1]
        assertEquals(
            "<html><b>Layer 2 · Hold models and repository</b>&nbsp;&nbsp;The request, view and status types of a hold, its repository, and the fields other models gain.</html>",
            ReviewCaptions.layerBanner(layer),
        )
    }
}
