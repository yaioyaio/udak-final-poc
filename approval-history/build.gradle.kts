plugins { `java-library` }

group = "dev.udak"
version = "0.1.0-poc"
java { toolchain { languageVersion.set(JavaLanguageVersion.of(17)) } }

dependencies {
    api(project(":rewrite-core"))
    api(project(":rewrite-jdbc"))
    testImplementation(project(":rewrite-jsqlparser"))
    testImplementation("org.springframework:spring-jdbc:6.2.19")
    testImplementation("com.h2database:h2:2.3.232")
    testRuntimeOnly("org.slf4j:slf4j-nop:2.0.18")
}

sourceSets.test { java.srcDir("../rewrite-testkit/src/test/java") }

project(":rewrite-jsqlparser").tasks.withType<ProcessResources>().configureEach {
    from(rootProject.file("../sql-jsqlparser/src/main/resources/META-INF")) {
        include("LICENSE-jsqlparser.txt", "NOTICE-jsqlparser.txt")
        into("META-INF")
    }
}
