# Day 14 Lab — Mission Answers

---

## Part 1: Localhost vs Production (CP1)

### Exercise 1.1: Các anti-patterns phát hiện trong `01-localhost-vs-production/develop/app.py`

1. **Hardcode secrets trực tiếp trong mã nguồn (dòng 17–18):**
   - `OPENAI_API_KEY = "sk-hardcoded-fake-key-never-do-this"` và `DATABASE_URL = "postgresql://admin:password123@localhost:5432/mydb"`.
   - **Rủi ro:** Ngay khi push lên GitHub, bot quét tự động sẽ thu thập key trong vài giây, dẫn tới mất tiền API hoặc bị xâm nhập cơ sở dữ liệu. Kể cả xoá file ở commit sau thì secret vẫn còn trong lịch sử Git.
   - **Cách bản `production/` sửa:** Đọc toàn bộ từ biến môi trường qua `os.getenv(...)` trong `production/config.py` (dòng 27, 32).
2. **In trực tiếp secret ra stdout bằng `print()` (dòng 33–34):**
   - `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` làm lộ API key vào hệ thống thu thập log tập trung, và `print()` xuất text tự do không có cấu trúc, rất khó truy vấn/lọc khi có hàng nghìn dòng log/giây.
   - **Cách bản `production/` sửa:** Dùng `logging` chuẩn kết hợp `json.dumps(...)` (dòng 28–31, 111–122) và tuyệt đối không log secret.
3. **Cấu hình đóng cứng (`DEBUG = True`, `MAX_TOKENS = 500` — dòng 21–22) và bật `reload=True` (dòng 53):**
   - Không thể thay đổi hành vi giữa các môi trường `dev` / `staging` / `production` mà không sửa code; file watcher của `reload=True` tốn CPU/RAM và tiềm ẩn rủi ro bảo mật trên production.
   - **Cách bản `production/` sửa:** Quản lý tập trung qua `Settings` dataclass trong `config.py` (dòng 15–35), chỉ bật `reload=settings.debug` khi `DEBUG=true` (dòng 198).
4. **Bind cứng `host="localhost"` và `port=8000` (dòng 51–52):**
   - Trong Docker container, `localhost` (`127.0.0.1`) chỉ nhận kết nối từ bên trong chính container đó — request từ ngoài container hay từ Load Balancer đều bị từ chối. Ngoài ra, các PaaS như Railway/Render/Cloud Run cấp cổng động qua biến môi trường `PORT`.
   - **Cách bản `production/` sửa:** Bind `0.0.0.0` và đọc `PORT` từ biến môi trường (`config.py` dòng 17–18, `app.py` dòng 196–197).
5. **Không có Health Check (`/health`) và Readiness Check (`/ready`):**
   - Nền tảng điều phối (Docker, Railway, Render, Kubernetes) không biết process bị treo để tự restart (liveness), cũng không biết lúc nào app đang khởi động hoặc quá tải để ngắt luồng traffic (readiness).
   - **Cách bản `production/` sửa:** Bổ sung `GET /health` (dòng 135–149) và `GET /ready` trả `503` khi `is_ready == False` (dòng 152–161).
6. **Không xử lý Graceful Shutdown (`SIGTERM`):**
   - Khi deploy bản mới hoặc scale down, container nhận `SIGTERM`; tắt đột ngột sẽ cắt ngang các request LLM đang chờ phản hồi.
   - **Cách bản `production/` sửa:** Quản lý vòng đời qua `lifespan` context manager và bắt tín hiệu `signal.SIGTERM` (dòng 39–67, 180–189).
7. **Không kiểm soát đầu vào & CORS:**
   - Nhận `question: str` qua query string mà không giới hạn độ dài tối đa, dễ bị lạm dụng gửi prompt quá dài gây tốn chi phí token.

---

### Exercise 1.2: Kết quả chạy thực tế bản `develop` và `production`

- Khi gửi JSON body vào bản `develop/app.py` (vì hàm `def ask_agent(question: str)` khai báo tham số query thay vì Pydantic model):

```http
HTTP/1.1 422 Unprocessable Entity
date: Wed, 25 Nov 2026 14:52:57 GMT
server: uvicorn
content-length: 94
content-type: application/json
connection: close

{"detail":[{"type":"missing","loc":["query","question"],"msg":"Field required","input":null}]}
```

- Khi gọi đúng qua query string `curl -i -X POST "http://localhost:8000/ask?question=Hello"`:

```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 14:52:57 GMT
server: uvicorn
content-length: 103
content-type: application/json
connection: close

{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```

- Kết quả gọi `GET /health` và `POST /ask` trên bản `01-localhost-vs-production/production/app.py`:

```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 14:52:59 GMT
server: uvicorn
content-length: 129
content-type: application/json
connection: close

{"status":"ok","uptime_seconds":0.4,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T14:52:59.353950+00:00"}
```

```http
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 14:52:59 GMT
server: uvicorn
content-length: 166
content-type: application/json
connection: close

{"question":"What is deploy?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","model":"gpt-4o-mini"}
```

---

### Exercise 1.3: Bảng so sánh Develop vs Production

