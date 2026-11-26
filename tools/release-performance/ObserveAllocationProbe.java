package dev.udak.observe;

import com.sun.management.ThreadMXBean;
import dev.udak.bench.JdbcCacheMissBenchmark;
import java.lang.management.ManagementFactory;
import java.util.Arrays;

/** Single-threaded allocation diagnostic compiled only into the guarded test workspace. */
public final class ObserveAllocationProbe {
    static final int NORMALIZATION = 0;
    static final int FINGERPRINT = 1;
    static final int EVENT = 2;

    private static final int NO_STAGE = -1;
    private static final int OPERATIONS = 200_000;
    private static final int BLOCKS = 3;
    private static final int EMPTY_OPERATIONS = 2_048;
    private static final int[] STAGES = {FINGERPRINT, NORMALIZATION, FINGERPRINT, NORMALIZATION, FINGERPRINT, EVENT};
    private static final long[] stageTotals = new long[3];

    private static ThreadMXBean allocationBean;
    private static Thread owner;
    private static boolean enabled;
    private static boolean inOperation;
    private static boolean invalid;
    private static int activeStage = NO_STAGE;
    private static int completedStages;
    private static long operationStart;
    private static long stageStart;
    private static long lastReading;
    private static long blockTotal;
    private static volatile SqlObservation lastObservation;

    private ObserveAllocationProbe() {}

    static void begin(int stage) {
        if (!enabled) return;
        require(inOperation && activeStage == NO_STAGE && completedStages < STAGES.length
                && stage == STAGES[completedStages]);
        stageStart = checkpoint();
        activeStage = stage;
    }

    static void end(int stage) {
        if (!enabled) return;
        require(inOperation && stage >= 0 && activeStage == stage);
        stageTotals[stage] += checkpoint() - stageStart;
        activeStage = NO_STAGE;
        completedStages++;
    }

    private static long checkpoint() {
        require(owner == Thread.currentThread());
        long reading = allocationBean.getCurrentThreadAllocatedBytes();
        require(reading >= lastReading);
        lastReading = reading;
        return reading;
    }

    private static void startOperation() {
        require(!inOperation && activeStage == NO_STAGE && !invalid);
        inOperation = true;
        completedStages = 0;
        operationStart = checkpoint();
    }

    private static void finishOperation() {
        require(inOperation && activeStage == NO_STAGE && completedStages == STAGES.length && !invalid);
        blockTotal += checkpoint() - operationStart;
        inOperation = false;
    }

    private static void resetBlock() {
        Arrays.fill(stageTotals, 0L);
        blockTotal = 0;
    }

    private static long accounted() {
        return stageTotals[NORMALIZATION] + stageTotals[FINGERPRINT] + stageTotals[EVENT];
    }

    private static void emptyOperations() {
        resetBlock();
        for (int operation = 0; operation < EMPTY_OPERATIONS; operation++) {
            startOperation();
            for (int stage : STAGES) {
                begin(stage);
                end(stage);
            }
            finishOperation();
        }
    }

    private static void measure(JdbcCacheMissBenchmark fixture) {
        resetBlock();
        SqlObservation previous = lastObservation;
        for (int operation = 0; operation < OPERATIONS; operation++) {
            startOperation();
            SqlObservation event = fixture.cacheMiss();
            finishOperation();
            require(event != null && previous != event);
            previous = event;
        }
        lastObservation = previous;
        require(accounted() <= blockTotal);
    }

    private static long[][] run() {
        require(ManagementFactory.getThreadMXBean() instanceof ThreadMXBean);
        allocationBean = (ThreadMXBean) ManagementFactory.getThreadMXBean();
        require(allocationBean.isThreadAllocatedMemorySupported());
        if (!allocationBean.isThreadAllocatedMemoryEnabled()) allocationBean.setThreadAllocatedMemoryEnabled(true);
        owner = Thread.currentThread();
        checkpoint();

        var fixture = new JdbcCacheMissBenchmark();
        fixture.setup();
        var results = new long[BLOCKS][4];

        enabled = true;
        emptyOperations();
        measure(fixture);
        emptyOperations();
        require(blockTotal == 0 && accounted() == 0);
        for (long[] result : results) {
            measure(fixture);
            require(stageTotals[NORMALIZATION] > 0 && stageTotals[FINGERPRINT] > 0 && stageTotals[EVENT] > 0);
            System.arraycopy(stageTotals, 0, result, 0, stageTotals.length);
            result[3] = blockTotal;
        }
        emptyOperations();
        require(blockTotal == 0 && accounted() == 0);
        enabled = false;
        return results;
    }

    public static void main(String[] args) {
        try {
            require(args.length == 0);
            long[][] results = run();
            System.out.println("OBSERVE_ALLOCATION PASS");
            for (long[] block : results) {
                System.out.println("BLOCK " + OPERATIONS + " " + block[0] + " " + block[1] + " " + block[2]
                        + " " + block[3]);
            }
        } catch (RuntimeException | LinkageError failure) {
            System.out.println("OBSERVE_ALLOCATION FAIL");
            System.exit(1);
        }
    }

    private static void require(boolean condition) {
        if (!condition) {
            invalid = true;
            throw new IllegalStateException("Allocation probe invariant failed");
        }
    }
}
