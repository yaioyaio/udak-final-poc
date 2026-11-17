package dev.udak.testkit;

import javax.sql.DataSource;

/** External provider supplies an explicitly approved dedicated schema and DataSource. */
public interface RealDatabaseProvider {
    DatabaseProfile profile();
    DataSource dataSource();
    boolean dedicatedSchemaApproved();
}
