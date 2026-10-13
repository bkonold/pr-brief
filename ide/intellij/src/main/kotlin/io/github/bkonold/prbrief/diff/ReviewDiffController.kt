package io.github.bkonold.prbrief.diff

import com.intellij.diff.editor.DiffEditorTabFilesManager
import com.intellij.diff.impl.DiffSettingsHolder.DiffSettings
import com.intellij.diff.tools.fragmented.UnifiedDiffTool
import com.intellij.diff.tools.simple.SimpleDiffTool
import com.intellij.diff.util.Side
import com.intellij.ide.util.PropertiesComponent
import com.intellij.notification.NotificationType
import com.intellij.openapi.Disposable
import com.intellij.openapi.application.WriteIntentReadAction
import com.intellij.openapi.components.Service
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.project.Project
import io.github.bkonold.prbrief.BriefListener
import io.github.bkonold.prbrief.BriefService
import io.github.bkonold.prbrief.LoadedBrief
import io.github.bkonold.prbrief.Selection
import io.github.bkonold.prbrief.git.GitSupport
import io.github.bkonold.prbrief.model.Review
import io.github.bkonold.prbrief.model.Stop

/**
 * Keeps the single review tab in step with what is picked in the tool window: a stop, a layer, a layer's file or a
 * changed file. The tab is reused, so each pick swaps the chain of diffs in the open tab instead of opening another.
 * Changes are applied under the write-intent lock, which the editor and diff APIs read under.
 */
@Service(Service.Level.PROJECT)
class ReviewDiffController(private val project: Project) : Disposable {
    private val service: BriefService = project.getService(BriefService::class.java)
    private val file = ReviewDiffFile()
    private var shownBrief: LoadedBrief? = null
    private var base: BaseTexts? = null
    private var shownSelection: Selection = Selection.None

    init {
        seedUnifiedView()
        service.addListener(BriefListener { WriteIntentReadAction.run { onChanged() } }, this)
    }

    private fun onChanged() {
        val brief: LoadedBrief? = service.brief
        if (brief !== shownBrief) {
            shownBrief = brief
            base = brief?.let { BaseTexts(GitSupport.forProject(project), it.mergeBase, it.review) }
            shownSelection = Selection.None
            FileEditorManager.getInstance(project).closeFile(file)
            file.pending = null
            return
        }
        val selection: Selection = service.selection
        if (brief == null || selection == shownSelection) return
        shownSelection = selection
        val chain: ReviewChain = chainFor(brief, selection) ?: return
        show(chain)
    }

    private fun show(chain: ReviewChain) {
        val open: ReviewDiffProcessor? = file.processor
        if (open == null) {
            file.pending = chain
        } else if (open.chain.key == chain.key) {
            open.showIndex(chain.index)
        } else {
            open.setChain(chain)
        }
        DiffEditorTabFilesManager.getInstance(project).showDiffFile(file, false)
    }

    /**
     * No selection keeps an open tab on its file, as the plain base against local diff; with nothing open there is
     * nothing to show. A stop opens its file at the stop's line, a layer its files in first-hunk order.
     */
    private fun chainFor(brief: LoadedBrief, selection: Selection): ReviewChain? {
        val review: Review = brief.review
        return when (selection) {
            is Selection.StopAt -> stopChain(brief, selection.index)
            is Selection.LayerAt -> layerChain(brief, selection)
            is Selection.FileAt -> filesChain(brief, selection.path)
            Selection.None -> if (file.processor == null) null else filesChain(brief, file.processor?.currentName ?: review.changedPaths.firstOrNull())
        }
    }

    private fun stopChain(brief: LoadedBrief, index: Int): ReviewChain? {
        val stops: List<Stop> = brief.review.walkthrough
        if (index !in stops.indices) return null
        val producers: List<ReviewFileProducer> = stops.mapIndexed { position, stop ->
            val target: ScrollTarget? = stop.line?.let { ScrollTarget(if (stop.side == "L") Side.LEFT else Side.RIGHT, it) }
            producer(brief, stop.path, null, StopFocus(stop, position, stops.size), target)
        }
        return ReviewChain("stops", producers, index)
    }

    private fun layerChain(brief: LoadedBrief, selection: Selection.LayerAt): ReviewChain? {
        val layer = service.layer(selection.index) ?: return null
        val paths: List<String> = layer.paths
        val producers: List<ReviewFileProducer> = paths.map { path ->
            val first = layer.hunks.first { it.path == path }
            val target: ScrollTarget? = if (first.newCount > 0) ScrollTarget(Side.RIGHT, first.newStart) else null
            producer(brief, path, layer.index, null, target)
        }
        return ReviewChain("layer:${layer.index}", producers, paths.indexOf(selection.file).coerceAtLeast(0))
    }

    private fun filesChain(brief: LoadedBrief, current: String?): ReviewChain? {
        val paths: List<String> = brief.review.changedPaths
        if (paths.isEmpty()) return null
        val producers: List<ReviewFileProducer> = paths.map { producer(brief, it, null, null, null) }
        return ReviewChain("files", producers, paths.indexOf(current).coerceAtLeast(0))
    }

    private fun producer(brief: LoadedBrief, path: String, layer: Int?, stop: StopFocus?, target: ScrollTarget?): ReviewFileProducer =
        ReviewFileProducer(
            project = project,
            review = brief.review,
            root = GitSupport.forProject(project)?.root,
            base = base ?: BaseTexts(null, null, brief.review),
            path = path,
            layer = layer,
            stop = stop,
            scrollTo = target,
            notifier = { service.notify(it, NotificationType.WARNING) },
        )

    /**
     * The review tab opens in the unified viewer. The viewer is whichever tool comes first in the order stored for this
     * tab's diff place, so the order is written once and the reviewer's later choice of side-by-side is kept.
     */
    private fun seedUnifiedView() {
        val properties: PropertiesComponent = PropertiesComponent.getInstance()
        if (properties.getBoolean(SEEDED_KEY)) return
        DiffSettings.getSettings(DIFF_PLACE).diffToolsOrder = listOf(UnifiedDiffTool::class.java.canonicalName, SimpleDiffTool::class.java.canonicalName)
        properties.setValue(SEEDED_KEY, true)
    }

    override fun dispose() = Unit

    companion object {
        private const val SEEDED_KEY = "prbrief.unifiedSeeded"

        fun getInstance(project: Project): ReviewDiffController = project.getService(ReviewDiffController::class.java)
    }
}
