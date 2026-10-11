package io.github.bkonold.prbrief.brief

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import io.github.bkonold.prbrief.model.Review
import io.github.bkonold.prbrief.model.ReviewParser
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.util.Base64
import java.util.zip.GZIPInputStream

/**
 * Reads a brief out of the PR comment that `post.py` writes: a collapsed "Brief data" block whose code fence holds the
 * base64 of the gzip of review.json plus the run's `diagram_svg` and `body_html`, which the IDE ignores.
 */
object BriefDecoder {
    const val MARKER = "<!-- pr-brief:v1"
    const val MAX_INFLATED_BYTES: Int = 16 * 1024 * 1024

    private val DATA_BLOCK = Regex(
        """<details>\s*<summary>\s*Brief data\s*</summary>\s*```[^\n]*\n([A-Za-z0-9+/=\s]*?)\s*```""",
        RegexOption.DOT_MATCHES_ALL,
    )

    class DecodeException(message: String) : Exception(message)

    fun isBriefComment(body: String): Boolean = body.contains(MARKER)

    /** The text of the code fence in the first "Brief data" block of `comment`, or null when it has none. */
    fun extractPayload(comment: String): String? =
        DATA_BLOCK.find(comment)?.groupValues?.get(1)?.trim()?.takeIf { it.isNotEmpty() }

    /** The review in a comment body; null when the comment holds no data block (it was over GitHub's size limit). */
    fun decodeComment(comment: String): Review? = extractPayload(comment)?.let { decode(it) }

    fun decode(base64: String): Review {
        val gzipped: ByteArray = try {
            Base64.getMimeDecoder().decode(base64.filterNot { it.isWhitespace() })
        } catch (e: IllegalArgumentException) {
            throw DecodeException("The brief data is not base64")
        }
        val json: String = inflate(gzipped).toString(Charsets.UTF_8)
        val root: JsonObject = try {
            JsonParser.parseString(json).asJsonObject
        } catch (e: RuntimeException) {
            throw DecodeException("The brief data is not a JSON object")
        }
        return try {
            ReviewParser.parse(root)
        } catch (e: ReviewParser.InvalidReviewException) {
            throw DecodeException(e.message ?: "Invalid review")
        } catch (e: RuntimeException) {
            throw DecodeException("The brief data is missing a field: ${e.message}")
        }
    }

    /** The bytes `gzipped` holds, failing once they pass [MAX_INFLATED_BYTES] so a bomb is never fully inflated. */
    internal fun inflate(gzipped: ByteArray, limit: Int = MAX_INFLATED_BYTES): ByteArray {
        val out = ByteArrayOutputStream()
        try {
            GZIPInputStream(ByteArrayInputStream(gzipped)).use { input ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val read: Int = input.read(buffer)
                    if (read < 0) break
                    if (out.size() + read > limit) throw DecodeException("The brief data inflates past $limit bytes")
                    out.write(buffer, 0, read)
                }
            }
        } catch (e: IOException) {
            throw DecodeException("The brief data is not gzip")
        }
        return out.toByteArray()
    }
}
