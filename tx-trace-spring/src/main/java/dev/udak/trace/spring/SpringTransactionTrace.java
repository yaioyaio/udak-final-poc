package dev.udak.trace.spring;

import dev.udak.observe.Framework;
import dev.udak.observe.ObservationSink;
import dev.udak.observe.SqlObservation;
import jakarta.persistence.EntityManagerFactory;
import org.springframework.jdbc.datasource.ConnectionHolder;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.orm.jpa.EntityManagerHolder;
import org.springframework.orm.jpa.JpaTransactionManager;
import org.springframework.transaction.TransactionExecution;
import org.springframework.transaction.TransactionExecutionListener;
import org.springframework.transaction.support.AbstractPlatformTransactionManager;
import org.springframework.transaction.support.DefaultTransactionStatus;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import javax.sql.DataSource;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.ReentrantLock;

/** Captures Spring callbacks and metadata from Observe adapters explicitly wired to the configured resources. */
public final class SpringTransactionTrace implements ObservationSink {
    public enum Kind {
        ATTACHED, CHECKPOINT_REUSED, SUSPENDED, RESUMED, BEFORE_COMMIT, BEFORE_COMPLETION,
        COMPLETED, SAVEPOINT_CREATED, SAVEPOINT_ROLLBACK_REQUESTED, FLUSH_COMPLETED, SQL
    }

    public enum Association {
        BOUND_CONTEXT, NO_TRANSACTION, UNMATCHED_RESOURCE, UNTRACKED_TRANSACTION, UNAVAILABLE
    }

    public enum Outcome { NONE, COMMITTED, ROLLED_BACK, UNKNOWN }

    public enum ManagerKind { NONE, JDBC, JPA }

    /** Sequence starts at one. Unassociated SQL has transaction ID zero. Only SQL carries an observation. */
    public record Event(long sequence, long transactionId, Kind kind, Association association,
                        SqlObservation observation, Outcome outcome, ManagerKind managerKind) {}

    /** A positive dropped count indicates that the trace is incomplete. */
    public record Report(int dropped, List<Event> events) {
        public Report {
            events = List.copyOf(events);
        }
    }

    private static final int MAX_EVENTS = 256;
    private final DataSource dataSource;
    private final EntityManagerFactory entityManagerFactory;
    private final int maxEvents;
    private final List<Event> events;
    private final ReentrantLock lock = new ReentrantLock();
    private final AtomicInteger dropped = new AtomicInteger();
    private final AtomicLong lastTransactionId = new AtomicLong();
    private final Object markerKey = new Object();
    private final BeginListener jdbcListener = new BeginListener(ManagerKind.JDBC);
    private final BeginListener jpaListener = new BeginListener(ManagerKind.JPA);

    public SpringTransactionTrace(DataSource dataSource, EntityManagerFactory entityManagerFactory) {
        this(dataSource, entityManagerFactory, MAX_EVENTS);
    }

    public SpringTransactionTrace(DataSource dataSource, EntityManagerFactory entityManagerFactory, int maxEvents) {
        this.dataSource = Objects.requireNonNull(dataSource, "DataSource required");
        this.entityManagerFactory = entityManagerFactory;
        if (maxEvents < 1 || maxEvents > MAX_EVENTS) {
            throw new IllegalArgumentException("Event capacity must be between 1 and 256");
        }
        this.maxEvents = maxEvents;
        this.events = new ArrayList<>(maxEvents);
    }

    /** Install during setup, before the manager is used. Existing listeners retain their order. */
    public void registerWith(AbstractPlatformTransactionManager manager) {
        try {
            BeginListener listener;
            if (manager instanceof DataSourceTransactionManager jdbc && jdbc.getDataSource() == dataSource) {
                listener = jdbcListener;
            } else if (manager instanceof JpaTransactionManager jpa && jpa.getDataSource() == dataSource
                    && entityManagerFactory != null && jpa.getEntityManagerFactory() == entityManagerFactory) {
                listener = jpaListener;
            } else {
                throw new IllegalArgumentException("Unsupported transaction manager or resources");
            }
            synchronized (manager) {
                var existing = manager.getTransactionExecutionListeners();
                for (var registered : existing) {
                    if (registered == listener) return;
                }
                try {
                    manager.addListener(listener);
                } catch (UnsupportedOperationException immutable) {
                    var updated = new ArrayList<>(existing);
                    updated.add(listener);
                    manager.setTransactionExecutionListeners(updated);
                }
            }
        } catch (Throwable failure) {
            rethrowFatal(failure);
            throw new IllegalArgumentException("Cannot register trace on the specified transaction manager");
        }
    }

    private final class BeginListener implements TransactionExecutionListener {
        private final ManagerKind managerKind;

