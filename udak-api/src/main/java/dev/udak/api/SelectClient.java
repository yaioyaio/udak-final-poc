package dev.udak.api;

import dev.udak.core.Bind;
import dev.udak.core.CompiledQuery;
import dev.udak.core.DbVendor;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.regex.Pattern;

/** Builds SELECT queries against an application-configured table allowlist. */
public final class SelectClient {
    private static final String ROW_NUMBER = "udak_rn";
    // 30 ASCII bytes also fit Oracle 11g's identifier limit.
    private static final Pattern ALIAS = Pattern.compile("[A-Za-z_][A-Za-z_0-9]{0,29}");

    private final DbVendor vendor;
    private final SqlExecutor executor;
    private final Map<String, TableDefinition> tables;

    public SelectClient(DbVendor vendor, SqlExecutor executor, List<TableDefinition> tables) {
        this.vendor = Objects.requireNonNull(vendor, "vendor");
        this.executor = Objects.requireNonNull(executor, "executor");
        Map<String, TableDefinition> registered = new LinkedHashMap<>();
        for (TableDefinition table : List.copyOf(tables)) {
            if (registered.putIfAbsent(table.table(), table) != null) {
                throw new IllegalArgumentException("Duplicate table definition");
            }
        }
        this.tables = Map.copyOf(registered);
    }

    /** Creates a table reference to reuse wherever its alias is in scope. */
    public TableRef table(String name, String alias) {
        TableDefinition table = tables.get(Objects.requireNonNull(name, "table name"));
        if (table == null) {
            throw new IllegalArgumentException("Table is not registered");
        }
        return new TableRef(this, table, requireAlias(alias));
    }

    public SelectBuilder select(Column... columns) {
        return new SelectBuilder(List.of(columns));
    }

    public static final class TableRef {
        private final SelectClient owner;
        private final TableDefinition definition;
        private final String alias;

        private TableRef(SelectClient owner, TableDefinition definition, String alias) {
            this.owner = owner;
            this.definition = definition;
            this.alias = alias;
        }

        public Column column(String name) {
            if (!definition.columns().contains(name)) {
                throw new IllegalArgumentException("Column is not registered for this table");
            }
            return new Column(this, name, name);
        }
    }

    public static final class Column {
        private final TableRef table;
        private final String name;
        private final String label;

        private Column(TableRef table, String name, String label) {
            this.table = table;
            this.name = name;
            this.label = label;
        }

        public Column as(String label) {
            return new Column(table, name, requireLabel(label));
        }

        public On equalTo(Column other) {
            return new On(this, Objects.requireNonNull(other, "column"));
        }
    }

    public static final class On {
        private final Column left;
        private final Column right;

        private On(Column left, Column right) {
            this.left = left;
            this.right = right;
        }
    }

    /** A mutable builder for one SELECT. Compile and fetch do not change it. */
    public final class SelectBuilder {
        private final List<Column> projections;
        private final Map<String, TableRef> scope = new LinkedHashMap<>();
        private final List<Join> joins = new ArrayList<>();
        private final List<Filter> filters = new ArrayList<>();
        private final List<Sort> sorts = new ArrayList<>();
        private final Set<ColumnKey> sortedColumns = new HashSet<>();
        private TableRef from;
        private Page page;

        private SelectBuilder(List<Column> projections) {
            if (projections.isEmpty()) {
                throw new IllegalArgumentException("At least one selected column is required");
            }
            Set<String> labels = new HashSet<>();
            for (Column column : projections) {
                if (!labels.add(fold(requireLabel(column.label)))) {
                    throw new IllegalArgumentException("Duplicate result label");
                }
            }
            this.projections = projections;
        }

        public SelectBuilder from(TableRef table) {
            if (from != null) {
                throw new IllegalArgumentException("FROM is already specified");
            }
            String alias = newAlias(table);
            scope.put(alias, table);
            from = table;
            return this;
        }

