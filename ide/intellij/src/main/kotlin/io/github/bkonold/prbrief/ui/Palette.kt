package io.github.bkonold.prbrief.ui

import com.intellij.ui.JBColor
import com.intellij.util.ui.JBUI
import java.awt.Color

internal object Palette {
    val added: Color = JBColor(Color(0x1A7F37), Color(0x57AB5A))
    val removed: Color = JBColor(Color(0xCF222E), Color(0xE5534B))
    val low: Color = JBColor(Color(0x1A7F37), Color(0x57AB5A))
    val medium: Color = JBColor(Color(0x9A6700), Color(0xC69026))
    val high: Color = JBColor(Color(0xCF222E), Color(0xE5534B))
    val guide: Color = JBColor(Color(0x534AB7), Color(0x9D94F5))
    val selectedRow: Color = JBColor(Color(0xEEECFB), Color(0x2F2D4A))
    val muted: Color = JBUI.CurrentTheme.Label.disabledForeground()

    fun risk(risk: String): Color = when (risk) {
        "high" -> high
        "medium" -> medium
        else -> low
    }
}
