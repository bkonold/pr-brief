# Chunk evals

Hand-written groupings of a PR's hunks, one TOML per PR, that `scripts/eval_chunks.py` scores a `chunks` run against.
Each expected chunk is a table: `[chunks."Payment terms on the entity"]` with `hunks = ["path/File.java", "path/Other.java:10-40"]`.
A bare path is every hunk of that file; `path:a-b` is the hunks whose new-side lines overlap a to b (old-side lines for a hunk that adds none).
Run it on a run's folder: `python scripts/eval_chunks.py runs/12298/chunks eval/12298.toml`.
It prints the pair agreement, where each expected chunk's hunks landed, and the hunks the file does not mention; a range that hits no hunk is an error.
