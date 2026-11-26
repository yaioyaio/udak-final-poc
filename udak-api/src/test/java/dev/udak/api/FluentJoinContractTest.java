package dev.udak.api;

import dev.udak.core.Bind;
import dev.udak.core.CompiledQuery;
import dev.udak.core.DbVendor;
import java.sql.SQLException;
import java.util.List;
import java.util.Objects;

/** Standalone contract checks for the fluent SELECT compiler and executor boundary. */
public final class FluentJoinContractTest {
    private static final List<TableDefinition> TABLES = List.of(
        new TableDefinition("customers", List.of("id", "tenant", "name", "manager_id"), "id"),
        new TableDefinition("orders", List.of("id", "customer_id", "tenant", "state"), "id"),
        new TableDefinition("shipments", List.of("id", "order_id", "tracking"), "id")
    );
    private static final String FILTER_VALUE = "customer's draft?";
    private static int checks;

    public static void main(String[] args) {
        for (DbVendor vendor : DbVendor.values()) {
            checkRendering(vendor);
        }
        checkReferencesAndPagination();
        System.out.println("Fluent JOIN contract checks: " + checks);
    }

    private static void checkRendering(DbVendor vendor) {
        Capture capture = new Capture();
        var db = new SelectClient(vendor, capture, TABLES);
        var customer = db.table("customers", "c");
        var order = db.table("orders", "o");
        var shipment = db.table("shipments", "s");
        var query = db.select(customer.column("id").as("customerId"), order.column("id").as("orderId"),
                shipment.column("tracking"))
            .from(customer)
            .innerJoin(order, customer.column("id").equalTo(order.column("customer_id")),
                customer.column("tenant").equalTo(order.column("tenant")))
            .leftJoin(shipment, order.column("id").equalTo(shipment.column("order_id")))
            .whereEqual(order.column("state"), FILTER_VALUE)
            .whereIsNull(shipment.column("tracking"))
            .whereEqual(customer.column("tenant"), 9)
            .orderBy(order.column("id"), true)
            .page(4, 3);
        CompiledQuery compiled = query.compile();

        String c = quote(vendor, "c");
        String o = quote(vendor, "o");
        String s = quote(vendor, "s");
        String customerId = quote(vendor, "customerId");
        String orderId = quote(vendor, "orderId");
        String tracking = quote(vendor, "tracking");
        String base = "SELECT " + c + ".id AS " + customerId + ", " + o + ".id AS " + orderId + ", "
            + s + ".tracking AS " + tracking + " FROM customers " + c
            + " INNER JOIN orders " + o + " ON " + c + ".id = " + o + ".customer_id AND "
            + c + ".tenant = " + o + ".tenant LEFT JOIN shipments " + s
            + " ON " + o + ".id = " + s + ".order_id WHERE " + o + ".state = ? AND "
            + s + ".tracking IS NULL AND " + c + ".tenant = ? ORDER BY " + o + ".id DESC, "
            + c + ".id ASC, " + s + ".id ASC";

        Bind stateFilter = new Bind("filter", FILTER_VALUE);
        Bind tenantFilter = new Bind("filter", 9);
        switch (vendor) {
            case POSTGRESQL, MYSQL -> {
                equal(vendor + " SQL", base + " LIMIT ? OFFSET ?", compiled.sql());
                equal(vendor + " binds", List.of(stateFilter, tenantFilter,
                    new Bind("limit", 4), new Bind("offset", 3L)), compiled.binds());
            }
            case SQLSERVER, ORACLE_19 -> {
                equal(vendor + " SQL", base + " OFFSET ? ROWS FETCH NEXT ? ROWS ONLY", compiled.sql());
                equal(vendor + " binds", List.of(stateFilter, tenantFilter,
                    new Bind("offset", 3L), new Bind("limit", 4)), compiled.binds());
            }
            case ORACLE_11 -> {
                String rowNumber = quote(vendor, "udak_rn");
                String prefix = "SELECT udak_page." + customerId + ", udak_page." + orderId
                    + ", udak_page." + tracking + " FROM (SELECT udak_inner.*, ROWNUM AS " + rowNumber;
                String suffix = "FROM (" + base + ") udak_inner WHERE ROWNUM <= ?) udak_page"
                    + " WHERE udak_page." + rowNumber + " > ? ORDER BY udak_page." + rowNumber + " ASC";
                equal(vendor + " SQL", prefix + " " + suffix, compiled.sql());
                equal(vendor + " binds", List.of(stateFilter, tenantFilter,
                    new Bind("upperBound", 7L), new Bind("offset", 3L)), compiled.binds());
            }
        }
        equal("compiled vendor", vendor, compiled.vendor());
        equal("fetch returns executor result", List.of("mapped"), query.fetch((row, index) -> "mapped"));
        equal("fetch passes compiled query to executor", compiled, capture.last);
    }

