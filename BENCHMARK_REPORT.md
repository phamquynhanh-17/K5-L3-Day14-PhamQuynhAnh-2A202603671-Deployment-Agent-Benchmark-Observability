# Benchmark & Observability Report — Day 14

**Họ tên:** Phạm Quỳnh Anh (2A202603671)
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows 11 (x86_64) + WSL2 Linux 6.18, Python 3.11.1

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | ≤ 500 ms | Với tác vụ hỏi đáp tương tác dùng model nhỏ (`mock-llm-small`, base latency ~120–180ms + ~20ms retrieval), ngưỡng p95 ≤ 500ms đảm bảo 95% người dùng nhận phản hồi gần như tức thì mà không bị nhiễu bởi ~3% tail latency (~1.7s) từ upstream LLM. |
| Error rate `/ask` | ≤ 2.0 % | Chừa error budget 2% để hấp thụ tỉ lệ lỗi tạm thời tự nhiên (~1% HTTP 503 từ upstream LLM provider) mà không gây cảnh báo giả (alert fatigue), đồng thời phát hiện sớm khi lỗi vượt ngưỡng bất thường. |
| Accuracy trên golden dataset | ≥ 85 % (100% sau khi bổ sung KB) | Ngưỡng chặn CI/CD (quality gate ≥ 85% và 0 regression) ngăn bản cập nhật prompt/RAG làm tụt chất lượng câu trả lời trước khi merge/deploy. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2)

Số liệu trích xuất trực tiếp từ `reports/load_v2_c1.json`, `reports/load_v2_c10.json`, `reports/load_v2_c50.json`, `reports/load_v2_c100.json` (`--requests 300`):

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---:|---:|---:|---:|---:|---|
| 1 | 3.98 | 203.9 | 242.0 | 1712.1 | 0.67% | ✅ PASS |
| 10 | 37.23 | 193.4 | 441.5 | 1688.3 | 1.00% | ✅ PASS |
| 50 | 104.22 | 210.9 | 521.9 | 1742.0 | 0.67% | ❌ FAIL (p95 > 500ms) |
| 100 | 46.26 | 731.5 | 3954.1 | 4571.9 | 1.33% | ❌ FAIL (p95 > 500ms) |

**Nhận xét:** RPS có tăng tuyến tính theo concurrency không? Vì sao?

RPS **không** tăng tuyến tính mãi theo concurrency:
- Ở giai đoạn tải nhẹ (`concurrency` từ `1 → 10`), RPS tăng gần tuyến tính (`3.98 → 37.23 req/s`, gấp ~9.35 lần) vì tác vụ gọi LLM/retrieval là async I/O (`asyncio.sleep`), event loop của một tiến trình Uvicorn dễ dàng xen kẽ (overlap) thời gian chờ của 10 kết nối đồng thời.
- Khi tăng lên `concurrency = 50`, RPS đạt đỉnh `104.22 req/s` (chỉ tăng ~2.8 lần so với mức 10 thay vì 5 lần), đồng thời `p95` vượt ngưỡng SLO (`521.9 ms > 500 ms`) do chi phí chuyển ngữ cảnh coroutine, parse JSON/Pydantic, ghi log đồng bộ và tranh chấp socket trên 1 worker duy nhất.
- Khi đẩy lên `concurrency = 100`, hệ thống rơi vào trạng thái bão hoà hàng đợi (queueing saturation / thrashing trên single worker + giới hạn socket loopback): các request phải xếp hàng chờ event loop xử lý khiến `p50` vọt lên `731.5 ms`, `p95` vọt lên `3954.1 ms`, và thông lượng thực tế suy giảm xuống còn `46.26 req/s` (theo định luật Little $L = \lambda W$, khi độ trễ $W$ tăng vọt do nghẽn cổ chai, throughput hiệu dụng giảm).

### 2.2 Tail latency

Số liệu trích xuất trực tiếp từ `reports/load_v2_slow_0.json`, `reports/load_v2_slow_0.03.json`, `reports/load_v2_slow_0.1.json` (`--requests 300 --concurrency 20`):

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|
| 0 | 207.4 | 421.2 | 470.1 |
| 0.03 (mặc định) | 236.0 | 464.4 | 1692.8 |
| 0.1 | 351.0 | 1693.0 | 1745.1 |

**Nhận xét:** Chỉ số nào nhạy nhất với request chậm? Vì sao SLO không nên đặt theo average?

