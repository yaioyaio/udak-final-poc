package dev.udak.boot3;

import dev.udak.api.SqlExecutor;
import dev.udak.jdbc.SpringJdbcExecutor;
import dev.udak.observe.ObservationSink;
import dev.udak.observe.SqlObserver;
import javax.sql.DataSource;
import org.springframework.beans.factory.BeanFactoryUtils;
import org.springframework.beans.factory.ListableBeanFactory;
import org.springframework.beans.factory.config.BeanFactoryPostProcessor;
import org.springframework.boot.SpringBootVersion;
import org.springframework.boot.autoconfigure.AutoConfiguration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Condition;
import org.springframework.context.annotation.ConditionContext;
import org.springframework.context.annotation.Conditional;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.ConfigurationCondition;
import org.springframework.context.annotation.Lazy;
import org.springframework.core.env.Environment;
import org.springframework.core.type.AnnotatedTypeMetadata;

@AutoConfiguration(value = "udakBoot3AutoConfiguration",
        afterName = "org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration")
public class UdakAutoConfiguration {
    private static final String OTHER_STARTER = "dev/udak/boot4/UdakAutoConfiguration.class";

    // Validate at startup even when the application enables lazy initialization.
    @Bean
    static BeanFactoryPostProcessor udakBoot3StartupGuard(Environment environment) {
        return beans -> {
            ClassLoader loader = beans.getBeanClassLoader();
            if (loader != null && loader.getResource(OTHER_STARTER) != null) {
                throw new IllegalStateException("UDAK starters cannot be mixed");
            }
            String version = SpringBootVersion.getVersion();
            if (version == null || !version.startsWith("3.")) {
                throw new IllegalStateException("UDAK starter requires Spring Boot 3");
            }
            UdakSettings.validate(environment);
        };
    }

    @Configuration(proxyBeanMethods = false)
    @Conditional(Enabled.class)
    static class EnabledConfiguration {
        @Bean
        @ConditionalOnMissingBean(ObservationSink.class)
        ObservationSink udakObservationSink() {
            return event -> { };
        }

        @Bean
        @ConditionalOnMissingBean(SqlObserver.class)
        SqlObserver udakSqlObserver(ObservationSink sink) {
            return new SqlObserver(sink);
        }

        @Bean
        @Lazy
        @ConditionalOnMissingBean(SqlExecutor.class)
        @Conditional(JdbcReady.class)
        SqlExecutor udakSqlExecutor(ListableBeanFactory beans, Environment environment) {
            String[] candidates = dataSources(beans);
            if (candidates.length != 1) {
                throw new IllegalStateException("UDAK JDBC requires exactly one DataSource");
            }
            DataSource source = beans.getBean(candidates[0], DataSource.class);
            return new SpringJdbcExecutor(source, UdakSettings.vendor(environment),
                    UdakSettings.queryTimeoutSeconds(environment), UdakSettings.maxRows(environment));
        }
    }

    static final class Enabled implements Condition {
        @Override
        public boolean matches(ConditionContext context, AnnotatedTypeMetadata metadata) {
            return UdakSettings.enabled(context.getEnvironment());
        }
    }

    static final class JdbcReady implements ConfigurationCondition {
        @Override
        public ConfigurationPhase getConfigurationPhase() {
            return ConfigurationPhase.REGISTER_BEAN;
        }

        @Override
        public boolean matches(ConditionContext context, AnnotatedTypeMetadata metadata) {
            ListableBeanFactory beans = context.getBeanFactory();
            return UdakSettings.jdbcEnabled(context.getEnvironment())
                    && beans != null && dataSources(beans).length == 1;
        }
    }

    private static String[] dataSources(ListableBeanFactory beans) {
        return BeanFactoryUtils.beanNamesForTypeIncludingAncestors(beans, DataSource.class, true, false);
    }
}
