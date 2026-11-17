package dev.udak.api;

import dev.udak.core.CompiledQuery;
import java.util.List;

/**
 * Execution boundary for trusted compiled queries. This interface is not a SQL
 * firewall, parser, approval gate, or rewrite mechanism; callers must establish
 * query provenance. A mapper is invoked within the JDBC row's lifetime.
 */
public interface SqlExecutor {
    <T> List<T> query(CompiledQuery query, RowMapper<T> mapper);
    int update(CompiledQuery query);
}
