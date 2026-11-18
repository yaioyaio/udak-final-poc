package dev.udak.observe;

/** Called synchronously. Implementations must bound their work and avoid blocking the SQL thread. */
@FunctionalInterface
public interface ObservationSink {
    void accept(SqlObservation event);
}
