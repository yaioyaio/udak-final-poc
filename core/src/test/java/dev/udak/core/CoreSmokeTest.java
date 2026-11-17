package dev.udak.core;
import java.util.*;
/** Self-contained executable tests that require only JDK 17+. */
public final class CoreSmokeTest {
    static void ok(boolean condition, String message) { if (!condition) throw new AssertionError(message); }
    static void throwsType(Class<? extends Throwable> t, Runnable r) {
        try { r.run(); } catch(Throwable ex) { if(t.isInstance(ex)) return; throw new AssertionError("Unexpected: " + ex, ex); }
        throw new AssertionError("Expected " + t.getSimpleName());
    }
    public static void main(String[] args) {
        SqlCompiler compiler = new BasicSqlCompiler(Set.of("users","id","name","status"));
        var q = new QueryDefinition("users", List.of("id","name"), "status", "ACTIVE", "id", true, 20, 5);
        for (DbVendor v : DbVendor.values()) {
            var c = compiler.compile(q, v);
            ok(c.binds().size()==3,"binding count " + v);
            ok(c.sql().contains("ORDER BY id DESC"),"stable order " + v);
            ok(c.binds().get(0).value().equals("ACTIVE"),"filter " + v);
            if(v==DbVendor.SQLSERVER || v==DbVendor.ORACLE_19) {
                ok(c.sql().contains("OFFSET ? ROWS FETCH NEXT ?"),"offset/fetch " + v);
                ok(c.binds().get(1).name().equals("offset"),"binding order " + v);
            }
            if(v==DbVendor.ORACLE_11) {
                ok(c.sql().contains("ROWNUM"),"oracle11 " + v);
                ok(c.binds().get(1).value().equals(25L),"bound " + v);
            }
            System.out.println("PASS compiler " + v + " :: " + c.sql());
        }
        throwsType(IllegalArgumentException.class, () -> compiler.compile(
            new QueryDefinition("users;DROP", List.of("id"),"status","A","id",false,10,0), DbVendor.POSTGRESQL));
        throwsType(IllegalArgumentException.class, () -> compiler.compile(
            new QueryDefinition("users", List.of("id"),"status","A","id",false,0,0), DbVendor.MYSQL));
        var sql = "SELECT id FROM users WHERE status = ?";
        var approval = new ApprovedRewriteGuard.Approval("user.list", SqlFingerprint.sha256(sql),
            DbVendor.MYSQL, DbVendor.ORACLE_19, "review-1");
        var guard = new ApprovedRewriteGuard(Map.of("user.list", approval));
        guard.requireApproved("user.list", sql, DbVendor.MYSQL, DbVendor.ORACLE_19, "review-1");
        throwsType(SecurityException.class, () -> guard.requireApproved("user.list",sql+" ",DbVendor.MYSQL,DbVendor.ORACLE_19,"review-1"));
        throwsType(SecurityException.class, () -> guard.requireApproved("user.list",sql,DbVendor.MYSQL,DbVendor.ORACLE_11,"review-1"));
        ConsistencyGuard.requireSingleLocalResource(Set.of("main"));
        throwsType(IllegalStateException.class, () -> ConsistencyGuard.requireSingleLocalResource(Set.of("oracle", "postgres")));
        System.out.println("PASS fingerprint + default-deny rewrite + multi-DataSource guard");
        System.out.println("CORE SMOKE: ALL TESTS PASSED");
    }
}
