package io.github.bkonold.prbrief.diff

import com.intellij.diff.DiffContentFactory
import com.intellij.diff.chains.DiffRequestProducer
import com.intellij.diff.chains.DiffRequestProducerException
import com.intellij.diff.contents.DiffContent
import com.intellij.diff.requests.DiffRequest
import com.intellij.diff.requests.SimpleDiffRequest
import com.intellij.diff.util.DiffNotificationProvider
import com.intellij.diff.util.DiffUserDataKeys
import com.intellij.diff.util.Side
import com.intellij.openapi.application.ReadAction
import com.intellij.openapi.editor.Document
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileTypes.FileTypeManager
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Pair
import com.intellij.openapi.util.UserDataHolder
import com.intellij.openapi.vfs.LocalFileSystem
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.ui.EditorNotificationPanel
import io.github.bkonold.prbrief.model.HunkRange
import io.github.bkonold.prbrief.model.Review
import java.io.File

/** Where a stop sends the viewer: a 1-based line on one side of the diff. */
data class ScrollTarget(val side: Side, val line: Int)

/**
 * The diff of one file. The right side is the local file itself, so the editor on it is a normal one. The left side is
 * the base, or with a layer selected the head with that layer's hunks reverted to base, so the diff shows only that
 * layer's change in the file.
 */
class ReviewFileProducer(
    private val project: Project,
    private val review: Review,
    private val root: VirtualFile?,
    private val base: BaseTexts,
    private val path: String,
    private val layer: Int?,
    private val scrollTo: ScrollTarget? = null,
    private val notifier: (String) -> Unit,
) : DiffRequestProducer {
    override fun getName(): String = path

    override fun process(context: UserDataHolder, indicator: ProgressIndicator): DiffRequest {
        val local: VirtualFile? = findLocal()
        if (local != null && local.fileType.isBinary) throw DiffRequestProducerException("$path is a binary file")
        val headText: String? = local?.let { readHead(it) }
        val baseText: String? = base.of(path, BaseTexts.charsetOf(local))
        val fileHunks: List<HunkRange> = review.hunksOf(path)
        val selected: Set<String> = review.layers.firstOrNull { it.index == layer }
            ?.hunks?.filter { it.path == path }?.mapTo(HashSet()) { it.id }.orEmpty()

        val matches: Boolean = headText == null || baseText == null || fileHunks.isEmpty() ||
            LayerFilter.leftText(headText, baseText, fileHunks, emptySet()) != null
        var leftText: String = baseText.orEmpty()
        var leftTitle = "Base (merge base)"
        var warning: String? = null
        if (layer != null && selected.isNotEmpty() && headText != null && baseText != null) {
            val filtered: String? = LayerFilter.leftText(headText, baseText, fileHunks, selected)
            if (filtered != null) {
                leftText = filtered
                leftTitle = "Before layer $layer"
            } else {
                warning = "The local $path differs from the version the brief was made for, so this is the whole change " +
                    "of the file against the base, not just layer $layer."
                notifier(warning)
            }
        } else if (!matches) {
            warning = "The local $path differs from the version the brief was made for, so the layer markers are off."
        }

        val factory: DiffContentFactory = DiffContentFactory.getInstance()
        val left: DiffContent = if (baseText == null && leftText.isEmpty()) factory.createEmpty() else leftContent(factory, leftText, local)
        val right: DiffContent = if (local != null) {
            factory.createDocument(project, local) ?: throw DiffRequestProducerException("$path cannot be opened as text")
        } else {
            factory.createEmpty()
        }
        val request = SimpleDiffRequest(path, left, right, leftTitle, "Local file")

        if (warning != null) {
            val text: String = warning
            request.putUserData(
                DiffUserDataKeys.NOTIFICATION_PROVIDERS,
                listOf(DiffNotificationProvider { EditorNotificationPanel(EditorNotificationPanel.Status.Warning).apply { setText(text) } }),
            )
        }
        scrollTo?.let { request.putUserData(DiffUserDataKeys.SCROLL_TO_LINE, Pair.create(it.side, it.line - 1)) }
        if (layer != null && matches && local != null) request.putUserData(LAYER_MARKERS, markersFor(fileHunks))
        return request
    }

    /** The hunks of the other layers in this file: lines that look unchanged against the left side but are not the layer's own. */
    private fun markersFor(fileHunks: List<HunkRange>): List<LayerMarker> =
        fileHunks.filter { it.newCount > 0 }.mapNotNull { hunk ->
            val owner = review.layerOfHunk(hunk.id)
            if (owner == null || owner.index == layer) null else LayerMarker(hunk.newStart - 1, hunk.newStart - 1 + hunk.newCount, owner.index, owner.title)
        }

    private fun findLocal(): VirtualFile? {
        val dir: String = root?.path ?: return null
        val file = File(dir, path)
        return LocalFileSystem.getInstance().refreshAndFindFileByIoFile(file)?.takeIf { !it.isDirectory }
    }

    private fun readHead(file: VirtualFile): String? = ReadAction.compute<String?, RuntimeException> {
        val document: Document? = FileDocumentManager.getInstance().getDocument(file)
        document?.text
    }

    /** The left side is typed like the local file, or by the path's name when the file is not on disk. */
    private fun leftContent(factory: DiffContentFactory, text: String, local: VirtualFile?): DiffContent =
        if (local != null) {
            factory.create(project, text, local)
        } else {
            factory.create(project, text, FileTypeManager.getInstance().getFileTypeByFileName(path))
        }
}
