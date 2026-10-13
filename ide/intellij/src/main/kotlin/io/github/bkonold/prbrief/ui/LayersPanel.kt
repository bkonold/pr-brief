package io.github.bkonold.prbrief.ui

import com.intellij.icons.AllIcons
import com.intellij.openapi.project.Project
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBScrollPane
import com.intellij.util.ui.JBUI
import com.intellij.util.ui.UIUtil
import io.github.bkonold.prbrief.BriefService
import io.github.bkonold.prbrief.Selection
import io.github.bkonold.prbrief.model.HunkRange
import io.github.bkonold.prbrief.model.Layer
import java.awt.BorderLayout
import java.awt.Color
import java.awt.Component
import java.awt.Cursor
import java.awt.Dimension
import java.awt.FlowLayout
import java.awt.Graphics
import java.awt.Graphics2D
import java.awt.RenderingHints
import java.awt.event.MouseAdapter
import java.awt.event.MouseEvent
import javax.swing.BorderFactory
import javax.swing.Box
import javax.swing.BoxLayout
import javax.swing.JButton
import javax.swing.JComponent
import javax.swing.JPanel

/**
 * The layers, one row each: number, title, a risk pill and a tick once judged. One layer at a time is selected; its row
 * expands to its files grouped by folder, each with that layer's line counts. Clicking the selected row clears it.
 */
class LayersPanel(private val project: Project) : JPanel(BorderLayout()) {
    private val service: BriefService = project.getService(BriefService::class.java)
    private val header = JBLabel().apply { foreground = Palette.muted }
    private val showAll = JButton("Show all").apply { addActionListener { service.select(Selection.None) } }
    private val rows = JPanel().apply { layout = BoxLayout(this, BoxLayout.Y_AXIS) }

    init {
        val top = JPanel(BorderLayout()).apply {
            border = JBUI.Borders.empty(6, 10)
            add(header, BorderLayout.CENTER)
            add(showAll, BorderLayout.EAST)
        }
        add(top, BorderLayout.NORTH)
        add(JBScrollPane(JPanel(BorderLayout()).apply { add(rows, BorderLayout.NORTH) }).apply { border = null }, BorderLayout.CENTER)
    }

    fun refresh(layers: List<Layer>, selection: Selection, judged: Set<Int>) {
        val count: Int = layers.size
        header.text = "Every change in $count ${if (count == 1) "layer" else "layers"}, foundations first · ${judged.size} judged"
        val selectedLayer: Int? = (selection as? Selection.LayerAt)?.index
        showAll.isEnabled = selectedLayer != null
        rows.removeAll()
        for (layer in layers) {
            val isSelected: Boolean = layer.index == selectedLayer
            rows.add(layerRow(layer, isSelected, layer.index in judged))
            if (isSelected) rows.add(details(layer, (selection as Selection.LayerAt).file, layer.index in judged))
        }
        rows.revalidate()
        rows.repaint()
    }

    private fun layerRow(layer: Layer, selected: Boolean, judged: Boolean): JComponent {
        val row = JPanel(BorderLayout(8, 0)).apply {
            border = JBUI.Borders.empty(5, 10)
            isOpaque = true
            background = if (selected) Palette.selectedRow else UIUtil.getListBackground()
            cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
            toolTipText = layer.summary.takeIf { it.isNotBlank() }
        }
        row.add(JBLabel("%2d".format(layer.index)).apply { foreground = Palette.muted }, BorderLayout.WEST)
        row.add(JBLabel(layer.title), BorderLayout.CENTER)
        val trailing = JPanel(FlowLayout(FlowLayout.RIGHT, 6, 0)).apply { isOpaque = false }
        trailing.add(RiskPill(layer.risk))
        if (judged) trailing.add(JBLabel(AllIcons.RunConfigurations.TestPassed).apply { toolTipText = "Judged" })
        row.add(trailing, BorderLayout.EAST)
        row.addMouseListener(object : MouseAdapter() {
            override fun mouseClicked(e: MouseEvent) {
                service.select(if (selected) Selection.None else Selection.LayerAt(layer.index))
            }
        })
        row.maximumSize = Dimension(Int.MAX_VALUE, row.preferredSize.height)
        return row
    }

