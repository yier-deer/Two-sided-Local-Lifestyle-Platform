package com.scoutbite.shop.service;

import com.scoutbite.shop.entity.Shop;
import com.scoutbite.shop.repository.ShopRepository;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 地理服务：距离计算与附近检索的唯一实现。
 * 的 /internal/shops/search 将直接复用本类（Agent 与用户看到的"附近"必须同源）。
 *
 * 三步策略：
 *  ① SQL 方盒粗筛（bounding box，status=approved 强制过滤）
 *  ② Java Haversine 精算（盒的角落可能超出半径，这里精筛）
 *  ③ 按距离升序输出
 */
@Service
public class GeoService {

    /** 地球半径（米） */
    private static final double EARTH_RADIUS_M = 6371000;

    private final ShopRepository shopRepo;

    public GeoService(ShopRepository shopRepo) {
        this.shopRepo = shopRepo;
    }

    /**
     * Haversine 公式：两经纬度点的球面距离（米）。
     * a = sin²(Δlat/2) + cos(lat1)·cos(lat2)·sin²(Δlng/2)；d = 2R·asin(√a)
     */
    public static double haversine(double lat1, double lng1, double lat2, double lng2) {
        double dLat = Math.toRadians(lat2 - lat1);
        double dLng = Math.toRadians(lng2 - lng1);
        double a = Math.pow(Math.sin(dLat / 2), 2)
                + Math.cos(Math.toRadians(lat1)) * Math.cos(Math.toRadians(lat2))
                * Math.pow(Math.sin(dLng / 2), 2);
        return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(a));
    }

    /**
     * 附近检索：粗筛 → 精算过滤 → 排序。
     * @param lat,lng 用户坐标
     * @param radiusM 半径（米）
     * @param category 品类过滤（null = 全部）
     */
    public List<Map<String, Object>> nearby(double lat, double lng, int radiusM, String category) {
        // 度数换算：1 度纬度约 111km；经度圈随纬度收窄要乘 cos(lat)
        double latDelta = radiusM / 111000.0;
        double lngDelta = radiusM / (111000.0 * Math.cos(Math.toRadians(lat)));

        List<Shop> candidates = shopRepo.findInBox(
                lat - latDelta, lat + latDelta,
                lng - lngDelta, lng + lngDelta,
                category);

        List<Map<String, Object>> result = new ArrayList<>();
        for (Shop s : candidates) {
            double d = haversine(lat, lng, s.getLat(), s.getLng());
            if (d <= radiusM) {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("id", s.getId());
                m.put("name", s.getName());
                m.put("category", s.getCategory());
                m.put("lat", s.getLat());
                m.put("lng", s.getLng());
                m.put("distanceMeters", Math.round(d));
                result.add(m);
            }
        }
        result.sort(Comparator.comparingLong(m -> (Long) m.get("distanceMeters")));
        return result;
    }
}
