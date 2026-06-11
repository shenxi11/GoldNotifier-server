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
    "open": 890.77,
    "prevClose": 890.77,
    "high": 891.20,
    "low": 890.70,
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
- `open`：今开
- `prevClose`：昨收
- `high`：最高
- `low`：最低
- `unit`：单位，固定为 `元/克`
- `updateTime`：行情更新时间
- `serverTime`：服务端响应时间

## 说明

- 当前服务端已切换到 Finnhub 数据源。
- 客户端每次请求都会触发一次上游刷新，失败时才回退最近成功缓存。
- `open`、`prevClose`、`high`、`low`、`price` 都保持数值型，便于客户端直接展示和计算。
