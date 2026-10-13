package io.github.bkonold.prbrief.github

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class GitHubClientTest {
    private class Recorded(val url: String, val headers: Map<String, String>)

    private fun client(token: String?, calls: MutableList<Recorded>, host: String = "github.com", reply: (String) -> HttpReply): GitHubClient =
        GitHubClient(host, token) { url, headers ->
            calls.add(Recorded(url, headers))
            reply(url)
        }

    @Test
    fun findsTheBriefCommentOnALaterPage() {
        val calls = mutableListOf<Recorded>()
        val second = "https://api.github.com/repositories/1/issues/7/comments?per_page=100&page=2"
        val github: GitHubClient = client(null, calls) { url ->
            if (url.endsWith("page=2")) {
                HttpReply(200, """[{"body":"first <!-- pr-brief:v1 -->"}]""", null)
            } else {
                HttpReply(200, """[{"body":"hello"}]""", """<$second>; rel="next", <$second>; rel="last"""")
            }
        }
        assertEquals("first <!-- pr-brief:v1 -->", github.briefComment("o", "r", 7))
        assertEquals(2, calls.size)
        assertEquals("https://api.github.com/repos/o/r/issues/7/comments?per_page=100", calls[0].url)
    }

    @Test
    fun noBriefCommentGivesNull() {
        val github: GitHubClient = client(null, mutableListOf()) { HttpReply(200, """[{"body":"hello"}]""", null) }
        assertNull(github.briefComment("o", "r", 7))
    }

    @Test
    fun doesNotFollowANextLinkToAnotherHost() {
        val calls = mutableListOf<Recorded>()
        val github: GitHubClient = client("secret", calls) {
            HttpReply(200, "[]", """<https://example.com/steal>; rel="next"""")
        }
        assertNull(github.briefComment("o", "r", 7))
        assertEquals(1, calls.size)
    }

    @Test
    fun sendsTheTokenOnlyInTheAuthorizationHeader() {
        val calls = mutableListOf<Recorded>()
        client("secret", calls) { HttpReply(200, "[]", null) }.pullsForCommit("o", "r", "abc")
        assertEquals("Bearer secret", calls[0].headers["Authorization"])
        assertEquals(false, calls[0].url.contains("secret"))
        val anonymous = mutableListOf<Recorded>()
        client(null, anonymous) { HttpReply(200, "[]", null) }.pullsForCommit("o", "r", "abc")
        assertEquals(false, anonymous[0].headers.containsKey("Authorization"))
    }

    @Test
    fun readsThePullsOfACommitAndABasePull() {
        val github: GitHubClient = client(null, mutableListOf()) { url ->
            if (url.contains("/commits/")) {
                HttpReply(200, """[{"number":4,"title":"Holds","state":"open"}]""", null)
            } else {
                HttpReply(200, """{"title":"Holds","base":{"ref":"main","sha":"b1"},"head":{"sha":"h1"}}""", null)
            }
        }
        assertEquals(listOf(PullSummary(4, "Holds", "open")), github.pullsForCommit("o", "r", "abc"))
        assertEquals(PullInfo(4, "Holds", "main", "b1", "h1"), github.pull("o", "r", 4))
    }

    @Test
    fun usesTheApiPathOfAnEnterpriseHost() {
        val calls = mutableListOf<Recorded>()
        client(null, calls, host = "git.example.com") { HttpReply(200, "[]", null) }.pullsForCommit("o", "r", "abc")
        assertEquals("https://git.example.com/api/v3/repos/o/r/commits/abc/pulls?per_page=100", calls[0].url)
    }

    @Test
    fun explainsANotFound() {
        val github: GitHubClient = client(null, mutableListOf()) { HttpReply(404, "{}", null) }
        val failure: GitHubException = assertThrows(GitHubException::class.java) { github.pull("o", "r", 1) }
        assertEquals(404, failure.status)
    }
}
