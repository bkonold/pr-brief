package io.github.bkonold.prbrief.ui

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.application.ModalityState
import com.intellij.openapi.options.Configurable
import com.intellij.openapi.options.ShowSettingsUtil
import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.project.DumbAware
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBPasswordField
import com.intellij.util.ui.FormBuilder
import io.github.bkonold.prbrief.github.GitHubAuth
import javax.swing.JComponent
import javax.swing.JPanel

/**
 * The optional GitHub token, kept in the password safe and used only when the IDE has no GitHub account for the host.
 * The password safe is read and written on a pooled thread; the field stays disabled until the saved token has been read.
 */
class PrBriefSettings : Configurable {
    private val tokenField = JBPasswordField()
    private var panel: JPanel? = null

    /** The token as last read from or written to the password safe; null until the first read finishes. */
    private var savedToken: String? = null

    override fun getDisplayName(): String = "PR Brief"

    override fun createComponent(): JComponent {
        val form: JPanel = FormBuilder.createFormBuilder()
            .addLabeledComponent("GitHub token:", tokenField)
            .addComponent(JBLabel("Optional. Used only when the IDE's GitHub plugin has no account for the remote's host. Public repositories need none."))
            .addComponentFillVertically(JPanel(), 0)
            .panel
        panel = form
        reset()
        return form
    }

    override fun isModified(): Boolean = savedToken?.let { String(tokenField.password) != it } ?: false

    override fun apply() {
        if (savedToken == null) return
        val token: String = String(tokenField.password)
        savedToken = token
        ApplicationManager.getApplication().executeOnPooledThread { GitHubAuth.saveToken(token) }
    }

    override fun reset() {
        tokenField.isEnabled = false
        ApplicationManager.getApplication().executeOnPooledThread {
            val token: String = GitHubAuth.savedToken() ?: ""
            ApplicationManager.getApplication().invokeLater({
                if (panel == null) return@invokeLater
                savedToken = token
                tokenField.text = token
                tokenField.isEnabled = true
            }, ModalityState.any())
        }
    }

    override fun disposeUIResources() {
        panel = null
    }
}

class OpenBriefSettingsAction : AnAction(), DumbAware {
    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.BGT

    override fun actionPerformed(e: AnActionEvent) {
        ShowSettingsUtil.getInstance().showSettingsDialog(e.project, PrBriefSettings::class.java)
    }
}
