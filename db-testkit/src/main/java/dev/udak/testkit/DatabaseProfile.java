package dev.udak.testkit;

import dev.udak.core.DbVendor;
import java.util.Locale;
import java.util.Set;

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
    public String createFixtureSql(String table) {
        validateFixture(table);
        return "CREATE TABLE " + table + " (id " + integerType + " PRIMARY KEY, name " + textType + "(120))";
    }
    static void validateFixture(String table) {
        if (table == null || !table.matches("udak_p2_[0-9a-f]{12}"))
            throw new IllegalArgumentException("Invalid fixture identifier");
    }
}
