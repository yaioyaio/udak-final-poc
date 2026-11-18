package dev.udak.rewrite.jsqlparser;

import dev.udak.rewrite.Rewrite.Code;
import dev.udak.rewrite.Rewrite.Denied;
import dev.udak.rewrite.Rewrite.Dialect;
import dev.udak.rewrite.Rewrite.Environment;
import dev.udak.rewrite.Rewrite.Plan;
import dev.udak.rewrite.Rewrite.Role;
import dev.udak.rewrite.Rewrite.Template;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

public final class PaginationRewriteContractTest {
    private static final String TABLE = "udak_p5_entry";
    private static final Set<String> COLUMNS = Set.of("id", "name", "status");
    private static final String FROM = " FROM udak_p5_entry WHERE status = ? ORDER BY id ASC";
    private static final String PREFIX = "SELECT id, name" + FROM;
    private static final String LIMIT_OFFSET = " LIMIT ? OFFSET ?";
    private static final String OFFSET_FETCH = " OFFSET ? ROWS FETCH NEXT ? ROWS ONLY";
    private static final String SOURCE = PREFIX + LIMIT_OFFSET;
    private static final String DOUBLE_QUOTED_SELECT = "SELECT id AS \"id\", name AS \"name\"" + FROM;
    private static final PaginationRewriteProvider PROVIDER = new PaginationRewriteProvider(Set.of(TABLE), COLUMNS);
    private static int assertions;

    public static void main(String[] args) {
        check("jsqlparser-5.4-subset-1".equals(PROVIDER.version()), "provider-version");
        supportsTargets();
        enforcesAllowlist();
        rejectsUnsupportedShapes();
        deniesWithoutSqlDiagnostics();
        System.out.println("Rewrite Parser assertions: " + assertions);
    }

    private static void supportsTargets() {
        List<Role> limitOrder = List.of(Role.FILTER, Role.LIMIT, Role.OFFSET);
        List<Role> fetchOrder = List.of(Role.FILTER, Role.OFFSET, Role.LIMIT);
        checkPlan(Dialect.H2, DOUBLE_QUOTED_SELECT + LIMIT_OFFSET, limitOrder);
        checkPlan(Dialect.POSTGRESQL, DOUBLE_QUOTED_SELECT + LIMIT_OFFSET, limitOrder);
        checkPlan(Dialect.MYSQL, "SELECT id AS `id`, name AS `name`" + FROM + LIMIT_OFFSET, limitOrder);
        checkPlan(Dialect.SQLSERVER, "SELECT id AS [id], name AS [name]" + FROM + OFFSET_FETCH, fetchOrder);
        checkPlan(Dialect.ORACLE, DOUBLE_QUOTED_SELECT + OFFSET_FETCH, fetchOrder);
    }

    private static void checkPlan(Dialect target, String sql, List<Role> roles) {
        Plan plan = PROVIDER.translate(template(SOURCE, target));
        check(sql.equals(plan.sql()), "sql-" + target);
        check(roles.equals(plan.bindOrder()), "bind-order-" + target);
        check(List.of("id", "name").equals(plan.columns()), "labels-" + target);
        check(plan.sql().chars().filter(character -> character == '?').count() == 3, "placeholders-" + target);
        check(!plan.toString().contains(TABLE), "plan-redacted-" + target);
    }

    private static void enforcesAllowlist() {
        reject("table-allowlist", SOURCE.replace(TABLE, "unlisted_entry"));
        reject("projection-allowlist", SOURCE.replace("name", "unlisted_column"));
        reject("filter-allowlist", SOURCE.replace("status", "unlisted_column"));
        reject("sort-allowlist", SOURCE.replace("ORDER BY id", "ORDER BY unlisted_column"));

        Set<String> tables = new HashSet<>(Set.of("inventory"));
        Set<String> columns = new HashSet<>(Set.of("item_id", "title", "state"));
        PaginationRewriteProvider alternate = new PaginationRewriteProvider(tables, columns);
        tables.clear();
        columns.clear();
        String from = " FROM inventory WHERE state = ? ORDER BY item_id ASC";
        Plan plan = alternate.translate(template("SELECT item_id, title" + from + LIMIT_OFFSET, Dialect.ORACLE));
        String expected = "SELECT item_id AS \"item_id\", title AS \"title\"" + from + OFFSET_FETCH;
        check(expected.equals(plan.sql()), "allowlist-snapshot-sql");
        check(List.of("item_id", "title").equals(plan.columns()), "allowlist-snapshot-labels");
        reject("invalid-table-configuration", Code.INVALID_INPUT,
            () -> new PaginationRewriteProvider(Set.of("public.inventory"), COLUMNS));
        reject("invalid-column-configuration", Code.INVALID_INPUT,
            () -> new PaginationRewriteProvider(Set.of(TABLE), Set.of("i".repeat(64))));
        reject("null-configuration", Code.INVALID_INPUT, () -> new PaginationRewriteProvider(null, COLUMNS));
    }