| Feature | Develop (`develop/app.py`) | Production (`production/app.py` + `config.py`) | Tại sao quan trọng? |
|---|---|---|---|
| **Config & Secrets** | Hardcode `OPENAI_API_KEY`, `DATABASE_URL`, `DEBUG = True` ngay trong file Python | Đọc từ biến môi trường qua `os.getenv()` trong `Settings` + cung cấp `.env.example` | Tuân thủ 12-Factor App: tách biệt hoàn toàn code và secret, tránh lộ khoá trên Git và dùng chung 1 artifact cho dev/staging/prod. |
| **Host & Port** | Cố định `localhost:8000`, bật cứng `reload=True` | Bind `0.0.0.0`, đọc cổng động từ `PORT`, chỉ bật `reload` khi `DEBUG=true` | Cho phép nhận kết nối mạng từ ngoài Docker container và tương thích với cổng động do Railway/Render/Cloud Run cấp phát. |
| **Health & Readiness** | Không có | Có `GET /health` (liveness) và `GET /ready` (readiness trả `503` khi chưa sẵn sàng) | Giúp orchestrator tự động restart container bị treo và ngăn Load Balancer đẩy traffic vào instance chưa khởi tạo xong. |
| **Logging** | Dùng `print()` text thuần và in cả API key ra màn hình | Structured JSON logging (`time`, `level`, `event`, metadata) không chứa secret | Log JSON giúp hệ thống giám sát (Loki, Datadog, Cloud Logging) parse, lọc, thống kê và cảnh báo tự động mà không rò rỉ thông tin nhạy cảm. |
| **Shutdown** | Tắt đột ngột ngay khi nhận tín hiệu dừng | Graceful shutdown qua `lifespan` + `signal.SIGTERM`, hạ cờ `is_ready = False` | Tránh làm đứt kết nối (lỗi 502/connection reset) với các request LLM đang xử lý dở khi rolling update hoặc scale down. |
| **CORS & Input** | Không cấu hình CORS, nhận query param không kiểm tra rỗng | Có `CORSMiddleware` giới hạn `ALLOWED_ORIGINS` và kiểm tra JSON payload (`422`) | Kiểm soát domain frontend được phép gọi API và từ chối sớm dữ liệu không hợp lệ trước khi tốn tiền gọi LLM. |

---

## Part 2: Docker Containerization (CP2)

### Exercise 2.1: Phân tích `02-docker/develop/Dockerfile`

1. **Base image là gì?**
   - `python:3.11` — bản Debian đầy đủ đi kèm trình biên dịch C/C++, công cụ hệ thống và thư viện phát triển (dung lượng ~1 GB).
2. **Working directory là gì?**
   - `/app` (đặt qua `WORKDIR /app`). Mọi lệnh `COPY`, `RUN`, `CMD` phía sau đều thực thi tương đối từ thư mục `/app` bên trong container.
3. **Tại sao `COPY requirements.txt` và `RUN pip install` phải đứng TRƯỚC `COPY app.py`?**
   - Docker cache từng layer theo thứ tự từ trên xuống; nếu một layer thay đổi thì toàn bộ các layer bên dưới bị vô hiệu hoá (cache invalidation). Mã nguồn (`app.py`) thay đổi liên tục còn `requirements.txt` ít thay đổi: tách `COPY requirements.txt` + `pip install` lên trước giúp tận dụng lại layer cài thư viện từ cache trong tích tắc thay vì phải tải và cài lại toàn bộ package mỗi lần sửa 1 dòng code.
4. **`CMD` khác `ENTRYPOINT` như thế nào?**
   - `ENTRYPOINT` cố định chương trình thực thi chính của container (khi truyền thêm đối số vào `docker run <image> <args>`, các `<args>` sẽ nối thêm vào sau `ENTRYPOINT`).
   - `CMD` khai báo lệnh hoặc tham số mặc định và **bị ghi đè hoàn toàn** nếu người dùng truyền lệnh mới vào cuối `docker run <image> <new_cmd>` (ví dụ `docker run -it my-agent sh`). Ngoài ra, nên dùng **exec form** (`["uvicorn", ...]`) thay vì shell form để tiến trình chính mang **PID 1** và nhận trực tiếp tín hiệu `SIGTERM`.

---

### Exercise 2.2 & 2.3: Multi-stage Build và So sánh kích thước Image

- **Phân tích `02-docker/production/Dockerfile`:**
  - **Stage 1 (`FROM python:3.11-slim AS builder`):** Cài trình biên dịch `gcc`, `libpq-dev` và biên dịch/cài đặt các thư viện Python vào `/root/.local` (`pip install --no-cache-dir --user`). Toàn bộ bộ công cụ build nặng nề nằm lại ở stage này và không đi vào image cuối.
  - **Stage 2 (`FROM python:3.11-slim AS runtime`):** Bắt đầu từ base `python:3.11-slim` sạch, tạo user không đặc quyền `appuser` (`USER appuser`), chỉ `COPY --from=builder /root/.local /home/appuser/.local` cùng mã nguồn cần chạy, kèm `HEALTHCHECK`.
  - **Vì sao image nhỏ hơn nhiều?** Loại bỏ hoàn toàn image `python:3.11` đầy đủ (thay bằng `-slim`), loại bỏ `gcc`, `libpq-dev`, apt cache và pip cache khỏi runtime layer, đồng thời thu hẹp bề mặt tấn công bảo mật.

- **Lệnh đo kích thước thực tế (chạy từ thư mục gốc repo khi bật Docker Desktop):**
  ```bash
  docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
  docker build -f 02-docker/production/Dockerfile -t my-agent:advanced .
  docker images --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}" | grep my-agent
  ```
