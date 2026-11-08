# Iranian monitor backend 1.0.0

Python 3.10+; standard library only. From repository root:

```sh
export IRAN_MONITOR_TOKEN='choose-a-long-random-secret'
python3 -m iran_monitor
python3 -m unittest discover -s tests/iran -v
```

Defaults: `127.0.0.1:8000`, SQLite `data/iran-monitor.sqlite3`, panel `iran_web/` next to package. Supports `IRAN_MONITOR_HOST`, `IRAN_MONITOR_PORT`, `IRAN_MONITOR_DB`, `IRAN_MONITOR_STATIC_DIR` and equivalent CLI `--host --port --db --static-dir`. Docker can use host `0.0.0.0` and DB `/app/data/iran-monitor.sqlite3`. Mount the data directory to persist it. No dependency on upstream services, config or accounts. Backend does not create frontend files. Graceful Ctrl-C stops scheduling; scheduler is daemonized, not a durable external job runner.

## REST contract

All `/api/*` routes except GET `/api/health` require `Authorization: Bearer <IRAN_MONITOR_TOKEN>`. An unset/empty server token yields 503, not open access. Wrong/missing credentials yield 401. No login endpoint, cookies, query tokens or CORS. Frontend can keep a user-entered token in sessionStorage (explicit requested single-user compromise; JS-readable storage is vulnerable to XSS). Never bake token into static assets. Use HTTPS reverse proxy outside localhost.

GET collections return direct arrays, not envelopes. Errors: `{ "error": "message" }`. JSON writes require Content-Type application/json, max 16 KiB. Unknown watch/settings fields rejected. PUT watch is partial-update semantics like PATCH.

- GET `/api/health`: `{ok,service,version,auth_configured,scheduler_running}`; public.
- GET `/api/sources`: `[{id,name,status,detail,checked_at?,parsed_items?}]`. IDs `divar`, `sheypoor`, `feed`, `esam`, `komodaa`. Initial status never claims connection. Connected requires a successfully parsed nonempty collection, not HTTP 200 alone.
- GET/POST `/api/watches`: list / create (201).
- GET/PATCH/PUT/DELETE `/api/watches/{id}`: retrieve / update / delete (200 `{ok:true}`, missing 404).
- Watch: `{id,name,source,query,city,min_price,max_price,interval_minutes,enabled}`. Server-generated 32-char ID, name/query required, city lowercase slug default `tehran`, bounds integer toman or null, interval integer 1..10080 default30, enabled actual boolean defaulttrue. Maximum100 watches.
- GET `/api/items`: filters `watch_id,source,q,city,min_price,max_price,limit,offset`. Default limit100, maximum500. Query uses normalized substring; source exact. Watch query requires all normalized space-separated words to occur in card title/snippet. Price-bounded watches exclude unknown prices.
- Item: `{id,source,title,price,url,image,city,description,score,reason,created_at,ai_evaluated}`. `price` integer toman or null. `score` null unless actually AI evaluated, then0..100; no synthetic AI score. ISO UTC created_at is **first observed by monitor**, not the source publication date. Esam/Komodaa city is `unknown`, and requested watch city is NOT applied for those feeds.
- POST `/api/scan` with `{}` or `{watch_id}`: synchronous `{ok,results:[{watch_id,status,detail?,new_items,matched,...}],new_items,duration_seconds}`. Prefer **one watch per request** and client timeout90s. Concurrent scans409. Per-source10s cooldown. Each request admits at most3 attempted watches within20s; current bounded fetch/one AI call may finish later. Remaining watches are not processed in that request. Scheduler retries due work. `ok` indicates batch execution, not successful source connectivity; inspect per-result status.
- GET `/api/settings`; PATCH/PUT accepts only booleans `ai_enabled,scheduler_enabled`. Returns those plus `ai_configured,ai_model,currency,notifications_enabled,feed_configured,auth_configured,ai_budget_per_scan,ai_min_score,scan_batch_limit,scan_admission_seconds`. No API keys/tokens/base URLs returned or stored. Scheduler and AI default **false**; enable explicitly. Scheduler checks persisted due timestamps every5s, starts only when authentication is configured.
- GET `/api/notifications?unread=true`: max200 newest persisted new-match notifications, `{id,watch_id,item_id,created_at,read,item}`. PATCH `/api/notifications/{id}` with `{read:true}` marks read. Deduplicated by (watch,item). Watch deletion cascades its notifications/match links. Orphan public items remain in history. No Telegram or arbitrary webhooks.

## Sources and honest limits

Only public result-card fields are extracted. Never request login, phone, chat, contact or private APIs. No captcha solving, cookies or browser fingerprint impersonation. A provider may block or change markup at any time. Use must respect applicable site terms, robots rules and permission; technical accessibility is not authorization.

