# Deployment Information — Day 14 Final Project

## Public URL
> **TODO (CP6):** Thay URL bên dưới bằng URL thật sau khi chạy `railway domain` (hoặc deploy trên Render):

`https://<your-agent-service>.up.railway.app`

## Platform
**Railway** (Docker build từ `06-lab-complete/Dockerfile` + Railway Redis plugin)

### Quy trình deploy nhanh từ `06-lab-complete/`
```bash
cd 06-lab-complete
npm i -g @railway/cli
railway login
railway init
# Trên Railway Dashboard: + New -> Database -> Add Redis
# Liên kết biến REDIS_URL=${{Redis.REDIS_URL}} cho service agent
railway variables set ENVIRONMENT=production RATE_LIMIT_PER_MINUTE=10 DAILY_BUDGET_USD=1.0 MONTHLY_BUDGET_USD=10.0 AGENT_API_KEY="<sinh-key-bi-mat-khong-commit>"
railway up
railway domain
```

## Test Commands (4 lệnh tự kiểm chuẩn CP6)

```bash
export BASE="https://<your-agent-service>.up.railway.app"
export AGENT_API_KEY="<your-secret-api-key>"

# 1. Liveness check -> 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"

# 2. Readiness check (kết nối Redis thành công) -> 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"

# 3. Gọi /ask không có X-API-Key -> 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -d '{"question":"Hello"}'

# 4. Gọi /ask có X-API-Key hợp lệ -> 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $AGENT_API_KEY" \
  -d '{"user_id":"test","question":"What is deployment?"}'
```

### Kiểm tra tự động kèm Public URL
```bash
cd 06-lab-complete
python check_production_ready.py --public-url "$BASE"
```

## Environment Variables Set (trên Cloud Dashboard, không lưu secret trong Git)
- `PORT` (Railway/Render tự động cấp phát và inject vào container)
- `ENVIRONMENT` (`production`)
- `REDIS_URL` (kết nối tới managed Redis instance trên Railway/Render)
- `AGENT_API_KEY` (secret sinh riêng trên nền tảng, không hardcode trong code)
- `RATE_LIMIT_PER_MINUTE` (`10`)
- `DAILY_BUDGET_USD` (`1.0`)
- `MONTHLY_BUDGET_USD` (`10.0`)
- `LOG_LEVEL` (`INFO`)

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
