package dev.udak.api;

import dev.udak.core.BasicSqlCompiler;
import dev.udak.core.Bind;
import dev.udak.core.CompiledQuery;
import dev.udak.core.DbVendor;
import dev.udak.core.QueryDefinition;
import dev.udak.core.SqlCompiler;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;

/**
 * Minimal explicit JDBC-oriented CRUD; it does not implement ORM lifecycle,
 * identity generation, generated keys, upsert, cache, or flush semantics.
 * Inserts require a caller-supplied non-null ID. Values are bound, not inlined.
 * Snapshots are shallow: objects used as values are not copied.
 */
public final class CrudClient {
    private final TableDefinition table;
    private final DbVendor vendor;
    private final SqlExecutor executor;
    private final Set<String> columns;
    private final SqlCompiler compiler;

    public CrudClient(TableDefinition table, DbVendor vendor, SqlExecutor executor) {
        this(table, vendor, executor, defaultCompiler(table));
    }

    /** Uses a supplied compiler after enforcing this table's identifier allowlist. */
    public CrudClient(TableDefinition table, DbVendor vendor, SqlExecutor executor, SqlCompiler compiler) {
        this.table = Objects.requireNonNull(table, "table");
        this.vendor = Objects.requireNonNull(vendor, "vendor");
        this.executor = Objects.requireNonNull(executor, "executor");
        this.columns = Set.copyOf(table.columns());
        this.compiler = Objects.requireNonNull(compiler, "compiler");
    }

    private static SqlCompiler defaultCompiler(TableDefinition table) {
        Objects.requireNonNull(table, "table");
        Set<String> identifiers = new HashSet<>(table.columns());
        identifiers.add(table.table());
        return new BasicSqlCompiler(identifiers);
    }

    public int insert(Map<String, ?> values) {
        Map<String, ?> snapshot = snapshot(values, false);
        if (!snapshot.containsKey(table.idColumn()) || snapshot.get(table.idColumn()) == null)
            throw new IllegalArgumentException("A non-null ID is required");
        List<String> selected = orderedColumns(snapshot);
        List<Bind> binds = new ArrayList<>();
        for (String column : selected) binds.add(new Bind(column, snapshot.get(column)));
        String placeholders = String.join(", ", java.util.Collections.nCopies(selected.size(), "?"));
        return executor.update(new CompiledQuery("INSERT INTO " + table.table() + " ("
                + String.join(", ", selected) + ") VALUES (" + placeholders + ")", binds, vendor));
    }

    public int updateById(Object id, Map<String, ?> values) {
        requireId(id);
        Map<String, ?> snapshot = snapshot(values, true);
        List<String> assignments = new ArrayList<>();
        List<Bind> binds = new ArrayList<>();
        for (String column : orderedColumns(snapshot)) {
            assignments.add(column + " = ?");
            binds.add(new Bind(column, snapshot.get(column)));
        }
        binds.add(new Bind(table.idColumn(), id));
        return executor.update(new CompiledQuery("UPDATE " + table.table() + " SET "
                + String.join(", ", assignments) + " WHERE " + table.idColumn() + " = ?", binds, vendor));
    }

    public int deleteById(Object id) {
        requireId(id);
        return executor.update(new CompiledQuery("DELETE FROM " + table.table() + " WHERE "
                + table.idColumn() + " = ?", List.of(new Bind(table.idColumn(), id)), vendor));
    }

    /** Fetches at most two rows and rejects duplicate IDs or null mapped values. */
    public <T> Optional<T> findById(Object id, RowMapper<T> mapper) {
        requireId(id);
        List<T> rows = select(new QueryDefinition(table.table(), table.columns(), table.idColumn(),
                id, table.idColumn(), false, 2, 0), mapper);
        if (rows.size() > 1) throw new IllegalStateException("Multiple rows matched the ID");
        return rows.isEmpty() ? Optional.empty() : Optional.of(rows.get(0));
    }

    /** Executes a structured SELECT after checking every identifier against this table. */
    public <T> List<T> select(QueryDefinition query, RowMapper<T> mapper) {
        Objects.requireNonNull(query, "query");
        Objects.requireNonNull(mapper, "mapper");
        if (!table.table().equals(query.table()) || !columns.containsAll(query.columns())
                || !columns.contains(query.whereColumn()) || !columns.contains(query.orderColumn()))
            throw new IllegalArgumentException("Invalid or disallowed identifier");
        return List.copyOf(executor.query(compiler.compile(query, vendor), mapper));
    }

    private Map<String, ?> snapshot(Map<String, ?> values, boolean update) {
        if (values == null || values.isEmpty()) throw new IllegalArgumentException("Values are required");
        // HashMap accepts null values, which are valid SQL bind values.
        Map<String, ?> copy = new java.util.HashMap<>(values);
        if (!columns.containsAll(copy.keySet()) || (update && copy.containsKey(table.idColumn())))
            throw new IllegalArgumentException("Invalid or disallowed column");
        return copy;
    }
    private List<String> orderedColumns(Map<String, ?> values) {
        return table.columns().stream().filter(values::containsKey).toList();
    }
    private static void requireId(Object id) {
        if (id == null) throw new IllegalArgumentException("A non-null ID is required");
    }
}
