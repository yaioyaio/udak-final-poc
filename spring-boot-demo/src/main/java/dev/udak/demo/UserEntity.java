package dev.udak.demo;
import jakarta.persistence.*;
@Entity
@Table(name="app_user")
public class UserEntity {
    @Id @GeneratedValue(strategy=GenerationType.IDENTITY)
    private Long id;
    @Column(nullable=false) private String name;
    protected UserEntity() {}
    public UserEntity(String name) { this.name=name; }
    public Long getId() { return id; }
    public String getName() { return name; }
}
