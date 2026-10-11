package io.github.bkonold.prbrief.diff

import com.intellij.openapi.util.Key

/** A hunk of another layer, as 0-based lines `[startLine, endLine)` of the diff's right side. */
data class LayerMarker(val startLine: Int, val endLine: Int, val layer: Int, val title: String)

/** Set on a diff request by the producer and read by [LayerMarkerExtension] once the viewer exists. */
val LAYER_MARKERS: Key<List<LayerMarker>> = Key.create("prbrief.layerMarkers")
