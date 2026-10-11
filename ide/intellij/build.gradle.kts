import org.jetbrains.intellij.platform.gradle.TestFrameworkType
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    kotlin("jvm") version "2.4.10"
    id("org.jetbrains.intellij.platform") version "2.19.0"
}

group = "io.github.bkonold.prbrief"
version = "0.1.0"

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

dependencies {
    intellijPlatform {
        local("/Applications/IntelliJ IDEA.app")
        bundledPlugin("Git4Idea")
        bundledPlugin("org.jetbrains.plugins.github")
        testFramework(TestFrameworkType.Platform)
    }
    testImplementation("junit:junit:4.13.2")
}

kotlin {
    compilerOptions {
        jvmTarget = JvmTarget.JVM_25
    }
}

java {
    sourceCompatibility = JavaVersion.VERSION_25
    targetCompatibility = JavaVersion.VERSION_25
}

intellijPlatform {
    pluginConfiguration {
        name = "PR Brief"
        ideaVersion {
            sinceBuild = "262"
        }
    }
    pluginVerification {
        ides {
            local("/Applications/IntelliJ IDEA.app")
        }
    }
}

tasks.test {
    systemProperty("fixtures.dir", layout.projectDirectory.dir("../fixtures").asFile.absolutePath)
}
