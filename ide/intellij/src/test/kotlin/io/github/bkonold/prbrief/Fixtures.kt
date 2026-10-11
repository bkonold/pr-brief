package io.github.bkonold.prbrief

import java.nio.file.Files
import java.nio.file.Path

/** Files under `ide/fixtures`, which are shared with other editors' plugins. */
object Fixtures {
    val dir: Path = Path.of(System.getProperty("fixtures.dir") ?: "../fixtures")

    fun read(name: String): String = Files.readString(dir.resolve(name))
}
