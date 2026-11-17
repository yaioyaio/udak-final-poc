package dev.udak.core;
import java.util.List;
import java.util.Objects;
public record QueryDefinition(String table, List<String> columns, String whereColumn,
                              Object whereValue, String orderColumn, boolean descending,
                              int limit, long offset) {
    public QueryDefinition {
        Objects.requireNonNull(table, "table");
        columns = List.copyOf(columns);
        Objects.requireNonNull(whereColumn, "whereColumn");
        Objects.requireNonNull(orderColumn, "orderColumn");
    }
}
