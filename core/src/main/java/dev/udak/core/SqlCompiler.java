package dev.udak.core;
/** Provider-neutral contract. Real parsers/renderers can be added as adapters. */
public interface SqlCompiler {
    CompiledQuery compile(QueryDefinition query, DbVendor vendor);
}