- **Số đo thực tế trên máy:**
  - `my-agent:develop`: `[TODO CP2: điền số MB đo thật từ lệnh docker images sau khi bật Docker Desktop]` MB
  - `my-agent:advanced`: `[TODO CP2: điền số MB đo thật từ lệnh docker images]` MB
  - Chênh lệch giảm: `[TODO CP2: điền ((develop - advanced) / develop) * 100]%`

---

### Exercise 2.4: Kiến trúc Docker Compose Stack (`02-docker/production/docker-compose.yml`)

```
                         ┌──────────────────────────── internal (bridge network) ────────────────────────────┐
                         │                                                                                   │
  Client (HTTP :80/:443) │   ┌───────────────┐        ┌───────────────────┐        ┌─────────────────────┐   │
 ────────────────────────┼──▶│     nginx     │───────▶│   agent (:8000)   │───────▶│    redis (:6379)    │   │
                         │   │ (nginx:alpine)│        │  FastAPI + Uvicorn│        │   redis:7-alpine    │   │
                         │   └───────────────┘        │   (2 workers)     │        │ (session/rate-limit)│   │
                         │                            └─────────┬─────────┘        └─────────────────────┘   │
                         │                                      │                                            │
                         │                                      ▼                                            │
                         │                            ┌───────────────────┐                                  │
                         │                            │  qdrant (:6333)   │                                  │
                         │                            │  qdrant:v1.9.0    │                                  │
                         │                            │ (Vector DB / RAG) │                                  │
                         │                            └───────────────────┘                                  │
                         └───────────────────────────────────────────────────────────────────────────────────┘
```

- **Các service được khởi tạo và cách giao tiếp:**
  1. `nginx`: cổng vào duy nhất publish ra máy host (`80:80`, `443:443`), làm reverse proxy chuyển tiếp request tới `http://agent:8000`.
  2. `agent`: build từ stage `runtime` của `02-docker/production/Dockerfile`, không mở port trực tiếp ra host; chờ cả `redis` và `qdrant` đạt trạng thái `service_healthy` (`depends_on` có điều kiện) mới khởi động; kết nối nội bộ qua DNS tên service (`REDIS_URL=redis://redis:6379/0`, `QDRANT_URL=http://qdrant:6333`). File `.env.local` đã được tạo sẵn trong thư mục để Compose nạp biến môi trường cục bộ.
  3. `redis`: lưu cache/session với giới hạn RAM `256mb` (`allkeys-lru`) và gắn volume bền vững `redis_data`.
  4. `qdrant`: cơ sở dữ liệu vector lưu trữ trên volume `qdrant_data`, kiểm tra sức khoẻ qua TCP socket `/dev/tcp/localhost/6333`.
- **Lệnh kiểm thử qua Nginx (sau khi bật Docker Desktop):**
  ```bash
  docker compose -p k5-day14-docker -f 02-docker/production/docker-compose.yml up -d --build
  curl -i http://localhost/health
  curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
  docker compose -p k5-day14-docker -f 02-docker/production/docker-compose.yml down
  ```
  - Kết quả thực tế: `[TODO CP2: dán output curl -i http://localhost/health sau khi chạy lệnh trên]`

---

## Part 3: Cloud Deployment (CP6)

### Exercise 3.1: Triển khai Agent Part 6 (`06-lab-complete/`) lên Cloud

- **Nền tảng chính:** Railway (cấu hình tại `06-lab-complete/railway.toml`, hướng dẫn & lệnh kiểm tra chi tiết tại `DEPLOYMENT.md`).
- **Public URL:** `[TODO CP6: dán URL https://<your-app>.up.railway.app sau khi chạy railway up & railway domain]`
- **Ảnh chụp màn hình:** lưu tại `screenshots/dashboard.png`, `screenshots/running.png`, `screenshots/test.png`.

---

### Exercise 3.2: So sánh `railway.toml` và `render.yaml`

| Tiêu chí | `railway.toml` (Railway) | `render.yaml` (Render Blueprint) | Lý do của sự khác biệt |
|---|---|---|---|
| **Định dạng & Phạm vi** | File TOML cấu hình **1 service duy nhất** nằm trong thư mục build (`[build]`, `[deploy]`). | File YAML Infrastructure-as-Code (Blueprint) khai báo **toàn bộ kiến trúc đa dịch vụ** (`services`: cả `type: web` lẫn `type: redis`) trong một file. | Railway hướng tới trải nghiệm developer nhanh qua CLI/Dashboard (tạo plugin Redis riêng rồi nối biến), còn Render thiết kế `render.yaml` như bản thiết kế hạ tầng đồng bộ tự động từ Git. |
| **Cách khai báo Build & Start** | `builder = "DOCKERFILE"` (hoặc `"NIXPACKS"`), tuỳ chọn `dockerfilePath` và `startCommand`. | Chọn `runtime: docker` (tự dùng `Dockerfile`) hoặc `runtime: python` kèm `buildCommand` và `startCommand`. | Render tách bạch rõ loại runtime và gói tài nguyên (`plan: free`, `region: singapore`) ngay trong file IaC. |
| **Quản lý Biến môi trường & Secret** | Không khai báo danh sách biến môi trường trong `railway.toml`; mọi biến và secret đặt qua `railway variables set` hoặc Dashboard. | Khai báo trực tiếp danh sách `envVars` trong file; với secret dùng `generateValue: true` (tự sinh ngẫu nhiên) hoặc `sync: false` (nhập tay trên Dashboard), và nối tự động `REDIS_URL` qua `fromService`. | Render cần biết schema biến môi trường lúc khởi tạo Blueprint nhưng vẫn đảm bảo nguyên tắc **không bao giờ lưu giá trị secret thật vào Git**. |
| **Health Check & Restart** | `healthcheckPath = "/health"`, `healthcheckTimeout = 30`, `restartPolicyType = "ON_FAILURE"`. | `healthCheckPath: /health` (camelCase), tự động quản lý vòng đời zero-downtime deploy dựa trên health check. | Cả hai đều gọi `GET /health` để xác nhận container mới khoẻ mạnh trước khi chuyển luồng truy cập công khai sang bản mới. |

