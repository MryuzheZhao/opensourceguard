// Demo fixture: a small Java component with intentional issues.
package com.example.demo;

import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;

public class UserRepository {

    private final Connection connection;

    public UserRepository(Connection connection) {
        this.connection = connection;
    }

    // Intentional finding: JAVA-SQL-CONCAT (CWE-89)
    public ResultSet findByName(String name) throws SQLException {
        Statement statement = connection.createStatement();
        return statement.executeQuery("SELECT id FROM users WHERE name = '" + name + "'");
    }

    // Intentional finding: JAVA-RUNTIME-EXEC (CWE-78)
    public void exportReport(String path) throws Exception {
        Runtime.getRuntime().exec("sh -c 'generate-report " + path + "'");
    }

    public int countUsers() {
        return 0;
    }
}
