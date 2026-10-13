package io.github.bkonold.prbrief.ui

import com.intellij.openapi.Disposable
import com.intellij.openapi.actionSystem.ActionManager
import com.intellij.openapi.actionSystem.ActionToolbar
import com.intellij.openapi.actionSystem.DefaultActionGroup
import com.intellij.openapi.project.Project
import com.intellij.ui.EditorNotificationPanel
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBTabbedPane
import com.intellij.util.ui.JBUI
import io.github.bkonold.prbrief.BriefListener
import io.github.bkonold.prbrief.BriefService
import io.github.bkonold.prbrief.BriefState
import io.github.bkonold.prbrief.LoadedBrief
import java.awt.BorderLayout
import java.awt.CardLayout
import javax.swing.Box
import javax.swing.BoxLayout
import javax.swing.JButton
import javax.swing.JComponent
import javax.swing.JPanel
import javax.swing.SwingConstants

/** The tool window's content: a toolbar, banners, and the Walkthrough, Layers and Files tabs. */
class PrBriefPanel(private val project: Project, parent: Disposable) : JPanel(BorderLayout()) {
    private val service: BriefService = project.getService(BriefService::class.java)
    private val walkthrough = WalkthroughPanel(project)
    private val layers = LayersPanel(project)
    private val files = FilesPanel(project)
    private val tabs = JBTabbedPane().apply {
        addTab("Walkthrough", walkthrough)
        addTab("Layers", layers)
        addTab("Files", files)
    }
    private val banners = JPanel().apply { layout = BoxLayout(this, BoxLayout.Y_AXIS) }
    private val message = JBLabel("", SwingConstants.CENTER)
    private val loadButton = JButton("Load the brief of this checkout").apply { addActionListener { service.loadFromGitHub() } }
    private val emptyState = JPanel().apply {
        layout = BoxLayout(this, BoxLayout.Y_AXIS)
        border = JBUI.Borders.empty(24)
        add(message.apply { alignmentX = 0.5f })
        add(Box.createVerticalStrut(10))
        add(loadButton.apply { alignmentX = 0.5f })
    }
    private val cards = CardLayout()
    private val body = JPanel(cards).apply {
        add(emptyState, EMPTY)
        add(tabs, TABS)
    }

    init {
        val group = DefaultActionGroup().apply {
            add(ActionManager.getInstance().getAction("PrBrief.Refresh"))
            add(ActionManager.getInstance().getAction("PrBrief.LoadFile"))
            add(ActionManager.getInstance().getAction("PrBrief.Settings"))
        }
        val toolbar: ActionToolbar = ActionManager.getInstance().createActionToolbar("PrBriefToolWindow", group, true)
        toolbar.targetComponent = this
        val north = JPanel(BorderLayout()).apply {
            add(toolbar.component, BorderLayout.NORTH)
            add(banners, BorderLayout.CENTER)
        }
        add(north, BorderLayout.NORTH)
        add(body, BorderLayout.CENTER)
        service.addListener(BriefListener { render() }, parent)
        render()
    }

    private fun render() {
        banners.removeAll()
        when (val state: BriefState = service.state) {
            BriefState.Idle -> showMessage("No brief is loaded.", canLoad = true)
            is BriefState.Loading -> showMessage(state.message, canLoad = false)
            is BriefState.Failed -> showMessage(state.message, canLoad = true)
            is BriefState.Ready -> showBrief(state.brief)
        }
        banners.revalidate()
        banners.repaint()
    }

    private fun showMessage(text: String, canLoad: Boolean) {
        message.text = text
        loadButton.isVisible = canLoad
        cards.show(body, EMPTY)
    }

    private fun showBrief(brief: LoadedBrief) {
        if (brief.stale) {
            banners.add(banner(EditorNotificationPanel.Status.Warning,
                "This brief was written for ${brief.review.headSha.take(7)}, but this checkout is at ${brief.localHead?.take(7)}."))
        }
        val via: String = brief.auth?.let { " · read with ${it.label}" } ?: ""
        banners.add(JBLabel("${brief.origin}$via").apply {
            foreground = Palette.muted
            border = JBUI.Borders.empty(2, 10)
        })
        brief.baseNote?.let { banners.add(banner(EditorNotificationPanel.Status.Info, it)) }
        if (brief.mergeBase == null) {
            banners.add(banner(EditorNotificationPanel.Status.Warning, "No base commit was found, so diffs cannot show what changed."))
        }
        walkthrough.refresh(brief.review.walkthrough, service.selection)
        layers.refresh(brief.review.layers, service.selection, service.judged)
        files.refresh(brief.review.changedPaths, brief.review.fileSets, service.selection)
        tabs.setEnabledAt(1, brief.review.layers.isNotEmpty())
        cards.show(body, TABS)
    }

    private fun banner(status: EditorNotificationPanel.Status, text: String): JComponent {
        val panel = EditorNotificationPanel(status)
        panel.text(text)
        panel.createActionLabel("Refresh") { service.refresh() }
        return panel
    }

    private companion object {
        const val EMPTY = "empty"
        const val TABS = "tabs"
    }
}