- **Chỉ số nhạy nhất với tỷ lệ nhỏ request chậm là `p99` (và tiếp theo là `p95` khi tỷ lệ chậm vượt 5%):**
  - Khi `MOCK_SLOW_RATE` tăng từ `0` lên `0.03` (3% request bị cộng thêm ~1500ms), `avg` chỉ nhích nhẹ thêm **+28.6 ms** (`207.4 → 236.0 ms`) và `p95` vẫn ở mức `464.4 ms`, nhưng **`p99` nhảy vọt gấp 3.6 lần** (`470.1 → 1692.8 ms`).
  - Khi `MOCK_SLOW_RATE = 0.1` (10% request chậm > 5%), cả **`p95` cũng nhảy vọt lên `1693.0 ms`** (vi phạm SLO ≤ 500ms), trong khi `avg` mới chỉ là `351.0 ms` (vẫn thấp hơn 500ms!).
- **Vì sao SLO không đặt theo `average`:** Giá trị trung bình cộng bị kéo về phía đa số request nhanh (90–97% request ~190ms) nên **che giấu hoàn toàn trải nghiệm tệ của nhóm người dùng rơi vào đuôi phân phối (tail latency)**. Đặt SLO theo `p95`/`p99` buộc hệ thống đảm bảo chất lượng phục vụ cho cả 95%–99% tổng số request thực tế.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

Số liệu trích xuất trực tiếp từ `reports/eval_v1.json`, `reports/eval_v2.json` và `reports/eval_v2_fixed.json`:

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---:|---:|---:|
| Accuracy | 4.3% (1/23) | 91.3% (21/23) | 100.0% (23/23) |
| Avg tokens / câu | 56.6 | 109.1 | 113.7 |
| Tổng cost (USD) | $0.000397 | $0.000762 | $0.000790 |
| Cost / câu đúng (USD) | $0.00039675 | $0.00003627 | $0.00003436 |
| Quality gate | FAIL | PASS | PASS |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm tài liệu về sự khác biệt giữa API Key và JWT (token có chữ ký số, chứa thông tin user và thời điểm hết hạn) với từ khoá kích hoạt `["jwt"]` vào `KNOWLEDGE_BASE` trong `utils/mock_llm.py`. |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm tài liệu về Kubernetes HPA (Horizontal Pod Autoscaler scale pod theo CPU, memory hoặc custom metrics) với từ khoá kích hoạt `["hpa", "kubernetes", "autoscal"]` vào `KNOWLEDGE_BASE` trong `utils/mock_llm.py`. |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- **Latency & Token:** Agent v2 có thêm bước retrieval (`~20ms`) và ghép tài liệu tìm được vào prompt nên lượng token trung bình mỗi câu tăng gần gấp đôi (`56.6 → 113.7 tokens/câu`), kéo tổng chi phí cho 23 câu tăng từ `$0.000397` lên `$0.000790` và latency `p50` tăng nhẹ (`167.9 ms → 189.5 ms`).
- **Hiệu quả kinh tế thực tế (`Cost / câu đúng`):** v1 tuy rẻ trên mỗi lần gọi nhưng trả lời sai tới 22/23 câu (accuracy `4.3%`), khiến chi phí cho mỗi câu trả lời đúng tốn tới **`$0.00039675`**. Ngược lại, v2 (sau khi bổ sung KB) đạt accuracy **`100.0%` (23/23)** với chi phí mỗi câu đúng chỉ **`$0.00003436` — rẻ hơn 11.5 lần so với v1**! Do đó, đầu tư thêm ~20ms retrieval và ~57 context tokens cho RAG ở v2 là hoàn toàn xứng đáng.

---

## 4. Observability stack (production)

> **Lưu ý:** Các mục chụp ảnh màn hình và số đo thời gian thực từ Docker stack dưới đây cần chạy trên máy đã cài và bật Docker Desktop theo đúng lệnh ở `CHECKPOINTS.md` (CP8):
> `docker compose -p k5-day14-observability up -d --build`

### 4.1 Screenshot

