# `/api/v1/gold/history` 接口说明

## 请求

- Method: `GET`
- Path: `/api/v1/gold/history`
- Query:
  - `symbol`：行情标识，当前默认仅支持 `XAU`
  - `date`：可选，格式 `YYYY-MM-DD`；默认使用 `Asia/Shanghai` 当天
  - `startMillis`：可选，Unix 毫秒时间戳，作为查询窗口起点
  - `endMillis`：可选，Unix 毫秒时间戳，作为查询窗口终点
  - `limit`：可选，默认 `2000`，最大按 `10000` 截断

## 响应结构

返回统一 envelope：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "symbol": "XAU",
    "date": "2026-06-15",
    "timezone": "Asia/Shanghai",
    "count": 2,
    "points": [
      {
        "timestampMillis": 1781519739000,
        "price": 943.08,
        "updateTime": "2026-06-15 20:35:39",
        "serverTime": "2026-06-15 20:35:39",
        "source": "finnhub"
      }
    ]
  }
}
```

## 存储策略

- 历史行情写入 Redis ZSet，key 为 `gold:history:{SYMBOL}:{YYYY-MM-DD}`。
- ZSet score 使用 `timestampMillis`，value 为精简历史点 JSON。
- 每次写入新鲜历史点后，会同步更新每日汇总 key `gold:daily_summary:{SYMBOL}:{YYYY-MM-DD}`。
- 每日汇总保存当天第一条价格 `open`、最高价 `high`、最低价 `low` 和最后一条价格 `close`。
- 如果每日汇总 key 缺失，服务端会从已有历史行情回填汇总并写回 Redis。
- `/api/v1/gold/latest` 使用当天每日汇总计算 `open/high/low`，使用前一天每日汇总的 `close` 作为今天的 `prevClose`。
- 只有成功刷新且 `isStale=false`、`source!="cache"`、`price>0` 的行情会进入历史。
- 上游失败回退的缓存行情不会写入历史，避免污染趋势图。
- 历史 key 默认保留 `2` 天，可通过 `HISTORY_RETENTION_DAYS` 调整。
- Redis 写历史失败只记录日志，不影响 `/api/v1/gold/latest` 返回。

## 说明

- 本接口只读取服务端已经采集到的新鲜行情点，不主动刷新第三方上游。
- 空历史返回 `code=0`、`count=0` 和空数组。
- 当前只支持默认品种 `XAU`，其他 symbol 会返回业务错误。
