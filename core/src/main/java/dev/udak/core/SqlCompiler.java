package dev.udak.core;

/**
 * Compiles the supported structured query subset into SQL and ordered binds.
 * Implementations reject null query or vendor and invalid input, including identifiers
 * outside the application-supplied allowlist, in every identifier position. A null
 * filter value is allowed and is passed as a bind. Filter values must never be
 * inlined into SQL. Bind order is deterministic for each vendor profile, and repeated
 * compilation of equal inputs produces equal output. Input and output lists are
 * immutable snapshots; objects held as bind values are not deep copied.
 *
 * <p>Compilation does not execute or validate against a database, guarantee that a
 * query succeeds, or translate existing SQL between dialects. Providers reject
 * unsupported input rather than silently weakening these requirements. Exceptions
 * must not include input values or sensitive SQL.
 */
public interface SqlCompiler {
    CompiledQuery compile(QueryDefinition query, DbVendor vendor);
}
