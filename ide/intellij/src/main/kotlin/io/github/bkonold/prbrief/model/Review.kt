package io.github.bkonold.prbrief.model

/** One hunk of a layer: where it sits in the old (base) and new (head) file, as 1-based `[start, count]` ranges. */
data class HunkRange(
    val id: String,
    val path: String,
    val change: String,
    val oldStart: Int,
    val oldCount: Int,
    val newStart: Int,
    val newCount: Int,
    val added: Int?,
    val removed: Int?,
)

data class Stop(
    val index: Int,
    val title: String,
    val why: String,
    val path: String,
    val side: String,
    val line: Int?,
)

data class Layer(
    val index: Int,
    val title: String,
    val summary: String,
    val risk: String,
    val riskReason: String?,
    val dependsOn: List<Int>,
    val hunks: List<HunkRange>,
) {
    /** The paths of this layer's hunks, in the order of each path's first hunk. */
    val paths: List<String> get() = hunks.map { it.path }.distinct()
}

data class FileSets(val contract: Set<String>, val data: Set<String>, val tests: Set<String>)

/** The parts of review.json the IDE reads. */
data class Review(
    val repo: String,
    val pr: Int,
    val headSha: String,
    val walkthrough: List<Stop>,
    val layers: List<Layer>,
    val fileSets: FileSets,
) {
    val allHunks: List<HunkRange> get() = layers.flatMap { it.hunks }

    /** Every changed path: the paths of the hunks in the order of their first hunk, or without layers the stops' and file sets' paths. */
    val changedPaths: List<String>
        get() = if (layers.isNotEmpty()) {
            allHunks.map { it.path }.distinct()
        } else {
            (walkthrough.map { it.path } + fileSets.contract + fileSets.data + fileSets.tests).distinct()
        }

    fun hunksOf(path: String): List<HunkRange> = allHunks.filter { it.path == path }

    fun layerOfHunk(hunkId: String): Layer? = layers.firstOrNull { layer -> layer.hunks.any { it.id == hunkId } }
}