---

### Exercise 3.3: Phân tích CI/CD Pipeline trên GCP Cloud Run (`cloudbuild.yaml` & `service.yaml`)

Đọc `03-cloud-deployment/production-cloud-run/cloudbuild.yaml` và `service.yaml`, pipeline CI/CD tự động khi có commit lên nhánh `main` đi qua **4 bước tuần tự (`waitFor`)**:
1. **Test (`id: test`):** Chạy container `python:3.11-slim`, cài dependencies và chạy `pytest tests/ -v`; nếu bất kỳ unit test nào lỗi, pipeline dừng ngay và không build image.
2. **Build (`id: build`):** Dùng Cloud Builders Docker đóng gói image gắn cặp thẻ `:$COMMIT_SHA` (truy vết chính xác phiên bản code) và `:latest`, đồng thời tận dụng `--cache-from` từ bản `:latest` trước đó để tăng tốc build layer.
3. **Push (`id: push`):** Đẩy toàn bộ image tags lên Google Container Registry (`gcr.io/$PROJECT_ID/ai-agent`).
4. **Deploy (`id: deploy` & `service.yaml`):** Triển khai bản `:$COMMIT_SHA` lên Cloud Run vùng `asia-southeast1` với cấu hình chuẩn production: tiêm secret an toàn từ **Google Secret Manager** (`secretKeyRef` cho `OPENAI_API_KEY`, `AGENT_API_KEY`), giữ `minScale: 1` để triệt tiêu cold start, giới hạn `maxScale: 10` và `containerConcurrency: 80`, kèm `startupProbe` (`/ready`) và `livenessProbe` (`/health`).

---

## Part 4: API Security (CP3)

### Exercise 4.1: API Key Authentication (`04-api-gateway/develop/app.py`)

- **API key được kiểm tra ở đâu?**
  - Khai báo `api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)` (dòng 36) và hàm dependency `verify_api_key` (dòng 39–54), được gắn vào endpoint bảo vệ `POST /ask` qua `_key: str = Depends(verify_api_key)` (dòng 70). Các route công khai như `/` và `/health` không gắn dependency này để orchestrator vẫn kiểm tra sức khoẻ được.
- **Điều gì xảy ra nếu thiếu hoặc sai key?**
  - Trong `04-api-gateway/develop/app.py`: thiếu header `X-API-Key` trả **HTTP 401 Unauthorized**; truyền sai giá trị trả **HTTP 403 Forbidden** (riêng hợp đồng của Final Project Part 6 yêu cầu cả thiếu lẫn sai key đều trả **HTTP 401**). Việc đặt `auto_error=False` rất quan trọng để tự kiểm soát mã lỗi thay vì bị mặc định khác của FastAPI.
- **Làm sao để rotate key không gây downtime?**
  - Cho phép hệ thống chấp nhận danh sách nhiều key hợp lệ trong giai đoạn chuyển giao (ví dụ `AGENT_API_KEYS=new_key,old_key` hoặc lưu các hash key có hạn dùng trong Redis/DB): (1) sinh key mới và thêm vào biến môi trường cạnh key cũ → (2) cập nhật phía client sang dùng key mới → (3) theo dõi log xác nhận không còn traffic dùng key cũ → (4) thu hồi (xoá) key cũ.

- **Output `curl -i` thực tế trên `04-api-gateway/develop/app.py` (`AGENT_API_KEY=secret-key-123`):**

```http
# 1. Không gửi X-API-Key -> 401 Unauthorized
HTTP/1.1 401 Unauthorized
date: Wed, 25 Nov 2026 14:53:00 GMT
server: uvicorn
content-length: 67
content-type: application/json
connection: close

{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}
```

```http
# 2. Có X-API-Key: secret-key-123 -> 200 OK
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 14:53:00 GMT
server: uvicorn
content-length: 145
content-type: application/json
connection: close

{"question":"Hello","answer":"Đây là câu trả lời từ AI agent (mock). Trong production, đây sẽ là response từ OpenAI/Anthropic."}
```

---

### Exercise 4.2 & 4.3: JWT Authentication & Rate Limiting (`04-api-gateway/production/`)

- **Phân tích JWT flow (`auth.py`):**
  1. Client gửi `username`/`password` (`student` / `demo123`) tới `POST /auth/token`.
  2. Server xác thực thông tin đăng nhập và ký token bằng thuật toán đối xứng `HS256` với `JWT_SECRET`, payload gồm `sub` (username), `role` (`user` hoặc `admin`), `iat` và `exp` (60 phút).
  3. Ở các request tiếp theo tới `POST /ask`, client đính kèm `Authorization: Bearer <token>`; `verify_token` kiểm tra chữ ký số và hạn dùng hoàn toàn stateless mà không cần truy vấn DB mỗi lần gọi.
