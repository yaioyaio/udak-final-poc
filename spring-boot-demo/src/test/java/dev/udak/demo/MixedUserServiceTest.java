package dev.udak.demo;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import static org.junit.jupiter.api.Assertions.*;
@SpringBootTest(properties="spring.main.web-application-type=none")
class MixedUserServiceTest {
    @Autowired MixedUserService service;
    @Test void visibilityAcrossJpaMybatisJdbc() {
        assertDoesNotThrow(() -> service.createAndRead("Visible"));
    }
    @Test void rollbackAcrossJpaAndJdbc() {
        long before=service.countByName("RollbackMe");
        assertThrows(IllegalStateException.class, () -> service.createThenFail("RollbackMe"));
        assertEquals(before,service.countByName("RollbackMe"));
    }
}
