import java.time.Duration

plugins { `java-library` }

group = "dev.udak"
version = "0.1.0-poc"
java { toolchain { languageVersion.set(JavaLanguageVersion.of(17)) } }
dependencies { api(project(":observe-core")) }

val inventoryContract by tasks.registering(JavaExec::class) {
    dependsOn(tasks.testClasses)
    classpath = sourceSets.test.get().runtimeClasspath
    mainClass.set("dev.udak.inventory.InventoryContractTest")
    maxHeapSize = "256m"
    jvmArgs("-XX:MaxMetaspaceSize=128m", "-XX:ActiveProcessorCount=2")
    timeout.set(Duration.ofSeconds(30))
}
tasks.check { dependsOn(inventoryContract) }
