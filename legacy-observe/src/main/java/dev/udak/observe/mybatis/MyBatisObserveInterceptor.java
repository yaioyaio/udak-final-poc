package dev.udak.observe.mybatis;

import dev.udak.observe.Framework;
import dev.udak.observe.ObservationPoint;
import dev.udak.observe.SqlObserver;
import java.lang.reflect.InvocationTargetException;
import java.sql.Connection;
import java.util.Objects;
import org.apache.ibatis.cache.CacheKey;
import org.apache.ibatis.executor.Executor;
import org.apache.ibatis.executor.statement.StatementHandler;
import org.apache.ibatis.mapping.BoundSql;
import org.apache.ibatis.mapping.MappedStatement;
import org.apache.ibatis.plugin.Interceptor;
import org.apache.ibatis.plugin.Intercepts;
import org.apache.ibatis.plugin.Invocation;
import org.apache.ibatis.plugin.Signature;
import org.apache.ibatis.session.ResultHandler;
import org.apache.ibatis.session.RowBounds;

/** Observes prepared SQL under the nearest intercepted mapped operation on this thread. */
@Intercepts({
    @Signature(type = Executor.class, method = "query", args = {
        MappedStatement.class, Object.class, RowBounds.class, ResultHandler.class
    }),
    @Signature(type = Executor.class, method = "query", args = {
        MappedStatement.class, Object.class, RowBounds.class, ResultHandler.class, CacheKey.class, BoundSql.class
    }),
    @Signature(type = Executor.class, method = "update", args = {
        MappedStatement.class, Object.class
    }),
    @Signature(type = StatementHandler.class, method = "prepare", args = {
        Connection.class, Integer.class
    })
})
public final class MyBatisObserveInterceptor implements Interceptor {
    private final SqlObserver observer;
    private final ThreadLocal<String> queryId = new ThreadLocal<>();

    public MyBatisObserveInterceptor(SqlObserver observer) {
        this.observer = Objects.requireNonNull(observer, "observer");
    }

    @Override
    public Object intercept(Invocation invocation) throws Throwable {
        if (invocation.getMethod().getDeclaringClass() == Executor.class) {
            String previousId = queryId.get();
            queryId.set(mappedId(invocation));
            try {
                return proceed(invocation);
            } finally {
                if (previousId == null) {
                    queryId.remove();
                } else {
                    queryId.set(previousId);
                }
            }
        }

        // MyBatis has already built BoundSql. Cache hits that skip prepare emit no event.
        String currentId = queryId.get();
        if (currentId == null) {
            queryId.remove();
        }
        try {
            BoundSql boundSql = ((StatementHandler) invocation.getTarget()).getBoundSql();
            if (boundSql != null) {
                observer.observe(Framework.MYBATIS, ObservationPoint.MYBATIS_PREPARE, currentId,
                        boundSql.getSql());
            }
        } catch (VirtualMachineError | ThreadDeath fatal) {
            throw fatal;
        } catch (Throwable failure) {
            // Metadata retrieval is optional to the original prepare operation.
            if (failure instanceof InterruptedException) {
                Thread.currentThread().interrupt();
            }
        }
        return proceed(invocation);
    }

    private static String mappedId(Invocation invocation) {
        Object mapped = invocation.getArgs()[0];
        return mapped instanceof MappedStatement statement ? statement.getId() : null;
    }

    private static Object proceed(Invocation invocation) throws Throwable {
        try {
            return invocation.proceed();
        } catch (InvocationTargetException wrapper) {
            throw wrapper.getCause();
        }
    }
}
