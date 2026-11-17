package dev.udak.api;

import java.util.HashSet;
import java.util.List;
import java.util.regex.Pattern;

/** Per-table identifier allowlist. Column order controls write SQL and bind order. */
public record TableDefinition(String table, List<String> columns, String idColumn) {
    private static final Pattern IDENTIFIER = Pattern.compile("[A-Za-z_][A-Za-z_0-9]*");
    public TableDefinition {
        validateIdentifier(table);
        validateIdentifier(idColumn);
        if (columns == null) throw new IllegalArgumentException("Invalid columns");
        for (String column : columns) validateIdentifier(column);
        columns = List.copyOf(columns);
        if (columns.isEmpty() || new HashSet<>(columns).size() != columns.size() || !columns.contains(idColumn))
            throw new IllegalArgumentException("Invalid columns");
    }
    private static void validateIdentifier(String value) {
        if (value == null || !IDENTIFIER.matcher(value).matches())
            throw new IllegalArgumentException("Invalid identifier");
    }
}