        private BeginListener(ManagerKind managerKind) {
            this.managerKind = managerKind;
        }

        @Override
        public void afterBegin(TransactionExecution transaction, Throwable beginFailure) {
            try {
                if (beginFailure != null || !transaction.isNewTransaction()
                        || !(transaction instanceof DefaultTransactionStatus status) || !status.isNewSynchronization()
                        || !TransactionSynchronizationManager.isActualTransactionActive()
                        || !TransactionSynchronizationManager.isSynchronizationActive()) return;
                attach(managerKind);
            } catch (Throwable failure) {
                diagnosticFailure(failure);
            }
        }
    }

    private void attach(ManagerKind managerKind) {
        // An earlier afterCompletion callback can start another transaction before our callback runs.
        Marker previous = currentMarker();
        if (previous != null) {
            previous.active = false;
            drop();
            return;
        }
        Holders live = currentHolders();
        if (live.competingResource || (managerKind == ManagerKind.JDBC ? live.jdbc == null : live.jpa == null)) return;
        // A JDBC manager owns only its JDBC holder, even if an entity manager is already open.
        Holders attached = managerKind == ManagerKind.JDBC ? new Holders(live.jdbc, null, false) : live;
        long previousId = lastTransactionId.getAndUpdate(id -> id == Long.MAX_VALUE ? id : id + 1);
        if (previousId == Long.MAX_VALUE) {
            drop();
            return;
        }
        Marker marker = new Marker(previousId + 1, attached, managerKind);
        TransactionSynchronizationManager.bindResource(markerKey, marker);
        try {
            TransactionSynchronizationManager.registerSynchronization(marker);
        } catch (Throwable failure) {
            marker.release();
            throw failure;
        }
        marker.lifecycle(Kind.ATTACHED);
    }

    /** Marks a checkpoint in an already enrolled transaction, including REQUIRED participation. */
    public void checkpoint() {
        try {
            if (!TransactionSynchronizationManager.isActualTransactionActive()
                    || !TransactionSynchronizationManager.isSynchronizationActive()) return;
            Marker marker = currentMarker();
            if (marker != null && marker.matches(currentHolders())) marker.lifecycle(Kind.CHECKPOINT_REUSED);
        } catch (Throwable failure) {
            diagnosticFailure(failure);
        }
    }

    /** Caller invokes this after a successful explicit flush on the configured JPA resource. */
    public void markFlushCompleted() {
        try {
            if (!TransactionSynchronizationManager.isActualTransactionActive()
                    || !TransactionSynchronizationManager.isSynchronizationActive()) return;
            Marker marker = currentMarker();
            if (marker != null && marker.attached.jpa != null && marker.matches(currentHolders())) {
                marker.lifecycle(Kind.FLUSH_COMPLETED);
            }
        } catch (Throwable failure) {
            diagnosticFailure(failure);
        }
    }

    /** Correlates the current thread-bound context. The observation point can precede SQL execution. */
    @Override
    public void accept(SqlObservation observation) {
        if (observation == null) {
            drop();
            return;
        }
        long transactionId = 0;
        ManagerKind managerKind = ManagerKind.NONE;
        Association association;
        try {
            if (!TransactionSynchronizationManager.isActualTransactionActive()) {
                association = Association.NO_TRANSACTION;
            } else {
                Holders live = currentHolders();
                Marker marker = TransactionSynchronizationManager.isSynchronizationActive() ? currentMarker() : null;
                if (live.competingResource || !live.has(observation.framework())) {
                    association = Association.UNMATCHED_RESOURCE;
                } else if (marker == null || marker.correlationClosed) {
                    association = Association.UNTRACKED_TRANSACTION;
                } else if (!marker.attached.has(observation.framework()) || !marker.matches(live)) {
                    association = Association.UNMATCHED_RESOURCE;
                } else {
                    transactionId = marker.id;
                    managerKind = marker.managerKind;
                    association = Association.BOUND_CONTEXT;
                }
            }
        } catch (Throwable failure) {
            diagnosticFailure(failure);
            association = Association.UNAVAILABLE;
        }
        record(transactionId, Kind.SQL, association, observation, Outcome.NONE, managerKind);
    }

    public Report snapshot() {
        lock.lock();
        try {
            return new Report(dropped.get(), events);
        } finally {
            lock.unlock();
        }
    }

