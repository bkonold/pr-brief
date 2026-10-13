package io.github.bkonold.prbrief.diff

import io.github.bkonold.prbrief.model.HunkRange

/**
 * Builds the left side of a layer's diff: the head text with the selected hunks reverted to their base lines. Compared
 * with head, the file then differs exactly in the selected hunks, and every other layer's change counts as unchanged.
 *
 * A hunk's ranges are 1-based `[start, count]`. For a range with a count of 0 the start is the line before the
 * insertion point (0 at the top of the file), as in a unified diff header.
 */
object LayerFilter {
    /**
     * `head` with the lines of every hunk in `selected` replaced by the base lines of that hunk, or null when `head`
     * is not the file the hunks were cut from. `fileHunks` must hold every hunk of the file, in any order: the lines
     * outside all hunks are the same in head and base, which is what proves that head matches the hunks' ranges.
     */
    fun leftText(head: String, base: String, fileHunks: List<HunkRange>, selected: Set<String>): String? {
        val headLines: List<String> = splitLines(head)
        val baseLines: List<String> = splitLines(base)
        val ordered: List<HunkRange> = fileHunks.sortedWith(compareBy({ headStart(it) }, { baseStart(it) }))
        val result = ArrayList<String>(headLines.size)
        var headPos = 0
        var basePos = 0
        for (hunk in ordered) {
            val headFrom: Int = headStart(hunk)
            val baseFrom: Int = baseStart(hunk)
            val headTo: Int = headFrom + hunk.newCount
            val baseTo: Int = baseFrom + hunk.oldCount
            if (headFrom < headPos || baseFrom < basePos || headTo > headLines.size || baseTo > baseLines.size) return null
            if (!sameLines(headLines, headPos, headFrom, baseLines, basePos, baseFrom)) return null
            result.addAll(headLines.subList(headPos, headFrom))
            result.addAll(if (hunk.id in selected) baseLines.subList(baseFrom, baseTo) else headLines.subList(headFrom, headTo))
            headPos = headTo
            basePos = baseTo
        }
        if (!sameLines(headLines, headPos, headLines.size, baseLines, basePos, baseLines.size)) return null
        result.addAll(headLines.subList(headPos, headLines.size))
        return join(result)
    }

    /** The index in head's lines of the first line the hunk covers, or where its lines would be inserted. */
    private fun headStart(hunk: HunkRange): Int = if (hunk.newCount > 0) hunk.newStart - 1 else hunk.newStart

    private fun baseStart(hunk: HunkRange): Int = if (hunk.oldCount > 0) hunk.oldStart - 1 else hunk.oldStart

    private fun sameLines(a: List<String>, aFrom: Int, aTo: Int, b: List<String>, bFrom: Int, bTo: Int): Boolean {
        if (aTo - aFrom != bTo - bFrom) return false
        for (offset in 0 until aTo - aFrom) {
            if (a[aFrom + offset] != b[bFrom + offset]) return false
        }
        return true
    }

    /** The lines of `text`, each with its own `\n`; the last has none when the text does not end in one. */
    internal fun splitLines(text: String): List<String> {
        val lines = ArrayList<String>()
        var start = 0
        while (start < text.length) {
            val newline: Int = text.indexOf('\n', start)
            if (newline < 0) {
                lines.add(text.substring(start))
                break
            }
            lines.add(text.substring(start, newline + 1))
            start = newline + 1
        }
        return lines
    }

    /** The lines joined back, with a `\n` added to any line before the last that lacks one. */
    private fun join(lines: List<String>): String {
        val out = StringBuilder()
        for ((index, line) in lines.withIndex()) {
            out.append(line)
            if (index < lines.size - 1 && !line.endsWith("\n")) out.append('\n')
        }
        return out.toString()
    }
}
