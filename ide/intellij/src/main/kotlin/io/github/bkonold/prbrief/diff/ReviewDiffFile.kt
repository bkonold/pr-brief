package io.github.bkonold.prbrief.diff

import com.intellij.diff.chains.DiffRequestProducer
import com.intellij.diff.editor.DiffVirtualFile
import com.intellij.diff.editor.DiffVirtualFileWithTabName
import com.intellij.diff.impl.DiffRequestProcessor
import com.intellij.openapi.fileEditor.FileEditor
import com.intellij.openapi.project.Project

/** What one diff tab holds: producers of the diffs to page through, and which one to open first. */
class ReviewChain(val key: String, val producers: List<DiffRequestProducer>, val index: Int)

/**
 * The one editor tab of the review. It is a single file instance per project, so showing it again focuses the tab that
 * is already open, and [processor] lets the controller put a new chain into that tab.
 */
class ReviewDiffFile : DiffVirtualFile("PR Brief"), DiffVirtualFileWithTabName {
    /** The chain the next processor starts with; read when the editor opens the tab. */
    @Volatile
    var pending: ReviewChain? = null

    @Volatile
    var processor: ReviewDiffProcessor? = null

    override fun createProcessor(project: Project): DiffRequestProcessor {
        val created = ReviewDiffProcessor(project, this, pending ?: ReviewChain("empty", emptyList(), 0))
        processor = created
        return created
    }

    override fun getEditorTabName(project: Project, editors: List<FileEditor>): String = "PR Brief"
}
