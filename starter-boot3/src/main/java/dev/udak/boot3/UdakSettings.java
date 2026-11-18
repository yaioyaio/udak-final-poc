package dev.udak.boot3;

import dev.udak.core.DbVendor;
import java.util.Locale;
import org.springframework.boot.context.properties.bind.Binder;
import org.springframework.core.env.Environment;

final class UdakSettings {
    private UdakSettings() { }

    static void validate(Environment environment) {
        requireObserve(environment, "udak.mode");
        requireObserve(environment, "udak.legacy.default-mode");
        requireFalse(environment, "udak.rewrite.enabled");
        requireFalse(environment, "udak.legacy.rewrite.enabled");
        requireFalse(environment, "udak.observability.log-parameters");
        maxRows(environment);
        queryTimeoutSeconds(environment);
        boolean enabled = enabled(environment);
        boolean jdbcEnabled = jdbcEnabled(environment);
        if ((enabled && jdbcEnabled)
                || property(environment, "udak.jdbc.vendor", null) != null) {
            vendor(environment);
        }
    }

    static boolean enabled(Environment environment) {
        return booleanProperty(environment, "udak.enabled", true);
    }

    static boolean jdbcEnabled(Environment environment) {
        return booleanProperty(environment, "udak.jdbc.enabled", false);
    }

    static DbVendor vendor(Environment environment) {
        String name = "udak.jdbc.vendor";
        String value = property(environment, name, "");
        try {
            return DbVendor.valueOf(value.toUpperCase(Locale.ROOT));
        } catch (IllegalArgumentException ignored) {
            throw invalid(name);
        }
    }

    static int maxRows(Environment environment) {
        return boundedInteger(environment, "udak.jdbc.max-rows", 1000, 1000);
    }

    static int queryTimeoutSeconds(Environment environment) {
        return boundedInteger(environment, "udak.jdbc.query-timeout-seconds", 5, 30);
    }

    private static String property(Environment environment, String name, String defaultValue) {
        try {
            return Binder.get(environment).bind(name, String.class).orElse(defaultValue);
        } catch (RuntimeException ignored) {
            throw invalid(name);
        }
    }

    private static boolean booleanProperty(Environment environment, String name, boolean defaultValue) {
        String value = property(environment, name, Boolean.toString(defaultValue));
        if ("true".equalsIgnoreCase(value)) return true;
        if ("false".equalsIgnoreCase(value)) return false;
        throw invalid(name);
    }

    private static int boundedInteger(Environment environment, String name, int defaultValue, int maximum) {
        int value;
        try {
            value = Integer.parseInt(property(environment, name, Integer.toString(defaultValue)));
        } catch (NumberFormatException ignored) {
            throw invalid(name);
        }
        if (value < 1 || value > maximum) throw invalid(name);
        return value;
    }

    private static void requireObserve(Environment environment, String name) {
        if (!"observe".equalsIgnoreCase(property(environment, name, "observe"))) throw invalid(name);
    }

    private static void requireFalse(Environment environment, String name) {
        if (booleanProperty(environment, name, false)) throw invalid(name);
    }

    private static IllegalStateException invalid(String name) {
        return new IllegalStateException("Invalid UDAK setting: " + name);
    }
}
