package io.github.bkonold.prbrief.diff

import com.intellij.diff.util.DiffNotificationProvider
import com.intellij.openapi.project.Project
import com.intellij.ui.EditorNotificationPanel
import io.github.bkonold.prbrief.BriefService
import io.github.bkonold.prbrief.Selection
import io.github.bkonold.prbrief.model.Layer
import io.github.bkonold.prbrief.model.Stop

/** A walkthrough stop as the reason a file is shown: the stop, its 0-based position in the walkthrough and the stop count. */
data class StopFocus(val stop: Stop, val position: Int, val total: Int)

/** The banners above a review diff that say why the file is being shown. */
internal object ReviewBanners {
    /** The stop's place and reason, with links to the stops on either side of it. */
    fun stop(project: Project, focus: StopFocus): DiffNotificationProvider = DiffNotificationProvider {
        val panel = EditorNotificationPanel(EditorNotificationPanel.Status.Info)
        panel.setText(ReviewCaptions.stopBanner(focus.stop, focus.total))
        stepStop(focus.position, focus.total, -1)?.let { panel.createActionLabel("Previous stop", Runnable { select(project, it) }) }
        stepStop(focus.position, focus.total, 1)?.let { panel.createActionLabel("Next stop", Runnable { select(project, it) }) }
        panel
    }

    fun layer(layer: Layer): DiffNotificationProvider = DiffNotificationProvider {
        EditorNotificationPanel(EditorNotificationPanel.Status.Info).apply { setText(ReviewCaptions.layerBanner(layer)) }
    }

    private fun select(project: Project, position: Int) {
        project.getService(BriefService::class.java).select(Selection.StopAt(position))
    }
}
