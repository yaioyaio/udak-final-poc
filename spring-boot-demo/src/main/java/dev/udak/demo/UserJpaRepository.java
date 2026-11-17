package dev.udak.demo;
import org.springframework.data.jpa.repository.JpaRepository;
public interface UserJpaRepository extends JpaRepository<UserEntity,Long> {}
