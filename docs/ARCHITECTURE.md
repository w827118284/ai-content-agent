# Architecture
## 1. Purpose

This document describes runtime boundaries and failure semantics for code review, operations, and
technical interviews.

The system is a modular monolith. FastAPI, LangGraph, provider services, authentication, and business
metadata live in one backend process. PostgreSQL and Nginx are separate runtime components managed by
Docker Compose.

## 2. System Context

```text
User Browser
    |
    v
React SPA
    |
    v
Nginx :8080
    |
    +-- /api/*   -> FastAPI :8000
    +-- /health  -> FastAPI :8000
    +-- /media/* -> FastAPI static mount
    |
    v
FastAPI
    |
    +-- Auth and ownership
    +-- REST and SSE transport
    +-- Business history synchronization
    |
    v
LangGraph
    |
    +-- PostgreSQL AsyncPostgresSaver
    +-- LLM service -> DeepSeek Chat Completions
    +-- Image service -> OpenAI-compatible Image API
```

Only Nginx publishes a host port in Compose. FastAPI and PostgreSQL use `expose`, so they remain on the
internal Compose network.

## 3. Backend Component Boundaries

### API layer

`app/api/v1` owns HTTP validation, JWT dependencies, ownership checks, response schemas, and SSE event
encoding. It does not decide workflow routing.

The workflow API performs these steps:

1. Authenticate the access token.
2. Resolve the current user from the business database.
3. Verify `user_id + thread_id` ownership where a thread already exists.
4. Call the graph runner.
5. Synchronize only summary fields to `content_projects`.
6. Return REST JSON or sanitized SSE events.

### Graph layer

`app/graph` owns AgentState, nodes, edges, interrupt/resume, RunnableConfig, checkpoint access, and the
application-scoped compiled graph.

`thread_id` is not duplicated in AgentState. It is passed only through:

```python
{"configurable": {"thread_id": thread_id}}
```

### Service layer

`app/services` owns external model protocols and provider governance. Graph nodes depend on service
behavior, not on HTTP SDK details.

Mock and real services share the same business method shapes:

- `plan_topics`
- `write_article`
- `extract_visual_points`
- `generate_images`

### Repository layer

Repositories contain the small set of SQLAlchemy queries required by auth, ownership, and history.
They do not store full workflow state.

## 4. Workflow State

AgentState contains:

```text
topic_direction
generated_topics
selected_topic
article_content
review_feedback
review_status
visual_points
image_urls
status
revision_count
```

The successful state path is:

```text
planning_topics
    -> waiting_topic_selection
    -> drafting
    -> waiting_article_review
    -> rewriting
    -> waiting_article_review
    -> extracting_visuals
    -> generating_images
    -> completed
```

The Reject branch can repeat any number of times. Approve clears review feedback and moves forward to
visual extraction.

Known LLM service failures in topic planning, article generation, or visual extraction transition to
terminal `failed`. Image service failures also transition to `failed`. A failed workflow has no pending
human interrupt and the current UI asks the user to create a new task.

Programming errors are not converted into business failures. They still surface as runtime errors so
that defects are visible during tests and operations.

## 5. Human-in-the-loop

`human_select_topic` and `human_review` call LangGraph `interrupt()`. On resume, LangGraph restarts the
human node from its beginning, so code before `interrupt()` must be replay-safe.

Human nodes therefore only:

- build the interrupt payload;
- validate the resumed payload;
- return AgentState updates.

They do not write the business database, invoke paid providers, or mutate external systems before the
interrupt.

The runner validates a resume payload against the current checkpoint before constructing
`Command(resume=...)`. This prevents an article approval from being submitted while the graph is waiting
for a topic, and prevents an unknown topic id from becoming a recorded resume value.

## 6. Persistence Model

The project intentionally separates execution state from business metadata.

### LangGraph checkpoint tables

Managed by `AsyncPostgresSaver.setup()`:

```text
checkpoints
checkpoint_blobs
checkpoint_writes
checkpoint_migrations
```

