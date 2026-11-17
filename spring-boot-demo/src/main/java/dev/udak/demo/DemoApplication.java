package dev.udak.demo;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.CommandLineRunner;
import org.springframework.context.annotation.Bean;
@SpringBootApplication
public class DemoApplication {
    public static void main(String[] args) { SpringApplication.run(DemoApplication.class,args); }
    @Bean CommandLineRunner demo(MixedUserService service) {
        return args -> {
            long id = service.createAndRead("Alice");
            System.out.println("UDAK demo: inserted and read ID=" + id);
            try { service.createThenFail("Bob"); } catch (IllegalStateException expected) {
                System.out.println("UDAK demo: rollback path executed");
            }
        };
    }
}
