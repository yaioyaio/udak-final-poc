package dev.udak.core;
import java.util.List;
public record QueryDefinition(String table, List<String> columns, String whereColumn,
                              Object whereValue, String orderColumn, boolean descending,
                              int limit, long offset) {
    public QueryDefinition { columns = List.copyOf(columns); }
}
