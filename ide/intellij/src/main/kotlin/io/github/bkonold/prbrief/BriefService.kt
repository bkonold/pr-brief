package io.github.bkonold.prbrief

import com.intellij.ide.util.PropertiesComponent
import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.Service
import com.intellij.openapi.progress.ProcessCanceledException
import com.intellij.openapi.progress.ProgressIndicator
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.progress.Task
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.Messages
import com.intellij.openapi.util.Disposer
import io.github.bkonold.prbrief.brief.BriefDecoder
import io.github.bkonold.prbrief.git.GitSupport
import io.github.bkonold.prbrief.git.RemoteSlug
import io.github.bkonold.prbrief.github.AuthSource
import io.github.bkonold.prbrief.github.AuthToken
import io.github.bkonold.prbrief.github.GitHubAuth
import io.github.bkonold.prbrief.github.GitHubClient
import io.github.bkonold.prbrief.github.PullInfo
import io.github.bkonold.prbrief.github.PullSummary
import io.github.bkonold.prbrief.model.Layer
import io.github.bkonold.prbrief.model.Review
import io.github.bkonold.prbrief.model.ReviewParser
import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.CopyOnWriteArrayList

/** A brief that was read, with what is needed to show it against the local checkout. */
data class LoadedBrief(
    val review: Review,
    val origin: String,
    val auth: AuthSource?,
    /** The commit the base side of every diff is read from; null when none could be found. */
    val mergeBase: String?,
    val baseNote: String?,
    val localHead: String?,
) {
    val stale: Boolean get() = localHead != null && localHead != review.headSha
}

sealed interface BriefState {
    data object Idle : BriefState
    data class Loading(val message: String) : BriefState
    data class Failed(val message: String) : BriefState
    data class Ready(val brief: LoadedBrief) : BriefState
}

/** What the reviewer has picked in the tool window; the diff tab follows it. */
sealed interface Selection {
    data object None : Selection
    data class StopAt(val index: Int) : Selection
    data class LayerAt(val index: Int, val file: String? = null) : Selection
    data class FileAt(val path: String) : Selection
}

fun interface BriefListener {
    fun changed()
}

@Service(Service.Level.PROJECT)
class BriefService(private val project: Project) : Disposable {
    var state: BriefState = BriefState.Idle
        private set

    var selection: Selection = Selection.None
        private set

    var judged: Set<Int> = emptySet()
        private set

    private val listeners = CopyOnWriteArrayList<BriefListener>()
    private var reload: (() -> Unit)? = null
    private var lastPr: Int? = null

    val brief: LoadedBrief? get() = (state as? BriefState.Ready)?.brief

    fun addListener(listener: BriefListener, parent: Disposable) {
        listeners.add(listener)
        Disposer.register(parent) { listeners.remove(listener) }
    }

    fun select(next: Selection) {
        selection = next
        fire()
    }

    fun toggleJudged(layer: Int) {
        val loaded: LoadedBrief = brief ?: return
        judged = if (layer in judged) judged - layer else judged + layer
        PropertiesComponent.getInstance(project).setValue(judgedKey(loaded.review), judged.sorted().joinToString(","))
        fire()
    }

    fun layer(index: Int): Layer? = brief?.review?.layers?.firstOrNull { it.index == index }

    /** Re-reads the brief from where it was last read from; the GitHub PR is looked up afresh if none was chosen. */
    fun refresh() {
        val again: (() -> Unit)? = reload
        if (again != null) again() else loadFromGitHub()
    }

    fun loadFromGitHub(prNumber: Int? = null) {
        reload = { loadFromGitHub(lastPr) }
        runTask("Loading the PR brief") { indicator -> readFromGitHub(indicator, prNumber ?: lastPr) }
    }

    fun loadFromFile(path: Path) {
        reload = { loadFromFile(path) }
        runTask("Reading review.json") { indicator ->
            val review: Review = ReviewParser.parse(Files.readString(path))
            val git: GitSupport? = GitSupport.forProject(project)
            val base: BaseResult = resolveBase(indicator, git, review, null)
            LoadedBrief(review, path.toString(), null, base.mergeBase, base.note, git?.headSha)
        }
    }

    private fun readFromGitHub(indicator: ProgressIndicator, knownPr: Int?): LoadedBrief {
        val git: GitSupport = GitSupport.forProject(project) ?: throw LoadFailure("This project has no Git repository")
        val slug: RemoteSlug = git.remoteSlug() ?: throw LoadFailure("No GitHub remote found in the repository")
        val localHead: String? = git.headSha
        indicator.text = "Finding credentials"
        val auth: AuthToken = GitHubAuth.resolve(project, slug.host)
        val client = GitHubClient(slug.host, auth.token)
        val number: Int = knownPr ?: pickPull(indicator, client, slug, localHead)
        lastPr = number
        indicator.text = "Reading comments of PR $number"
        val comment: String = client.briefComment(slug.owner, slug.repo, number)
            ?: throw LoadFailure("PR $number has no PR Brief comment yet")
        val review: Review = try {
            BriefDecoder.decodeComment(comment) ?: throw LoadFailure("The brief comment has no data block, so it cannot be opened here")
        } catch (e: BriefDecoder.DecodeException) {
            throw LoadFailure(e.message ?: "The brief could not be decoded")
        }
        indicator.text = "Reading PR $number"
        val pull: PullInfo? = try {
            client.pull(slug.owner, slug.repo, number)
        } catch (e: Exception) {
            null
        }
        val base: BaseResult = resolveBase(indicator, git, review, pull)
        return LoadedBrief(review, "${slug.owner}/${slug.repo}#$number", auth.source, base.mergeBase, base.note, localHead)
    }