These tables contain authoritative graph state, pending nodes, interrupts, and checkpoint history.
Alembic excludes them from autogenerate.

### Business tables

Managed by Alembic:

```text
users
content_projects
alembic_version
```

`content_projects` stores only list and ownership metadata:

- project id;
- owner user id;
- thread id;
- topic direction;
- selected topic title;
- status;
- revision count;
- timestamps.

Article text, review feedback, visual points, and image URLs are not copied into the business table.

Legacy rows may have nullable `user_id`. They remain unowned and are hidden from authenticated users.
All newly created projects require a concrete user id at the application boundary.

## 7. REST and SSE

REST endpoints:

```text
POST /api/v1/workflows/start
POST /api/v1/workflows/{thread_id}/resume
GET  /api/v1/workflows/{thread_id}/state
GET  /api/v1/projects
```

SSE endpoints mirror start and resume:

```text
POST /api/v1/workflows/start/stream
POST /api/v1/workflows/{thread_id}/resume/stream
```

SSE event types:

```text
meta
progress
interrupt
completed
error
```

The terminal workflow object comes from the authoritative checkpoint. A failed graph is included in a
sanitized error event so the frontend can persist the real terminal state.

The frontend uses an AbortController, request generation counters, expected thread ids, and an access
token snapshot. These checks prevent stale history loads or old SSE events from replacing a newer user
selection or a new authenticated session.

SSE cancellation is intentionally propagated. The backend does not continue or retry a paid operation
silently after the client disconnects. A cancellation during a graph node can leave that operation
pending and may require a new task; there is no detached job worker in this demo.

## 8. Authentication and Ownership

Passwords are hashed with Argon2 through pwdlib. The API signs short-lived HS256 access tokens with a
minimum 32-byte secret.

JWT payloads contain only:

```text
sub
iat
exp
```

The token does not contain a password, database credential, provider key, article, or workflow state.

Every thread state read and resume path, including SSE resume, verifies ownership in
`content_projects` before reading the LangGraph checkpoint. A foreign thread and an unknown thread both
return 404, avoiding an ownership existence oracle.

The browser stores the access token in localStorage. This is accepted for the current demo and requires
strict XSS prevention. A higher-security deployment should evaluate HttpOnly cookies together with
CSRF and CORS changes.

## 9. Provider Governance

### LLM

The real text service uses DeepSeek `deepseek-v4-pro` through OpenAI-compatible Chat Completions.
`ChatOpenAI` is configured with SDK `max_retries=0`.

Application retry policy:

```text
maximum total attempts: 2
retry delay: configurable, default 0.5 seconds
retry: timeout, connection, HTTP 429, HTTP 5xx
no retry: 400, 401, 403, 404, parsing, validation
```

One failed operation contributes at most one breaker failure, regardless of the number of attempts.

### Image

The image service uses an OpenAI-compatible image generation endpoint and `gpt-image-2`. Both SDK and
application retries are disabled. Each visual point causes at most one paid POST attempt.

Batch generation is all-or-nothing. On the first observed failure, queued tasks are cancelled before
they enter a Provider call. In-flight async requests may receive cancellation, but a remote Provider may
already have accepted a paid request. Successfully persisted files from the failed batch are removed.

### Rate limiting and breaker

LLM and image providers have independent:

- concurrency semaphores;
- sliding-window requests-per-minute limiters;
- circuit breakers.

The circuit breaker states are CLOSED, OPEN, and HALF_OPEN. After cooldown, exactly one probe operation
can enter HALF_OPEN. A successful probe closes and resets the breaker; an eligible failure reopens it.

Eligible breaker categories are timeout, connection, rate limit, and server error. Authentication,
permission, bad request, not found, parsing, and local persistence failures do not open the breaker.

Limiters and breakers are process-local. Their state is neither shared across replicas nor persisted
across restart. Multiple backend replicas require a gateway or distributed coordination layer.

