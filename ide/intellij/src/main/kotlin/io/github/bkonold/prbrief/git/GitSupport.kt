package io.github.bkonold.prbrief.git

import com.intellij.openapi.project.Project
import com.intellij.openapi.vcs.VcsException
import com.intellij.openapi.vfs.VirtualFile
import git4idea.commands.Git
import git4idea.commands.GitBinaryHandler
import git4idea.commands.GitCommand
import git4idea.commands.GitCommandResult
import git4idea.commands.GitLineHandler
import git4idea.repo.GitRemote
import git4idea.repo.GitRepository
import git4idea.repo.GitRepositoryManager

data class RemoteSlug(val host: String, val owner: String, val repo: String)

/** The Git operations the review needs, on one repository. All of them block, so call them from a background thread. */
class GitSupport(private val project: Project, val repository: GitRepository) {
    val root: VirtualFile get() = repository.root

    val headSha: String? get() = repository.currentRevision

    /** `owner/repo` of `origin`, or of the first remote that points at a GitHub-style host. */
    fun remoteSlug(): RemoteSlug? {
        val remotes: List<GitRemote> = repository.remotes.sortedBy { if (it.name == "origin") 0 else 1 }
        return remotes.flatMap { it.urls }.firstNotNullOfOrNull { parseRemoteUrl(it) }
    }

    fun hasCommit(sha: String): Boolean {
        val handler = GitLineHandler(project, root, GitCommand.CAT_FILE)
        handler.setSilent(true)
        handler.addParameters("-e", "$sha^{commit}")
        return Git.getInstance().runCommand(handler).success()
    }

    /** Fetches `ref` from the repository's remote so that commits reachable from it exist locally. */
    fun fetch(ref: String): Boolean {
        val remote: GitRemote = repository.remotes.firstOrNull { it.name == "origin" } ?: repository.remotes.firstOrNull() ?: return false
        return Git.getInstance().fetch(repository, remote, emptyList(), ref).success()
    }

    fun mergeBase(a: String, b: String): String? {
        val handler = GitLineHandler(project, root, GitCommand.MERGE_BASE)
        handler.setSilent(true)
        handler.addParameters(a, b)
        return singleLine(Git.getInstance().runCommand(handler))
    }

    /** The bytes of `path` at `revision`, or null when the file does not exist there. */
    fun showFile(revision: String, path: String): ByteArray? {
        val handler = GitBinaryHandler(project, root, GitCommand.SHOW)
        handler.setSilent(true)
        handler.addParameters("$revision:$path")
        return try {
            handler.run()
        } catch (e: VcsException) {
            null
        }
    }

    /** The path a renamed file had at `base`, found by a rename-detecting diff of `base` against `head`. */
    fun renamedFrom(base: String, head: String, newPath: String): String? {
        val handler = GitLineHandler(project, root, GitCommand.DIFF)
        handler.setSilent(true)
        handler.addParameters("--name-status", "-M", "--diff-filter=R", base, head)
        val result: GitCommandResult = Git.getInstance().runCommand(handler)
        if (!result.success()) return null
        return result.output.map { it.split('\t') }
            .firstOrNull { it.size >= 3 && it[0].startsWith("R") && it[2] == newPath }
            ?.get(1)
    }

    /** Resolves `rev` to a full commit id, or null when git does not know it. */
    fun resolve(rev: String): String? {
        val handler = GitLineHandler(project, root, GitCommand.REV_PARSE)
        handler.setSilent(true)
        handler.addParameters("--verify", "--quiet", "$rev^{commit}")
        return singleLine(Git.getInstance().runCommand(handler))
    }

    private fun singleLine(result: GitCommandResult): String? =
        if (result.success()) result.output.firstOrNull()?.trim()?.takeIf { it.isNotEmpty() } else null

    companion object {
        private val SCP_LIKE = Regex("""^(?:[\w.-]+@)?([\w.-]+):([\w.-]+)/([\w.-]+?)(?:\.git)?/?$""")
        private val URL_LIKE = Regex("""^[a-z+]+://(?:[^@/]+@)?([\w.-]+)(?::\d+)?/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$""")

        fun parseRemoteUrl(url: String): RemoteSlug? {
            val match: MatchResult = URL_LIKE.find(url.trim()) ?: SCP_LIKE.find(url.trim()) ?: return null
            val (host, owner, repo) = match.destructured
            return RemoteSlug(host, owner, repo)
        }

        fun forProject(project: Project): GitSupport? {
            val repositories: List<GitRepository> = GitRepositoryManager.getInstance(project).repositories
            val repository: GitRepository = repositories.firstOrNull { repo -> repo.remotes.any { it.urls.any { url -> parseRemoteUrl(url) != null } } }
                ?: repositories.firstOrNull()
                ?: return null
            return GitSupport(project, repository)
        }
    }
}
