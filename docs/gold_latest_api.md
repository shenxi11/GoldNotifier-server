# `/api/v1/gold/latest` 接口说明

## 请求

- Method: `GET`
- Path: `/api/v1/gold/latest`
- Query:
  - `symbol`：行情标识，当前默认仅支持 `XAU`

## 响应结构

返回统一 envelope：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "name": "现货黄金",
    "symbol": "XAU",
    "price": 891.13,
    "change": 0.0,
    "changePercent": 0.0,
    "unit": "元/克",
    "open": 891.13,
    "prevClose": 891.13,
    "high": 891.13,
    "low": 891.13,
    "updateTime": "2026-06-11 17:16:11",
    "serverTime": "2026-06-11 17:16:11",
    "source": "finnhub",
    "marketStatus": "trading",
    "isStale": false
  }
}
```

## 字段说明

- `price`：当前价格
- `open`：今开，取当天第一条服务端新鲜历史行情
- `prevClose`：昨收，优先取前一天每日汇总的最后一条新鲜行情
- `high`：最高，取当天服务端新鲜历史行情最高价
- `low`：最低，取当天服务端新鲜历史行情最低价
- `unit`：单位，固定为 `元/克`
- `updateTime`：行情更新时间
- `serverTime`：服务端响应时间

## 说明

- 当前服务端已切换到 Finnhub 数据源，黄金/日元和美元/日元使用 Finnhub WebSocket 实时流式报价，美元/人民币汇率使用 Alpha Vantage `CURRENCY_EXCHANGE_RATE`。
- `/latest` 只读取服务端已经缓存的最新行情，客户端请求不会触发 Finnhub 或 Alpha Vantage 上游刷新。
- 服务端后台调度器默认每 `2` 秒刷新一次默认品种，启动后会立即执行第一轮刷新，用统一缓存供所有客户端读取。
- 最新行情短缓存默认保留 `10` 秒；短缓存过期但存在最近成功行情时，接口返回 `source="cache"`、`isStale=true` 的兜底数据。
- 服务端还没有任何成功行情缓存时，接口返回 `code=503`，等待后台调度器刷新成功后恢复。
- 后台刷新到新鲜行情时，服务端会同步追加写入当天历史行情，并更新当天每日汇总；回退缓存不会写入历史。
- 每日汇总中的 `close` 会随当天最后一条新鲜行情持续覆盖更新；日期结束后，该值即作为当天收盘价记录。
- `/latest` 返回时会用本地历史汇总覆盖上游 OHLC 兜底值：当天第一条作为 `open`，当天最高/最低作为 `high/low`，前一天 `close` 作为今天的 `prevClose`。
- 如果前一天没有每日汇总记录，`prevClose` 会保留上游或兜底值，避免因历史缺口导致接口不可用。
- `open`、`prevClose`、`high`、`low`、`price` 都保持数值型，便于客户端直接展示和计算。
- 如果 Alpha Vantage 汇率临时失败，服务端会优先使用进程内最近成功美元/人民币汇率；仍不可用时使用 `USD_CNY_FALLBACK_RATE` 配置兜底，并返回 `isStale=true` 提醒客户端行情可能延迟。
- 现有 Finnhub WebSocket 只提供实时现价，服务端不再依赖 Finnhub OHLC 字段生成客户端展示用的 `open`、`prevClose`、`high`、`low`。
