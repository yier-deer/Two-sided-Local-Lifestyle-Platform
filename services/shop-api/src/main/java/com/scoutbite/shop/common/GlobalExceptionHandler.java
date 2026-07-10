package com.scoutbite.shop.common;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

/**
 * 全局异常兜底（升级：从一张大网变成两张网）。
 * 细网：参数类异常 → 40001（遗留问题的修复：缺参/类型错/坏 JSON 不再掉进 50000）
 * 粗网：其余未预期异常 → 50000（真实堆栈只进日志）
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    /** 细网①：缺必填参数（如 nearby 不传 lat）→ 40001 */
    @ExceptionHandler(MissingServletRequestParameterException.class)
    public ApiResponse<Void> missingParam(MissingServletRequestParameterException e) {
        return ApiResponse.fail(ErrorCode.PARAM_ERROR, "缺少必填参数: " + e.getParameterName());
    }

    /** 细网②：参数类型不匹配（如 lat=abc）→ 40001 */
    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ApiResponse<Void> typeMismatch(MethodArgumentTypeMismatchException e) {
        return ApiResponse.fail(ErrorCode.PARAM_ERROR, "参数类型错误: " + e.getName());
    }

    /** 细网③：请求体不是合法 JSON → 40001 */
    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ApiResponse<Void> badBody(HttpMessageNotReadableException e) {
        return ApiResponse.fail(ErrorCode.PARAM_ERROR, "请求体不是合法 JSON");
    }

    /** 细网④：路径不存在的接口 → 40001（比 Spring 默认 404 页友好，且保持信封格式） */
    @ExceptionHandler(NoResourceFoundException.class)
    @ResponseStatus(HttpStatus.NOT_FOUND)
    public ApiResponse<Void> notFound(NoResourceFoundException e) {
        return ApiResponse.fail(ErrorCode.PARAM_ERROR, "接口不存在: " + e.getResourcePath());
    }

    /** 细网⑤（）：业务异常（带 ErrorCode）→ 各业务码。交易主链路的正产出口 */
    @ExceptionHandler(com.scoutbite.shop.service.OrderService.BizException.class)
    public ApiResponse<Void> bizException(com.scoutbite.shop.service.OrderService.BizException e) {
        return ApiResponse.fail(e.code, e.getMessage());
    }

    /** 粗网：最后一道防线。50000 系统码；堆栈只进日志，按 requestId 追 */
    @ExceptionHandler(Exception.class)
    @ResponseStatus(HttpStatus.INTERNAL_SERVER_ERROR)
    public ApiResponse<Void> handleUnexpected(Exception e) {
        String requestId = java.util.UUID.randomUUID().toString().substring(0, 8);
        log.error("[{}] 未预期异常: {}", requestId, e.getMessage(), e);
        ApiResponse<Void> r = new ApiResponse<>();
        r.setCode(50000);
        r.setMessage("系统繁忙，请稍后再试");
        r.setRequestId(requestId);
        return r;
    }
}