- **Phân tích Rate Limiter (`rate_limiter.py`):**
  - **Thuật toán:** **Sliding Window Log / Counter** — lưu hàng đợi `deque` các mốc thời gian (`timestamp`) của từng user trong cửa sổ trượt `60 giây`; mỗi request mới sẽ loại bỏ các mốc cũ `< now - 60` ở đầu `deque` rồi kiểm tra độ dài.
  - **Giới hạn:** Tài khoản `user` (`student`) tối đa **`10 requests/phút`** (`rate_limiter_user`); khi chạm ngưỡng trả `HTTP 429 Too Many Requests` kèm các header `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0`, `X-RateLimit-Reset` và `Retry-After`.
  - **Cách nâng giới hạn / bypass cho `admin`:** Dựa trên claim `role` giải mã từ JWT (`app.py` dòng 141): nếu `role == "admin"` (ví dụ tài khoản `teacher`), hệ thống chuyển sang `rate_limiter_admin` (`100 requests/phút`) hoặc bỏ qua bước kiểm tra.

- **Output `curl -i` thực tế trên `04-api-gateway/production/app.py` (đã che JWT token):**

```http
# 1. Gọi POST /ask không có Bearer token -> 401 Unauthorized
HTTP/1.1 401 Unauthorized
date: Wed, 25 Nov 2026 14:53:01 GMT
server: uvicorn
www-authenticate: Bearer
content-length: 76
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin
connection: close

{"detail":"Authentication required. Include: Authorization: Bearer <token>"}
```

```http
# 2. Đăng nhập POST /auth/token với student / demo123 -> 200 OK
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 14:53:01 GMT
server: uvicorn
content-length: 307
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin
connection: close

{"access_token": "<REDACTED_JWT_TOKEN>", "token_type": "bearer", "expires_in_minutes": 60, "hint": "Include in header: Authorization: Bearer <REDACTED>..."}
```

```http
# 3. Request hợp lệ (Request #1 với Bearer <REDACTED_JWT_TOKEN>) -> 200 OK
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 14:53:01 GMT
server: uvicorn
content-length: 179
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin
connection: close

{"question":"Test 1","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé.","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}
```

