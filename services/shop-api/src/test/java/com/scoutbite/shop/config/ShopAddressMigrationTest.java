package com.scoutbite.shop.config;

import org.junit.jupiter.api.Test;
import org.yaml.snakeyaml.Yaml;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class ShopAddressMigrationTest {
    @Test
    void existingSchemaRunsBeforeAdditiveAddressUpdate() {
        Map<?, ?> config = new Yaml().load(getClass().getResourceAsStream("/application.yml"));
        Map<?, ?> spring = (Map<?, ?>) config.get("spring");
        Map<?, ?> sql = (Map<?, ?>) spring.get("sql");
        Map<?, ?> init = (Map<?, ?>) sql.get("init");
        assertEquals(List.of("classpath:schema.sql", "classpath:db/updates/20261010-shop-address.sql"), init.get("schema-locations"));
    }

    @Test
    void addressUpdateIsNullableAdditiveAndRepeatable() throws Exception {
        try (InputStream input = getClass().getResourceAsStream("/db/updates/20261010-shop-address.sql")) {
            assertNotNull(input, "地址列必须具有独立增量脚本，兼容既有数据库");
            String sql = new String(input.readAllBytes(), StandardCharsets.UTF_8).toLowerCase();
            assertTrue(sql.contains("alter table shops add column if not exists address varchar(255)"));
            assertFalse(sql.contains("not null"));
            assertFalse(sql.contains("drop "));
            assertFalse(sql.contains("truncate "));
        }
    }
}
