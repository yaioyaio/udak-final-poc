package dev.udak.core;
import java.util.List;
import java.util.Objects;
public record CompiledQuery(String sql, List<Bind> binds, DbVendor vendor) {
    public CompiledQuery {
        Objects.requireNonNull(sql, "sql");
        if (sql.isBlank()) throw new IllegalArgumentException("SQL must not be blank");
        binds = List.copyOf(binds);
        Objects.requireNonNull(vendor, "vendor");
    }

    @Override
    public String toString() {
        return "CompiledQuery[vendor=" + vendor.name() + ", bindCount=" + binds.size() + "]";
    }
}
