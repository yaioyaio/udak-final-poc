package dev.udak.demo;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
@Mapper
public interface UserMapper {
    @Select("SELECT name FROM app_user WHERE id = #{id}")
    String findName(@Param("id") long id);
}
