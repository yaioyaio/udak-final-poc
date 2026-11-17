import java.time.Duration

plugins { `java-library` }
java { toolchain { languageVersion.set(JavaLanguageVersion.of(17)) } }
dependencies {
    api(project(":core"))
    implementation("com.github.jsqlparser:jsqlparser:5.4")
}
sourceSets.test {
    java {
        srcDir(rootProject.file("core/src/test/java"))
        include("dev/udak/core/CompilerContractTest.java", "dev/udak/jsqlparser/**")
    }
}
val compilerContract by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass.set("dev.udak.jsqlparser.JSqlParserCompilerTest")
    maxHeapSize = "256m"
    jvmArgs("-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2")
    timeout.set(Duration.ofSeconds(60))
}
tasks.check { dependsOn(compilerContract) }
