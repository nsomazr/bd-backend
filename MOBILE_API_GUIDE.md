# Maisha Chat Mobile API Guide

This guide is for mobile app developers integrating with the Maisha Chat backend.

## Swagger / OpenAPI

- Swagger UI: `/api/docs/swagger/`
- ReDoc: `/api/docs/redoc/`
- Raw OpenAPI schema: `/api/schema/`

Production base URL:

- `https://api.maishachat.or.tz`

Local development base URL:

- `http://127.0.0.1:8090`

## Authentication model

The API supports two client modes:

1. Guest mode
2. Logged-in mode

### Guest mode

Generate a UUID once on app install and persist it locally. Send it on every request:

`X-Visitor-Id: <uuid>`

This is how guest conversations, arena activity, feedback, and analytics stay linked to the same device/session.

### Logged-in mode

After login/register, send:

`Authorization: Bearer <access_token>`

Keep sending `X-Visitor-Id` as well. If a guest later logs in, the backend can merge guest data into the account.

## Main mobile flow

1. Generate and store `visitor_id` on first app launch.
2. Call `GET /api/models/` to load available models.
3. Create a conversation with `POST /api/conversations/`.
4. Stream answers with `POST /api/conversations/{id}/complete/`.
5. Optionally submit thumbs-up/down feedback.
6. Optionally allow login/register for cross-device continuity.

## Core endpoints

### Health

- `GET /api/health/`

Use for environment diagnostics only. Not required in normal app flow.

### Models

- `GET /api/models/`

Returns available models and the default model key.

### Auth

- `POST /api/auth/register/`
- `POST /api/auth/login/`
- `POST /api/auth/refresh/`
- `GET /api/auth/me/`
- `PATCH /api/auth/me/`

### Conversations

- `GET /api/conversations/`
- `POST /api/conversations/`
- `GET /api/conversations/{public_id}/`
- `PATCH /api/conversations/{public_id}/`
- `DELETE /api/conversations/{public_id}/`
- `GET /api/conversations/{public_id}/messages/`
- `POST /api/conversations/{public_id}/complete/`
- `POST /api/conversations/{public_id}/regenerate/`

### Message feedback

- `POST /api/messages/{message_id}/feedback/`
- `DELETE /api/messages/{message_id}/feedback/`

### Arena

- `POST /api/arena/battles/`
- `POST /api/arena/battles/{id}/vote/`
- `GET /api/arena/leaderboard/`
- `GET /api/arena/leaderboard/stream/`

## SSE endpoints

The following endpoints return `text/event-stream`:

- `POST /api/conversations/{public_id}/complete/`
- `POST /api/conversations/{public_id}/regenerate/`
- `POST /api/arena/battles/`
- `GET /api/arena/leaderboard/stream/`

### Expected SSE event format

Each event looks like:

```text
event: token
data: {"delta":"Hello"}
```

Events are separated by a blank line.

### Chat completion events

- `start`
- `model_ready`
- `token`
- `done`
- `error`

### Regenerate events

- `start`
- `model_ready`
- `token`
- `done`
- `error`

### Arena events

- `start`
- `model_loading`
- `model_ready`
- `token`
- `response_done`
- `done`
- `error`

## Error handling guidance

For non-streaming endpoints, standard JSON API errors are returned.

For SSE endpoints:

- listen for `error` events
- show a user-friendly retry state
- do not expose raw backend details to end users

The backend now masks infrastructure errors such as GPU memory failures with friendly text.

## Recommended client headers

For guest requests:

```http
Content-Type: application/json
Accept: application/json
X-Visitor-Id: 123e4567-e89b-12d3-a456-426614174000
```

For authenticated requests:

```http
Content-Type: application/json
Accept: application/json
Authorization: Bearer <access_token>
X-Visitor-Id: 123e4567-e89b-12d3-a456-426614174000
```

For SSE requests:

```http
Content-Type: application/json
Accept: text/event-stream
Authorization: Bearer <access_token>
X-Visitor-Id: 123e4567-e89b-12d3-a456-426614174000
```

## Implementation notes for mobile

- Persist `visitor_id` in secure local storage or app storage.
- Persist JWT `access` and `refresh` tokens securely.
- Refresh access tokens using `/api/auth/refresh/`.
- Treat conversation IDs as opaque strings.
- Arena battle IDs and message IDs are integers.
- Prefer retry UI for streaming failures.
- Swahili/English reply language is auto-detected from user input.

## Admin endpoints

Admin and staff-only endpoints are also included in Swagger, but typical mobile clients should ignore:

- `/api/admin/rlhf/...`

These are for internal moderation, analytics, and data export workflows.
