import java.time.Duration

plugins { java }

java { toolchain { languageVersion.set(JavaLanguageVersion.of(17)) } }

dependencies {
    testImplementation(platform("org.springframework.boot:spring-boot-dependencies:3.5.16"))
    testImplementation(project(":consistency-core"))
    testImplementation(project(":consistency-spring"))
    testImplementation(project(":spring-boot-demo"))
    testImplementation("org.springframework:spring-orm:6.2.19")
    testImplementation("org.springframework:spring-jdbc:6.2.19")
    testImplementation("org.springframework.data:spring-data-jpa:3.5.13")
    testImplementation("org.hibernate.orm:hibernate-core:6.6.53.Final")
    testImplementation("org.mybatis:mybatis:3.5.19")
    testImplementation("org.mybatis:mybatis-spring:3.0.5")
    testImplementation("com.h2database:h2:2.3.232")
    testRuntimeOnly("org.slf4j:slf4j-nop:2.0.18")
}

val transactionContract by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass.set("dev.udak.consistency.Phase4TransactionTest")
    maxHeapSize = "256m"
    jvmArgs("-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2")
    timeout.set(Duration.ofSeconds(90))
}

tasks.check { dependsOn(transactionContract) }