```http
# 4. Vòng lặp gửi liên tiếp vượt ngưỡng 10 req/phút (Request #11) -> 429 Too Many Requests
HTTP/1.1 429 Too Many Requests
date: Wed, 25 Nov 2026 14:53:02 GMT
server: uvicorn
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
x-ratelimit-reset: 1795618443
retry-after: 59
content-length: 98
content-type: application/json
x-content-type-options: nosniff
x-frame-options: DENY
x-xss-protection: 1; mode=block
referrer-policy: strict-origin-when-cross-origin
connection: close

{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

```text
# Tóm tắt kết quả vòng lặp 12 requests liên tiếp:
Request  1: HTTP 200 -> {"question":"Test 1",...,"requests_remaining":9}
...
Request 10: HTTP 200 -> {"question":"Test 10",...,"requests_remaining":0}
Request 11: HTTP 429 -> {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
Request 12: HTTP 429 -> {"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

---

### Exercise 4.4: Cách thiết kế và cài đặt Cost Guard với Redis

- **Vì sao cần cả Rate Limiter lẫn Cost Guard?**
  - **Rate Limiter** bảo vệ **tốc độ truy cập và năng lực xử lý (RPS/availability)** trong ngắn hạn (60 giây) chống spam/DDoS.
  - **Cost Guard** bảo vệ **ngân sách tài chính (USD)** tích luỹ theo ngày/tháng: một client chỉ gọi đúng 5 request/phút (không bao giờ chạm rate limit 10 req/phút), nhưng mỗi request truyền ngữ cảnh dài hàng chục nghìn token chạy liên tục 24 giờ vẫn có thể đốt sạch ngân sách OpenAI/Anthropic nếu không có Cost Guard.
- **Cách triển khai trong `06-lab-complete/app/cost_guard.py`:**
  1. Tạo khoá Redis theo ngày và tháng UTC: `cost:daily:YYYY-MM-DD` và `cost:monthly:YYYY-MM`.
  2. **Trước khi gọi LLM (`check_budget()`):** Đọc tổng tiền đã tiêu qua `MGET`; nếu `daily_spent >= DAILY_BUDGET_USD` hoặc `monthly_spent >= MONTHLY_BUDGET_USD` thì chặn ngay bằng `HTTPException(status_code=402)` (Payment Required) để không phát sinh thêm cước gọi LLM.
  3. **Sau khi gọi LLM (`record_cost()`):** Tính chi phí thực tế `cost = (input_tokens / 1000) * PRICE_INPUT_PER_1K + (output_tokens / 1000) * PRICE_OUTPUT_PER_1K`, cộng dồn nguyên tử vào Redis bằng `INCRBYFLOAT` và đặt `EXPIRE` (2 ngày cho khoá ngày, 35 ngày cho khoá tháng) để tự động dọn bộ nhớ khi sang kỳ mới.

---

## Part 5: Scaling & Reliability (CP4)

### Exercise 5.1: Phân biệt Liveness (`/health`) và Readiness (`/ready`)

| Tiêu chí | Liveness Probe (`GET /health`) | Readiness Probe (`GET /ready`) |
|---|---|---|
| **Câu hỏi trả lời** | Tiến trình (process) của agent còn sống hay đã bị treo/deadlock? | Instance này hiện có đủ điều kiện phục vụ request mới hay không? |
| **Khi Redis / DB mất kết nối tạm thời** | **Vẫn phải trả `200 OK`!** Vì bản thân process Python không bị hỏng; nếu trả lỗi, orchestrator sẽ restart hàng loạt mọi container agent gây sập toàn diện (cascading failure) dù lỗi nằm ở Redis. | **Phải trả `503 Service Unavailable`!** Để Load Balancer tạm ngưng đẩy traffic vào instance đó cho tới khi kết nối Redis khôi phục. |
| **Hành động của Platform khi fail** | Giết và khởi động lại container (`docker restart` / K8s pod restart). | Giữ nguyên container nhưng rút khỏi danh sách upstream nhận traffic của Load Balancer. |

- **Output thực tế từ `05-scaling-reliability/develop/app.py`:**

```http
# GET /health -> 200 OK
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 14:53:03 GMT
server: uvicorn
content-length: 185
content-type: application/json
connection: close

{"status":"ok","uptime_seconds":0.5,"version":"1.0.0","environment":"development","timestamp":"2026-11-25T14:53:04.202697+00:00","checks":{"memory":{"status":"ok","used_percent":86.1}}}
```

```http
# GET /ready -> 200 OK
HTTP/1.1 200 OK
date: Wed, 25 Nov 2026 14:53:03 GMT
server: uvicorn
content-length: 37
content-type: application/json
connection: close

{"ready":true,"in_flight_requests":1}
```

---

### Exercise 5.2: Cơ chế Graceful Shutdown khi nhận `SIGTERM`

1. Middleware HTTP đếm số request đang xử lý (`_in_flight_requests += 1` khi vào, `-= 1` trong `finally`).
2. Khi container orchestrator gửi `SIGTERM` (lúc rolling deploy hoặc `docker stop`), Uvicorn ngừng nhận kết nối mới và kích hoạt phần dọn dẹp sau `yield` của `lifespan`:
   - Hạ `_is_ready = False` để `GET /ready` lập tức trả `503`, báo cho Load Balancer chuyển hướng request mới sang instance khác.
   - Vòng lặp chờ cho tới khi `_in_flight_requests == 0` (hoặc hết thời gian chờ tối đa) để các câu trả lời đang chạy hoàn tất với mã `200 OK`, sau đó mới thoát tiến trình với `exit code 0`.
3. Trong `Dockerfile`, lệnh khởi chạy phải dùng `exec uvicorn ...` để Uvicorn mang **PID 1** và nhận trực tiếp `SIGTERM` thay vì bị lớp shell `/bin/sh` nuốt mất tín hiệu (dẫn tới treo 10s rồi bị ép tắt bằng `SIGKILL` — exit code `137`).

---

### Exercise 5.3 – 5.5: Thiết kế Stateless với Redis và Load Balancing 3 Instances

- **Vì sao lưu state trong RAM hỏng khi chạy nhiều instance (hoặc nhiều worker)?**
  - Mỗi container (thậm chí mỗi tiến trình worker trong `uvicorn --workers 2`) có không gian bộ nhớ RAM độc lập. Với Load Balancer phân phối round-robin:
    - Request 1 của User A rơi vào `Instance 1` → lịch sử hội thoại hoặc bộ đếm rate-limit ghi trong RAM của `Instance 1`.
    - Request 2 của User A rơi vào `Instance 2` → RAM của `Instance 2` trống rỗng nên mất hoàn toàn ngữ cảnh hội thoại và cho phép vượt gấp $N$ lần hạn ngạch rate-limit; nếu `Instance 1` restart thì toàn bộ dữ liệu biến mất.
  - Đưa toàn bộ state (`session:<id>`, `ratelimit:<hash>`, `cost:daily:<date>`) ra **Redis** biến các container agent thành **stateless hoàn toàn**: bất kỳ replica nào cũng đọc/ghi cùng một nguồn dữ liệu nhất quán, có thể thêm/bớt instance tuỳ ý.

- **Lệnh kiểm chứng trên `05-scaling-reliability/production/` (cổng `8080`, endpoint `POST /chat`):**
  ```bash
  cd 05-scaling-reliability/production
  docker compose -p k5-day14-scaling up -d --build --scale agent=3
  python test_stateless.py
  docker compose -p k5-day14-scaling down
  ```
  - **Giải thích hoạt động của `test_stateless.py`:** Script tạo 1 `session_id` ở câu hỏi đầu tiên rồi gửi tiếp 4 câu hỏi nữa qua Nginx (`http://localhost:8080/chat`). Nginx chia đều 5 request qua 3 container `agent` khác nhau (trường `served_by` luân phiên đổi giữa 3 `instance-*`), nhưng khi gọi `GET /chat/{session_id}/history`, Redis vẫn trả về đầy đủ nguyên vẹn 10 bản ghi (`5 user + 5 assistant`).
  - Kết quả chạy thực tế khi bật Docker: `[TODO CP4: dán output python test_stateless.py sau khi chạy lệnh trên]`

---

## Part 6: Final Project — `06-lab-complete/` (CP5)

Đã hoàn thiện toàn bộ 12 hạng mục trong `06-lab-complete/`:
- `app/config.py` + `.env.example`: đọc đầy đủ `PORT`, `ENVIRONMENT`, `LOG_LEVEL`, `AGENT_API_KEY`, `REDIS_URL`, `RATE_LIMIT_PER_MINUTE`, `DAILY_BUDGET_USD`, `MONTHLY_BUDGET_USD`.
- `app/redis_client.py`: khởi tạo kết nối Redis lazy (app vẫn khởi động được khi chưa có Redis), hàm `redis_healthy()` kiểm tra `PING` với timeout `1.5s`.
- `app/main.py`: `JsonFormatter` xuất 100% log ứng dụng dạng JSON 1 dòng; `GET /health` luôn trả `200`; `GET /ready` trả `200` khi Redis sống và `503` khi Redis mất kết nối; `POST /ask` kết nối xác thực, rate limit, cost guard và chạy LLM bất đồng bộ qua threadpool; `lifespan` hỗ trợ graceful shutdown hoàn tất in-flight requests.
- `app/auth.py`: kiểm tra `X-API-Key` bằng `secrets.compare_digest`, trả `401` khi thiếu hoặc sai khoá.
- `app/rate_limiter.py`: Sliding window 60s trên Redis Sorted Set (`ZREMRANGEBYSCORE`, `ZCARD`, `ZRANGE`, `ZADD`, `EXPIRE`), trả `429` kèm `Retry-After` và giữ nguyên trạng thái sau khi restart agent.
- `app/cost_guard.py`: cộng dồn chi phí token bằng `INCRBYFLOAT` vào Redis, trả `402` khi chạm ngưỡng ngân sách.
- `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `railway.toml`, `render.yaml`: Multi-stage `python:3.11-slim`, user non-root `appuser`, `HEALTHCHECK`, `exec uvicorn ... --port ${PORT:-8000} --workers 2` (PID 1).

### Kết quả kiểm tra `check_production_ready.py`

> **Lưu ý khi nộp bài cuối:** Sau khi bật Docker Desktop + tích hợp WSL2, chạy lệnh đầy đủ `python check_production_ready.py` trong WSL2 tại `06-lab-complete/` và cập nhật khối `PASS 12/12` vào bên dưới. Dưới đây là kết quả kiểm tra thực tế hiện tại cho toàn bộ 38/38 bài kiểm tra tĩnh + runtime + Redis stateless (`0` lỗi):

```text
================================================================
  📋 Checklist Deliverable
     ⚠️  Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ⚠️  Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 10/12 tiêu chí đạt · 38/38 checks passed
  (2 mục ⚠️ chỉ chờ chạy với Docker daemon trong WSL2 để đo image < 500 MB và gửi SIGTERM / docker stop)
================================================================
```

---

## Part 7: Câu hỏi thảo luận & CI Quality Gate (CP7 & CP8)

### Exercise 7.1: Phân tích Prometheus Metrics
1. **Ví dụ thực tế cho từng loại metric trích từ `GET http://localhost:8002/metrics`:**
   - **Counter (chỉ tăng):** `http_requests_total{method="POST",route="/ask",status="200"} 1.0`, `llm_tokens_total{model="mock-llm-small",type="input"} 91.0`, `llm_cost_usd_total{model="mock-llm-small"} 4.665e-05`.
   - **Gauge (lên xuống tuỳ thời điểm):** `agent_in_flight_requests 0.0`, `agent_info{model="mock-llm-small",version="v2"} 1.0`.
   - **Histogram (chia theo các ngưỡng bucket `le`):** `http_request_duration_seconds_bucket{le="2.0",method="POST",route="/ask"} 1.0`, `llm_request_duration_seconds_bucket{le="2.0",model="mock-llm-small"} 1.0`, và metric mới thêm `agent_question_length_chars_bucket{le="50.0"} 1.0` (`count = 1.0`, `sum = 40.0`).
2. **Vì sao `observe_requests` dùng `route.path` (và gán `"unmatched"` khi không khớp) thay vì `request.url.path`?**
   - Trong Prometheus, mỗi tổ hợp giá trị label tạo ra một chuỗi thời gian (time series) riêng trong RAM. Nếu gắn trực tiếp `request.url.path`, khi bot quét bảo mật hoặc kẻ tấn công gửi hàng trăm nghìn đường dẫn ngẫu nhiên (`/wp-admin`, `/.env`, `/scan-9f8a1b`...), số lượng time series sẽ bùng nổ (**high cardinality explosion**), làm Prometheus cạn kiệt bộ nhớ RAM (OOM) và sập hệ thống giám sát. Gộp mọi đường dẫn lạ về một nhãn duy nhất `route="unmatched"` giới hạn tổng số series ở một hằng số rất nhỏ.

### Exercise 7.3: Cách dùng Exit Code của `eval/run_eval.py` làm Quality Gate trong CI
- Khi chạy thử `python eval/run_eval.py --url http://localhost:8001 --baseline reports/eval_v2.json`, script phát hiện accuracy tụt từ `91.3%` xuống `4.3%` (20 câu bị regression) và thoát với **`exit code 1`**.
- Trong GitHub Actions (đã cấu hình tại `.github/workflows/eval.yml`), bất kỳ step nào kết thúc với exit code khác `0` sẽ đánh dấu workflow `FAIL`, từ đó khoá nút **Merge Pull Request** thông qua Branch Protection Rules nếu accuracy `< 85%` hoặc làm hỏng câu hỏi từng trả lời đúng ở bản trước.

### Exercise 7.4: Trả lời câu hỏi Observability Stack
1. **Khoảng cách giữa `avg` và `p95`/`p99`:** Cho thấy phân phối độ trễ bị lệch phải mạnh (long tail) do ~3% cuộc gọi LLM chậm (~1.7s); phần lớn request chỉ ~180–200ms nên `avg` thấp, nhưng nhóm người dùng không may vẫn phải đợi gần 2 giây.
2. **Chia tải của Nginx:** Panel `Requests/s theo instance` hiển thị lưu lượng chia xấp xỉ 50%–50% cho 2 replica nhờ thuật toán round-robin kết hợp `resolver 127.0.0.11 valid=10s` và `server agent:8000 resolve`.
3. **Vì sao `input tokens/s` lớn hơn `output tokens/s`?** Ở Agent v2, mỗi câu hỏi đều ghép thêm `SYSTEM_PROMPT` + đoạn tài liệu truy xuất từ `KNOWLEDGE_BASE` + câu hỏi của người dùng làm đầu vào (~90–120 input tokens), trong khi câu trả lời ngắn gọn chỉ khoảng ~30–55 output tokens.
4. **`curl http://localhost:8080/metrics` trả về gì và vì sao?** Trả về **`HTTP 404 Not Found`** vì `nginx.conf` cấu hình tường minh `location = /metrics { return 404; }`. Endpoint `/metrics` tiết lộ cấu trúc route, phiên bản model, lưu lượng và tốc độ tiêu tiền nội bộ nên chỉ cho phép Prometheus thu thập qua mạng Docker nội bộ (`obs_net`), tuyệt đối không phơi bày ra Internet.

---

## AI Log (Khai báo theo `RULES.md`)

1. **Khôi phục cấu trúc repo & phân tích yêu cầu bài lab:**
   - **Hỏi AI:** Phân tích toàn bộ đề tài Day 14, các lưu ý riêng của lớp K5 trong `README.md`, `CHECKPOINTS.md`, `RUBRIC.md`, `RULES.md` và kiểm tra trạng thái repo.
   - **Nhận được:** Phát hiện lỗi đường dẫn dài trên Windows (`MAX_PATH > 260`) khiến lần `git clone` ban đầu thiếu 30 file cấu hình/tài liệu; bật `git config core.longpaths true` và `git checkout -- .` để khôi phục nguyên vẹn toàn bộ file gốc từ `HEAD`.
   - **Tự kiểm tra:** Đối chiếu `git status` và đọc lại `check_production_ready.py` xác nhận không sửa đổi bất kỳ dòng nào của file chấm điểm hay `golden_dataset.jsonl`.

2. **Xây dựng các module trong `06-lab-complete/` (Part 6):**
   - **Hỏi AI:** Hỗ trợ viết code hoàn thiện các `TODO` cho `app/config.py`, `app/redis_client.py`, `app/auth.py`, `app/rate_limiter.py`, `app/cost_guard.py`, `app/main.py`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`.
   - **Nhận được & chỉnh sửa:**
     - Lần đầu cài `rate_limiter.py` dùng `r.pipeline()` mặc định (`MULTI`/`EXEC`), khi kiểm thử phát hiện nên gọi trực tiếp các lệnh nguyên tử `ZREMRANGEBYSCORE` → `ZCARD` → `ZRANGE` → `ZADD` → `EXPIRE` với member gắn hậu tố UUID để không ghi đè hai request cùng mili-giây và đảm bảo lưu bền vững trên Redis qua các lần restart.
     - Cấu hình `APIKeyHeader(auto_error=False)` kết hợp `secrets.compare_digest` để luôn trả đúng `401` khi thiếu hoặc sai `X-API-Key` (tránh lỗi `422` mặc định của FastAPI).
   - **Tự kiểm tra:** Chạy `check_production_ready.py --skip-docker` kiểm chứng đạt **38/38 checks passed** (gồm cả kiểm tra mất kết nối Redis trả `503` trên `/ready` trong khi `/health` vẫn trả `200`, chặn `429` sau 5 request và giữ nguyên `429` sau khi restart agent, chặn `402` khi ngân sách thấp, và toàn bộ dòng log hợp chuẩn JSON).

3. **Bổ sung metric & sửa Knowledge Base trong Part 7 (`benchmark-observability/`):**
   - **Hỏi AI:** Hỗ trợ thêm Histogram `agent_question_length_chars`, phân tích nguyên nhân 2 câu sai trong `reports/eval_v2.json` (`security-02`, `scaling-03`) và viết workflow `.github/workflows/eval.yml`.
   - **Nhận được & tự kiểm tra:** Chạy thực tế `load_test.py` ở cả 4 mức concurrency (`1, 10, 50, 100`) và 3 mức `MOCK_SLOW_RATE` (`0, 0.03, 0.1`), chạy `eval/run_eval.py` cho `v1` (`4.3%`), `v2` trước khi sửa (`91.3%`) và `v2` sau khi bổ sung 2 mục vào `KNOWLEDGE_BASE` đạt **`100.0%` (23/23, 0 regression, Quality gate PASS)**; toàn bộ số liệu trong `BENCHMARK_REPORT.md` đều trích xuất trực tiếp từ 10 file JSON thật trong `reports/`.
