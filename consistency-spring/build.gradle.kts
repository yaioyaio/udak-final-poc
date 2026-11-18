import java.time.Duration

plugins { `java-library` }

java { toolchain { languageVersion.set(JavaLanguageVersion.of(17)) } }

dependencies {
    api(project(":consistency-core"))
    listOf(
        "org.springframework:spring-orm:6.2.19",
        "org.springframework:spring-jdbc:6.2.19",
        "org.springframework:spring-tx:6.2.19",
        "jakarta.persistence:jakarta.persistence-api:3.1.0",
        "org.mybatis:mybatis:3.5.19",
        "org.mybatis:mybatis-spring:3.0.5"
    ).forEach { dependency ->
        compileOnly(dependency)
        testImplementation(dependency)
    }
}

val springGuardContract by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass.set("dev.udak.consistency.spring.SpringGuardContractTest")
    maxHeapSize = "256m"
    jvmArgs("-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2")
    timeout.set(Duration.ofSeconds(60))
}

tasks.check { dependsOn(springGuardContract) }
