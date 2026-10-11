package io.github.bkonold.prbrief.ui

import com.intellij.openapi.project.Project
import com.intellij.ui.ColoredListCellRenderer
import com.intellij.ui.SimpleTextAttributes
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBList
import com.intellij.ui.components.JBScrollPane
import com.intellij.util.ui.JBUI
import io.github.bkonold.prbrief.BriefService
import io.github.bkonold.prbrief.Selection
import io.github.bkonold.prbrief.model.Stop
import java.awt.BorderLayout
import java.awt.event.MouseEvent
import javax.swing.DefaultListModel
import javax.swing.JList
import javax.swing.JPanel
import javax.swing.ListSelectionModel

/** The walkthrough's stops as a list: number and title, with the stop's `why` as the tooltip. */
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
        list.cellRenderer = object : ColoredListCellRenderer<Stop>() {
            override fun customizeCellRenderer(list: JList<out Stop>, value: Stop, index: Int, selected: Boolean, hasFocus: Boolean) {
                append("%2d  ".format(value.index), SimpleTextAttributes.GRAYED_ATTRIBUTES)
                append(value.title)
                ipad = JBUI.insets(3, 6)
            }
        }
        list.addListSelectionListener { event ->
            if (!event.valueIsAdjusting && !updating) {
                list.selectedValue?.let { project.getService(BriefService::class.java).select(Selection.StopAt(it.index)) }
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
            val selected: Int = (selection as? Selection.StopAt)?.let { s -> stops.indexOfFirst { it.index == s.index } } ?: -1
            if (selected >= 0) list.selectedIndex = selected else list.clearSelection()
        } finally {
            updating = false
        }
    }
}
