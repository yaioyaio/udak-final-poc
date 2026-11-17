package dev.udak.demo;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.jdbc.core.JdbcTemplate;
import jakarta.persistence.EntityManager;
import java.util.Objects;
@Service
public class MixedUserService {
    private final UserJpaRepository jpa;
    private final UserMapper mybatis;
    private final JdbcTemplate jdbc;
    private final EntityManager em;
    public MixedUserService(UserJpaRepository jpa, UserMapper mybatis, JdbcTemplate jdbc, EntityManager em) {
        this.jpa=jpa; this.mybatis=mybatis; this.jdbc=jdbc; this.em=em;
    }
    @Transactional
    public long createAndRead(String name) {
        var entity=jpa.save(new UserEntity(name));
        em.flush(); // explicit before MyBatis/JDBC observation
        long id=Objects.requireNonNull(entity.getId());
        String mybatisValue=mybatis.findName(id);
        String jdbcValue=jdbc.queryForObject("SELECT name FROM app_user WHERE id = ?", String.class, id);
        if(!name.equals(mybatisValue) || !name.equals(jdbcValue))
            throw new IllegalStateException("Cross-framework visibility mismatch");
        return id;
    }
    @Transactional
    public void createThenFail(String name) {
        var entity=jpa.save(new UserEntity(name));
        em.flush();
        jdbc.update("UPDATE app_user SET name=? WHERE id=?", "temporary", entity.getId());
        throw new IllegalStateException("test rollback");
    }
    @Transactional(readOnly=true)
    public long countByName(String name) {
        return jdbc.queryForObject("SELECT COUNT(*) FROM app_user WHERE name=?", Long.class, name);
    }
}
