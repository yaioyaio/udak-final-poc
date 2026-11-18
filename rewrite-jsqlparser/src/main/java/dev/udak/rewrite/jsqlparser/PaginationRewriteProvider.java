package dev.udak.rewrite.jsqlparser;

import dev.udak.rewrite.Rewrite;
import dev.udak.rewrite.Rewrite.Code;
import dev.udak.rewrite.Rewrite.Denied;
import dev.udak.rewrite.Rewrite.Dialect;
import dev.udak.rewrite.Rewrite.Plan;
import dev.udak.rewrite.Rewrite.Role;
import dev.udak.rewrite.Rewrite.Template;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;
import net.sf.jsqlparser.JSQLParserException;
import net.sf.jsqlparser.expression.Alias;
import net.sf.jsqlparser.expression.Expression;
import net.sf.jsqlparser.expression.JdbcParameter;
import net.sf.jsqlparser.expression.operators.relational.EqualsTo;
import net.sf.jsqlparser.parser.CCJSqlParserUtil;
import net.sf.jsqlparser.parser.ParseException;
import net.sf.jsqlparser.schema.Column;
import net.sf.jsqlparser.schema.Table;
import net.sf.jsqlparser.statement.select.Fetch;
import net.sf.jsqlparser.statement.select.Limit;
import net.sf.jsqlparser.statement.select.Offset;
import net.sf.jsqlparser.statement.select.OrderByElement;
import net.sf.jsqlparser.statement.select.PlainSelect;
import net.sf.jsqlparser.statement.select.SelectItem;

/** Translates canonical PostgreSQL pagination with a caller-verified unique, non-null sort key. */
public final class PaginationRewriteProvider implements Rewrite.Provider {
    public static final String VERSION = "jsqlparser-5.4-subset-1";
    private static final int MAX_SQL_LENGTH = 16_384;
    private static final Pattern IDENTIFIER = Pattern.compile("[a-z][a-z0-9_]{0,62}");

    // Keep parser work bounded if cancellation takes time. A full queue denies translation.
    private static final ThreadPoolExecutor PARSER = new ThreadPoolExecutor(1, 1, 0,
        TimeUnit.MILLISECONDS, new ArrayBlockingQueue<>(1), task -> {
            Thread thread = new Thread(task, "udak-rewrite-parser");
            thread.setDaemon(true);
            return thread;
        });

    private final Set<String> allowedTables;
    private final Set<String> allowedColumns;

    public PaginationRewriteProvider(Set<String> allowedTables, Set<String> allowedColumns) {
        this.allowedTables = snapshotAllowlist(allowedTables);
        this.allowedColumns = snapshotAllowlist(allowedColumns);
    }

    @Override public String version() {
        return VERSION;
    }

    @Override public Plan translate(Template template) {
        try {
            if (template == null || template.sql().length() > MAX_SQL_LENGTH
                    || !VERSION.equals(template.environment().providerVersion())) {
                throw new Denied(Code.INVALID_INPUT);
            }
            require(template.environment().source() == Dialect.POSTGRESQL);

            String sourceSql = template.sql();
            PlainSelect source = parseSelect(sourceSql, LabelQuotes.NONE);
            Selection selection = readSelection(source, LabelQuotes.NONE);
            requireLimitOffset(source);
            // The parser can omit tokens such as comments and redundant syntax from the AST.
            require(Paging.LIMIT_OFFSET.render(selection, LabelQuotes.NONE).equals(sourceSql));

            Dialect target = template.environment().target();
            Paging paging = switch (target) {
                case H2, POSTGRESQL, MYSQL -> Paging.LIMIT_OFFSET;
                case SQLSERVER, ORACLE -> Paging.OFFSET_FETCH;
            };
            LabelQuotes labelQuotes = switch (target) {
                case H2, POSTGRESQL, ORACLE -> LabelQuotes.DOUBLE;
                case MYSQL -> LabelQuotes.BACKTICK;
                case SQLSERVER -> LabelQuotes.BRACKET;
            };
            String targetSql = paging.render(selection, labelQuotes);
            validateTarget(targetSql, paging, labelQuotes, selection);
            return new Plan(targetSql, paging.bindOrder, List.of(selection.first(), selection.second()));
        } catch (Denied denied) {
            throw denied;
        } catch (VirtualMachineError | ThreadDeath fatal) {
            throw fatal;
        } catch (Throwable failure) {
            throw new Denied(Code.PROVIDER_FAILED);
        }
    }

    private void validateTarget(String sql, Paging paging, LabelQuotes labelQuotes, Selection expected) {
        try {
            PlainSelect select = parseSelect(sql, labelQuotes);
            require(expected.equals(readSelection(select, labelQuotes)));
            switch (paging) {
                case LIMIT_OFFSET -> requireLimitOffset(select);
                case OFFSET_FETCH -> requireOffsetFetch(select);
            }
        } catch (Denied denied) {
            throw new Denied(Code.PROVIDER_FAILED);
        }
    }

    private static PlainSelect parseSelect(String sql, LabelQuotes labelQuotes) {
        try {
            var statements = CCJSqlParserUtil.parseStatements(sql, PARSER,
                parser -> parser.withAllowComplexParsing(false)
                    .withSquareBracketQuotation(labelQuotes == LabelQuotes.BRACKET).withTimeOut(1_000));
            if (statements.size() != 1 || !(statements.get(0) instanceof PlainSelect select)) {
                throw new Denied(Code.UNSUPPORTED);
            }
            return select;
        } catch (JSQLParserException failure) {
            Throwable cause = failure.getCause();
            if (cause instanceof ExecutionException execution) {
                cause = execution.getCause();
            }
            if (cause instanceof VirtualMachineError fatal) {
                throw fatal;
            }
            if (cause instanceof ThreadDeath fatal) {
                throw fatal;
            }
            throw new Denied(cause instanceof ParseException ? Code.UNSUPPORTED : Code.PROVIDER_FAILED);
        }
    }

