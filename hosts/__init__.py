"""Where a pull request is read from: GitHub, through the `gh` CLI (hosts/github.py), which only reads.

    pr(owner, repo, n)        title, body, head branch, base and head SHA, commits and files, in the
                              shape `gh pr view --json` gives (the shape pr.json, render.py and
                              context_pack.py read)
    diff(owner, repo, n)      the unified diff
"""
