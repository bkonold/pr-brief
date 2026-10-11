package io.github.bkonold.prbrief.diff

import com.intellij.icons.AllIcons
import com.intellij.diff.DiffContext
import com.intellij.diff.DiffExtension
import com.intellij.diff.FrameDiffTool.DiffViewer
import com.intellij.diff.requests.DiffRequest
import com.intellij.diff.tools.fragmented.UnifiedDiffViewer
import com.intellij.diff.tools.util.base.DiffViewerBase
import com.intellij.diff.tools.util.base.DiffViewerListener
import com.intellij.diff.tools.util.side.TwosideTextDiffViewer
import com.intellij.diff.util.Side
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.editor.markup.GutterIconRenderer
import com.intellij.openapi.editor.markup.HighlighterLayer
import com.intellij.openapi.editor.markup.HighlighterTargetArea
import com.intellij.openapi.editor.markup.RangeHighlighter
import com.intellij.openapi.editor.markup.TextAttributes
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.project.Project
import com.intellij.ui.JBColor
import com.intellij.util.ui.JBUI
import io.github.bkonold.prbrief.BriefService
import io.github.bkonold.prbrief.Selection
import io.github.bkonold.prbrief.ui.Palette
import java.awt.Component
import java.awt.Font
import java.awt.Graphics
import java.awt.Graphics2D
import java.awt.RenderingHints
import javax.swing.Icon

/**
 * Marks lines of a review diff. The hunks of other layers on the right side of a layer's diff get a tinted background and
 * a numbered gutter badge whose tooltip names the layer and whose click selects it; the line a stop points at gets the
 * same tint and an arrow whose tooltip is the stop's title. In the unified viewer the layer markers sit on lines the
 * viewer folds when they are far from a change, so they show once that region is expanded.
 */
class LayerMarkerExtension : DiffExtension() {
    override fun onViewerCreated(viewer: DiffViewer, context: DiffContext, request: DiffRequest) {
        val layerMarkers: List<LayerMarker> = request.getUserData(LAYER_MARKERS).orEmpty()
        val stopMarker: StopMarker? = request.getUserData(STOP_MARKER)
        val project: Project = context.project ?: return
        if (viewer !is DiffViewerBase || (layerMarkers.isEmpty() && stopMarker == null)) return
        viewer.addListener(MarkerPainter(project, viewer, layerMarkers, stopMarker))
    }
}

private class MarkerPainter(
    private val project: Project,
    private val viewer: DiffViewerBase,
    private val layerMarkers: List<LayerMarker>,
    private val stopMarker: StopMarker?,
) : DiffViewerListener() {
    private var placed: List<Pair<Editor, RangeHighlighter>> = emptyList()

    override fun onAfterRediff() {
        clear()
        val next = ArrayList<Pair<Editor, RangeHighlighter>>()
        for (marker in layerMarkers) {
            val (editor, line) = sideLine(Side.RIGHT, marker.startLine) ?: continue
            val last: Int = sideLine(Side.RIGHT, marker.endLine - 1)?.second ?: line
            place(next, editor, line, last, MarkerRenderer(project, marker))
        }
        stopMarker?.let { marker ->
            val (editor, line) = sideLine(marker.side, marker.line) ?: return@let
            place(next, editor, line, line, StopRenderer(marker))
        }
        placed = next
    }

    /** Tints the lines `[first, last]` of the editor and puts the gutter icon on them; nothing when they lie outside the document. */
    private fun place(into: MutableList<Pair<Editor, RangeHighlighter>>, editor: Editor, first: Int, last: Int, renderer: GutterIconRenderer) {
        val document = editor.document
        if (first !in 0 until document.lineCount) return
        val end: Int = last.coerceIn(first, document.lineCount - 1)
        val highlighter: RangeHighlighter = editor.markupModel.addRangeHighlighter(
            document.getLineStartOffset(first),
            document.getLineEndOffset(end),
            HighlighterLayer.ADDITIONAL_SYNTAX,
            TextAttributes().apply { backgroundColor = Palette.selectedRow },
            HighlighterTargetArea.LINES_IN_RANGE,
        )
        highlighter.gutterIconRenderer = renderer
        into.add(editor to highlighter)
    }

    override fun onDispose() = clear()

    private fun clear() {
        for ((editor, highlighter) in placed) editor.markupModel.removeHighlighter(highlighter)
        placed = emptyList()
    }

    /** The editor that shows [side] and the line in it, for a 0-based line of that side's content. */
    private fun sideLine(side: Side, line: Int): Pair<Editor, Int>? = when (val v = viewer) {
        is UnifiedDiffViewer -> v.transferLineToOneside(side, line).takeIf { it >= 0 }?.let { v.editor to it }
        is TwosideTextDiffViewer -> v.getEditor(side) to line
        else -> null
    }
}

private class MarkerRenderer(private val project: Project, private val marker: LayerMarker) : GutterIconRenderer() {
    override fun getIcon(): Icon = LayerBadge(marker.layer)

    override fun getTooltipText(): String = "Changed in layer ${marker.layer} · ${marker.title}"

    override fun getClickAction(): AnAction = object : AnAction(), DumbAware {
        override fun actionPerformed(e: AnActionEvent) {
            project.getService(BriefService::class.java).select(Selection.LayerAt(marker.layer))
        }
    }

    override fun isNavigateAction(): Boolean = true

    override fun equals(other: Any?): Boolean = other is MarkerRenderer && other.marker == marker

    override fun hashCode(): Int = marker.hashCode()
}

private class StopRenderer(private val marker: StopMarker) : GutterIconRenderer() {
    override fun getIcon(): Icon = AllIcons.General.ArrowRight

    override fun getTooltipText(): String = marker.title

    override fun equals(other: Any?): Boolean = other is StopRenderer && other.marker == marker

    override fun hashCode(): Int = marker.hashCode()
}

private class LayerBadge(private val number: Int) : Icon {
    private val size: Int = JBUI.scale(14)

    override fun getIconWidth(): Int = size

    override fun getIconHeight(): Int = size

    override fun paintIcon(c: Component?, g: Graphics, x: Int, y: Int) {
        val g2 = g.create() as Graphics2D
        try {
            g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
            g2.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING, RenderingHints.VALUE_TEXT_ANTIALIAS_ON)
            g2.color = Palette.guide
            g2.fillRoundRect(x, y, size, size, JBUI.scale(4), JBUI.scale(4))
            g2.color = JBColor.WHITE
            g2.font = g2.font.deriveFont(Font.BOLD, size * 0.7f)
            val text: String = number.toString()
            val metrics = g2.fontMetrics
            g2.drawString(text, x + (size - metrics.stringWidth(text)) / 2, y + (size + metrics.ascent - metrics.descent) / 2)
        } finally {
            g2.dispose()
        }
    }
}
