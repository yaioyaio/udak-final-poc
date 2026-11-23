# Feature development handoff

English | [한국어](../ko/33-FEATURE-HANDOFF.md)

## ThingsBoard CE external pilot dependencies

The selected independent application is ThingsBoard CE `v4.3.1.8`. The device registration success and rollback methods were verified in its pinned checkout. The previous synthetic H2 order replay remains separate evidence. [ThingsBoard pilot prerequisites](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-external-pilot)

## Verified scope

The pinned checkout and selection of both test methods passed review. The official published BOM, parent POM and two library POM/JAR pairs passed supplier SHA-256 verification. Host memory pressure reached level 2 at the Maven model gate. The DAO build, PostgreSQL baseline and Observe OFF/ON are NOT RUN. [Official artifact verification](../../evidence/THINGSBOARD-TB1-OFFICIAL-ARTIFACTS.json)

## Following task

Check local capacity for the DAO reactor and isolated PostgreSQL. Use the acquired Maven artifacts and run model validation and test compilation. Run the two existing methods and require both to pass without skips. Then attach Observe to the test Hibernate factory and compare the same methods' registration, rollback and observation results. When those pass, verify detection of a reviewed upstream SQL change. [Pilot procedure](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-external-pilot)

Public publication is deferred. Resume the remaining official performance and DB support checks when their documented prerequisites are met. [Release and support evidence](30-RELEASE-SUPPORT-EVIDENCE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)