        public SelectBuilder innerJoin(TableRef table, On... conditions) {
            return join(JoinType.INNER, table, List.of(conditions));
        }

        public SelectBuilder leftJoin(TableRef table, On... conditions) {
            return join(JoinType.LEFT, table, List.of(conditions));
        }

        private SelectBuilder join(JoinType type, TableRef table, List<On> conditions) {
            requireFrom();
            String alias = newAlias(table);
            if (conditions.isEmpty()) {
                throw new IllegalArgumentException("JOIN requires an ON condition");
            }
            for (On condition : conditions) {
                boolean leftIsNew = condition.left.table == table;
                boolean rightIsNew = condition.right.table == table;
                if (leftIsNew == rightIsNew) {
                    throw new IllegalArgumentException("ON must compare the joined table to an in-scope table");
                }
                requireScope(leftIsNew ? condition.right : condition.left);
            }
            scope.put(alias, table);
            joins.add(new Join(type, table, conditions));
            return this;
        }

        public SelectBuilder whereEqual(Column column, Object value) {
            requireScope(column);
            if (value == null) {
                throw new IllegalArgumentException("Use whereIsNull for null values");
            }
            filters.add(new Filter(column, new Bind("filter", value)));
            return this;
        }

        public SelectBuilder whereIsNull(Column column) {
            requireScope(column);
            filters.add(new Filter(column, null));
            return this;
        }

        public SelectBuilder orderBy(Column column, boolean descending) {
            requireScope(column);
            if (!sortedColumns.add(new ColumnKey(column.table, column.name))) {
                throw new IllegalArgumentException("Duplicate ORDER BY column");
            }
            sorts.add(new Sort(column, descending));
            return this;
        }

        public SelectBuilder page(int limit, long offset) {
            if (limit < 1 || limit > 1000 || offset < 0
                    || (vendor == DbVendor.ORACLE_11 && offset > Long.MAX_VALUE - limit)) {
                throw new IllegalArgumentException("Invalid pagination");
            }
            page = new Page(limit, offset);
            return this;
        }

        public CompiledQuery compile() {
            requireFrom();
            for (Column column : projections) {
                requireScope(column);
            }
            if (page != null && sorts.isEmpty()) {
                throw new IllegalArgumentException("Pagination requires ORDER BY");
            }
            String projectionSql = String.join(", ", projections.stream()
                    .map(column -> qualified(column) + " AS " + quoted(column.label)).toList());
            StringBuilder sql = new StringBuilder("SELECT ").append(projectionSql)
                    .append(" FROM ").append(relation(from));
            for (Join join : joins) {
                List<String> conditions = join.conditions.stream()
                        .map(on -> qualified(on.left) + " = " + qualified(on.right)).toList();
                sql.append(join.type.sql).append(relation(join.table))
                        .append(" ON ").append(String.join(" AND ", conditions));
            }
            List<Bind> binds = new ArrayList<>();
            appendFilters(sql, binds);
            appendOrder(sql);
            String rendered = page == null ? sql.toString() : renderPage(sql, binds);
            return new CompiledQuery(rendered, binds, vendor);
        }

        public <T> List<T> fetch(RowMapper<T> mapper) {
            Objects.requireNonNull(mapper, "mapper");
            return List.copyOf(executor.query(compile(), mapper));
        }

        private String newAlias(TableRef table) {
            Objects.requireNonNull(table, "table reference");
            if (table.owner != SelectClient.this) {
                throw new IllegalArgumentException("Table reference belongs to a different client");
            }
            String alias = fold(table.alias);
            if (scope.containsKey(alias)) {
                throw new IllegalArgumentException("Duplicate table alias");
            }
            return alias;
        }

        private void requireScope(Column column) {
            Objects.requireNonNull(column, "column");
            if (scope.get(fold(column.table.alias)) != column.table) {
                throw new IllegalArgumentException("Column's table is outside query scope");
            }
        }

        private void requireFrom() {
            if (from == null) {
                throw new IllegalArgumentException("FROM is required");
            }
        }

