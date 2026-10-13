package io.github.bkonold.prbrief.ui

import com.intellij.openapi.project.Project
import com.intellij.ui.SimpleColoredComponent
import com.intellij.ui.SimpleTextAttributes
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBList
import com.intellij.ui.components.JBScrollPane
import com.intellij.util.ui.JBUI
import com.intellij.util.ui.UIUtil
import io.github.bkonold.prbrief.BriefService
import io.github.bkonold.prbrief.Selection
import io.github.bkonold.prbrief.diff.ReviewCaptions
import io.github.bkonold.prbrief.model.Stop
import java.awt.BorderLayout
import java.awt.Color
import java.awt.Component
import java.awt.GridLayout
import java.awt.event.MouseEvent
import javax.swing.DefaultListModel
import javax.swing.JList
import javax.swing.JPanel
import javax.swing.ListCellRenderer
import javax.swing.ListSelectionModel

/** The walkthrough's stops as a list: number and title over the file and line, with the stop's `why` as the tooltip. */
class WalkthroughPanel(private val project: Project) : JPanel(BorderLayout()) {
    private val model = DefaultListModel<Stop>()
    private val header = JBLabel().apply {
        foreground = Palette.muted
        border = JBUI.Borders.empty(6, 10)
    }
    private var updating = false

    private val list: JBList<Stop> = object : JBList<Stop>(model) {
        override fun getToolTipText(event: MouseEvent): String? {
            val index: Int = locationToIndex(event.point)
            if (index < 0 || !getCellBounds(index, index).contains(event.point)) return null
            return model.getElementAt(index).why.takeIf { it.isNotBlank() }
        }
    }

    init {
        list.selectionMode = ListSelectionModel.SINGLE_SELECTION
        list.cellRenderer = StopRowRenderer()
        list.addListSelectionListener { event ->
            if (!event.valueIsAdjusting && !updating && list.selectedIndex >= 0) {
                project.getService(BriefService::class.java).select(Selection.StopAt(list.selectedIndex))
            }
        }
        add(header, BorderLayout.NORTH)
        add(JBScrollPane(list), BorderLayout.CENTER)
    }

    fun refresh(stops: List<Stop>, selection: Selection) {
        updating = true
        try {
            model.clear()
            stops.forEach(model::addElement)
            val count: Int = stops.size
            header.text = if (count == 1) "1 stop, in reading order" else "$count stops, in reading order"
            val selected: Int = (selection as? Selection.StopAt)?.index ?: -1
            if (selected in stops.indices) list.selectedIndex = selected else list.clearSelection()
        } finally {
            updating = false
        }
    }
}

/** One row per stop: its number and title, and under the title the file and line in a quieter colour. */
private class StopRowRenderer : ListCellRenderer<Stop> {
    private val number = SimpleColoredComponent().apply { isOpaque = false }
    private val title = SimpleColoredComponent().apply { isOpaque = false }
    private val fileLine = SimpleColoredComponent().apply { isOpaque = false }
    private val row = JPanel(BorderLayout(JBUI.scale(8), 0)).apply {
        border = JBUI.Borders.empty(3, 6)
        val text = JPanel(GridLayout(2, 1)).apply {
            isOpaque = false
            add(title)
            add(fileLine)
        }
        add(number, BorderLayout.WEST)
        add(text, BorderLayout.CENTER)
    }

    override fun getListCellRendererComponent(list: JList<out Stop>, value: Stop, index: Int, selected: Boolean, hasFocus: Boolean): Component {
        val foreground: Color = UIUtil.getListForeground(selected, hasFocus)
        val quiet: Color = if (selected) foreground else Palette.muted
        row.background = UIUtil.getListBackground(selected, hasFocus)
        number.clear()
        number.append("%2d".format(value.index), SimpleTextAttributes(SimpleTextAttributes.STYLE_PLAIN, quiet))
        title.clear()
        title.append(value.title, SimpleTextAttributes(SimpleTextAttributes.STYLE_PLAIN, foreground))
        fileLine.clear()
        fileLine.append(ReviewCaptions.location(value), SimpleTextAttributes(SimpleTextAttributes.STYLE_PLAIN, quiet))
        return row
    }
}
