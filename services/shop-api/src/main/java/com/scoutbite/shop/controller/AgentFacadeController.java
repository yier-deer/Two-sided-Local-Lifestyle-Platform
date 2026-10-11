package com.scoutbite.shop.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.scoutbite.shop.common.ApiResponse;
import com.scoutbite.shop.common.ErrorCode;
import com.scoutbite.shop.entity.AgentTrace;
import com.scoutbite.shop.repository.AgentTraceRepository;
import com.scoutbite.shop.repository.ShopRepository;
import com.scoutbite.shop.service.OrderService;
import com.scoutbite.shop.service.ReviewService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.RestClient;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Agent 门面（完全体）：前端调 AI 的唯一入口。
 * 三条纪律：
 *  1. 验 JWT → 注入 X-User-Id 转发（Python 不解析 JWT）
 *  2. 写路径只在本类发生：publish = 取草稿 → ReviewService 二次校验 → 写库
 *     （Python 只起草仓，没有写库通道——签字权闭环）
 *  3. 商家 analyze 先做归属校验（只能分析自己的店），Python 不知道谁是店主人
 * 错误码透传：agent-api 返回的业务码（42201/40903/50000…）原样透传给前端，不二次翻译。
 */
@RestController
@Tag(name = "Agent", description = "AI 门面：转发+注入身份；publish 在此写库（签字权）")
public class AgentFacadeController {

    private static final Logger log = LoggerFactory.getLogger(AgentFacadeController.class);

