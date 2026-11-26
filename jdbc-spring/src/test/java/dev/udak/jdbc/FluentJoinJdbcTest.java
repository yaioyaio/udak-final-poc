package dev.udak.jdbc;

import dev.udak.api.RowMapper;
import dev.udak.api.SelectClient;
import dev.udak.api.TableDefinition;
import dev.udak.core.DbVendor;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.List;
import java.util.Objects;
import org.h2.jdbcx.JdbcDataSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/** Executes fluent JOINs through SpringJdbcExecutor against a small in-memory H2 fixture. */
public final class FluentJoinJdbcTest {
    private static final DbVendor VENDOR = DbVendor.POSTGRESQL;
    private static final String DRAFT = "customer's draft?";
    private static final RowMapper<JoinedRow> ROW_MAPPER = (row, index) -> new JoinedRow(
        row.getInt("customerId"), row.getObject("orderId", Integer.class), row.getString("orderState"));
    private static int checks;

    public static void main(String[] args) throws SQLException {
        JdbcDataSource dataSource = new JdbcDataSource();
        dataSource.setURL("jdbc:h2:mem:udak_fluent_join");
        try (Connection anchor = dataSource.getConnection()) {
            checkQueries(dataSource);
        }
        System.out.println("Fluent JOIN Spring/H2 checks: " + checks);
    }

    private static void checkQueries(JdbcDataSource dataSource) {
        JdbcTemplate raw = new JdbcTemplate(dataSource);
        raw.execute("CREATE TABLE customers (id INT PRIMARY KEY, tenant INT NOT NULL, name VARCHAR(80) NOT NULL)");
        raw.execute("CREATE TABLE orders (id INT PRIMARY KEY, customer_id INT NOT NULL, tenant INT NOT NULL,"
            + " state VARCHAR(80) NOT NULL)");
        raw.update("INSERT INTO customers (id, tenant, name) VALUES (1, 8, 'A'), (2, 8, 'B'), (3, 9, 'C')");
        raw.update("INSERT INTO orders (id, customer_id, tenant, state)"
            + " VALUES (102, 1, 8, 'complete'), (101, 1, 8, ?), (201, 2, 8, 'complete'), (301, 3, 8, 'other tenant')",
            DRAFT);

        var db = new SelectClient(VENDOR, new SpringJdbcExecutor(dataSource, VENDOR, 3, 20), List.of(
            new TableDefinition("customers", List.of("id", "tenant", "name"), "id"),
            new TableDefinition("orders", List.of("id", "customer_id", "tenant", "state"), "id")
        ));
        var customer = db.table("customers", "c");
        var order = db.table("orders", "o");
        var customerId = customer.column("id");
        var orderId = order.column("id");
        var state = order.column("state");
        var onCustomer = customerId.equalTo(order.column("customer_id"));
        var onTenant = customer.column("tenant").equalTo(order.column("tenant"));
        SelectClient.Column[] projections = {customerId.as("customerId"), orderId.as("orderId"), state.as("orderState")};

        JoinedRow first = new JoinedRow(1, 101, DRAFT);
        JoinedRow second = new JoinedRow(1, 102, "complete");
        JoinedRow third = new JoinedRow(2, 201, "complete");
        JoinedRow unmatched = new JoinedRow(3, null, null);
        List<JoinedRow> expectedInner = List.of(first, second, third);
        List<JoinedRow> expectedLeft = List.of(first, second, third, unmatched);

        var inner = db.select(projections).from(customer).innerJoin(order, onCustomer, onTenant)
            .orderBy(customerId, false).orderBy(orderId, false);
        var left = db.select(projections).from(customer).leftJoin(order, onCustomer, onTenant)
            .orderBy(customerId, false).orderBy(orderId, false);
        equal("INNER JOIN matches both ON columns", expectedInner, inner.fetch(ROW_MAPPER));
        equal("LEFT JOIN preserves unmatched customers with SQL NULLs", expectedLeft,
            left.fetch(ROW_MAPPER));
        equal("WHERE IS NULL selects the unmatched customer", List.of(unmatched),
            left.whereIsNull(orderId).fetch(ROW_MAPPER));
        equal("WHERE equality binds punctuation literally", List.of(first),
            db.select(projections).from(customer).innerJoin(order, onCustomer, onTenant)
                .whereEqual(state, DRAFT).fetch(ROW_MAPPER));

        var paged = db.select(projections).from(customer).leftJoin(order, onCustomer, onTenant)
            .orderBy(customerId, false);
        equal("first page starts with the smaller order ID", List.of(first), paged.page(1, 0).fetch(ROW_MAPPER));
        equal("second page continues within the same customer", List.of(second), paged.page(1, 1).fetch(ROW_MAPPER));
        equal("tail page includes the unmatched customer", List.of(third, unmatched), paged.page(2, 2).fetch(ROW_MAPPER));
        equal("page after all matches is empty", List.of(), paged.page(2, 4).fetch(ROW_MAPPER));

        var transactions = new TransactionTemplate(new DataSourceTransactionManager(dataSource));
        transactions.executeWithoutResult(status -> {
            raw.update("INSERT INTO orders (id, customer_id, tenant, state) VALUES (?, ?, ?, ?)",
                202, 2, 8, "temporary");
            equal("fluent query sees writes in the same Spring transaction",
                List.of(first, second, third, new JoinedRow(2, 202, "temporary")), inner.fetch(ROW_MAPPER));
            status.setRollbackOnly();
        });
        equal("fluent query observes the rolled back fixture", expectedInner, inner.fetch(ROW_MAPPER));
    }

    private static void equal(String label, Object expected, Object actual) {
        checks++;
        if (!Objects.equals(expected, actual)) {
            throw new AssertionError(label + ": expected " + expected + ", got " + actual);
        }
    }

    private record JoinedRow(int customerId, Integer orderId, String orderState) { }
}
