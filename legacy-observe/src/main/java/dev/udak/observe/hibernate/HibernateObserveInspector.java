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

    private final SqlObserver observer;

    public HibernateObserveInspector(SqlObserver observer) {
        this.observer = Objects.requireNonNull(observer, "observer");
    }

    @Override
    public String inspect(String sql) {
        observer.observe(Framework.JPA, ObservationPoint.JPA_INSPECT, null, sql);
        return sql;
    }
}
