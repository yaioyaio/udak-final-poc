package dev.udak.startertest;

import dev.udak.api.RowMapper;
import dev.udak.api.SqlExecutor;
import dev.udak.core.Bind;
import dev.udak.core.CompiledQuery;
import dev.udak.core.DbVendor;
import dev.udak.jdbc.SpringJdbcExecutor;
import dev.udak.observe.Framework;
import dev.udak.observe.ObservationPoint;
import dev.udak.observe.ObservationSink;
import dev.udak.observe.SqlObservation;
import dev.udak.observe.SqlObserver;
import java.io.OutputStream;
import java.io.PrintStream;
import java.sql.Connection;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import javax.sql.DataSource;
import org.h2.jdbcx.JdbcDataSource;
import org.springframework.boot.Banner;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.SpringBootVersion;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.autoconfigure.EnableAutoConfiguration;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Lazy;
import org.springframework.context.annotation.Primary;
import org.springframework.core.env.MapPropertySource;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DelegatingDataSource;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Runs the same actual Boot application contracts on one Boot major at a time. */
public final class StarterContractMain {
    private static final Map<String, Object> JDBC = Map.of(
            "udak.jdbc.enabled", true, "udak.jdbc.vendor", "POSTGRESQL");
    private static final String FIXTURE_VALUE = "PHASE6_UNSAFE_VALUE_FIXTURE";
    private static final CompiledQuery SELECT_COUNT = new CompiledQuery(
            "SELECT COUNT(*) FROM phase6_record", List.of(), DbVendor.POSTGRESQL);
    private static final CompiledQuery INSERT = new CompiledQuery(
            "INSERT INTO phase6_record (id) VALUES (?)", List.of(new Bind("id", 7)), DbVendor.POSTGRESQL);

    private final List<String> passed = new ArrayList<>();
    private int assertions;
    private String scenario = "BOOT_VERSION";

    public static void main(String[] args) {
        if (args.length < 1 || args.length > 2 || !List.of("BOOT3", "BOOT4").contains(args[0])
                || (args.length == 2 && !List.of("mixed", "wrong-major").contains(args[1]))) {
            System.out.println("STARTER FAIL");
            System.exit(1);
            return;
        }

        StarterContractMain contract = new StarterContractMain();
        PrintStream output = System.out;
        PrintStream error = System.err;
        boolean success = false;
        List<String> diagnostics = new ArrayList<>();
        try (PrintStream quiet = new PrintStream(OutputStream.nullOutputStream())) {
            System.setOut(quiet);
            System.setErr(quiet);
            try {
                contract.run(args[0], args.length == 2 ? args[1] : "");
                success = true;
            } catch (Exception | AssertionError | LinkageError ignored) {
                Throwable cause = ignored;
                for (int depth = 0; cause != null && depth < 6; depth++, cause = cause.getCause()) {
                    diagnostics.add("DIAGNOSTIC=" + cause.getClass().getName());
                    for (StackTraceElement frame : cause.getStackTrace()) {
                        if (frame.getClassName().startsWith("dev.udak.") && frame.getLineNumber() > 0) {
                            diagnostics.add("DIAGNOSTIC=" + frame.getClassName() + ":" + frame.getLineNumber());
                            if (diagnostics.size() >= 10) break;
                        }
                    }
                    if (diagnostics.size() >= 10) break;
                }
            } finally {
                System.setOut(output);
                System.setErr(error);
            }
        }
        if (!success) {
            output.println(args[0] + " FAIL");
            output.println("SCENARIO=" + contract.scenario + ":FAIL");
            diagnostics.forEach(output::println);
            System.exit(1);
            return;
        }
        output.println(args[0] + " PASS");
        output.println("ASSERTIONS=" + contract.assertions);
        for (String name : contract.passed) {
            output.println("SCENARIO=" + name + ":PASS");
        }
    }

