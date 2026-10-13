package io.github.bkonold.prbrief.github

import com.intellij.credentialStore.CredentialAttributes
import com.intellij.credentialStore.Credentials
import com.intellij.credentialStore.generateServiceName
import com.intellij.ide.passwordSafe.PasswordSafe
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.progress.runBlockingCancellable
import com.intellij.openapi.project.Project
import org.jetbrains.plugins.github.authentication.GHAccountsUtil
import org.jetbrains.plugins.github.authentication.accounts.GHAccountManager
import org.jetbrains.plugins.github.authentication.accounts.GithubAccount

/** Where the token for a request came from; the token itself is never kept in this value. */
enum class AuthSource(val label: String) {
    GITHUB_ACCOUNT("the IDE's GitHub account"),
    PASSWORD_SAFE("the token saved in PR Brief settings"),
    NONE("no credentials"),
}

data class AuthToken(val token: String?, val source: AuthSource)

/**
 * Finds a GitHub token without asking the user: the account of the IDE's bundled GitHub plugin for the remote's host
 * (the project's default account first), then the optional token kept in the password safe, then none, which is enough
 * for a public repository. Call from a background thread.
 */
object GitHubAuth {
    private val attributes: CredentialAttributes =
        CredentialAttributes(generateServiceName("PR Brief", "GitHub token"))

    fun resolve(project: Project, host: String): AuthToken {
        val fromAccount: String? = tokenFromGitHubAccount(project, host)
        if (fromAccount != null) return AuthToken(fromAccount, AuthSource.GITHUB_ACCOUNT)
        val saved: String? = savedToken()
        if (saved != null) return AuthToken(saved, AuthSource.PASSWORD_SAFE)
        return AuthToken(null, AuthSource.NONE)
    }

    fun savedToken(): String? = PasswordSafe.instance.getPassword(attributes)?.takeIf { it.isNotBlank() }

    fun saveToken(token: String?) {
        PasswordSafe.instance.set(attributes, token?.takeIf { it.isNotBlank() }?.let { Credentials("PR Brief", it) })
    }

    private fun tokenFromGitHubAccount(project: Project, host: String): String? {
        return try {
            val matching: List<GithubAccount> = GHAccountsUtil.accounts.filter { it.server.host.equals(host, ignoreCase = true) }
            val account: GithubAccount = GHAccountsUtil.getDefaultAccount(project)?.takeIf { it in matching }
                ?: matching.firstOrNull()
                ?: return null
            val manager: GHAccountManager = ApplicationManager.getApplication().getService(GHAccountManager::class.java)
            runBlockingCancellable { manager.findCredentials(account) }?.takeIf { it.isNotBlank() }
        } catch (e: Exception) {
            null
        }
    }
}
