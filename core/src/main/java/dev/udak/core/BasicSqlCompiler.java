package dev.udak.core;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;
/**
 * POC subset only: equality, deterministic sort, LIMIT/OFFSET.
 * Identifiers MUST match an application-supplied schema allowlist.
 * Do not use as a general-purpose SQL parser or production compiler.
 */
public final class BasicSqlCompiler implements SqlCompiler {
    private static final Pattern IDENT = Pattern.compile("[A-Za-z_][A-Za-z_0-9]*");
    private final Set<String> allowedIdentifiers;
    public BasicSqlCompiler(Set<String> allowedIdentifiers) {
        this.allowedIdentifiers = Set.copyOf(allowedIdentifiers);
    }
    private String identifier(String value) {
        if (value == null || !IDENT.matcher(value).matches() || !allowedIdentifiers.contains(value)) {
            throw new IllegalArgumentException("Identifier not allowlisted: " + value);
        }
        return value;
    }
    @Override public CompiledQuery compile(QueryDefinition q, DbVendor vendor) {
        if(q.columns().isEmpty()) throw new IllegalArgumentException("At least one selected column is required");
        if(q.limit() <= 0 || q.limit() > 1000 || q.offset() < 0)
            throw new IllegalArgumentException("Invalid pagination");
        var cols = q.columns().stream().map(this::identifier).toList();
        String table = identifier(q.table());
        String where = identifier(q.whereColumn());
        String order = identifier(q.orderColumn());
        String sort = q.descending() ? " DESC" : " ASC";
        String base = "SELECT " + String.join(", ", cols) + " FROM " + table
            + " WHERE " + where + " = ? ORDER BY " + order + sort;
        List<Bind> binds = new ArrayList<>();
        binds.add(new Bind("filter", q.whereValue()));
        String sql;
        switch(vendor) {
            case POSTGRESQL, MYSQL -> {
                sql = base + " LIMIT ? OFFSET ?";
                binds.add(new Bind("limit", q.limit()));
                binds.add(new Bind("offset", q.offset()));
            }
            case SQLSERVER, ORACLE_19 -> {
                sql = base + " OFFSET ? ROWS FETCH NEXT ? ROWS ONLY";
                binds.add(new Bind("offset", q.offset()));
                binds.add(new Bind("limit", q.limit()));
            }
            case ORACLE_11 -> {
                long bound = Math.addExact(q.offset(), q.limit());
                sql = "SELECT " + String.join(", ", cols) + " FROM (SELECT inner_q.*, ROWNUM udak_rn "
                    + "FROM (" + base + ") inner_q WHERE ROWNUM <= ?) WHERE udak_rn > ?";
                binds.add(new Bind("upperBound", bound));
                binds.add(new Bind("offset", q.offset()));
            }
            default -> throw new IllegalArgumentException("Unsupported vendor: " + vendor);
        }
        return new CompiledQuery(sql, binds, vendor);
    }
}
