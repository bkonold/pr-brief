package io.github.bkonold.prbrief.git

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class GitSupportTest {
    @Test
    fun parsesHttpsAndSshRemotes() {
        val expected = RemoteSlug("github.com", "bkonold", "pr-brief")
        assertEquals(expected, GitSupport.parseRemoteUrl("https://github.com/bkonold/pr-brief.git"))
        assertEquals(expected, GitSupport.parseRemoteUrl("https://github.com/bkonold/pr-brief"))
        assertEquals(expected, GitSupport.parseRemoteUrl("git@github.com:bkonold/pr-brief.git"))
        assertEquals(expected, GitSupport.parseRemoteUrl("ssh://git@github.com/bkonold/pr-brief.git"))
        assertEquals(expected, GitSupport.parseRemoteUrl("https://user:token@github.com/bkonold/pr-brief.git"))
    }

    @Test
    fun keepsTheHostOfAnEnterpriseRemote() {
        assertEquals(RemoteSlug("git.example.com", "team", "app"), GitSupport.parseRemoteUrl("git@git.example.com:team/app.git"))
    }

    @Test
    fun aLocalPathIsNotARemote() {
        assertNull(GitSupport.parseRemoteUrl("/Users/someone/repo"))
    }
}
