import java.time.Duration

plugins {
    `java-library`
}

java {
    toolchain {
        languageVersion.set(JavaLanguageVersion.of(17))
    }
}

val rewritePolicyContract by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass.set("dev.udak.rewrite.RewritePolicyContractTest")
    maxHeapSize = "256m"
    jvmArgs("-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2")
    timeout.set(Duration.ofSeconds(60))
}

tasks.check { dependsOn(rewritePolicyContract) }
