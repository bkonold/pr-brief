package io.github.bkonold.prbrief.diff

import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.project.DumbAware
import io.github.bkonold.prbrief.BriefService
import io.github.bkonold.prbrief.Selection

/** Steps the walkthrough: the stop after (or before) the selected one, or the first (last) one when none is selected. */
abstract class StepStopAction(private val direction: Int) : AnAction(), DumbAware {
    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT

    override fun update(e: AnActionEvent) {
        val service: BriefService? = e.project?.getService(BriefService::class.java)
        e.presentation.isEnabled = service != null && target(service) != null
    }

    override fun actionPerformed(e: AnActionEvent) {
        val service: BriefService = e.project?.getService(BriefService::class.java) ?: return
        target(service)?.let { service.select(Selection.StopAt(it)) }
    }

    private fun target(service: BriefService): Int? {
        val stops: Int = service.brief?.review?.walkthrough?.size ?: return null
        val current: Int? = (service.selection as? Selection.StopAt)?.index
        val next: Int = if (current == null) (if (direction > 0) 0 else stops - 1) else current + direction
        return next.takeIf { it in 0 until stops }
    }
}

class NextStopAction : StepStopAction(1)

class PreviousStopAction : StepStopAction(-1)
