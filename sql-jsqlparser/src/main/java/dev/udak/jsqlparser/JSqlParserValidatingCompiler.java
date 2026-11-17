package dev.udak.jsqlparser;

import dev.udak.core.BasicSqlCompiler;
import dev.udak.core.CompiledQuery;
import dev.udak.core.DbVendor;
import dev.udak.core.QueryDefinition;
import dev.udak.core.SqlCompiler;
import java.util.Set;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import net.sf.jsqlparser.parser.CCJSqlParserUtil;
import net.sf.jsqlparser.statement.select.Select;

/** Validates BasicSqlCompiler output as a single SELECT; it does not rewrite SQL. */
public final class JSqlParserValidatingCompiler implements SqlCompiler {
    private static final int MAX_SQL_LENGTH = 16_384;
    // One daemon worker and one queued parse bound resource use even if a parser stalls.
    private static final ThreadPoolExecutor PARSER = new ThreadPoolExecutor(1, 1, 0,
        TimeUnit.MILLISECONDS, new ArrayBlockingQueue<>(1), task -> {
            Thread thread = new Thread(task, "udak-sql-parser");
            thread.setDaemon(true);
            return thread;
        });
    private final SqlCompiler baseline;
    private final SqlCompiler delegate;

    public JSqlParserValidatingCompiler(Set<String> allowedIdentifiers) {
        this(new BasicSqlCompiler(allowedIdentifiers), null);
    }
    JSqlParserValidatingCompiler(SqlCompiler baseline, SqlCompiler delegate) {
        if (baseline == null) throw new IllegalArgumentException("Compiler required");
        this.baseline = baseline;
        this.delegate = delegate == null ? baseline : delegate;
    }
    @Override public CompiledQuery compile(QueryDefinition query, DbVendor vendor) {
        try {
            CompiledQuery expected = baseline.compile(query, vendor);
            CompiledQuery result = delegate == baseline ? expected : delegate.compile(query, vendor);
            if (result == null || result.sql().length() > MAX_SQL_LENGTH)
                throw new IllegalArgumentException();
            var statements = CCJSqlParserUtil.parseStatements(result.sql(), PARSER, p -> p.withTimeOut(1000));
            // Equality with the trusted baseline enforces its exact SQL and ordered bind count/values.
            if (statements.size() != 1 || !(statements.get(0) instanceof Select) || !expected.equals(result))
                throw new IllegalArgumentException();
            return result;
        } catch (Exception failure) {
            // Parser and delegate exceptions may contain SQL or bind values: never retain their causes.
            throw new IllegalArgumentException("SQL compilation or validation failed");
        }
    }
}
