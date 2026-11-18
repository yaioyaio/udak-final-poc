import java.time.Duration

plugins { java }

java { toolchain { languageVersion.set(JavaLanguageVersion.of(17)) } }

dependencies {
    testImplementation(project(":rewrite-jdbc"))
    testImplementation(project(":rewrite-jsqlparser"))
    testImplementation("org.springframework:spring-jdbc:6.2.19")
    testImplementation("org.springframework:spring-tx:6.2.19")
    testImplementation("com.h2database:h2:2.3.232")
    testRuntimeOnly("org.slf4j:slf4j-nop:2.0.18")
}

val rewriteEquivalence by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass.set("dev.udak.rewrite.testkit.RewriteEquivalenceTest")
    maxHeapSize = "256m"
    jvmArgs("-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2")
    timeout.set(Duration.ofSeconds(90))
}

tasks.check { dependsOn(rewriteEquivalence) }