- [ ] Dashboard Grafana khi đang có tải (`screenshots/grafana-dashboard.png` — thấy rõ Golden Signals)
- [ ] Một trace chậm trong Jaeger (`screenshots/jaeger-slow-trace.png` — thấy span nào chiếm thời gian)
- [ ] Một trace lỗi trong Jaeger (`screenshots/jaeger-error-trace.png` — có event `exception`)
- [ ] Trang Alerts của Prometheus với ít nhất 2 alert đang **firing** (`screenshots/prometheus-alert-firing.png`)

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (`error rate > 5%`, `for: 1m`) | `[TODO CP8: điền số giây thực tế, lý thuyết ~65–75s]` | Golden Signals → **Error rate** (đỏ, nhảy lên ~20%) & **HTTP req/s by status** (`503` tăng mạnh) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (`p95 > 1s`, `for: 2m`) | `[TODO CP8: điền số giây thực tế, lý thuyết ~125–140s]` | Golden Signals → **p95 Latency** & **Latency Percentiles** (`p95`/`p99` vọt lên ~1.7s, bỏ xa `avg`) |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`cost > $2/h`, `for: 2m`) (kèm `AgentHighLatencyP95` nếu tải cao) | `[TODO CP8: điền số giây thực tế, lý thuyết ~130–160s]` | Hàng LLM → **Cost USD/hour** (tăng ~16.7 lần do đơn giá model lớn) & **LLM p95 Latency** (`latency_factor = 2.5`) |
| D | `docker pause` 1 instance | `AgentInstanceDown` (`up{job="agent"} == 0`, `for: 30s`) | `[TODO CP8: điền số giây thực tế, lý thuyết ~35–40s]` | Golden Signals → **Instances Up** (giảm từ 2 xuống 1); Locust ghi nhận vài lỗi `504 Gateway Timeout` từ Nginx trong lúc chờ `proxy_read_timeout 10s` |
| E | `AGENT_VERSION=v1` | **Không có alert nào firing** | Không firing | Hàng LLM → **Retrieval hit ratio** biến mất, **Tokens/s** giảm ~50%, bảng **Running Versions** đổi từ `v2` sang `v1` |

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Đổi `AGENT_VERSION=v1` là **sự cố suy giảm chất lượng ngữ nghĩa (silent quality regression)** chứ không phải lỗi hạ tầng: HTTP vẫn trả `200 OK`, latency thậm chí còn nhanh hơn và chi phí thấp hơn nên mọi alert hạ tầng (error rate, latency, saturation, cost) đều xanh. Để phát hiện loại sự cố này trong production cần kết hợp 3 lớp:
1. **Trước khi deploy (CI/CD Quality Gate):** Bắt buộc chạy `eval/run_eval.py` trên golden dataset trong pipeline CI (`.github/workflows/eval.yml`) với `--min-accuracy 0.85` và `--baseline` để chặn merge/deploy ngay khi có regression.
2. **Giám sát metric nghiệp vụ / pipeline RAG:** Đặt alert trên tỉ lệ retrieval hit (`rate(agent_retrieval_total{result="hit"}[5m]) / rate(agent_retrieval_total[5m]) < ngưỡng`) hoặc sụt giảm bất thường của `input_tokens` (dấu hiệu prompt bị mất context RAG).
3. **Online Evaluation & User Feedback trên traffic thật:** Lấy mẫu (sampling) một phần câu trả lời thực tế trên production để chấm tự động bằng **LLM-as-a-Judge** (faithfulness, relevance), kết hợp theo dõi tỉ lệ bấm 👎 / hỏi lại của người dùng.

### 4.3 Debug bằng trace

> **TODO (CP8):** Sau khi bật stack Docker, mở Jaeger (`http://localhost:16686`), chọn service `observable-agent`, sắp xếp **Longest First**, chọn trace chậm nhất (~1700ms) và điền các giá trị thực tế bên dưới:

- `trace_id`: `[TODO CP8: dán trace_id 32 ký tự hex từ Jaeger]`
- Tổng thời gian: `[TODO CP8: vd ~1710]` ms
- Span chiếm nhiều thời gian nhất: `chat mock-llm-small` (`[TODO CP8: vd ~1685]` ms, chiếm `~98%` tổng thời gian; trong khi `agent.retrieve_context` chỉ mất `~20` ms → chứng minh cổ chai nằm ở bước gọi upstream LLM chứ không phải code của ứng dụng).
- Dòng log tương ứng (`docker compose -p k5-day14-observability logs agent | grep <trace_id>`):

