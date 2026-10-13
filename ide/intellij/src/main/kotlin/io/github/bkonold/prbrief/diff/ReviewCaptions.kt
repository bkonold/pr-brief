package io.github.bkonold.prbrief.diff

import com.intellij.openapi.util.text.StringUtil
import io.github.bkonold.prbrief.model.Layer
import io.github.bkonold.prbrief.model.Stop

/** The wording the review tab shows for a file: its tab name, the stop's location and the banners above the diff. */
internal object ReviewCaptions {
    const val EMPTY_TAB_NAME: String = "PR Brief"

    fun fileName(path: String): String = path.substringAfterLast('/')

    fun stopHeading(stop: Stop): String = "Stop ${stop.index}"

    fun layerHeading(layer: Int): String = "Layer $layer"

    /** The tab name of a file shown under a heading such as a stop or a layer; the bare file name when there is none. */
    fun tabName(heading: String?, path: String): String = if (heading == null) fileName(path) else "$heading · ${fileName(path)}"

    /** Where a stop points, as `File.java:12`, or just the file name when the stop has no line. */
    fun location(stop: Stop): String = stop.line?.let { "${fileName(stop.path)}:$it" } ?: fileName(stop.path)

    /** The banner text of a stop, as HTML: its place in the walkthrough and title, then why it matters. */
    fun stopBanner(stop: Stop, total: Int): String = banner("${stop.index} of $total · ${stop.title}", stop.why)

    /** The banner text of a layer, as HTML: its number and title, then its summary. */
    fun layerBanner(layer: Layer): String = banner("${layerHeading(layer.index)} · ${layer.title}", layer.summary)

    private fun banner(heading: String, detail: String): String {
        val body = StringBuilder("<b>").append(StringUtil.escapeXmlEntities(heading)).append("</b>")
        if (detail.isNotBlank()) body.append("&nbsp;&nbsp;").append(StringUtil.escapeXmlEntities(detail.trim()))
        return "<html>$body</html>"
    }
}
