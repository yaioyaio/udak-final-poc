plugins { `java-library` }

group = "dev.udak"
version = "0.1.0-poc"
repositories { mavenCentral() }
java { toolchain { languageVersion.set(JavaLanguageVersion.of(17)) } }

dependencies {
    api(project(":observe-core"))
    api("jakarta.persistence:jakarta.persistence-api:3.1.0")
    implementation("org.springframework:spring-orm:6.2.19")
    implementation("org.springframework:spring-jdbc:6.2.19")
    api("org.springframework:spring-tx:6.2.19")
}
