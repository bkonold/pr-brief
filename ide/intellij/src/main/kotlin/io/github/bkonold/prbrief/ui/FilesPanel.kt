package io.github.bkonold.prbrief.ui

import com.intellij.icons.AllIcons
import com.intellij.openapi.project.Project
import com.intellij.ui.ColoredTreeCellRenderer
import com.intellij.ui.SimpleTextAttributes
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.treeStructure.Tree
import io.github.bkonold.prbrief.BriefService
import io.github.bkonold.prbrief.Selection
import io.github.bkonold.prbrief.model.FileSets
import java.awt.BorderLayout
import javax.swing.JPanel
import javax.swing.JTree
import javax.swing.tree.DefaultMutableTreeNode
import javax.swing.tree.DefaultTreeModel
import javax.swing.tree.TreePath

/** The changed files as a tree grouped by folder, with a chip for each file set (API, Data, Tests) a file belongs to. */
class FilesPanel(private val project: Project) : JPanel(BorderLayout()) {
    private class FolderNode(val folder: String)

    private class FileNode(val path: String, val chips: List<String>)

    private val tree = Tree(DefaultTreeModel(DefaultMutableTreeNode()))
    private var updating = false

    init {
        tree.isRootVisible = false
        tree.showsRootHandles = true
        tree.cellRenderer = object : ColoredTreeCellRenderer() {
            override fun customizeCellRenderer(tree: JTree, value: Any?, selected: Boolean, expanded: Boolean, leaf: Boolean, row: Int, hasFocus: Boolean) {
                when (val user: Any? = (value as? DefaultMutableTreeNode)?.userObject) {
                    is FolderNode -> {
                        icon = AllIcons.Nodes.Folder
                        append(user.folder, SimpleTextAttributes.GRAYED_ATTRIBUTES)
                        toolTipText = user.folder
                    }
                    is FileNode -> {
                        icon = AllIcons.FileTypes.Any_type
                        append(user.path.substringAfterLast('/'))
                        for (chip in user.chips) append("  $chip", SimpleTextAttributes.GRAYED_SMALL_ATTRIBUTES)
                        toolTipText = user.path
                    }
                }
            }
        }
        tree.addTreeSelectionListener { event ->
            if (updating) return@addTreeSelectionListener
            val node: Any? = (event.path?.lastPathComponent as? DefaultMutableTreeNode)?.userObject
            if (node is FileNode) project.getService(BriefService::class.java).select(Selection.FileAt(node.path))
        }
        add(JBScrollPane(tree), BorderLayout.CENTER)
    }

    fun refresh(paths: List<String>, fileSets: FileSets, selection: Selection) {
        updating = true
        try {
            val root = DefaultMutableTreeNode()
            var selectedPath: TreePath? = null
            val selectedFile: String? = (selection as? Selection.FileAt)?.path
            for ((folder, files) in paths.groupBy { it.substringBeforeLast('/', "/") }.toSortedMap()) {
                val folderNode = DefaultMutableTreeNode(FolderNode(folder))
                for (path in files.sorted()) {
                    val node = DefaultMutableTreeNode(FileNode(path, chips(path, fileSets)))
                    folderNode.add(node)
                    if (path == selectedFile) selectedPath = TreePath(arrayOf(root, folderNode, node))
                }
                root.add(folderNode)
            }
            tree.model = DefaultTreeModel(root)
            tree.expandAll()
            selectedPath?.let { tree.selectionPath = it } ?: tree.clearSelection()
        } finally {
            updating = false
        }
    }

    private fun chips(path: String, sets: FileSets): List<String> = buildList {
        if (path in sets.contract) add("API")
        if (path in sets.data) add("Data")
        if (path in sets.tests) add("Tests")
    }

    private fun Tree.expandAll() {
        var row = 0
        while (row < rowCount) expandRow(row++)
    }
}
