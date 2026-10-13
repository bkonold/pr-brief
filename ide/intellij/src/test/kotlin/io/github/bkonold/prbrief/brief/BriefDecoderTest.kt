package io.github.bkonold.prbrief.brief

import io.github.bkonold.prbrief.Fixtures
import java.io.ByteArrayOutputStream
import java.util.Base64
import java.util.zip.GZIPOutputStream
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class BriefDecoderTest {
    private val comment: String = Fixtures.read("demo-brief-comment.md")

    private fun gzip(text: String): ByteArray {
        val out = ByteArrayOutputStream()
        GZIPOutputStream(out).use { it.write(text.toByteArray()) }
        return out.toByteArray()
    }

    @Test
    fun recognisesTheCommentByItsMarker() {
        assertTrue(BriefDecoder.isBriefComment(comment))
        assertFalse(BriefDecoder.isBriefComment("looks good to me"))
    }

    @Test
    fun decodesTheCommentThatPostPyWrites() {
        val review = BriefDecoder.decodeComment(comment)
        assertNotNull(review)
        assertEquals("bkonold/pr-brief-demo", review!!.repo)
        assertEquals(6, review.layers.size)
        assertEquals(38, review.allHunks.size)
    }

    @Test
    fun aCommentWithoutADataBlockHasNoReview() {
        assertNull(BriefDecoder.decodeComment("<details><summary>PR Brief</summary>text</details>\n<!-- pr-brief:v1 -->"))
    }

    @Test
    fun toleratesWrappedBase64() {
        val encoded: String = Base64.getEncoder().encodeToString(gzip(Fixtures.read("demo-review.json")))
        val wrapped: String = encoded.chunked(76).joinToString("\n")
        assertEquals(6, BriefDecoder.decode(wrapped).layers.size)
    }

    @Test
    fun refusesDataThatInflatesPastTheCap() {
        val bomb: ByteArray = gzip("x".repeat(10_000))
        assertThrows(BriefDecoder.DecodeException::class.java) { BriefDecoder.inflate(bomb, limit = 1_000) }
        assertEquals(10_000, BriefDecoder.inflate(bomb, limit = 10_000).size)
    }

    @Test
    fun refusesDataThatIsNotGzip() {
        val notGzip: String = Base64.getEncoder().encodeToString("plain".toByteArray())
        assertThrows(BriefDecoder.DecodeException::class.java) { BriefDecoder.decode(notGzip) }
    }
}
