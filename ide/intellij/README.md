# PR Brief for IntelliJ

A prototype IntelliJ plugin that opens a pull request's PR Brief inside the IDE. The walkthrough, the layers and the
changed files are in a tool window, and each opens in a diff whose right side is your local file, so go to definition,
find usages and editing work on the code under review.

Needs an IntelliJ-based IDE of build 262 or newer with the Git and GitHub plugins (both bundled), and the PR's branch
checked out.

## Run it

```
cd ide/intellij
./gradlew runIde          # a sandbox IDE with the plugin loaded
./gradlew buildPlugin     # build/distributions/pr-brief-intellij-0.1.0.zip, to install from disk
./gradlew test            # the unit tests, including the layer filter fixtures
./gradlew verifyPlugin    # checks the plugin against the IDE it is built for
```

To install the zip: Settings, Plugins, the gear menu, Install Plugin from Disk.

## Use it

1. Check out the PR's branch and open the project. Open the **PR Brief** tool window (right edge).
2. The plugin reads `owner/repo` from the git remote, finds the PR of the checked-out commit and reads the brief
   comment (the one marked `<!-- pr-brief:v1 -->`). If no PR or several match, it asks which one.
3. Tabs:
   - **Walkthrough**: the stops in reading order. Hover a row for its reason.
   - **Layers**: every change in layers, foundations first. Select a layer to expand its files; select it again, or
     press Show all, to clear. Mark judged / Unmark judged records your progress per repo, PR and head commit.
   - **Files**: the changed files by folder, with API, Data and Tests chips.
4. Every selection opens in the same editor tab. The tab starts in the unified viewer; the viewer toggle switches it to
   side-by-side and the choice is kept. F7 and Shift+F7 step through the hunks.
5. With a layer selected the left side is the file before that layer, so the diff shows only that layer's change. The
   hunks of the other layers show on the right side with a numbered gutter badge; hover it for the layer, click it to
   select that layer.
6. Next Stop and Previous Stop (Ctrl+Shift+Alt+Down and Up) step through the walkthrough from the diff tab.

A banner appears when the brief was made for another commit than the one checked out; Refresh reads it again. If the
local file no longer matches the hunks of the brief, the diff falls back to the whole change of the file against the
base and says so.

### Authentication

The plugin uses the GitHub account signed in to the IDE's GitHub plugin. Without one it reads unauthenticated, and
Settings, Tools, PR Brief takes an optional token that is kept in the IDE's password safe. The tool window shows which
was used. The token is only ever sent in the `Authorization` header to the GitHub API.

### Without GitHub

Tools menu, Load review.json from File… reads a `review.json` directly. `ide/fixtures/demo-review.json` is a sample for
the demo PR below, and `ide/fixtures/layer-filter/*.json` are the layer filter's test cases (base, head, hunks, the
selected hunk ids and the expected left side), in a shape another front end can reuse.

## Manual checklist

Against https://github.com/bkonold/pr-brief-demo/pull/1: clone the repo and check out `feat/holds`
(`git clone https://github.com/bkonold/pr-brief-demo && git checkout feat/holds`), open it in the IDE, then:

- [ ] ⌘B works inside the unified viewer on a layer's hunk (select a layer, click a symbol in the right side, jump to
      its declaration).
- [ ] The tool window loads the brief on its own: the Layers tab says 6 layers and the source line names
      `bkonold/pr-brief-demo#1` and how it was read.
- [ ] The Walkthrough lists 6 stops; clicking one opens its file at the stop's line in the review tab.
- [ ] Selecting a layer opens its first file; the left side is that file before the layer, and only the layer's hunks
      differ. Clicking a file row in the expanded layer jumps to its first hunk.
- [ ] Selecting another layer, a stop or a file reuses the same tab and never opens a second one.
- [ ] Clicking the selected layer again, or Show all, clears the selection and the tab shows the base against local.
- [ ] Layer 3 (Hold service) in `LoanService.java`: the hunk of layer 2 on the right side has a gutter badge
      "Changed in layer 2 · Hold models and repository"; clicking it selects layer 2. (In the unified viewer it is in a
      folded region unless it lies near the layer's own change.)
- [ ] Unified is the default; the toggle switches to side-by-side, and the next selection keeps the choice.
- [ ] F7 and Shift+F7 move between hunks; Ctrl+Shift+Alt+Down and Up move between stops.
- [ ] Editing the local file (type in the right side) is allowed, and the left side does not change.
- [ ] After editing a line above a hunk of the open file, selecting its layer again shows the warning that the local
      file differs, and the plain base diff.
- [ ] Mark judged on a layer puts a tick on its row; it survives closing and reopening the project.
- [ ] Checking out another commit of the branch (`git checkout HEAD~1`) and pressing Refresh shows the stale banner.
- [ ] Without an IDE GitHub account the brief still loads (the repo is public) and the source line says it read
      unauthenticated; with a token in Settings it says so.
- [ ] Load review.json from File… with `ide/fixtures/demo-review.json` shows the same layers without any network.
