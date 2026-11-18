plugins { `java-library` }

java {
    toolchain { languageVersion.set(JavaLanguageVersion.of(17)) }
}

dependencies {
    api(platform("org.springframework.boot:spring-boot-dependencies:4.1.2"))
    api("org.springframework.boot:spring-boot")
    api("org.springframework.boot:spring-boot-autoconfigure")
    api("org.springframework:spring-jdbc")
    api(project(":core"))
    api(project(":observe-core"))
    api(project(":udak-api"))
    api(project(":jdbc-spring"))
}