- Divar: public `https://divar.ir/s/{city}?q={query}` HTML cards. This is **not** official Kenar API; no official integration claim. Internal API/official approved-app credentials are not used. Partial first-page results only.
- Sheypoor: public `https://www.sheypoor.com/s/{city}?keyword={query}` HTML cards. Server can ignore keyword; local relevance filter mandatory, so zero matching items does not mean whole-market absence. Price can be visual `icon-toman`, explicitly parsed as toman.
- Esam (operator opt-in): fixed `https://api.esam.ir/api/items/v2/GetItemList?pageNumber=1` (10 sampled cards observed). API numeric prices are toman, verified against item UI: 11800000 API =11,800,000 تومان UI =118000000 IRR structured data. Auction bids are marked as current bids, not buy-now offers. No keyword or geographic server-side filtering claimed.
- Komodaa (operator opt-in): fixed `https://search.komodaa.com/api/v2.6/search/products` (18 sampled products observed). Numeric price is toman; product meta `product:price:currency=TMN` verified. Product status semantics/availability not assumed. Names, user IDs, avatars, raw descriptions never retained. No city/keyword server search claim.
- Opt into both experimental feeds with `IRAN_MONITOR_EXPERIMENTAL_SOURCES=1`. They are samples, not exhaustive used-only feeds; may contain new goods. Local query/price filter is applied.
- Generic approved JSON/RSS: operator sets `IRAN_MONITOR_FEED_URL` and comma-separated `IRAN_MONITOR_FEED_HOSTS`; API cannot set URLs/hosts. JSON list or `{items:[...]}` fields `title,url|link,price,image`; RSS item title/link/price. Numeric price assumed toman; explicit ریال strings converted. Link must stay on feed host. Basic RSS only (not Atom). XML DTD/entities refused; raw descriptions omitted.

## Optional AI

Set `OPENAI_API_KEY`, `OPENAI_MODEL`, optionally `OPENAI_BASE_URL` (default https://api.openai.com/v1); enable via PATCH settings. Only query/title/price are shared, not raw page, description, seller or contacts. OpenAI-compatible `/chat/completions`, one call maximum per entire scan,150 max output tokens, response schema/range validation. Existing watch-item matches skip AI cost. Evaluated scores below `IRAN_MONITOR_AI_MIN_SCORE` (default60) are neither persisted nor notified. Non-evaluated matches and AI failures fall back to explicit local matching, score null; budget exhaustion is not a verdict of relevance. Model reason is untrusted plain text; frontend must use textContent. No key needed for basic monitoring.

## Security / transport

Default outbound transport: HTTPS only; exact host allowlist; all DNS addresses public; chosen IP pinned; certificate/SNI validation; no redirects, cookies or environmental proxies; 8s socket timeout,15s response-reading deadline,2MiB payload cap, no compressed payload. Individual TCP/TLS/header operations are timeout-bounded;15s is a response-body deadline, not a hard wall-clock for the whole scan. No arbitrary proxy/image fetch endpoint. API:120 requests/min/IP,32 concurrent request workers,10s request socket timeout, bounded JSON, parameterized SQLite, path traversal and symlink escapes rejected, static type/4MiB allowlist, security headers, no credential/request body logging.

Some VPN/sandbox DNS returns synthetic198.18.0.0/15 and2001:2::/48 addresses for otherwise public hostnames. Default refuses these correctly. **Explicit trusted-runtime exception:** `IRAN_MONITOR_TRUST_SYNTHETIC_DNS=1` permits only these benchmark ranges and only the four fixed market hosts. It never permits private/loopback/link-local addresses and does not extend to feed/AI. This relaxes the public-IP guarantee and must only be enabled on an operator-trusted DNS interception runtime. SNI/TLS remains verified. Live scan_source extracted Divar23, Sheypoor26, Esam10, Komodaa18 in this runtime using this opt-in; counts are ephemeral, not availability guarantees.

Alternative explicit `IRAN_MONITOR_USE_ENV_PROXY=1` uses stdlib urllib with operator-provided HTTPS_PROXY. HTTPS host/scheme validation and redirects prohibition remain; DNS resolution/IP pinning is delegated to the **trusted proxy**, so its outbound policy must enforce public destinations. Literal private addresses/localhost are still refused. Never accept proxy configuration from API clients. Default never trusts env proxies. Proxy URLs and credentials are never logged or returned.

This is a single-user, single-process local backend, not a multi-tenant Internet service. SQLite is plaintext; protect filesystem and backups. Auth is one shared environment secret. Rate limiter is process-local. Notifications are in-panel persistence, not push. Source status is last observed attempt, not a live guarantee. No retention limit yet; operator must manage stored public listing history/DB backups. Unit/API tests are offline and do not invoke live marketplaces or paid AI.

### Trusted system DNS mode (recommended for this Minis runtime only)

`IRAN_MONITOR_TRUST_SYSTEM_DNS=1` uses stdlib urllib HTTPS with environmental proxies explicitly disabled, TLS verification intact, no redirects,8s socket timeout/15s body deadline/2MiB bound. Only fixed `divar.ir`, `www.sheypoor.com`, `api.esam.ir`, `search.komodaa.com` can take this path; feed and AI still use normal public-IP-pinned transport. DNS resolution is trusted rather than IP-pinned, so DNS rebinding/private routing protection is delegated to the operator runtime. This is an explicit compromise for native DNS interception, not a safe default for hostile DNS. It takes precedence over the other opt-in transport flags for these market hosts.

Verified actual `scan_source` with `IRAN_MONITOR_TRUST_SYSTEM_DNS=1 IRAN_MONITOR_EXPERIMENTAL_SOURCES=1`: Divar23 parsed cards/23 known prices; Sheypoor26/19 known prices; Esam10/10; Komodaa18/18. No raw scraped JSON fixtures, user IDs or names were committed. These live counts may change and do not prove keyword/city search correctness or market completeness.
