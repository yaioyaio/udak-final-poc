# Feature development handoff

English | [한국어](../ko/33-FEATURE-HANDOFF.md)

## ThingsBoard CE external pilot dependencies

The selected independent application is ThingsBoard CE `v4.3.1.8`. The device registration success and rollback methods were verified in its pinned checkout. The previous synthetic H2 order replay remains separate evidence. [ThingsBoard pilot prerequisites](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-external-pilot)

## Verified scope

The pinned checkout and selection of both existing test methods passed review. The supplier's BOM source and its parent POM were downloaded and their SHA-256 hashes verified. The published BOM and the required supplier libraries remain unresolved. The ThingsBoard build, isolated PostgreSQL baseline and Observe OFF/ON comparison are NOT RUN. [Dependency evidence](../../evidence/THINGSBOARD-DEVICE-PILOT-DEPENDENCIES.json)

## Following task

Resolve the published BOM and the matching `langchain4j` and `langchain4j-core` artifacts from the supplier. Confirm capacity for the limited DAO reactor and isolated PostgreSQL. Run the two existing methods and require both to pass without skips. Then attach Observe to the test Hibernate factory and compare the same methods' registration, rollback and observation results. When those pass, verify detection of a reviewed upstream SQL change. [Pilot procedure](34-LEGACY-ADOPTION-PILOT.md#thingsboard-ce-external-pilot)

Public publication is deferred. Resume the remaining official performance and DB support checks when their documented prerequisites are met. [Release and support evidence](30-RELEASE-SUPPORT-EVIDENCE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)