    private static void rejectsUnsupportedShapes() {
        reject("second-statement", SOURCE + "; SELECT 1");
        reject("trailing-separator", SOURCE + ";");
        reject("trailing-whitespace", SOURCE + " ");
        reject("different-keyword-case", SOURCE.toLowerCase(Locale.ROOT));
        reject("select-hint", SOURCE.replace("SELECT", "SELECT /*+ INDEX(udak_p5_entry) */"));
        reject("from-comment", SOURCE.replace("FROM", "FROM /* comment */"));
        reject("trailing-comment", SOURCE + " -- comment");
        reject("distinct", SOURCE.replace("SELECT", "SELECT DISTINCT"));
        reject("explicit-all", SOURCE.replace("SELECT", "SELECT ALL"));
        reject("column-alias", SOURCE.replace("name", "name AS entry_name"));
        reject("quoted-column-alias", DOUBLE_QUOTED_SELECT + LIMIT_OFFSET);
        reject("table-alias", SOURCE.replace(TABLE, TABLE + " AS e"));
        reject("qualified-table", SOURCE.replace(TABLE, "public." + TABLE));
        reject("qualified-column", SOURCE.replace("name", TABLE + ".name"));
        reject("quoted-identifier", SOURCE.replace("name", "\"name\""));
        reject("duplicate-column", SOURCE.replace("name", "id"));
        reject("third-column", SOURCE.replace("name", "name, status"));
        reject("wildcard", SOURCE.replace("id, name", "*"));
        reject("function", SOURCE.replace("name", "upper(name)"));
        reject("pair-of-tables", SOURCE.replace(TABLE, TABLE + ", other_entry"));
        reject("join", SOURCE.replace(TABLE, TABLE + " JOIN other_entry ON true"));
        reject("subquery", SOURCE.replace(TABLE, "(SELECT id, name, status FROM " + TABLE + ")"));
        reject("cte", "WITH other_entry AS (SELECT 1) " + SOURCE);
        reject("union", "SELECT id, name FROM " + TABLE + " UNION ALL " + SOURCE);
        reject("lock", SOURCE + " FOR UPDATE");
        reject("group", SOURCE.replace("ORDER BY", "GROUP BY id, name ORDER BY"));
        reject("another-order-key", SOURCE.replace("ORDER BY id", "ORDER BY name"));
        reject("ordinal-order", SOURCE.replace("ORDER BY id", "ORDER BY 1"));
        reject("implicit-order-direction", SOURCE.replace(" ASC", ""));
        reject("descending-order", SOURCE.replace(" ASC", " DESC"));
        reject("extra-order-column", SOURCE.replace(" ASC", " ASC, name ASC"));
        reject("explicit-null-order", SOURCE.replace(" ASC", " ASC NULLS LAST"));
        reject("additional-condition", SOURCE.replace("status = ?", "status = ? OR status = ?"));
        reject("filter-operator", SOURCE.replace("status = ?", "status <> ?"));
        reject("reversed-condition", SOURCE.replace("status = ?", "? = status"));
        reject("literal-filter", SOURCE.replace("status = ?", "status = 'synthetic'"));
        reject("named-parameter", SOURCE.replace("status = ?", "status = :state"));
        reject("fixed-parameter-index", SOURCE.replace("status = ?", "status = ?1"));
        reject("literal-limit", SOURCE.replace("LIMIT ?", "LIMIT 1"));
        reject("literal-offset", SOURCE.replace("OFFSET ?", "OFFSET 0"));
        reject("missing-offset", SOURCE.replace(" OFFSET ?", ""));
        reject("limit-comma", PREFIX + " LIMIT ?, ?");
        reject("fetch-source", PREFIX + OFFSET_FETCH);
        for (Dialect source : List.of(Dialect.H2, Dialect.MYSQL, Dialect.SQLSERVER, Dialect.ORACLE)) {
            reject("source-dialect-" + source, Code.UNSUPPORTED,
                () -> PROVIDER.translate(new Template("pagination", SOURCE,
                    environment(source, Dialect.H2, PaginationRewriteProvider.VERSION))));
        }
        reject("wrong-provider-version", Code.INVALID_INPUT,
            () -> PROVIDER.translate(new Template("pagination", SOURCE,
                environment(Dialect.POSTGRESQL, Dialect.H2, "alternate-version"))));
        reject("null-template", Code.INVALID_INPUT, () -> PROVIDER.translate(null));
        reject("input-bound", Code.INVALID_INPUT,
            () -> PROVIDER.translate(template("x".repeat(16_385), Dialect.H2)));
    }

    private static void deniesWithoutSqlDiagnostics() {
        String sql = "SELECT synthetic_marker FROM";
        Template input = template(sql, Dialect.H2);
        check(!input.toString().contains("synthetic_marker"), "template-redacted");
        Denied denial = reject("parser-syntax", Code.UNSUPPORTED, () -> PROVIDER.translate(input));
        check(!denial.getMessage().contains("synthetic_marker"), "denial-message-redacted");
        check(!denial.toString().contains("synthetic_marker"), "denial-redacted");
    }

    private static Template template(String sql, Dialect target) {
        return new Template("pagination", sql, environment(Dialect.POSTGRESQL, target, PaginationRewriteProvider.VERSION));
    }

    private static Environment environment(Dialect source, Dialect target, String version) {
        return new Environment(source, target, "fixture-source", "fixture-target", "fixture-driver",
            "fixture-schema", version, "fixture-runtime");
    }

    private static void reject(String label, String sql) {
        reject(label, Code.UNSUPPORTED, () -> PROVIDER.translate(template(sql, Dialect.H2)));
    }

    private static Denied reject(String label, Code expected, Runnable operation) {
        try {
            operation.run();
        } catch (Denied denied) {
            check(denied.code() == expected, label + "-code");
            check(denied.getCause() == null && denied.getSuppressed().length == 0, label + "-failure-redacted");
            return denied;
        }
        throw new AssertionError(label + "-accepted");
    }

    private static void check(boolean condition, String label) {
        if (!condition) {
            throw new AssertionError(label);
        }
        assertions++;
    }
}
