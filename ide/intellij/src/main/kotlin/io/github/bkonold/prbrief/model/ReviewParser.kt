package io.github.bkonold.prbrief.model

import com.google.gson.JsonArray
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonParser

/** Reads the review.json that `render.py` writes (schema 4); keys the IDE does not use are ignored. */
object ReviewParser {
    class InvalidReviewException(message: String) : Exception(message)

    fun parse(json: String): Review {
        val root: JsonElement = try {
            JsonParser.parseString(json)
        } catch (e: RuntimeException) {
            throw InvalidReviewException("Not valid JSON: ${e.message}")
        }
        if (!root.isJsonObject) throw InvalidReviewException("review.json is not an object")
        return parse(root.asJsonObject)
    }

    fun parse(root: JsonObject): Review {
        val schema: Int = root.get("schema")?.takeIf { it.isJsonPrimitive }?.asInt ?: 0
        if (schema != 4) throw InvalidReviewException("Unsupported review schema $schema, expected 4")
        val walkthrough: JsonArray = root.getAsJsonArray("walkthrough")
            ?: throw InvalidReviewException("review.json has no walkthrough")
        return Review(
            repo = root.get("repo").asString,
            pr = root.get("pr").asInt,
            headSha = root.get("head_sha").asString,
            walkthrough = walkthrough.map { stop(it.asJsonObject) },
            layers = root.getAsJsonArray("chunks")?.map { layer(it.asJsonObject) } ?: emptyList(),
            fileSets = fileSets(root.getAsJsonObject("file_sets")),
        )
    }

    private fun stop(json: JsonObject): Stop = Stop(
        index = json.get("i").asInt,
        title = json.get("title").asString,
        why = string(json, "why") ?: "",
        path = json.get("path").asString,
        side = string(json, "side") ?: "R",
        line = json.get("line")?.takeIf { !it.isJsonNull }?.asInt,
    )

    private fun layer(json: JsonObject): Layer = Layer(
        index = json.get("i").asInt,
        title = json.get("title").asString,
        summary = string(json, "summary") ?: "",
        risk = string(json, "risk") ?: "low",
        riskReason = string(json, "risk_reason"),
        dependsOn = json.getAsJsonArray("depends_on")?.map { it.asInt } ?: emptyList(),
        hunks = json.getAsJsonArray("hunks")?.map { hunk(it.asJsonObject) } ?: emptyList(),
    )

    private fun hunk(json: JsonObject): HunkRange {
        val old: JsonArray = json.getAsJsonArray("old")
        val new: JsonArray = json.getAsJsonArray("new")
        return HunkRange(
            id = json.get("id").asString,
            path = json.get("path").asString,
            change = string(json, "change") ?: "modified",
            oldStart = old[0].asInt,
            oldCount = old[1].asInt,
            newStart = new[0].asInt,
            newCount = new[1].asInt,
            added = json.get("added")?.takeIf { !it.isJsonNull }?.asInt,
            removed = json.get("removed")?.takeIf { !it.isJsonNull }?.asInt,
        )
    }

    private fun fileSets(json: JsonObject?): FileSets = FileSets(
        contract = paths(json, "contract"),
        data = paths(json, "data"),
        tests = paths(json, "tests"),
    )

    private fun paths(json: JsonObject?, key: String): Set<String> =
        json?.getAsJsonArray(key)?.map { it.asString }?.toSet() ?: emptySet()

    private fun string(json: JsonObject, key: String): String? =
        json.get(key)?.takeIf { !it.isJsonNull }?.asString
}
