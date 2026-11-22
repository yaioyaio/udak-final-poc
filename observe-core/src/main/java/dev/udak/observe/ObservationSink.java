package dev.udak.observe;

/** Called synchronously. Implementations must bound their work and avoid blocking the SQL thread. */
@FunctionalInterface
public interface ObservationSink {
    void accept(SqlObservation event);

    /**
     * Receives the same event with a separate fixed reason code. Normalized shapes use
     * {@link UnavailableReason#NONE}. The default implementation forwards the event to
     * existing sinks. Reasons describe the lexer's first rejection for an observation.
     */
    default void accept(SqlObservation event, UnavailableReason reason) {
        accept(event);
    }
}