    private void run(String lane, String mode) throws Exception {
        String expectedBoot = lane.equals("BOOT3") ? "3.5.16" : "4.1.2";
        check(expectedBoot.equals(SpringBootVersion.getVersion()));
        if (mode.equals("mixed")) {
            scenario("MIXED_STARTERS", () -> reject(
                    Map.of("udak.enabled", false), "UDAK starters cannot be mixed"));
        } else if (mode.equals("wrong-major")) {
            String wrongStarter = lane.equals("BOOT3") ? "4" : "3";
            scenario("WRONG_BOOT_MAJOR", () -> reject(
                    Map.of("udak.enabled", false), "UDAK starter requires Spring Boot " + wrongStarter));
        } else {
            scenario("DISCOVERY", () -> discovery(lane));
            scenario("DISABLED", this::disabled);
            scenario("USER_BEANS", this::userBeans);
            scenario("CUSTOM_SINK", this::customSink);
            scenario("JDBC_OPT_IN", this::jdbcOptIn);
            scenario("NO_DATASOURCE", this::noDataSource);
            scenario("AMBIGUOUS_DATASOURCES", this::ambiguousDataSources);
            scenario("JDBC_TRANSACTION", this::jdbcTransaction);
            scenario("VENDOR_REQUIRED", this::vendorRequired);
            scenario("INVALID_LIMITS", this::invalidLimits);
            scenario("UNSAFE_SETTINGS", this::unsafeSettings);
        }
    }

    private void discovery(String lane) {
        try (ConfigurableApplicationContext context = start(Map.of())) {
            String component = lane.equals("BOOT3") ? "udakBoot3AutoConfiguration" : "udakBoot4AutoConfiguration";
            String other = lane.equals("BOOT3") ? "udakBoot4AutoConfiguration" : "udakBoot3AutoConfiguration";
            check(context.containsBean(component));
            check(!context.containsBean(other));
            check(context.getBeanNamesForType(SqlObserver.class).length == 1);
            check(context.getBeanNamesForType(ObservationSink.class).length == 1);
            check(context.getBeanNamesForType(SqlExecutor.class).length == 0);
            check(context.getBeanNamesForType(PlatformTransactionManager.class).length == 0);
        }
    }

    private void disabled() {
        Map<String, Object> properties = new HashMap<>(JDBC);
        properties.put("udak.enabled", false);
        try (ConfigurableApplicationContext context = start(properties, OneDataSource.class)) {
            check(context.getBeanNamesForType(SqlObserver.class).length == 0);
            check(context.getBeanNamesForType(ObservationSink.class).length == 0);
            check(context.getBeanNamesForType(SqlExecutor.class).length == 0);
            check(context.getBeanNamesForType(PlatformTransactionManager.class).length == 0);
            check(context.getBean(CountingDataSource.class).connections == 0);
        }
    }

    private void userBeans() {
        try (ConfigurableApplicationContext context = start(JDBC, OneDataSource.class, UserBeans.class)) {
            check(context.getBeanNamesForType(SqlObserver.class).length == 1);
            check(context.getBean(SqlObserver.class) == context.getBean("customObserver"));
            check(context.getBeanNamesForType(ObservationSink.class).length == 1);
            check(context.getBean(ObservationSink.class) == context.getBean("customSink"));
            check(context.getBeanNamesForType(SqlExecutor.class).length == 1);
            check(context.getBean(SqlExecutor.class) == context.getBean("customExecutor"));
            check(context.getBean(CountingDataSource.class).connections == 0);
        }
    }

    private void customSink() {
        try (ConfigurableApplicationContext context = start(Map.of(), UserSink.class)) {
            check(context.getBeanNamesForType(ObservationSink.class).length == 1);
            CountingSink sink = context.getBean(CountingSink.class);
            SqlObserver observer = context.getBean(SqlObserver.class);
            observer.observe(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, "contract", "SELECT 1");
            check(sink.events == 1);
        }
    }

    private void jdbcOptIn() {
        try (ConfigurableApplicationContext context = start(
                Map.of("udak.jdbc.vendor", "POSTGRESQL"), OneDataSource.class)) {
            check(context.getBeanNamesForType(SqlExecutor.class).length == 0);
            check(context.getBean(CountingDataSource.class).connections == 0);
        }
        try (ConfigurableApplicationContext context = start(JDBC, LazyDataSource.class)) {
            check(context.getBeanNamesForType(SqlExecutor.class).length == 1);
            check(!context.getBeanFactory().containsSingleton("lazyDataSource"));
            check(context.getBean(SqlExecutor.class) instanceof SpringJdbcExecutor);
            check(context.getBean(CountingDataSource.class).connections == 0);
        }
    }

    private void noDataSource() {
        try (ConfigurableApplicationContext context = start(JDBC)) {
            check(context.getBeanNamesForType(DataSource.class).length == 0);
            check(context.getBeanNamesForType(SqlExecutor.class).length == 0);
            check(context.getBeanNamesForType(PlatformTransactionManager.class).length == 0);
            check(context.getBeanNamesForType(SqlObserver.class).length == 1);
        }
    }