    private fun details(layer: Layer, selectedFile: String?, judged: Boolean): JComponent {
        val panel = JPanel().apply {
            layout = BoxLayout(this, BoxLayout.Y_AXIS)
            border = JBUI.Borders.empty(2, 10, 8, 10)
            isOpaque = true
            background = Palette.selectedRow
        }
        val byFolder: Map<String, List<String>> = layer.paths.groupBy { folderOf(it) }
        for ((folder, paths) in byFolder) {
            panel.add(left(JBLabel(folder, AllIcons.Nodes.Folder, JBLabel.LEFT).apply {
                foreground = Palette.muted
                toolTipText = folder
            }))
            for (path in paths) panel.add(fileRow(layer, path, path == selectedFile))
        }
        panel.add(Box.createVerticalStrut(6))
        panel.add(left(JButton(if (judged) "Unmark judged" else "Mark judged").apply {
            addActionListener { service.toggleJudged(layer.index) }
        }))
        panel.maximumSize = Dimension(Int.MAX_VALUE, panel.preferredSize.height)
        return panel
    }

    private fun fileRow(layer: Layer, path: String, selected: Boolean): JComponent {
        val row = JPanel(BorderLayout(6, 0)).apply {
            border = JBUI.Borders.empty(1, 18, 1, 0)
            isOpaque = selected
            background = UIUtil.getListSelectionBackground(false)
            cursor = Cursor.getPredefinedCursor(Cursor.HAND_CURSOR)
            toolTipText = path
        }
        row.add(JBLabel(path.substringAfterLast('/'), AllIcons.FileTypes.Any_type, JBLabel.LEFT), BorderLayout.CENTER)
        counts(layer.hunks.filter { it.path == path })?.let { row.add(it, BorderLayout.EAST) }
        row.addMouseListener(object : MouseAdapter() {
            override fun mouseClicked(e: MouseEvent) {
                service.select(Selection.LayerAt(layer.index, path))
            }
        })
        row.maximumSize = Dimension(Int.MAX_VALUE, row.preferredSize.height)
        return row
    }

    /** The `+a −r` line counts of `hunks`, or null when any hunk has none. */
    private fun counts(hunks: List<HunkRange>): JComponent? {
        if (hunks.any { it.added == null || it.removed == null }) return null
        val added: Int = hunks.sumOf { it.added ?: 0 }
        val removed: Int = hunks.sumOf { it.removed ?: 0 }
        val box = JPanel(FlowLayout(FlowLayout.RIGHT, 4, 0)).apply { isOpaque = false }
        box.add(JBLabel("+$added").apply { foreground = Palette.added })
        box.add(JBLabel("−$removed").apply { foreground = Palette.removed })
        return box
    }

    private fun left(component: JComponent): JComponent {
        component.alignmentX = Component.LEFT_ALIGNMENT
        return component
    }

    private fun folderOf(path: String): String = path.substringBeforeLast('/', "/")

    private class RiskPill(private val risk: String) : JComponent() {
        private val color: Color = Palette.risk(risk)

        init {
            toolTipText = "$risk risk"
            font = JBUI.Fonts.smallFont()
        }

        override fun getPreferredSize(): Dimension {
            val metrics = getFontMetrics(font)
            return Dimension(metrics.stringWidth(risk) + 14, metrics.height + 4)
        }

        override fun paintComponent(g: Graphics) {
            val g2: Graphics2D = g.create() as Graphics2D
            try {
                g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
                g2.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING, RenderingHints.VALUE_TEXT_ANTIALIAS_ON)
                g2.color = color
                g2.drawRoundRect(0, 0, width - 1, height - 1, height, height)
                g2.font = font
                val metrics = g2.fontMetrics
                g2.drawString(risk, (width - metrics.stringWidth(risk)) / 2, (height + metrics.ascent - metrics.descent) / 2)
            } finally {
                g2.dispose()
            }
        }
    }
}
