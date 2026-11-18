pluginManagement { repositories { gradlePluginPortal(); mavenCentral() } }
rootProject.name = "udak-final-poc"
include("core", "spring-boot-demo", "sql-jsqlparser", "udak-api", "jdbc-spring", "db-testkit",
        "observe-core", "legacy-observe", "legacy-compat-testkit",
        "consistency-core", "consistency-spring", "consistency-testkit",
        "rewrite-core", "rewrite-jsqlparser", "rewrite-jdbc", "rewrite-testkit")