    private Holders currentHolders() {
        // Spring's getResource(key) can unwrap keys and unbind void holders. Inspect the map by identity.
        ConnectionHolder jdbc = null;
        EntityManagerHolder jpa = null;
        boolean competingResource = false;
        for (var entry : TransactionSynchronizationManager.getResourceMap().entrySet()) {
            Object key = entry.getKey();
            if (key instanceof DataSource && entry.getValue() instanceof ConnectionHolder holder && !holder.isVoid()) {
                if (key == dataSource) jdbc = holder;
                else competingResource = true;
            } else if (key instanceof EntityManagerFactory && entry.getValue() instanceof EntityManagerHolder holder
                    && !holder.isVoid()) {
                if (key == entityManagerFactory) jpa = holder;
                else competingResource = true;
            }
        }
        // DataSourceUtils may bind a second, auxiliary holder on a transaction owned by another manager.
        // With multiple resource identities the configured holder alone cannot distinguish the owner.
        return new Holders(jdbc, jpa, competingResource);
    }

    private Marker currentMarker() {
        Object value = TransactionSynchronizationManager.getResource(markerKey);
        if (value == null) return null;
        if (value instanceof Marker marker && marker.owner == this) return marker;
        throw new IllegalStateException("Trace marker slot is occupied");
    }

    private record Holders(ConnectionHolder jdbc, EntityManagerHolder jpa, boolean competingResource) {
        boolean has(Framework framework) {
            return switch (framework) {
                case JPA -> jpa != null;
                case JDBC, MYBATIS -> jdbc != null;
            };
        }
    }

    private final class Marker implements TransactionSynchronization {
        private final SpringTransactionTrace owner = SpringTransactionTrace.this;
        private final long id;
        private final Holders attached;
        private final ManagerKind managerKind;
        private boolean active = true;
        private boolean correlationClosed;

        private Marker(long id, Holders attached, ManagerKind managerKind) {
            this.id = id;
            this.attached = attached;
            this.managerKind = managerKind;
        }

        private boolean matches(Holders live) {
            return active && !correlationClosed && !live.competingResource && (attached.jdbc == null || attached.jdbc == live.jdbc)
                    && (attached.jpa == null || attached.jpa == live.jpa);
        }

        private void lifecycle(Kind kind) {
            record(id, kind, Association.BOUND_CONTEXT, null, Outcome.NONE, managerKind);
        }

        private void release() {
            active = false;
            try {
                if (currentMarker() == this) TransactionSynchronizationManager.unbindResource(markerKey);
            } catch (Throwable failure) {
                diagnosticFailure(failure);
            }
        }

        @Override
        public void suspend() {
            release();
            lifecycle(Kind.SUSPENDED);
        }

        @Override
        public void resume() {
            try {
                Marker current = currentMarker();
                if (current == null) TransactionSynchronizationManager.bindResource(markerKey, this);
                if (current == null || current == this) active = true;
                else drop();
            } catch (Throwable failure) {
                diagnosticFailure(failure);
            }
            lifecycle(Kind.RESUMED);
        }

        @Override
        public void savepoint(Object savepoint) {
            lifecycle(Kind.SAVEPOINT_CREATED);
        }

        @Override
        public void savepointRollback(Object savepoint) {
            lifecycle(Kind.SAVEPOINT_ROLLBACK_REQUESTED);
        }

        @Override
        public void beforeCommit(boolean readOnly) {
            lifecycle(Kind.BEFORE_COMMIT);
        }

        @Override
        public void beforeCompletion() {
            // Spring can still expose the holder during earlier completion callbacks.
            correlationClosed = true;
            lifecycle(Kind.BEFORE_COMPLETION);
        }

        @Override
        public void afterCompletion(int status) {
            release();
            Outcome outcome = switch (status) {
                case STATUS_COMMITTED -> Outcome.COMMITTED;
                case STATUS_ROLLED_BACK -> Outcome.ROLLED_BACK;
                default -> Outcome.UNKNOWN;
            };
            record(id, Kind.COMPLETED, Association.BOUND_CONTEXT, null, outcome, managerKind);
        }
    }

    private void record(long transactionId, Kind kind, Association association,
                        SqlObservation observation, Outcome outcome, ManagerKind managerKind) {
        if (!lock.tryLock()) {
            drop();
            return;
        }
        try {
            if (events.size() < maxEvents) {
                events.add(new Event(events.size() + 1L, transactionId, kind, association,
                        observation, outcome, managerKind));
            } else {
                drop();
            }
        } catch (Throwable failure) {
            diagnosticFailure(failure);
        } finally {
            lock.unlock();
        }
    }

    private void diagnosticFailure(Throwable failure) {
        rethrowFatal(failure);
        drop();
    }

    private static void rethrowFatal(Throwable failure) {
        if (failure instanceof VirtualMachineError fatal) throw fatal;
        if (failure instanceof ThreadDeath termination) throw termination;
    }

    private void drop() {
        dropped.getAndUpdate(count -> count == Integer.MAX_VALUE ? count : count + 1);
    }
}
