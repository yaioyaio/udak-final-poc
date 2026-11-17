package dev.udak.testkit;

import java.sql.Connection;
import java.io.PrintStream;
import java.util.ArrayList;
import java.util.List;
import java.util.ServiceLoader;
import javax.sql.DataSource;

/** No connection occurs in inventory mode. Provider and driver are supplied externally. */
public final class RealDatabaseContractRunner {
    private RealDatabaseContractRunner() { }
    public static void main(String[] args) {
        if (args.length == 0) {
            inventory(System.out);
            return;
        }
        if (args.length != 2 || !"--run".equals(args[0])) { System.out.println("NOT RUN: INVALID_ARGUMENT"); System.exit(2); }
        DatabaseProfile profile;
        try { profile = DatabaseProfile.valueOf(args[1]); }
        catch (IllegalArgumentException ex) { System.out.println("NOT RUN: INVALID_PROFILE"); System.exit(2); return; }
        String result;
        try { result = execute(profile, ServiceLoader.load(RealDatabaseProvider.class)); }
        catch (Throwable ex) { result = "FAIL: PROVIDER_ERROR"; }
        System.out.println(profile.name() + " " + result);
        if (!"PASS".equals(result)) System.exit(1);
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
    static String execute(DatabaseProfile profile, Iterable<RealDatabaseProvider> providers, DriverCheck driverCheck) {
        try {
            List<RealDatabaseProvider> matched = new ArrayList<>();
            for (RealDatabaseProvider provider : providers) if (profile == provider.profile()) matched.add(provider);
            if (matched.size() != 1 || !matched.get(0).dedicatedSchemaApproved()) return "NOT RUN: DEDICATED_PROVIDER_REQUIRED";
            try { driverCheck.load(profile.driverClass()); }
            catch (ClassNotFoundException | LinkageError ex) { return "NOT RUN: DRIVER_UNAVAILABLE"; }
            DataSource ds = matched.get(0).dataSource();
            if (ds == null) return "NOT RUN: DATASOURCE_UNAVAILABLE";
            try (Connection c = ds.getConnection()) {
                if (!profile.matchesProduct(c.getMetaData().getDatabaseProductName())) return "NOT RUN: PRODUCT_MISMATCH";
            }
            DatabaseScenario.run(ds, profile);
            return "PASS";
        } catch (DatabaseScenario.Failure ex) {
            return "FAIL: " + ex.code + (ex.fixture == null ? "" : " FIXTURE=" + ex.fixture);
        } catch (Throwable ex) {
            return "FAIL: EXECUTION_ERROR";
        }
    }
    // Embedded-only contract test entrypoint: no real-profile identity claim is made.
    static int runEmbeddedTest(DataSource ds) throws DatabaseScenario.Failure {
        return DatabaseScenario.run(ds, DatabaseProfile.POSTGRESQL);
    }
}
