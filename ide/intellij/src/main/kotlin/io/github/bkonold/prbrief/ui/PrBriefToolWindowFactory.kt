package io.github.bkonold.prbrief.ui

import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.content.ContentFactory
import io.github.bkonold.prbrief.BriefService
import io.github.bkonold.prbrief.BriefState

class PrBriefToolWindowFactory : ToolWindowFactory, DumbAware {
    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val panel = PrBriefPanel(project, toolWindow.disposable)
        toolWindow.contentManager.addContent(ContentFactory.getInstance().createContent(panel, "", false))
        val service: BriefService = project.getService(BriefService::class.java)
        if (service.state == BriefState.Idle) service.loadFromGitHub()
    }
}
