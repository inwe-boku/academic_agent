# Getting API access at BOKU

The agent talks to the **Academic AI** platform of BOKU University. The public
BOKU page only states that an API exists; the technical details are available
after logging in. This page lists what you need and where it comes from.

## What you need

| Item | Used for | Where it comes from |
| --- | --- | --- |
| **API host** (base URL) | `ACADEMIC_AI_BASE_URL` | The Python example on the BOKU Academic AI API page (`base_url=...`). The PDF documents only show the placeholder `https://api.example.com`. |
| **Client-ID** | `ACADEMIC_AI_CLIENT_ID` | An *API client* created in the Academic AI web application |
| **Client-Secret** | `ACADEMIC_AI_CLIENT_SECRET` | Generated for that API client; shown when created |
| **Model name** | `ACADEMIC_AI_MODEL` | `academic --list-models`, or `GET /api/v1/llm/models` |
| **API documentation and examples** | Reference | PDFs available after login ("Platform API Docs", "API examples") |

## Steps

1. **Log in** to Academic AI with your BOKU account and open the API
   documentation. It contains the two PDFs (documentation and code examples)
   and a Python example that includes the real host name.
2. **Obtain an API client.** According to the platform documentation, API
   clients are managed in the web application by administrators holding the
   `MANAGE_API_CLIENTS` permission. If you cannot create one yourself, ask your
   Academic AI administrator or the responsible IT/service contact at BOKU to
   create one for you.
3. **Request the right role.** The agent only needs plain chat access:

   | Permission | Needed? | Enables |
   | --- | --- | --- |
   | `USE_API_LLM` | **Yes** | `/api/v1/llm/*` (chat and model list) |
   | `USE_API_TAILORED_AI` | No | Tailored AI and Knowledge Base endpoints (RAG) |
   | `ACCESS_API_MONITOR_CREDIT` | No | `/api/v1/cost` |

4. **Note the client limits.** Each API client has a *cost limit* and a *rate
   limit* (requests per minute) set by the administrator. An agent session
   makes one request per step, so a low rate limit can interrupt long runs.
5. **Store the Client-ID and secret** in the config file described in
   [Getting started](getting-started.md). Up to two secrets can exist per
   client, which allows rotation without downtime: create a new secret, update
   your config, then deactivate the old one.

## Costs

API usage is **billed independently** of the normal Academic AI user account.
Prices differ per model; `GET /api/v1/llm/models` returns the
`input_tokens` and `output_tokens` costs per 1,000 tokens. Because the API is stateless,
the agent resends the full conversation on each step, so input tokens grow with
every step. For long tasks prefer a cheaper model, and check the cost
endpoint or ask your administrator for the usage report.

## Do not commit credentials

Keep the Client-Secret out of version control. If you keep a local note file
with credentials, such as `AAI_docs/api-zugangsdaten.txt`, add it to
`.gitignore`. If a secret was ever committed or shared, have it deactivated and
generate a new one.