    private static void checkReferencesAndPagination() {
        var db = new SelectClient(DbVendor.POSTGRESQL, new Capture(), TABLES);
        var customer = db.table("customers", "c");
        var manager = db.table("customers", "m");
        var order = db.table("orders", "o");
        var shipment = db.table("shipments", "s");
        var id = customer.column("id");
        var orderId = order.column("id");
        var orderCustomerId = order.column("customer_id");
        var on = id.equalTo(orderCustomerId);

        var selfJoin = db.select(id.as("customerId"), manager.column("id").as("managerId"))
            .from(customer)
            .leftJoin(manager, manager.column("id").equalTo(customer.column("manager_id")))
            .compile();
        equal("self join uses distinct scopes",
            "SELECT \"c\".id AS \"customerId\", \"m\".id AS \"managerId\" FROM customers \"c\""
                + " LEFT JOIN customers \"m\" ON \"m\".id = \"c\".manager_id", selfJoin.sql());
        equal("unpaged query has no binds", List.of(), selfJoin.binds());

        rejects("unregistered table", () -> db.table("missing", "x"));
        rejects("column known only on another table", () -> customer.column("state"));
        rejects("malformed physical column", () -> customer.column("c.id"));
        rejects("malformed table alias", () -> db.table("customers", "c x"));
        rejects("malformed projection label", () -> id.as("id.x"));
        rejects("empty projection", () -> db.select().from(customer).compile());
        rejects("duplicate default labels", () -> db.select(id, orderId).from(customer).innerJoin(order, on).compile());
        rejects("duplicate case-folded labels", () -> db.select(id.as("Label"), orderId.as("label"))
            .from(customer).innerJoin(order, on).compile());
        rejects("duplicate case-folded aliases", () -> {
            var collision = db.table("orders", "C");
            db.select(id).from(customer).innerJoin(collision, id.equalTo(collision.column("customer_id"))).compile();
        });
        rejects("projection from an unjoined table", () -> db.select(orderId).from(customer).compile());
        rejects("filter from an unjoined table", () -> db.select(id).from(customer).whereEqual(orderId, 2).compile());
        rejects("sort from an unjoined table", () -> db.select(id).from(customer).orderBy(orderId, false).compile());
        var foreignDb = new SelectClient(DbVendor.POSTGRESQL, new Capture(), TABLES);
        rejects("reference issued by another client", () -> db.select(foreignDb.table("customers", "c").column("id"))
            .from(customer).compile());
        rejects("join without ON", () -> db.select(id).from(customer).innerJoin(order).compile());
        rejects("ON referring only to the joined table", () -> db.select(id).from(customer)
            .innerJoin(order, orderId.equalTo(orderCustomerId)).compile());
        rejects("ON referring only to the existing table", () -> db.select(id).from(customer)
            .innerJoin(order, id.equalTo(customer.column("tenant"))).compile());
        rejects("second ON condition refers to an unjoined table", () -> db.select(id).from(customer)
            .innerJoin(order, on, orderId.equalTo(shipment.column("order_id"))).compile());
        rejects("null equality requires whereIsNull", () -> db.select(id).from(customer).whereEqual(id, null).compile());
        rejects("page without explicit sort", () -> db.select(id).from(customer).page(1, 0).compile());
        rejects("zero limit", () -> db.select(id).from(customer).orderBy(id, false).page(0, 0).compile());
        rejects("limit over bound", () -> db.select(id).from(customer).orderBy(id, false).page(1001, 0).compile());
        rejects("negative offset", () -> db.select(id).from(customer).orderBy(id, false).page(1, -1).compile());

        var oracle = new SelectClient(DbVendor.ORACLE_11, new Capture(), TABLES);
        var oracleCustomer = oracle.table("customers", "c");
        var oracleId = oracleCustomer.column("id");
        rejects("Oracle 11 row number label is reserved", () -> oracleId.as("UDAK_RN"));
        equal("Oracle 11 upper bound at the long limit", List.of(new Bind("upperBound", Long.MAX_VALUE),
            new Bind("offset", Long.MAX_VALUE - 1)), oracle.select(oracleId).from(oracleCustomer)
            .orderBy(oracleId, false).page(1, Long.MAX_VALUE - 1).compile().binds());
        rejects("Oracle 11 upper bound overflow", () -> oracle.select(oracleId).from(oracleCustomer)
            .orderBy(oracleId, false).page(1, Long.MAX_VALUE).compile());
    }

    private static String quote(DbVendor vendor, String name) {
        return switch (vendor) {
            case MYSQL -> "`" + name + "`";
            case SQLSERVER -> "[" + name + "]";
            default -> "\"" + name + "\"";
        };
    }

    private static void equal(String label, Object expected, Object actual) {
        checks++;
        if (!Objects.equals(expected, actual)) {
            throw new AssertionError(label + ": expected " + expected + ", got " + actual);
        }
    }

    private static void rejects(String label, Runnable action) {
        checks++;
        try {
            action.run();
        } catch (IllegalArgumentException | IllegalStateException | ArithmeticException expected) {
            return;
        }
        throw new AssertionError("Expected rejection for " + label);
    }

    private static final class Capture implements SqlExecutor {
        private CompiledQuery last;

        @Override
        public <T> List<T> query(CompiledQuery query, RowMapper<T> mapper) {
            last = query;
            try {
                return List.of(mapper.map(null, 0));
            } catch (SQLException e) {
                throw new AssertionError(e);
            }
        }

        @Override
        public int update(CompiledQuery query) {
            throw new AssertionError("A SELECT must not invoke update");
        }
    }
}
