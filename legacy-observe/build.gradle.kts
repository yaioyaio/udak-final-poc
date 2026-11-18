import java.time.Duration
plugins { `java-library` }
java { toolchain { languageVersion.set(JavaLanguageVersion.of(17)) } }
dependencies {
    api(project(":observe-core"))
    compileOnly("org.hibernate.orm:hibernate-core:6.6.53.Final")
    compileOnly("org.mybatis:mybatis:3.5.19")
    testImplementation("org.hibernate.orm:hibernate-core:6.6.53.Final")
    testImplementation("org.mybatis:mybatis:3.5.19")
}
val observeContract by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass.set("dev.udak.observe.LegacyObserveAdapterContractTest")
    maxHeapSize = "256m"
    jvmArgs("-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2")
    timeout.set(Duration.ofSeconds(60))
}
tasks.check { dependsOn(observeContract) }