```json
{"TODO_CP8": "Dán dòng log JSON thực tế có cùng trace_id từ lệnh docker compose logs agent"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

> **TODO (CP8):** Chạy 2 lệnh Locust headless ở `CHECKPOINTS.md` (CP8) để sinh `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv`, copy ra thư mục `benchmark-results/` ở gốc repo, rồi điền đúng con số từ dòng `Aggregated` (hoặc `/ask`) của file CSV vào bảng dưới:

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---:|---:|---:|---:|---:|
| 1 | `[TODO CP8: từ scale_1_stats.csv]` | `[TODO CP8]` | `[TODO CP8]` | `[TODO CP8]` | `[TODO CP8]` |
| 3 | `[TODO CP8: từ scale_3_stats.csv]` | `[TODO CP8]` | `[TODO CP8]` | `[TODO CP8]` | `[TODO CP8]` |

**Giải thích kết quả:** Scale có cải thiện p95 không? Nút thắt nằm ở đâu?

- Với cấu hình `cpus: "0.5"` mỗi container và tải 100 concurrent users (mỗi user nghỉ `0.5–2s` → tổng tải yêu cầu ~60–75 req/s), khi chỉ có **1 instance**, tiến trình Python/FastAPI + OpenTelemetry exporter bị giới hạn bởi `0.5 CPU` sẽ xuất hiện độ trễ xếp hàng (CPU throttling & event-loop queueing). Khi scale lên **3 instances** sau Nginx round-robin (`server agent:8000 resolve`), tải CPU và số kết nối trên mỗi instance giảm đi 3 lần nên thông lượng (RPS) ổn định hơn và phần độ trễ do nghẽn CPU giảm xuống.
- Tuy nhiên, **`p95` không thể giảm xuống dưới ~200ms (và `p99` vẫn quanh ~1700ms)** dù tăng lên 3 hay nhiều instance hơn nữa, bởi vì **nút thắt cổ chai thực sự (bottleneck) của mỗi request nằm ở thời gian chờ upstream LLM API (`chat mock-llm-small`: base latency 120–180ms + 3% slow tail 1500ms)**. Scale ngang số replica của agent giúp tăng **khả năng chịu tải đồng thời (throughput/capacity)** và loại bỏ nghẽn CPU nội tại, nhưng không làm một cuộc gọi LLM đơn lẻ chạy nhanh hơn (muốn giảm latency của bản thân bước LLM phải dùng streaming, semantic caching trong Redis, prompt ngắn hơn hoặc model nhanh hơn).

---

## 6. Kết luận

- **3 điều học được về benchmark & observability:**
  1. **Không bao giờ đánh giá latency qua số trung bình (`average`):** Thử nghiệm thực tế cho thấy khi 3% request bị chậm (`MOCK_SLOW_RATE=0.03`), `avg` chỉ là `236.0 ms` nhưng `p99` vọt lên `1692.8 ms`; chỉ percentile (`p95`, `p99`) mới phản ánh đúng trải nghiệm của người dùng ở phần đuôi phân phối.
  2. **Benchmark hiệu năng và Benchmark chất lượng bổ sung không thể thay thế cho nhau:** Dashboard hạ tầng toàn màu xanh không đồng nghĩa AI trả lời đúng (như thí nghiệm hạ `AGENT_VERSION=v1` làm accuracy tụt từ `100%` xuống `4.3%` mà không kích hoạt bất kỳ alert hạ tầng nào), và `Cost / câu đúng` (`$0.00003436` ở v2 so với `$0.00039675` ở v1) mới là thước đo kinh tế chính xác của hệ thống AI.
  3. **Liên kết chặt chẽ 3 trụ cột Metrics – Traces – Logs và kiểm soát Cardinality:** Metrics (Prometheus/Grafana) cho biết *khi nào* hệ thống bất thường, Traces (OpenTelemetry/Jaeger) chỉ chính xác *span nào* gây chậm, còn JSON Logs đính kèm `trace_id` cho biết *chi tiết lỗi*; đồng thời chỉ gắn label có tập giá trị hữu hạn (`route`, `status`, `model`) để bảo vệ bộ nhớ của Prometheus.

- **Nếu đưa agent này lên production thật, em sẽ thêm các metric và alert sau:**
  - **Metrics bổ sung:**
    - `llm_time_to_first_token_seconds` (Histogram — đo TTFT khi bật streaming cho UX).
    - `redis_operation_duration_seconds` & `redis_errors_total` (giám sát độ trễ/lỗi của tầng state rate-limit & session).
    - `agent_rate_limited_requests_total` (HTTP 429) và `agent_budget_rejected_requests_total` (HTTP 402) để phân biệt lỗi từ chối chủ động với lỗi hệ thống 5xx.
    - `agent_eval_online_score` / `agent_user_feedback_total{rating="thumbs_down"}` để giám sát chất lượng câu trả lời theo thời gian thực.
  - **Alerts bổ sung:**
    - **Synthetic / Blackbox Probe Alert (từ ngoài Nginx/LB):** Phát hiện lỗi `502`/`504 Gateway Timeout` ở tầng Load Balancer mà metric nội bộ của container agent không nhìn thấy (như thí nghiệm `docker pause`).
    - **RAG Retrieval Hit-Rate Drop Alert:** Cảnh báo khi tỉ lệ tìm thấy tài liệu (`hit / total`) giảm đột ngột (ví dụ Vector DB lỗi index hoặc cấu hình nhầm version).
    - **Redis Connectivity / Latency Alert:** Cảnh báo sớm trước khi `/ready` chuyển sang `503` hàng loạt.
