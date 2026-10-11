package io.github.bkonold.prbrief.diff

import com.intellij.diff.actions.impl.GoToChangePopupBuilder
import com.intellij.diff.chains.SimpleDiffRequestChain
import com.intellij.diff.impl.CacheDiffRequestProcessor
import com.intellij.diff.chains.DiffRequestProducer
import com.intellij.diff.util.DiffUserDataKeys
import com.intellij.diff.util.DiffUserDataKeysEx.ScrollToPolicy
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.UserDataHolder
import com.intellij.openapi.util.UserDataHolderBase
import com.intellij.util.Consumer

/** The diff place whose settings, including the unified or side-by-side choice, belong to this tab. */
const val DIFF_PLACE = "PrBrief"

private fun placeContext(): UserDataHolder {
    val context = UserDataHolderBase()
    context.putUserData(DiffUserDataKeys.PLACE, DIFF_PLACE)
    return context
}

/**
 * Pages through a chain of producers like the platform's chain processor, but the chain can be replaced while the tab
 * stays open, which is how clicking another layer or stop reuses the tab.
 */
class ReviewDiffProcessor(project: Project, private val file: ReviewDiffFile, initial: ReviewChain) :
    CacheDiffRequestProcessor.Simple(project, placeContext()) {

    var chain: ReviewChain = initial
        private set

    var index: Int = initial.index
        private set

    /** The name of the producer being shown, which is the file path for file-based chains. */
    val currentName: String? get() = chain.producers.getOrNull(index)?.name

    fun setChain(next: ReviewChain) {
        chain = next
        index = next.index
        dropCaches()
        updateRequest()
    }

    fun showIndex(next: Int) {
        if (next !in chain.producers.indices) return
        index = next
        updateRequest()
    }

    override fun getCurrentRequestProvider(): DiffRequestProducer? = chain.producers.getOrNull(index)

    override fun hasNextChange(fromUpdate: Boolean): Boolean = index + 1 < chain.producers.size

    override fun hasPrevChange(fromUpdate: Boolean): Boolean = index > 0

    override fun goToNextChange(fromDifferences: Boolean) {
        goToNextChangeImpl(fromDifferences) {
            index++
            updateRequest(false, ScrollToPolicy.FIRST_CHANGE)
        }
    }

    override fun goToPrevChange(fromDifferences: Boolean) {
        goToPrevChangeImpl(fromDifferences) {
            index--
            updateRequest(false, ScrollToPolicy.LAST_CHANGE)
        }
    }

    override fun isNavigationEnabled(): Boolean = chain.producers.size > 1

    override fun createGoToChangeAction(): AnAction =
        GoToChangePopupBuilder.create(SimpleDiffRequestChain.fromProducers(chain.producers, index), Consumer { showIndex(it) }, index)

    override fun onDispose() {
        if (file.processor === this) file.processor = null
        super.onDispose()
    }
}
