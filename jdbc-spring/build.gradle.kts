import java.time.Duration

plugins { `java-library` }
java { toolchain { languageVersion.set(JavaLanguageVersion.of(17)) } }
dependencies {
    api(project(":udak-api"))
    implementation("org.springframework:spring-jdbc:6.2.19")
    testImplementation("com.h2database:h2:2.3.232")
}
val jdbcContract by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass.set("dev.udak.jdbc.SpringJdbcExecutorTest")
    maxHeapSize = "256m"
    jvmArgs("-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2")
    timeout.set(Duration.ofSeconds(60))
}
tasks.check { dependsOn(jdbcContract) }
