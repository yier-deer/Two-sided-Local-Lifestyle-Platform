package com.scoutbite.shop.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.scoutbite.shop.common.ErrorCode;
import com.scoutbite.shop.repository.AgentTraceRepository;
import com.scoutbite.shop.repository.ShopRepository;
import com.scoutbite.shop.service.OrderService;
import com.scoutbite.shop.service.ReviewService;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;

/** Tests the public confirmation boundary with a real loopback HTTP Agent stub. */
class AgentFacadeControllerTest {
    private final ObjectMapper json = new ObjectMapper();
    private final AtomicInteger draftReads = new AtomicInteger();
    private final AtomicInteger completions = new AtomicInteger();
    private HttpServer agent;
    private MockMvc mvc;
    private ReviewService reviews;
    private int draftCode;
    private int completeStatus;

    @BeforeEach
    void setUp() throws Exception {
        draftCode = 0;
        completeStatus = 200;
        agent = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        agent.createContext("/", this::respond);
        agent.start();
        reviews = mock(ReviewService.class);
        when(reviews.create(eq(12L), eq(47L), anyMap(), anyString(), isNull()))
                .thenAnswer(call -> {
                    Map<String, Object> saved = new LinkedHashMap<>();
                    saved.put("id", 81L);
                    saved.put("orderId", call.getArgument(1));
                    saved.put("scores", call.getArgument(2));
                    saved.put("content", call.getArgument(3));
                    return saved;
                });
        AgentFacadeController controller = new AgentFacadeController(
                "http://127.0.0.1:" + agent.getAddress().getPort(),
                mock(AgentTraceRepository.class), reviews, mock(ShopRepository.class));
        mvc = MockMvcBuilders.standaloneSetup(controller).build();
    }

    @AfterEach
    void tearDown() {
        if (agent != null) agent.stop(0);
    }

    @Test
    void publishesConfirmedEditsUsingTheOriginalOrderAnchor() throws Exception {
        Map<String, Object> response = publish("""
                {"content":"User revised this review","scores":{"taste":4,"wait":2,"env":5},"orderId":9999}
                """);
        assertCode(0, response);
        Map<?, ?> saved = (Map<?, ?>) response.get("data");
        assertEquals("User revised this review", saved.get("content"));
        assertEquals(Map.of("taste", 4, "wait", 2, "env", 5), saved.get("scores"));
        assertEquals(47, ((Number) saved.get("orderId")).intValue());
        assertEquals(1, completions.get());
        verify(reviews).create(eq(12L), eq(47L), anyMap(), eq("User revised this review"), isNull());
    }

    @Test
    void publishesTheOriginalDraftWhenNoBodyIsProvided() throws Exception {
        Map<String, Object> response = publish(null);
        assertCode(0, response);
        assertEquals("Original draft", ((Map<?, ?>) response.get("data")).get("content"));
        assertEquals(1, completions.get());
    }

    @Test
    void supportsEditingOnlyTheContent() throws Exception {
        Map<String, Object> response = publish("{\"content\":\"Edited text only\"}");
        assertCode(0, response);
        Map<?, ?> saved = (Map<?, ?>) response.get("data");
        assertEquals("Edited text only", saved.get("content"));
        assertEquals(Map.of("taste", 5, "wait", 3, "env", 4), saved.get("scores"));
    }

