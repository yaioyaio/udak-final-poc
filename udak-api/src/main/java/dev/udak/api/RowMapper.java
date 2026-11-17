package dev.udak.api;

import java.sql.ResultSet;
import java.sql.SQLException;

/** Maps the current JDBC row while its ResultSet is open; returned values must be non-null. */
@FunctionalInterface
public interface RowMapper<T> {
    T map(ResultSet row, int rowNum) throws SQLException;
}