    private void ambiguousDataSources() {
        try (ConfigurableApplicationContext context = start(JDBC, TwoDataSources.class)) {
            check(context.getBeanNamesForType(DataSource.class).length == 2);
            check(context.getBeanNamesForType(SqlExecutor.class).length == 0);
            check(context.getBeanNamesForType(PlatformTransactionManager.class).length == 0);
            check(context.getBean(DataSource.class) == context.getBean("primaryDataSource"));
            // The alternate source is lazy. Candidate discovery must not instantiate it.
            check(!context.getBeanFactory().containsSingleton("alternateDataSource"));
            check(context.getBean("primaryDataSource", CountingDataSource.class).connections == 0);
        }
    }

    private void jdbcTransaction() throws SQLException {
        Map<String, Object> properties = new HashMap<>(JDBC);
        properties.put("udak.jdbc.max-rows", 1);
        properties.put("udak.jdbc.query-timeout-seconds", 30);
        try (ConfigurableApplicationContext context = start(properties, OneDataSource.class)) {
            SqlExecutor executor = context.getBean(SqlExecutor.class);
            CountingDataSource source = context.getBean(CountingDataSource.class);
            check(executor instanceof SpringJdbcExecutor);
            check(context.getBeanNamesForType(PlatformTransactionManager.class).length == 0);
            check(source.connections == 0);
            try (Connection setup = source.getConnection(); Statement statement = setup.createStatement()) {
                statement.executeUpdate("CREATE TABLE phase6_record (id INTEGER PRIMARY KEY)");
                check(rowCounts(executor).equals(List.of(0)));
                TransactionTemplate transaction = new TransactionTemplate(new DataSourceTransactionManager(source));
                transaction.executeWithoutResult(status -> {
                    check(executor.update(INSERT) == 1);
                    check(rowCounts(executor).equals(List.of(1)));
                    status.setRollbackOnly();
                });
                check(rowCounts(executor).equals(List.of(0)));
                check(source.connections == 4);
            }
        }
    }

    private List<Integer> rowCounts(SqlExecutor executor) {
        return executor.query(SELECT_COUNT, (row, index) -> row.getInt(1));
    }

    private void vendorRequired() {
        reject(Map.of("udak.jdbc.enabled", true), "Invalid UDAK setting: udak.jdbc.vendor",
                OneDataSource.class);
        reject(Map.of("udak.jdbc.enabled", true, "udak.jdbc.vendor", FIXTURE_VALUE),
                "Invalid UDAK setting: udak.jdbc.vendor", OneDataSource.class);
    }

    private void invalidLimits() {
        rejectSetting("udak.jdbc.max-rows", 0);
        rejectSetting("udak.jdbc.max-rows", 1001);
        rejectSetting("udak.jdbc.max-rows", FIXTURE_VALUE);
        rejectSetting("udak.jdbc.query-timeout-seconds", 0);
        rejectSetting("udak.jdbc.query-timeout-seconds", 31);
        rejectSetting("udak.jdbc.query-timeout-seconds", FIXTURE_VALUE);
    }

    private void unsafeSettings() {
        rejectSetting("udak.rewrite.enabled", true);
        rejectSetting("udak.legacy.rewrite.enabled", true);
        rejectSetting("udak.mode", FIXTURE_VALUE);
        rejectSetting("udak.legacy.default-mode", "rewrite");
        rejectSetting("udak.observability.log-parameters", true);
        rejectSetting("udak.observability.log-parameters", FIXTURE_VALUE);
        rejectSetting("udak.enabled", FIXTURE_VALUE);
        rejectSetting("udak.jdbc.enabled", FIXTURE_VALUE);
        reject(Map.of("udak.enabled", false, "udak.rewrite.enabled", true,
                "spring.main.lazy-initialization", true), "Invalid UDAK setting: udak.rewrite.enabled");
    }

    private void rejectSetting(String key, Object value) {
        reject(Map.of(key, value), "Invalid UDAK setting: " + key);
    }

    private void reject(Map<String, Object> properties, String expected, Class<?>... configuration) {
        try (ConfigurableApplicationContext context = start(properties, configuration)) {
            throw new AssertionError("Expected startup refusal");
        } catch (RuntimeException startupFailure) {
            boolean found = false;
            Throwable cause = startupFailure;
            for (int depth = 0; cause != null && depth < 24; depth++, cause = cause.getCause()) {
                String message = cause.getMessage();
                if (message != null && message.contains(FIXTURE_VALUE)) {
                    throw new AssertionError("Unsafe startup error");
                }
                if (expected.equals(message)) {
                    check(cause.getCause() == null && cause.getSuppressed().length == 0);
                    found = true;
                }
            }
            check(found);
        }
    }

