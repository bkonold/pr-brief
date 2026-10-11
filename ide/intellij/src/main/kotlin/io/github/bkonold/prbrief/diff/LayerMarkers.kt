package io.github.bkonold.prbrief.diff

import com.intellij.diff.util.Side
import com.intellij.openapi.util.Key

/** A hunk of another layer, as 0-based lines `[startLine, endLine)` of the diff's right side. */
data class LayerMarker(val startLine: Int, val endLine: Int, val layer: Int, val title: String)

/** Set on a diff request by the producer and read by [LayerMarkerExtension] once the viewer exists. */
val LAYER_MARKERS: Key<List<LayerMarker>> = Key.create("prbrief.layerMarkers")

/** The line a stop points at, as a 0-based line on one side of the diff, with the stop's title for the gutter tooltip. */
data class StopMarker(val side: Side, val line: Int, val title: String)

/** Set on a diff request by the producer of a stop's file and read by [LayerMarkerExtension] once the viewer exists. */
val STOP_MARKER: Key<StopMarker> = Key.create("prbrief.stopMarker")