    private fun pickPull(indicator: ProgressIndicator, client: GitHubClient, slug: RemoteSlug, head: String?): Int {
        indicator.text = "Finding the PR of the checked-out commit"
        val pulls: List<PullSummary> = if (head != null) client.pullsForCommit(slug.owner, slug.repo, head) else emptyList()
        if (pulls.size == 1) return pulls[0].number
        var chosen: Int? = null
        ApplicationManager.getApplication().invokeAndWait {
            chosen = if (pulls.isEmpty()) {
                Messages.showInputDialog(
                    project,
                    "No pull request is linked to the checked-out commit. Pull request number:",
                    "PR Brief",
                    null,
                )?.trim()?.removePrefix("#")?.toIntOrNull()
            } else {
                val labels: Array<String> = pulls.map { "#${it.number} ${it.title} (${it.state})" }.toTypedArray()
                val index: Int = Messages.showChooseDialog(
                    project,
                    "Several pull requests contain the checked-out commit. Which one?",
                    "PR Brief",
                    null,
                    labels,
                    labels[0],
                )
                pulls.getOrNull(index)?.number
            }
        }
        return chosen ?: throw ProcessCanceledException()
    }

    private data class BaseResult(val mergeBase: String?, val note: String?)

    /**
     * The commit the base side is read from: the merge base of the PR's base branch tip and the brief's head commit,
     * fetching the base branch first when its tip is not local. Without the PR (a review.json read from a file with no
     * network) it falls back to the merge base with the remote's default branch.
     */
    private fun resolveBase(indicator: ProgressIndicator, git: GitSupport?, review: Review, pull: PullInfo?): BaseResult {
        if (git == null) return BaseResult(null, "No Git repository, so the base side is empty")
        indicator.text = "Finding the merge base"
        val head: String = review.headSha.takeIf { git.hasCommit(it) } ?: git.headSha
            ?: return BaseResult(null, "The repository has no commits")
        val candidates: List<String> = buildList {
            if (pull != null) {
                if (!git.hasCommit(pull.baseSha)) git.fetch(pull.baseRef)
                add(pull.baseSha)
            }
            addAll(listOf("origin/HEAD", "origin/main", "origin/master", "main", "master"))
        }
        for (candidate in candidates) {
            val tip: String = git.resolve(candidate) ?: continue
            val base: String? = git.mergeBase(tip, head)
            if (base != null) {
                val note: String? = if (pull == null) "The base is the merge base with $candidate: the PR's own base was not available" else null
                return BaseResult(base, note)
            }
        }
        return BaseResult(null, "No merge base with the PR's base branch could be found")
    }

    private class LoadFailure(message: String) : Exception(message)

    private fun runTask(title: String, work: (ProgressIndicator) -> LoadedBrief) {
        update(BriefState.Loading("$title…"))
        ProgressManager.getInstance().run(object : Task.Backgroundable(project, title, true) {
            override fun run(indicator: ProgressIndicator) {
                try {
                    val loaded: LoadedBrief = work(indicator)
                    ApplicationManager.getApplication().invokeLater {
                        judged = readJudged(loaded.review)
                        selection = Selection.None
                        state = BriefState.Ready(loaded)
                        fire()
                    }
                } catch (e: ProcessCanceledException) {
                    update(BriefState.Idle)
                } catch (e: Exception) {
                    update(BriefState.Failed(e.message ?: e.javaClass.simpleName))
                }
            }
        })
    }

    fun notify(message: String, type: NotificationType) {
        NotificationGroupManager.getInstance().getNotificationGroup("PR Brief").createNotification(message, type).notify(project)
    }

    private fun update(next: BriefState) {
        ApplicationManager.getApplication().invokeLater {
            state = next
            fire()
        }
    }

    private fun fire() {
        listeners.forEach { it.changed() }
    }

    private fun readJudged(review: Review): Set<Int> =
        PropertiesComponent.getInstance(project).getValue(judgedKey(review), "")
            .split(',').mapNotNull { it.trim().toIntOrNull() }.toSet()

    private fun judgedKey(review: Review): String = "prbrief.judged:${review.repo}#${review.pr}@${review.headSha}"

    override fun dispose() = Unit
}
