import java.time.Duration

plugins { `java-library` }
java { toolchain { languageVersion.set(JavaLanguageVersion.of(17)) } }

dependencies {
    api(project(":rewrite-core"))
    implementation("com.github.jsqlparser:jsqlparser:5.4")
}

// The pinned parser and its license terms are shared with the Phase 1 adapter.
tasks.processResources {
    from(rootProject.file("sql-jsqlparser/src/main/resources/META-INF")) {
        include("LICENSE-jsqlparser.txt", "NOTICE-jsqlparser.txt")
        into("META-INF")
    }
}

val paginationRewriteContract by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass.set("dev.udak.rewrite.jsqlparser.PaginationRewriteContractTest")
    maxHeapSize = "256m"
    jvmArgs("-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2")
    timeout.set(Duration.ofSeconds(60))
}
tasks.check { dependsOn(paginationRewriteContract) }
