package dev.udak.testkit;

import dev.udak.core.DbVendor;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Real product identity and candidate driver; none is a declaration of support. */
public enum DatabaseProfile {
    POSTGRESQL(DbVendor.POSTGRESQL, "org.postgresql.Driver", Set.of("postgresql"), "INTEGER", "VARCHAR"),
    MYSQL(DbVendor.MYSQL, "com.mysql.cj.jdbc.Driver", Set.of("mysql"), "INTEGER", "VARCHAR"),
    SQLSERVER(DbVendor.SQLSERVER, "com.microsoft.sqlserver.jdbc.SQLServerDriver", Set.of("microsoft sql server"), "INTEGER", "VARCHAR"),
    ORACLE(DbVendor.ORACLE_19, "oracle.jdbc.OracleDriver", Set.of("oracle"), "NUMBER", "VARCHAR2");

    private final DbVendor vendor;
    private final String driver;
    private final Set<String> products;
    private final String integerType, textType;
    DatabaseProfile(DbVendor vendor, String driver, Set<String> products, String integerType, String textType) {
        this.vendor = vendor; this.driver = driver; this.products = products;
        this.integerType = integerType; this.textType = textType;
    }
    public DbVendor vendor() { return vendor; }
    public String driverClass() { return driver; }
    public boolean matchesProduct(String product) {
        return product != null && products.contains(product.toLowerCase(Locale.ROOT));
    }
    boolean matchesDriver(String name) {
        if (name == null) return false;
        String normalized = name.toLowerCase(Locale.ROOT);
        switch (this) {
            case POSTGRESQL: return normalized.equals("postgresql jdbc driver");
            case MYSQL: return normalized.equals("mysql connector/j");
            case SQLSERVER: return normalized.matches("microsoft jdbc driver(?: [0-9]+\\.[0-9]+)? for sql server");
            case ORACLE: return normalized.equals("oracle jdbc driver");
            default: return false;
        }
    }
    /** Extract only the numeric component from a profile-specific metadata format. */
    String numericDriverVersion(String raw) {
        if (raw == null || raw.length() > 256) return null;
        String numeric = "([0-9]+(?:\\.[0-9]+){1,5})";
        String expression;
        switch (this) {
            case MYSQL: expression = "mysql-connector-j-" + numeric + " \\(Revision: [A-Za-z0-9._-]{1,128}\\)"; break;
            case SQLSERVER: expression = "([0-9]+(?:\\.[0-9]+){3})"; break;
            case POSTGRESQL: case ORACLE: expression = numeric; break;
            default: return null;
        }
        Matcher match = Pattern.compile(expression).matcher(raw);
        return match.matches() ? match.group(1) : null;
    }
    public String createFixtureSql(String table) {
        validateFixture(table);
        return "CREATE TABLE " + table + " (id " + integerType + " PRIMARY KEY, name " + textType + "(120))";
    }
    static void validateFixture(String table) {
        if (table == null || !table.matches("udak_p2_[0-9a-f]{12}"))
            throw new IllegalArgumentException("Invalid fixture identifier");
    }
}
