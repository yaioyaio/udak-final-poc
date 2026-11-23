package dev.udak.pilot;

import dev.udak.inventory.InventoryCapture;
import dev.udak.observe.ObservationSink;
import dev.udak.observe.SqlObservation;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.UnavailableReason;
import dev.udak.observe.hibernate.HibernateObserveInspector;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.atomic.AtomicInteger;
import org.hibernate.resource.jdbc.spi.StatementInspector;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.orm.jpa.LocalContainerEntityManagerFactoryBean;
import org.springframework.test.context.ContextConfigurationAttributes;
import org.springframework.test.context.ContextCustomizer;
import org.springframework.test.context.ContextCustomizerFactory;
import org.springframework.test.context.MergedContextConfiguration;
import org.springframework.test.context.TestContext;
import org.springframework.test.context.support.AbstractTestExecutionListener;

/** Adds metadata-only Hibernate observation to the two pinned DAO pilot tests. */
public final class ThingsBoardObserve {
    private static final String TEST_CLASS = "org.thingsboard.server.dao.service.DeviceServiceTest";
    private static final String INSPECTOR = "hibernate.session_factory.statement_inspector";
    private static final String REVISION = "ebbfc6789b81a4e04cae2711208130fb2841b31f";
    private static final String PROFILE = "8cb56304849d88c66145d48c1c689a11da10a40f5bbb45b5f07ac7ddb6b4d821";
    private static final String LOOKUP = "testFindDeviceById";
    private static final String ROLLBACK = "testShouldRollbackValidatedDeviceIfDeviceCredentialsValidationFailed";
    private static final AtomicInteger BINDINGS = new AtomicInteger();
    private static final ThreadLocal<MethodCapture> ACTIVE_METHOD = new ThreadLocal<>();
    private static final Map<String, String> FINISHED = new TreeMap<>();

    private ThingsBoardObserve() {}

    private static boolean enabled() {
        return switch (System.getProperty("udak.thingsboard.observe", "off")) {
            case "off" -> false;
            case "on" -> true;
            default -> throw new IllegalArgumentException("Unknown ThingsBoard pilot mode");
        };
    }

    public static final class Factory implements ContextCustomizerFactory {
        @Override
        public ContextCustomizer createContextCustomizer(Class<?> testClass,
                List<ContextConfigurationAttributes> ignored) {
            return TEST_CLASS.equals(testClass.getName()) && enabled() ? Installer.INSTANCE : null;
        }
    }

    private enum Installer implements ContextCustomizer {
        INSTANCE;

        @Override
        public void customizeContext(ConfigurableApplicationContext context,
                MergedContextConfiguration ignored) {
            context.getBeanFactory().addBeanPostProcessor(new BeanPostProcessor() {
                @Override
                public Object postProcessBeforeInitialization(Object bean, String name) {
                    if ("entityManagerFactory".equals(name)
                            && bean instanceof LocalContainerEntityManagerFactoryBean factory) {
                        var properties = factory.getJpaPropertyMap();
                        var previous = properties.get(INSPECTOR);
                        var observer = new SqlObserver(new ScopedSink());
                        if (previous == null) {
                            properties.put(INSPECTOR, new HibernateObserveInspector(observer));
                        } else if (previous instanceof StatementInspector inspector) {
                            properties.put(INSPECTOR, HibernateObserveInspector.compose(inspector, observer));
                        } else {
                            throw new IllegalStateException("Unsupported existing pilot inspector configuration");
                        }
                        BINDINGS.incrementAndGet();
                    }
                    return bean;
                }
            });
        }
    }

    private static final class ScopedSink implements ObservationSink {
        @Override
        public void accept(SqlObservation observation) {
            var method = ACTIVE_METHOD.get();
            if (method != null) method.inventory().accept(observation);
        }

        @Override
        public void accept(SqlObservation observation, UnavailableReason reason) {
            var method = ACTIVE_METHOD.get();
            if (method != null) method.inventory().accept(observation, reason);
        }
    }

    private record MethodCapture(String name, InventoryCapture inventory) {}

    public static final class Listener extends AbstractTestExecutionListener {
        @Override
        public void beforeTestExecution(TestContext context) {
            if (!TEST_CLASS.equals(context.getTestClass().getName())) return;
            String name = context.getTestMethod().getName();
            if (LOOKUP.equals(name) || ROLLBACK.equals(name)) {
                ACTIVE_METHOD.set(new MethodCapture(name, new InventoryCapture()));
            }
        }

        @Override
        public void afterTestExecution(TestContext context) {
            if (!TEST_CLASS.equals(context.getTestClass().getName())) return;
            var method = ACTIVE_METHOD.get();
            ACTIVE_METHOD.remove();
            if (method != null) {
                FINISHED.put(method.name(), method.inventory().snapshotJson(REVISION, PROFILE));
            }
        }

        @Override
        public void afterTestClass(TestContext context) throws Exception {
            if (!TEST_CLASS.equals(context.getTestClass().getName())) return;
            if (!FINISHED.keySet().equals(java.util.Set.of(LOOKUP, ROLLBACK))) {
                throw new IllegalStateException("Both ThingsBoard pilot methods are required");
            }
            var report = new StringBuilder("{\"enabled\":").append(enabled())
                    .append(",\"inspector_bindings\":").append(BINDINGS.get()).append(",\"methods\":{");
            for (var entry : FINISHED.entrySet()) {
                report.append('"').append(entry.getKey()).append("\":").append(entry.getValue()).append(',');
            }
            report.setLength(report.length() - 1);
            report.append("}}\n");
            var output = Path.of(System.getProperty("udak.thingsboard.observations"));
            Files.writeString(output, report, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
            FINISHED.clear();
        }
    }
}