        private void appendFilters(StringBuilder sql, List<Bind> binds) {
            List<String> conditions = new ArrayList<>();
            for (Filter filter : filters) {
                if (filter.bind == null) {
                    conditions.add(qualified(filter.column) + " IS NULL");
                } else {
                    conditions.add(qualified(filter.column) + " = ?");
                    binds.add(filter.bind);
                }
            }
            if (!conditions.isEmpty()) {
                sql.append(" WHERE ").append(String.join(" AND ", conditions));
            }
        }

        private void appendOrder(StringBuilder sql) {
            if (sorts.isEmpty()) {
                return;
            }
            List<String> order = new ArrayList<>();
            for (Sort sort : sorts) {
                order.add(qualified(sort.column) + (sort.descending ? " DESC" : " ASC"));
            }
            if (page != null) {
                for (TableRef table : scope.values()) {
                    String id = table.definition.idColumn();
                    if (!sortedColumns.contains(new ColumnKey(table, id))) {
                        order.add(qualified(table.column(id)) + " ASC");
                    }
                }
            }
            sql.append(" ORDER BY ").append(String.join(", ", order));
        }

        private String renderPage(StringBuilder sql, List<Bind> binds) {
            Bind limit = new Bind("limit", page.limit);
            Bind offset = new Bind("offset", page.offset);
            return switch (vendor) {
                case POSTGRESQL, MYSQL -> {
                    binds.add(limit);
                    binds.add(offset);
                    yield sql.append(" LIMIT ? OFFSET ?").toString();
                }
                case SQLSERVER, ORACLE_19 -> {
                    binds.add(offset);
                    binds.add(limit);
                    yield sql.append(" OFFSET ? ROWS FETCH NEXT ? ROWS ONLY").toString();
                }
                case ORACLE_11 -> {
                    binds.add(new Bind("upperBound", page.offset + page.limit));
                    binds.add(offset);
                    String labels = String.join(", ", projections.stream()
                            .map(column -> "udak_page." + quoted(column.label)).toList());
                    String rowNumber = "udak_page." + quoted(ROW_NUMBER);
                    yield "SELECT " + labels + " FROM (SELECT udak_inner.*, ROWNUM AS " + quoted(ROW_NUMBER)
                            + " FROM (" + sql + ") udak_inner WHERE ROWNUM <= ?) udak_page WHERE "
                            + rowNumber + " > ? ORDER BY " + rowNumber + " ASC";
                }
            };
        }
    }

    private String relation(TableRef table) {
        return table.definition.table() + " " + quoted(table.alias);
    }

    private String qualified(Column column) {
        return quoted(column.table.alias) + "." + column.name;
    }

    private String quoted(String alias) {
        return switch (vendor) {
            case MYSQL -> "`" + alias + "`";
            case SQLSERVER -> "[" + alias + "]";
            case POSTGRESQL, ORACLE_19, ORACLE_11 -> "\"" + alias + "\"";
        };
    }

    private static String requireAlias(String alias) {
        if (alias == null || !ALIAS.matcher(alias).matches()) {
            throw new IllegalArgumentException("Invalid alias or result label");
        }
        return alias;
    }

    private static String requireLabel(String label) {
        if (ROW_NUMBER.equals(fold(requireAlias(label)))) {
            throw new IllegalArgumentException("Reserved result label");
        }
        return label;
    }

    private static String fold(String alias) {
        return alias.toLowerCase(Locale.ROOT);
    }

    private enum JoinType {
        INNER(" INNER JOIN "), LEFT(" LEFT JOIN ");

        private final String sql;

        JoinType(String sql) {
            this.sql = sql;
        }
    }

    private record Join(JoinType type, TableRef table, List<On> conditions) {}
    private record Filter(Column column, Bind bind) {}
    private record Sort(Column column, boolean descending) {}
    private record ColumnKey(TableRef table, String name) {}
    private record Page(int limit, long offset) {}
}
