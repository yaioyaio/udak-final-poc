import java.time.Duration

plugins { `java-library` }

java { toolchain { languageVersion.set(JavaLanguageVersion.of(17)) } }

dependencies {
    api(project(":rewrite-core"))
    compileOnly("org.springframework:spring-jdbc:6.2.19")
    testImplementation("org.springframework:spring-jdbc:6.2.19")
    testRuntimeOnly("org.slf4j:slf4j-nop:2.0.18")
}

val selectiveJdbcContract by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass.set("dev.udak.rewrite.jdbc.SelectiveJdbcContractTest")
    maxHeapSize = "256m"
    jvmArgs("-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2")
    timeout.set(Duration.ofSeconds(90))
}

tasks.check { dependsOn(selectiveJdbcContract) }