    private Selection readSelection(PlainSelect select, LabelQuotes labelQuotes) {
        if (!(select.getFromItem() instanceof Table table) || table.getAlias() != null) {
            throw new Denied(Code.UNSUPPORTED);
        }
        String tableName = table.getFullyQualifiedName();
        require(isIdentifier(tableName) && allowedTables.contains(tableName));

        List<SelectItem<?>> items = select.getSelectItems();
        require(items != null && items.size() == 2);
        String first = selectColumn(items.get(0), labelQuotes);
        String second = selectColumn(items.get(1), labelQuotes);
        require(!first.equals(second));

        if (!(select.getWhere() instanceof EqualsTo equality)) {
            throw new Denied(Code.UNSUPPORTED);
        }
        String filter = column(equality.getLeftExpression());
        require(isParameter(equality.getRightExpression(), 1));

        List<OrderByElement> order = select.getOrderByElements();
        require(order != null && order.size() == 1);
        OrderByElement sort = order.get(0);
        require(sort.isAscDescPresent() && sort.isAsc() && first.equals(column(sort.getExpression())));
        return new Selection(tableName, first, second, filter);
    }

    private String selectColumn(SelectItem<?> item, LabelQuotes labelQuotes) {
        String name = column(item.getExpression());
        Alias alias = item.getAlias();
        if (labelQuotes == LabelQuotes.NONE) {
            require(alias == null);
        } else {
            require(alias != null && alias.isUseAs() && labelQuotes.quote(name).equals(alias.getName()));
        }
        return name;
    }

    private String column(Expression expression) {
        if (!(expression instanceof Column column) || column.getTable() != null) {
            throw new Denied(Code.UNSUPPORTED);
        }
        String name = column.getColumnName();
        require(isIdentifier(name) && allowedColumns.contains(name));
        return name;
    }

    private static void requireLimitOffset(PlainSelect select) {
        Limit limit = select.getLimit();
        Offset offset = select.getOffset();
        require(limit != null && limit.getOffset() == null && isParameter(limit.getRowCount(), 2));
        require(offset != null && offset.getOffsetParam() == null && isParameter(offset.getOffset(), 3));
        require(select.getFetch() == null);
    }

    private static void requireOffsetFetch(PlainSelect select) {
        Offset offset = select.getOffset();
        Fetch fetch = select.getFetch();
        require(select.getLimit() == null);
        require(offset != null && "ROWS".equals(offset.getOffsetParam()) && isParameter(offset.getOffset(), 2));
        require(fetch != null && !fetch.isFetchParamFirst() && isParameter(fetch.getExpression(), 3)
            && List.of("ROWS", "ONLY").equals(fetch.getFetchParameters()));
    }

    private static boolean isParameter(Expression expression, int position) {
        return expression instanceof JdbcParameter parameter && !parameter.isUseFixedIndex()
            && "?".equals(parameter.getParameterCharacter()) && Integer.valueOf(position).equals(parameter.getIndex());
    }

    private static Set<String> snapshotAllowlist(Set<String> identifiers) {
        Set<String> snapshot;
        try {
            snapshot = Set.copyOf(identifiers);
        } catch (NullPointerException invalid) {
            throw new Denied(Code.INVALID_INPUT);
        }
        if (!snapshot.stream().allMatch(PaginationRewriteProvider::isIdentifier)) {
            throw new Denied(Code.INVALID_INPUT);
        }
        return snapshot;
    }

    private static boolean isIdentifier(String value) {
        return value != null && IDENTIFIER.matcher(value).matches();
    }

    private static void require(boolean condition) {
        if (!condition) {
            throw new Denied(Code.UNSUPPORTED);
        }
    }

    private record Selection(String table, String first, String second, String filter) {}

    private enum Paging {
        LIMIT_OFFSET(" LIMIT ? OFFSET ?", List.of(Role.FILTER, Role.LIMIT, Role.OFFSET)),
        OFFSET_FETCH(" OFFSET ? ROWS FETCH NEXT ? ROWS ONLY", List.of(Role.FILTER, Role.OFFSET, Role.LIMIT));

        private final String suffix;
        private final List<Role> bindOrder;

        Paging(String suffix, List<Role> bindOrder) {
            this.suffix = suffix;
            this.bindOrder = bindOrder;
        }

        String render(Selection selection, LabelQuotes labelQuotes) {
            return "SELECT " + labelQuotes.project(selection.first()) + ", " + labelQuotes.project(selection.second())
                + " FROM " + selection.table()
                + " WHERE " + selection.filter() + " = ? ORDER BY " + selection.first() + " ASC" + suffix;
        }
    }

    private enum LabelQuotes {
        NONE("", ""), DOUBLE("\"", "\""), BACKTICK("`", "`"), BRACKET("[", "]");

        private final String open;
        private final String close;

        LabelQuotes(String open, String close) {
            this.open = open;
            this.close = close;
        }

        // Projection identifiers were already checked against the ASCII identifier pattern and allowlist.
        String project(String name) {
            return this == NONE ? name : name + " AS " + quote(name);
        }

        String quote(String name) {
            return open + name + close;
        }
    }
}