## 10. Image Persistence and Network Boundary

Provider responses may contain base64 data or a temporary URL. Base64 is decoded directly. A temporary
URL is downloaded only after these checks:

- scheme is http or https;
- embedded URL credentials are rejected;
- localhost names are rejected;
- literal and DNS-resolved addresses must all be globally routable;
- private, loopback, link-local, multicast, reserved, and unspecified addresses are rejected;
- automatic redirects are disabled;
- every redirect target is resolved and validated before the next request;
- redirect count is bounded.

This blocks direct access to localhost, RFC1918 ranges, `::1`, and cloud metadata link-local addresses.
Application checks cannot completely eliminate DNS rebinding; production infrastructure should enforce
network egress policy as a second layer.

Images are written atomically through a temporary file and receive UUID-based names. State stores a
relative URL such as `/media/images/<uuid>.png`.

The static media mount does not require JWT. UUID names are impractical to guess, but possession of a URL
is sufficient to read that image. This is acceptable for the current shareable-content demo, not for a
strict private-media system.

## 11. Observability and Logging

LangSmith tracing is optional and disabled by default. Inputs and outputs are hidden by default. Workflow
metadata uses a fixed allowlist containing identifiers and execution modes, not business content or
credentials.

Operational Provider logs may contain:

```text
provider
operation
safe category
attempt and max attempts
breaker state
exception class name
```

They must not contain prompts, topics, articles, feedback, image URLs, API keys, Authorization headers,
raw Provider messages, or exception tracebacks containing those values.

## 12. Deployment Topology

Compose services start in this order:

```text
db healthy
    -> migrate exits 0
    -> backend healthy
    -> frontend healthy
```

The backend image runs as a non-root system user. The migration service uses the same non-root image.
PostgreSQL data and generated images use separate named volumes.

Default Docker smoke configuration is:

```text
USE_MOCK_LLM=true
USE_MOCK_IMAGE=true
LANGSMITH_TRACING=false
```

Real keys belong only in ignored local env files or an external secret manager. They do not belong in an
image layer, source file, review ZIP, log, or trace metadata.

## 13. Failure Semantics

```text
Input validation failure       -> HTTP 422, no graph mutation
Authentication failure         -> HTTP 401
Foreign or unknown thread      -> HTTP 404 before checkpoint access
Wrong interrupt action         -> HTTP 409
Known LLM service failure      -> checkpoint status=failed
Known image service failure    -> checkpoint status=failed
SSE runtime failure            -> sanitized error event
History metadata sync failure  -> graph result remains authoritative
Local image persist failure    -> batch fails, no breaker increment
Client cancellation            -> cancellation propagates, no hidden retry
```

History metadata is best-effort after graph execution. If metadata synchronization fails, the checkpoint
result is still returned. A later successful resume can update the summary row.

## 14. Test Strategy

Backend tests cover graph transitions, repeated Reject loops, interrupt validation, PostgreSQL recovery,
business migrations, ownership isolation, JWT/password handling, REST/SSE parity, cancellation,
LangSmith metadata, LLM bounded retry, image zero retry, batch cleanup, rate limiting, circuit breaker,
safe logging, and temporary URL SSRF controls.

Frontend tests cover auth lifecycle, history switching, stale response protection, SSE parsing, article
review, terminal failure, and completed media rendering.

Docker Mock E2E covers service health, migration, login, full Reject/Approve workflow, five Mock images,
history restoration, and persistence across Compose restart without real Provider calls.

## 15. Deliberate Limitations

There is no Redis, Celery, Kafka, distributed worker, distributed rate limit, shared circuit state, or
per-thread idempotency key. SSE cancellation does not become a detached background job.

There is no authenticated media server, object storage, refresh token, RBAC, OAuth, account admin,
multi-region topology, backup automation, or observability dashboard. SSE reports node progress rather
than token-level output.

These boundaries keep the repository focused on LangGraph workflow engineering while leaving clear
extension points for a production system.
