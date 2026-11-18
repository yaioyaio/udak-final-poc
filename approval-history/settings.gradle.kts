rootProject.name = "approval-history"

dependencyResolutionManagement {
    repositories { mavenCentral() }
}

include("rewrite-core", "rewrite-jdbc", "rewrite-jsqlparser")
for (name in listOf("rewrite-core", "rewrite-jdbc", "rewrite-jsqlparser")) {
    project(":$name").projectDir = file("../$name")
}
