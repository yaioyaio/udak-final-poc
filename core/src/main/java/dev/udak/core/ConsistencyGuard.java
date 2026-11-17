package dev.udak.core;
import java.util.Set;
/** Startup/config policy check; cannot guarantee distributed atomic commit or ORM cache coherence. */
public final class ConsistencyGuard {
    private ConsistencyGuard() {}
    public static void requireSingleLocalResource(Set<String> dataSourceIds) {
        if(dataSourceIds == null || dataSourceIds.isEmpty())
            throw new IllegalArgumentException("No DataSource configured");
        if(dataSourceIds.size() > 1)
            throw new IllegalStateException("Multiple DataSources: local transaction atomicity is not guaranteed; configure XA/JTA or Saga explicitly");
    }
}