    private ConfigurableApplicationContext start(Map<String, Object> properties, Class<?>... configuration) {
        SpringApplication application = new SpringApplication(App.class);
        application.addPrimarySources(List.of(configuration));
        application.setWebApplicationType(WebApplicationType.NONE);
        application.setBannerMode(Banner.Mode.OFF);
        application.setLogStartupInfo(false);
        application.setRegisterShutdownHook(false);

        StandardEnvironment environment = new StandardEnvironment();
        environment.getPropertySources().remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
        environment.getPropertySources().remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
        Map<String, Object> isolated = new HashMap<>(properties);
        isolated.put("logging.level.root", "OFF");
        isolated.put("spring.sql.init.mode", "never");
        isolated.put("spring.config.location", "optional:classpath:/udak-starter-fixture-no-config/");
        environment.getPropertySources().addFirst(new MapPropertySource("starterContract", isolated));
        application.setEnvironment(environment);
        return application.run();
    }

    private void scenario(String name, Check action) throws Exception {
        scenario = name;
        action.run();
        passed.add(name);
    }

    private void check(boolean predicate) {
        assertions++;
        if (!predicate) throw new AssertionError("Starter contract failed");
    }

    @FunctionalInterface
    private interface Check {
        void run() throws Exception;
    }

    @Configuration(proxyBeanMethods = false)
    @EnableAutoConfiguration(excludeName = {
            "org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration",
            "org.springframework.boot.autoconfigure.jdbc.DataSourceTransactionManagerAutoConfiguration",
            "org.springframework.boot.autoconfigure.jdbc.JdbcTemplateAutoConfiguration",
            "org.springframework.boot.jdbc.autoconfigure.DataSourceAutoConfiguration",
            "org.springframework.boot.jdbc.autoconfigure.DataSourceTransactionManagerAutoConfiguration",
            "org.springframework.boot.jdbc.autoconfigure.JdbcTemplateAutoConfiguration"
    })
    static class App { }

    @Configuration(proxyBeanMethods = false)
    static class OneDataSource {
        @Bean
        CountingDataSource singleDataSource() {
            return new CountingDataSource();
        }
    }

    @Configuration(proxyBeanMethods = false)
    static class LazyDataSource {
        @Bean
        @Lazy
        CountingDataSource lazyDataSource() {
            return new CountingDataSource();
        }
    }

    @Configuration(proxyBeanMethods = false)
    static class TwoDataSources {
        @Bean
        @Primary
        CountingDataSource primaryDataSource() {
            return new CountingDataSource();
        }

        @Bean
        @Lazy
        CountingDataSource alternateDataSource() {
            return new CountingDataSource();
        }
    }

    @Configuration(proxyBeanMethods = false)
    static class UserBeans {
        @Bean
        ObservationSink customSink() {
            return new CountingSink();
        }

        @Bean
        SqlObserver customObserver(ObservationSink sink) {
            return new SqlObserver(sink);
        }

        @Bean
        SqlExecutor customExecutor() {
            return new SqlExecutor() {
                @Override
                public <T> List<T> query(CompiledQuery query, RowMapper<T> mapper) {
                    throw new AssertionError("Unexpected query");
                }

                @Override
                public int update(CompiledQuery query) {
                    throw new AssertionError("Unexpected update");
                }
            };
        }
    }

    @Configuration(proxyBeanMethods = false)
    static class UserSink {
        @Bean
        CountingSink instance() {
            return new CountingSink();
        }
    }

    static final class CountingSink implements ObservationSink {
        private int events;

        @Override
        public void accept(SqlObservation event) {
            events++;
        }
    }

    static final class CountingDataSource extends DelegatingDataSource {
        private int connections;

        CountingDataSource() {
            super(newH2());
        }

        private static JdbcDataSource newH2() {
            JdbcDataSource source = new JdbcDataSource();
            source.setURL("jdbc:h2:mem:udak_starter_contract;MODE=PostgreSQL");
            return source;
        }

        @Override
        public Connection getConnection() throws SQLException {
            connections++;
            return super.getConnection();
        }

        @Override
        public Connection getConnection(String username, String password) throws SQLException {
            connections++;
            return super.getConnection(username, password);
        }
    }
}
