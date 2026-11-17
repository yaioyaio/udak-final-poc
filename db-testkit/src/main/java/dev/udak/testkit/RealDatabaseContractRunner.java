package dev.udak.testkit;

import java.io.OutputStream;
import java.io.PrintStream;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.util.ArrayList;
import java.util.List;
import java.util.ServiceLoader;
import java.util.logging.Level;
import java.util.logging.LogManager;
import java.util.regex.Pattern;
import javax.sql.DataSource;

/** No connection or service loading occurs in inventory mode. */
public final class RealDatabaseContractRunner {
    private static final Pattern VERSION = Pattern.compile("[0-9]+(?:\\.[0-9]+){1,5}");
    private RealDatabaseContractRunner() { }
    public static void main(String[] args) {
        if (args.length == 0) { inventory(System.out); return; }
        if (args.length != 6 || !"--run".equals(args[0]) || !"--driver-version".equals(args[2])
                || !VERSION.matcher(args[3]).matches() || !"--fixture".equals(args[4])) {
            System.out.println("NOT RUN: INVALID_ARGUMENT"); System.exit(2); return;
        }
        DatabaseProfile profile;
        try { profile = DatabaseProfile.valueOf(args[1]); }
        catch (IllegalArgumentException ex) { System.out.println("NOT RUN: INVALID_PROFILE"); System.exit(2); return; }
        try { DatabaseProfile.validateFixture(args[5]); }
        catch (IllegalArgumentException ex) { System.out.println("NOT RUN: INVALID_FIXTURE"); System.exit(2); return; }
        PrintStream originalOut = System.out;
        String result;
        try {
            // Keep the sink installed for the process lifetime, including shutdown hooks.
            PrintStream sink = new PrintStream(OutputStream.nullOutputStream());
            System.setOut(sink);
            System.setErr(sink);
            // Disable currently registered JUL loggers before loading third-party providers.
            LogManager manager = LogManager.getLogManager();
            manager.getLoggerNames().asIterator().forEachRemaining(name -> {
                java.util.logging.Logger logger = manager.getLogger(name);
                if (logger != null) logger.setLevel(Level.OFF);
            });
            result = executeEvidence(profile, ServiceLoader.load(RealDatabaseProvider.class),
                    name -> Class.forName(name, false, Thread.currentThread().getContextClassLoader()), args[3], args[5]);
        } catch (Throwable ex) { result = "FAIL: PROVIDER_ERROR"; }
        originalOut.println(profile.name() + " " + result);
        if (!result.startsWith("PASS\n")) System.exit(1);
    }
    static void inventory(PrintStream out) {
        for (DatabaseProfile p : DatabaseProfile.values())
            out.println(p.name() + " NOT RUN: DEDICATED_PROVIDER_REQUIRED");
    }
    @FunctionalInterface
    interface DriverCheck { void load(String className) throws ClassNotFoundException; }
    static String execute(DatabaseProfile profile, Iterable<RealDatabaseProvider> providers) {
        return execute(profile, providers, name -> Class.forName(name, false, Thread.currentThread().getContextClassLoader()));
    }
    // Legacy entrypoint cannot authorize a live scenario without a pinned version.
    static String execute(DatabaseProfile profile, Iterable<RealDatabaseProvider> providers, DriverCheck driverCheck) {
        return executeEvidence(profile, providers, driverCheck, null);
    }
    static String executeEvidence(DatabaseProfile profile, Iterable<RealDatabaseProvider> providers,
                                  DriverCheck driverCheck, String expectedVersion) {
        return executeEvidence(profile, providers, driverCheck, expectedVersion, null);
    }
    static String executeEvidence(DatabaseProfile profile, Iterable<RealDatabaseProvider> providers,
                                  DriverCheck driverCheck, String expectedVersion, String fixture) {
        try {
            if (fixture != null) {
                try { DatabaseProfile.validateFixture(fixture); }
                catch (IllegalArgumentException ex) { return "NOT RUN: INVALID_FIXTURE"; }
            }
            List<RealDatabaseProvider> matched = new ArrayList<>();
            for (RealDatabaseProvider provider : providers) if (profile == provider.profile()) matched.add(provider);
            if (matched.size() != 1 || !matched.get(0).dedicatedSchemaApproved()) return "NOT RUN: DEDICATED_PROVIDER_REQUIRED";
            try { driverCheck.load(profile.driverClass()); }
            catch (ClassNotFoundException | LinkageError ex) { return "NOT RUN: DRIVER_UNAVAILABLE"; }
            DataSource ds = matched.get(0).dataSource();
            if (ds == null) return "NOT RUN: DATASOURCE_UNAVAILABLE";
            int serverMajor, serverMinor, driverMajor, driverMinor;
            String actualVersion;
            try (Connection c = ds.getConnection()) {
                DatabaseMetaData metadata = c.getMetaData();
                if (!profile.matchesProduct(metadata.getDatabaseProductName())) return "NOT RUN: PRODUCT_MISMATCH";
                if (expectedVersion == null || !VERSION.matcher(expectedVersion).matches()) return "NOT RUN: DRIVER_VERSION_REQUIRED";
                if (!profile.matchesDriver(metadata.getDriverName())) return "NOT RUN: DRIVER_MISMATCH";
                actualVersion = profile.numericDriverVersion(metadata.getDriverVersion());
                if (!expectedVersion.equals(actualVersion)) return "NOT RUN: DRIVER_VERSION_MISMATCH";
                serverMajor = metadata.getDatabaseMajorVersion(); serverMinor = metadata.getDatabaseMinorVersion();
                driverMajor = metadata.getDriverMajorVersion(); driverMinor = metadata.getDriverMinorVersion();
                if (serverMajor < 0 || serverMinor < 0 || driverMajor < 0 || driverMinor < 0)
                    return "NOT RUN: INVALID_METADATA_VERSION";
                String[] parts = actualVersion.split("\\.");
                if (!parts[0].equals(Integer.toString(driverMajor)) || !parts[1].equals(Integer.toString(driverMinor)))
                    return "NOT RUN: DRIVER_VERSION_MISMATCH";
            }
            int checks = fixture == null ? DatabaseScenario.run(ds, profile) : DatabaseScenario.run(ds, profile, fixture);
            StringBuilder evidence = new StringBuilder("PASS\nSERVER_VERSION=").append(serverMajor).append('.').append(serverMinor)
                    .append("\nDRIVER_VERSION=").append(driverMajor).append('.').append(driverMinor).append("\nCHECKS=").append(checks)
                    .append("\nCLEANUP=CONFIRMED");
            for (String name : DatabaseScenario.CHECKS) evidence.append("\nSCENARIO=").append(name).append(":PASS");
            return evidence.toString();
        } catch (DatabaseScenario.Failure ex) {
            return "FAIL: " + ex.code + (ex.fixture == null ? "" : " FIXTURE=" + ex.fixture);
        } catch (Throwable ex) { return "FAIL: EXECUTION_ERROR"; }
    }
    // Embedded-only contract test entrypoint: no real-profile identity claim is made.
    static int runEmbeddedTest(DataSource ds) throws DatabaseScenario.Failure {
        return DatabaseScenario.run(ds, DatabaseProfile.POSTGRESQL);
    }
}
