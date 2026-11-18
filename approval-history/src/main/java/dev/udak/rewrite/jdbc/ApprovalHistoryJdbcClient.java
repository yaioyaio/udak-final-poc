package dev.udak.rewrite.jdbc;

import dev.udak.rewrite.ApprovalHistory;
import dev.udak.rewrite.Rewrite.Code;
import dev.udak.rewrite.Rewrite.Denied;
import dev.udak.rewrite.Rewrite.Environment;
import dev.udak.rewrite.Rewrite.Provider;
import dev.udak.rewrite.Rewrite.Template;
import java.util.List;
import java.util.Objects;
import javax.sql.DataSource;

/** The explicit SELECT entry point for a durable approval history owned by the caller. */
public final class ApprovalHistoryJdbcClient {
    private final DataSource dataSource;
    private final Environment environment;
    private final ApprovalHistory history;
    private final Provider provider;

    public ApprovalHistoryJdbcClient(DataSource dataSource, Environment environment, ApprovalHistory history,
                                     Provider provider) {
        this.dataSource = Objects.requireNonNull(dataSource, "dataSource");
        this.environment = Objects.requireNonNull(environment, "environment");
        this.history = Objects.requireNonNull(history, "history");
        this.provider = Objects.requireNonNull(provider, "provider");
    }

    public <T> List<T> query(Template template, SelectiveJdbcClient.Parameters parameters,
                            SelectiveJdbcClient.RowMapper<T> mapper) {
        Objects.requireNonNull(template, "template");
        Objects.requireNonNull(parameters, "parameters");
        Objects.requireNonNull(mapper, "mapper");
        if (!environment.equals(template.environment())) {
            throw new Denied(Code.MISMATCH);
        }
        return history.withRegistry(template, registry ->
                new SelectiveJdbcClient(dataSource, environment, registry, provider).query(template, parameters, mapper));
    }
}