    @Test
    void supportsEditingOnlyTheScores() throws Exception {
        Map<String, Object> response = publish("{\"scores\":{\"taste\":1,\"wait\":2,\"env\":3}}");
        assertCode(0, response);
        Map<?, ?> saved = (Map<?, ?>) response.get("data");
        assertEquals("Original draft", saved.get("content"));
        assertEquals(Map.of("taste", 1, "wait", 2, "env", 3), saved.get("scores"));
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "{\"content\":\"  \"}", "{\"content\":null}", "{\"content\":12}",
            "{\"scores\":null}", "{\"scores\":{}}", "{\"scores\":{\"taste\":5}}",
            "{\"scores\":{\"taste\":0,\"wait\":3,\"env\":4}}",
            "{\"scores\":{\"taste\":6,\"wait\":3,\"env\":4}}",
            "{\"scores\":{\"taste\":1.5,\"wait\":3,\"env\":4}}",
            "{\"scores\":{\"taste\":\"5\",\"wait\":3,\"env\":4}}",
            "{\"scores\":{\"taste\":true,\"wait\":3,\"env\":4}}",
            "{\"scores\":{\"taste\":5,\"wait\":3,\"env\":4,\"unknown\":4}}"
    })
    void rejectsMalformedConfirmationWithoutWritingOrConsuming(String body) throws Exception {
        assertCode(40001, publish(body));
        verifyNoInteractions(reviews);
        assertEquals(0, completions.get());
    }

    @Test
    void rejectsContentLongerThanTheReviewLimit() throws Exception {
        assertCode(40001, publish(json.writeValueAsString(Map.of("content", "x".repeat(501)))));
        verifyNoInteractions(reviews);
        assertEquals(0, completions.get());
    }

    @Test
    void requiresAuthenticatedUserBeforeFetchingTheDraft() throws Exception {
        String body = mvc.perform(post("/api/agent/user/review-draft/d-test/publish"))
                .andReturn().getResponse().getContentAsString(StandardCharsets.UTF_8);
        assertCode(40100, json.readValue(body, Map.class));
        assertEquals(0, draftReads.get());
        verifyNoInteractions(reviews);
    }

    @Test
    void cannotPublishAnotherUsersDraft() throws Exception {
        draftCode = 40300;
        assertCode(40300, publish("{\"content\":\"Attacker replacement\"}"));
        verifyNoInteractions(reviews);
        assertEquals(0, completions.get());
    }

    @Test
    void keepsTheDraftWhenTheOrderGateRejectsPublication() throws Exception {
        when(reviews.create(anyLong(), anyLong(), anyMap(), anyString(), isNull()))
                .thenThrow(new OrderService.BizException(ErrorCode.STATE_CONFLICT, "Order is not redeemed"));
        assertCode(40903, publish("{\"content\":\"User text\"}"));
        assertEquals(0, completions.get());
    }

    @Test
    void keepsTheDraftWhenDatabasePublicationFails() throws Exception {
        when(reviews.create(anyLong(), anyLong(), anyMap(), anyString(), isNull()))
                .thenThrow(new IllegalStateException("Database unavailable"));
        Map<String, Object> response = publish("{\"content\":\"User text\"}");
        assertCode(50000, response);
        assertFalse(response.get("message").toString().contains("已消费"));
        assertEquals(0, completions.get());
    }

    @Test
    void successfulDatabasePublicationRemainsSuccessfulIfCompletionIsUnavailable() throws Exception {
        completeStatus = 503;
        assertCode(0, publish("{\"content\":\"User text\"}"));
        assertEquals(1, completions.get(), "Completion should be attempted after the write");
        verify(reviews).create(eq(12L), eq(47L), anyMap(), eq("User text"), isNull());
    }

    private Map<String, Object> publish(String body) throws Exception {
        MockHttpServletRequestBuilder request = post("/api/agent/user/review-draft/d-test/publish")
                .requestAttr("userId", 12L);
        if (body != null) request.contentType(MediaType.APPLICATION_JSON).content(body);
        String output = mvc.perform(request).andReturn().getResponse().getContentAsString(StandardCharsets.UTF_8);
        return json.readValue(output, Map.class);
    }

    private void assertCode(int code, Map<?, ?> response) {
        assertEquals(code, ((Number) response.get("code")).intValue(), response.toString());
    }

    private void respond(HttpExchange exchange) throws IOException {
        int status = 200;
        Map<String, Object> response;
        if (exchange.getRequestURI().getPath().endsWith("/complete")) {
            completions.incrementAndGet();
            status = completeStatus;
            response = Map.of("code", 0, "message", "ok", "data", Map.of("draftId", "d-test"));
        } else {
            draftReads.incrementAndGet();
            response = Map.of("code", draftCode, "message", draftCode == 0 ? "ok" : "Draft belongs to another user",
                    "data", Map.of("orderId", 47, "content", "Original draft",
                            "scores", Map.of("taste", 5, "wait", 3, "env", 4)));
        }
        exchange.getRequestBody().readAllBytes();
        byte[] bytes = json.writeValueAsString(response).getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }
}
