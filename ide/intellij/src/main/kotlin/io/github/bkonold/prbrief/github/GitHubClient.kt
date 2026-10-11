package io.github.bkonold.prbrief.github

import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import io.github.bkonold.prbrief.brief.BriefDecoder
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

class GitHubException(val status: Int, message: String) : Exception(message)

data class HttpReply(val status: Int, val body: String, val link: String?)

/** One GET. The token, when there is one, travels only in `headers`. */
fun interface HttpTransport {
    fun get(url: String, headers: Map<String, String>): HttpReply
}

class JdkHttpTransport : HttpTransport {
    private val client: HttpClient = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(15))
        .followRedirects(HttpClient.Redirect.NORMAL)
        .build()

    override fun get(url: String, headers: Map<String, String>): HttpReply {
        val builder: HttpRequest.Builder = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(60)).GET()
        headers.forEach { (name, value) -> builder.header(name, value) }
        val response: HttpResponse<String> = client.send(builder.build(), HttpResponse.BodyHandlers.ofString())
        return HttpReply(response.statusCode(), response.body(), response.headers().firstValue("Link").orElse(null))
    }
}

data class PullSummary(val number: Int, val title: String, val state: String)

data class PullInfo(val number: Int, val title: String, val baseRef: String, val baseSha: String, val headSha: String)

/** The few GitHub REST calls the brief needs. */
class GitHubClient(
    host: String,
    private val token: String?,
    private val transport: HttpTransport = JdkHttpTransport(),
) {
    private val apiBase: String =
        if (host == "github.com") "https://api.github.com" else "https://$host/api/v3"

    fun pullsForCommit(owner: String, repo: String, sha: String): List<PullSummary> =
        array("/repos/$owner/$repo/commits/$sha/pulls?per_page=100").map {
            val pull: JsonObject = it.asJsonObject
            PullSummary(pull.get("number").asInt, pull.get("title").asString, pull.get("state").asString)
        }

    fun pull(owner: String, repo: String, number: Int): PullInfo {
        val pull: JsonObject = get("/repos/$owner/$repo/pulls/$number").body.asObject()
        val base: JsonObject = pull.getAsJsonObject("base")
        return PullInfo(
            number = number,
            title = pull.get("title").asString,
            baseRef = base.get("ref").asString,
            baseSha = base.get("sha").asString,
            headSha = pull.getAsJsonObject("head").get("sha").asString,
        )
    }

    /** The body of the first comment of the PR that carries the brief marker, or null when there is none. */
    fun briefComment(owner: String, repo: String, number: Int): String? {
        var url: String? = "/repos/$owner/$repo/issues/$number/comments?per_page=100"
        var pages = 0
        while (url != null && pages < MAX_PAGES) {
            val reply: HttpReply = get(url)
            reply.body.asArray().firstNotNullOfOrNull { comment ->
                comment.asJsonObject.get("body")?.takeIf { !it.isJsonNull }?.asString?.takeIf(BriefDecoder::isBriefComment)
            }?.let { return it }
            url = nextLink(reply.link)?.takeIf { it.startsWith(apiBase) }
            pages++
        }
        return null
    }

    private fun array(path: String): JsonArray = get(path).body.asArray()

    private fun get(path: String): HttpReply {
        val url: String = if (path.startsWith("http")) path else apiBase + path
        val headers: MutableMap<String, String> = mutableMapOf(
            "Accept" to "application/vnd.github+json",
            "X-GitHub-Api-Version" to "2022-11-28",
        )
        if (token != null) headers["Authorization"] = "Bearer $token"
        val reply: HttpReply = transport.get(url, headers)
        if (reply.status !in 200..299) throw GitHubException(reply.status, failureMessage(reply.status))
        return reply
    }

    private fun failureMessage(status: Int): String = when (status) {
        401 -> "GitHub refused the credentials (HTTP 401)"
        403 -> "GitHub refused the request (HTTP 403): rate limit, or the repository needs a token"
        404 -> "GitHub has no such pull request or repository for this account (HTTP 404); a private repository needs a token"
        else -> "GitHub answered HTTP $status"
    }

    private fun String.asObject(): JsonObject = JsonParser.parseString(this).asJsonObject

    private fun String.asArray(): JsonArray {
        val parsed: JsonElement = JsonParser.parseString(this)
        return if (parsed.isJsonArray) parsed.asJsonArray else JsonArray()
    }

    private companion object {
        const val MAX_PAGES = 50
        val NEXT_LINK = Regex("""<([^>]+)>;\s*rel="next"""")

        fun nextLink(header: String?): String? = header?.let { NEXT_LINK.find(it)?.groupValues?.get(1) }
    }
}
