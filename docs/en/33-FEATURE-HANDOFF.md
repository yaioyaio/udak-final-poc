# Feature development handoff

English | [한국어](../ko/33-FEATURE-HANDOFF.md)

## Dependencies verified across fingerprints under one Query ID

In the H2 order pilot, two MyBatis fingerprints shared one Query ID. The active-column change selected the ON test only. Removing either fingerprint row yielded `INCOMPLETE` and preserved any known impact. [Verify dependencies for each observed fingerprint](27-SCHEMA-IMPACT-REGRESSION.md#verify-dependencies-for-each-observed-fingerprint)

## Verified scope

The protected H2 run passed 89 capture assertions, 27 selected-test replay assertions, 30 schema-impact contracts, 16 extraction contracts and Core smoke. Existing audit selection and 15 migration contracts passed. External DB integration is NOT RUN. [Order fingerprint dependency evidence](../../evidence/ORDER-FINGERPRINT-DEPENDENCIES-VALIDATION.json)

## Following task

Capture the fingerprint-to-test association in the SQL inventory itself. Verify that a swapped association is detected even when both test hashes belong to the same Query ID. Preserve compatibility with v1 inventory readers.

Public publication is deferred. Resume the remaining official performance and DB support checks when their documented prerequisites are met. [Release and support evidence](30-RELEASE-SUPPORT-EVIDENCE.md) · [Product G5 criteria](32-PRODUCT-G5-ACCEPTANCE.md)
