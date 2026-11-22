package dev.udak.observe.hibernate;

import dev.udak.observe.Framework;
import dev.udak.observe.ObservationPoint;
import dev.udak.observe.SqlObserver;
import java.io.Serial;
import java.util.Objects;
import org.hibernate.resource.jdbc.spi.StatementInspector;

/** Observes SQL at the Hibernate 6 inspection point. */
public final class HibernateObserveInspector implements StatementInspector {
    @Serial
    private static final long serialVersionUID = 1L;

    private final StatementInspector existing;
    private final SqlObserver observer;

    public HibernateObserveInspector(SqlObserver observer) {
        this(null, observer);
    }

    /** Runs the existing inspector first and observes the SQL selected by its return value. */
    public static HibernateObserveInspector compose(StatementInspector existing, SqlObserver observer) {
        return new HibernateObserveInspector(Objects.requireNonNull(existing, "existing inspector"), observer);
    }

    private HibernateObserveInspector(StatementInspector existing, SqlObserver observer) {
        this.existing = existing;
        this.observer = Objects.requireNonNull(observer, "observer");
    }

    @Override
    public String inspect(String sql) {
        String inspected = existing == null ? sql : existing.inspect(sql);
        String effectiveSql = inspected == null ? sql : inspected;
        observer.observe(Framework.JPA, ObservationPoint.JPA_INSPECT, null, effectiveSql);
        return inspected;
    }
}
