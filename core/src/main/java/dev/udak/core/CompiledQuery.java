package dev.udak.core;
import java.util.List;
public record CompiledQuery(String sql, List<Bind> binds, DbVendor vendor) {
    public CompiledQuery { binds = List.copyOf(binds); }
}
