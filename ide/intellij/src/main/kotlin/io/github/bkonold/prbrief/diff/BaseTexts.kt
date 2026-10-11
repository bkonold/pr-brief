package io.github.bkonold.prbrief.diff

import com.intellij.openapi.vfs.VirtualFile
import io.github.bkonold.prbrief.git.GitSupport
import io.github.bkonold.prbrief.model.Review
import java.nio.charset.Charset
import java.util.Optional
import java.util.concurrent.ConcurrentHashMap

/** The base-side text of the review's files, read once per path from the merge base with `git show`. */
class BaseTexts(private val git: GitSupport?, private val mergeBase: String?, private val review: Review) {
    private val cache = ConcurrentHashMap<String, Optional<String>>()

    /** The text of `path` at the merge base, or null when the file did not exist there. Blocks on git. */
    fun of(path: String, charset: Charset): String? =
        cache.computeIfAbsent(path) { Optional.ofNullable(read(path, charset)) }.orElse(null)

    private fun read(path: String, charset: Charset): String? {
        if (git == null || mergeBase == null) return null
        val bytes: ByteArray = git.showFile(mergeBase, path) ?: renamedBytes(path) ?: return null
        return String(bytes, charset).replace("\r\n", "\n")
    }

    /** A renamed file has no base content under its new path, so it is read from the path it had at the merge base. */
    private fun renamedBytes(path: String): ByteArray? {
        if (git == null || mergeBase == null) return null
        val renamed: Boolean = review.hunksOf(path).any { it.change == "renamed" || it.oldCount > 0 }
        if (!renamed) return null
        val oldPath: String = git.renamedFrom(mergeBase, review.headSha, path) ?: return null
        return git.showFile(mergeBase, oldPath)
    }

    companion object {
        fun charsetOf(file: VirtualFile?): Charset = file?.charset ?: Charsets.UTF_8
    }
}