    private final RestClient restClient;
    private final RestClient completionClient;
    private final String agentApiUrl;
    private final AgentTraceRepository traceRepo;
    private final ReviewService reviewService;
    private final ShopRepository shopRepo;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public AgentFacadeController(@Value("${scoutbite.agent-api.url}") String agentApiUrl,
                                 AgentTraceRepository traceRepo,
                                 ReviewService reviewService,
                                 ShopRepository shopRepo) {
        this.agentApiUrl = agentApiUrl;
        this.traceRepo = traceRepo;
        this.reviewService = reviewService;
        this.shopRepo = shopRepo;
        var factory = new org.springframework.http.client.SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5_000);
        factory.setReadTimeout(60_000);
        this.restClient = RestClient.builder().requestFactory(factory).build();
        var completionFactory = new org.springframework.http.client.SimpleClientHttpRequestFactory();
        completionFactory.setConnectTimeout(2_000);
        completionFactory.setReadTimeout(3_000);
        this.completionClient = RestClient.builder().requestFactory(completionFactory).build();
    }

    /** 对话式推荐（）：转发 + trace */
    @Operation(summary = "对话式推荐（可多轮，3 家对比含缺点与引用）")
    @PostMapping("/api/agent/user/recommend")
    public ApiResponse<?> recommend(@RequestBody Map<String, Object> body, HttpServletRequest request) {
        Long userId = requireUser(request);
        if (userId == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");
        return forward(userId, "recommend", "/agent/recommend", body);
    }

    /** 生成评价草稿（CASDG）：Python 基于订单事实起草，存草稿仓，不发布 */
    @Operation(summary = "生成评价草稿（绑订单事实，不发布）")
    @PostMapping("/api/agent/user/review-draft")
    public ApiResponse<?> reviewDraft(@RequestBody Map<String, Object> body, HttpServletRequest request) {
        Long userId = requireUser(request);
        if (userId == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");
        return forward(userId, "review-draft", "/agent/review-draft", body);
    }

    /**
     * 确认发布（签字权闭环）：写路径只在这里。
     * 流程：用户 JWT → Python 读取草稿（验归属）→ 校验用户确认的编辑 →
     * ReviewService 按草稿原订单二次校验并写库 → 通知 Python 消费。
     * 无请求体时保留原草稿；写库前失败保留草稿，数据库唯一索引兜底并发双评。
     */
    @Operation(summary = "确认发布草稿（用户签字，二次校验后写库）")
    @PostMapping("/api/agent/user/review-draft/{id}/publish")
    public ApiResponse<?> publish(@PathVariable String id,
                                  @RequestBody(required = false) Map<String, Object> edits,
                                  HttpServletRequest request) {
        Long userId = requireUser(request);
        if (userId == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");

        long start = System.currentTimeMillis();
        // ① 只读草稿：Python 验归属；用户不能通过编辑请求更换原订单。
        Map<String, Object> draftResp;
        try {
            draftResp = restClient.post()
                    .uri(agentApiUrl + "/agent/review-draft/" + id + "/publish")
                    .contentType(MediaType.APPLICATION_JSON)
                    .header("X-User-Id", String.valueOf(userId))
                    .body(Map.of())
                    .retrieve().body(Map.class);
        } catch (Exception e) {
            log.error("取草稿失败 {}: {}", id, e.getMessage());
            return ApiResponse.fail(50000, "Agent 服务暂时不可用，草稿未消费，请稍后重试");
        }
        if (draftResp == null) return ApiResponse.fail(50000, "Agent 未返回草稿，请稍后重试");
        int code = draftResp != null && draftResp.get("code") != null
                ? ((Number) draftResp.get("code")).intValue() : 50000;
        if (code != 0) {
            return ApiResponse.fail(code, String.valueOf(draftResp.get("message")));
        }

        // ② 校验用户确认的正文/评分，再走原来的订单归属、核销与唯一索引校验。
        try {
            if (!(draftResp.get("data") instanceof Map<?, ?> draft)) {
                return ApiResponse.fail(50000, "Agent 草稿格式异常，请重新生成");
            }
            Long orderId = ((Number) draft.get("orderId")).longValue();
            Map<String, Object> confirmation = edits == null ? Map.of() : edits;
            Object contentValue = confirmation.containsKey("content")
                    ? confirmation.get("content") : draft.get("content");
            if (!(contentValue instanceof String content)
                    || content.isBlank() || content.length() > 500) {
                return ApiResponse.fail(ErrorCode.PARAM_ERROR, "正文 1~500 字");
            }
            Object scoresValue = confirmation.containsKey("scores")
                    ? confirmation.get("scores") : draft.get("scores");
            Map<String, Integer> scores = confirmedScores(scoresValue);
            if (scores == null) {
                return ApiResponse.fail(ErrorCode.PARAM_ERROR, "taste/wait/env 三维评分须为 1~5 的整数");
            }
            Map<String, Object> review = reviewService.create(userId, orderId, scores, content, null);

            // ③ DB 已成功：消费通知为 best-effort，不能把已写库的成功反报为失败。
            boolean consumed = completeDraft(userId, id);
            List<String> toolCalls = new ArrayList<>();
            toolCalls.add("agent:drafts.get(" + id + ")");
            toolCalls.add("ReviewService.create(orderId=" + orderId + ")");
            toolCalls.add(consumed ? "agent:drafts.pop(" + id + ")"
                    : "agent:drafts.complete(" + id + "): unconfirmed");
            saveTrace(userId, "review-publish", Map.of("draftId", id, "content", content, "scores", scores),
                    toolCalls, review,
                    System.currentTimeMillis() - start);
            return ApiResponse.ok(review);
        } catch (OrderService.BizException e) {
            return ApiResponse.fail(e.code, e.getMessage());
        } catch (Exception e) {
            log.error("发布草稿写库失败 {}: {}", id, e.getMessage());
            return ApiResponse.fail(50000, "发布失败，草稿已保留，可稍后重试");
        }
    }

    private Map<String, Integer> confirmedScores(Object value) {
        if (!(value instanceof Map<?, ?> scores)
                || !scores.keySet().equals(Set.of("taste", "wait", "env"))) return null;
        Map<String, Integer> result = new LinkedHashMap<>();
        for (String dimension : List.of("taste", "wait", "env")) {
            if (!(scores.get(dimension) instanceof Number number)) return null;
            double score = number.doubleValue();
            if (score < 1 || score > 5 || score != Math.floor(score)) return null;
            result.put(dimension, (int) score);
        }
        return result;
    }

    private boolean completeDraft(Long userId, String id) {
        try {
            Map<?, ?> result = completionClient.post()
                    .uri(agentApiUrl + "/agent/review-draft/" + id + "/complete")
                    .contentType(MediaType.APPLICATION_JSON)
                    .header("X-User-Id", String.valueOf(userId))
                    .body(Map.of()).retrieve().body(Map.class);
            if (result != null && result.get("code") instanceof Number code && code.intValue() == 0) {
                return true;
            }
            log.warn("评价已写库，但草稿消费未确认 id={}", id);
        } catch (Exception e) {
            log.warn("评价已写库，但草稿消费未确认 id={}: {}", id, e.getMessage());
        }
        return false;
    }

    /** 商家分析（三技能）：门面先做归属校验（只能分析自己的店）再转发 */
    @Operation(summary = "商家分析（skill=ops|reviews|competitors，仅店主）")
    @PostMapping("/api/agent/merchant/analyze")
    public ApiResponse<?> analyze(@RequestBody Map<String, Object> body, HttpServletRequest request) {
        Long userId = requireUser(request);
        if (userId == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");
        String role = (String) request.getAttribute("role");
        if (!"MERCHANT".equals(role)) {
            return ApiResponse.fail(ErrorCode.FORBIDDEN, "只有商家可以使用经营分析");
        }
        // 归属校验：shopId 必须是自己名下的店（不信 body 直转发）
        Long shopId = body.get("shopId") instanceof Number n ? n.longValue() : null;
        if (shopId == null) return ApiResponse.fail(ErrorCode.PARAM_ERROR, "shopId 必填");
        var shop = shopRepo.findById(shopId).orElse(null);
        if (shop == null || !shop.getOwnerId().equals(userId)) {
            return ApiResponse.fail(ErrorCode.FORBIDDEN, "只能分析自己的店铺");
        }
        String skill = String.valueOf(body.getOrDefault("skill", "ops"));
        return forward(userId, "analyze-" + skill, "/agent/merchant/analyze", body);
    }

    // ==================== 转发与 trace ====================

    /**
     * trace 回放端点——本人最近 20 条；ADMIN 可带 all=true 看全站最近 50 条。
     * @CrossOrigin：独立 replay 页（file:// 打开）需要跨域；演示项目放开，生产应收紧到前端域名。
     */
    @Operation(summary = "Agent trace 回放（本人；ADMIN&all=true 看全部）")
    @GetMapping("/api/agent/traces")
    @CrossOrigin(origins = "*")
    public ApiResponse<?> traces(HttpServletRequest request,
                                 @RequestParam(defaultValue = "false") boolean all) {
        Long userId = requireUser(request);
        if (userId == null) return ApiResponse.fail(ErrorCode.UNAUTHORIZED, "未登录");
        String role = (String) request.getAttribute("role");
        List<AgentTrace> list = (all && "ADMIN".equals(role))
                ? traceRepo.findTop50ByOrderByIdDesc()
                : traceRepo.findTop20ByUserIdOrderByIdDesc(userId);
        return ApiResponse.ok(list.stream().map(this::toTraceDto).toList());
    }

    /** trace DTO：id/skill/输入/工具链/输出/时延（输出可能大，前端按需展开） */
    private Map<String, Object> toTraceDto(AgentTrace t) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", t.getId());
        m.put("userId", t.getUserId());
        m.put("skill", t.getSkill());
        m.put("input", parseJson(t.getInput()));
        m.put("tools", parseJson(t.getToolsJson()));
        m.put("output", parseJson(t.getOutput()));
        m.put("latencyMs", t.getLatencyMs());
        m.put("createdAt", t.getCreatedAt().toString());
        return m;
    }

    private Object parseJson(String json) {
        if (json == null) return null;
        try {
            return objectMapper.readValue(json, Object.class);
        } catch (Exception e) {
            return json;
        }
    }

    /** 转发通用管道：注入身份 → POST agent-api → 拆信封（业务码透传）→ 落 trace */
    private ApiResponse<?> forward(Long userId, String skill, String path, Map<String, Object> body) {
        long start = System.currentTimeMillis();
        try {
            Map<String, Object> resp = restClient.post()
                    .uri(agentApiUrl + path)
                    .contentType(MediaType.APPLICATION_JSON)
                    .header("X-User-Id", String.valueOf(userId))
                    .body(body)
                    .retrieve()
                    .body(Map.class);

            long latency = System.currentTimeMillis() - start;
            int code = resp != null && resp.get("code") != null
                    ? ((Number) resp.get("code")).intValue() : 50000;
            String message = resp != null && resp.get("message") != null
                    ? String.valueOf(resp.get("message")) : "agent-api 无响应";
            Object data = resp != null ? resp.get("data") : null;

            saveTrace(userId, skill, body, extractToolCalls(data), data, latency);
            if (code != 0) {
                return ApiResponse.fail(code, message);   // 透传：前端看到的码 = Agent 层的码
            }
            return ApiResponse.ok(data);
        } catch (Exception e) {
            long latency = System.currentTimeMillis() - start;
            log.error("agent-api 调用失败 skill={}: {}", skill, e.getMessage());
            saveTrace(userId, skill, body, List.of(), Map.of("error", String.valueOf(e.getMessage())), latency);
            return ApiResponse.fail(50000, "Agent 服务暂时不可用：" + e.getMessage());
        }
    }

    /** 从 agent-api 返回的 data 里抽 toolCalls（Python 三张图带回的工具清单） */
    private List<?> extractToolCalls(Object data) {
        if (data instanceof Map<?, ?> m && m.get("toolCalls") instanceof List<?> l) {
            return l;
        }
        return List.of();
    }

    private void saveTrace(Long userId, String skill, Object input, List<?> toolCalls,
                           Object output, long latencyMs) {
        try {
            AgentTrace t = new AgentTrace();
            t.setUserId(userId);
            t.setSkill(skill);
            t.setInput(objectMapper.writeValueAsString(input));
            t.setToolsJson(objectMapper.writeValueAsString(Map.of("skill", skill, "toolCalls", toolCalls)));
            t.setOutput(objectMapper.writeValueAsString(output));
            t.setLatencyMs((int) latencyMs);
            traceRepo.save(t);
        } catch (Exception e) {
            log.warn("trace 落库失败: {}", e.getMessage());
        }
    }

    private Long requireUser(HttpServletRequest request) {
        return (Long) request.getAttribute("userId");
    }
}
