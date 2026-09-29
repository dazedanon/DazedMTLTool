# API Batch Translation within one run

DazedTL's API Settings own provider/model/credentials, and Batches owns supported persisted jobs.
The same starting prompt covers preparation, cost review, submission, collection, QA and local delivery.
The assistant handles each transition; the user does not choose tasks or copy a second prompt.
An arbitrary engine still needs a compatible adapter; the Len request plan is not itself an executable Batch job.

## Before paid translation

1. Read the saved API settings and inspect existing translation records and persisted jobs.
   Reuse accepted work and resume known jobs instead of submitting duplicates.
   Build the remaining request set with its full scope accounted for; do not rebill completed work.
2. Inspect, extract, build shared guidance and compile the request plan locally using `direct-workflow.md`.
   Adapt the engine's request builder in the project workspace as needed.
   These steps do not submit translation requests. Continue through preparation automatically.
   If the user explicitly requested preparation only, stop at that requested boundary.
3. Save the complete planned request set at `.dazedtl/len-method/api-requests.json`.
   Include all scoped request sources, shared context, speakers and field instructions.
   Bind exact source inputs to the plan; do not substitute a small sample or successful responses for the full denominator.
   Account separately for accepted units and in-flight requests excluded from a resumed submission.
4. Run the live helper yourself:

   ```bash
   python DAZEDTL_ROOT/scripts/len_translation.py api-estimate --game-root /path/to/game
   ```

   It uses the saved provider/model, checks source/context dependencies, writes an **unapproved**
   quote to `.dazedtl/len-method/api-estimate.json`, and prints its path, summary and structured estimate.
   A different compiled plan can be selected with `--requests <game-relative-path>`.
   Show the model/provider, source units, requests, estimated tokens, Batch cost, Live comparison and rates
   in the current conversation. Missing corpus or pricing is not a $0 estimate.
   Resolve missing settings or unsupported routes before submission; request only the missing choice/access.
5. Collect the adapter's actual provider requests through the supported backend and review their final
   estimate against the planned quote. Use existing spending authorization only if it covers this exact
   scope, provider/model and cost; otherwise request approval here after the concrete estimate is ready.
   Record the user's authorization and the quote's request/settings/scope fingerprints in local status.
   Only then set `approved=True` on that quote and call the live
   `util.len_api.validate_estimate(project, quote)` immediately before paid submission.
   Persist the authorized quote for resume; a file's approval flag alone does not establish user consent.
   If inputs changed, recompile and re-estimate, then obtain any additional authorization required.
6. Submit through the compatible engine/API backend, then continue automatically through collection,
   accepted-result validation, injection, targeted QA and packaging. A cost approval is a decision within
   the run, not a request for a new translation prompt.
   Do not assume the existing GUI's selected files are the Len game or that a Len plan can be submitted
   as an engine file. Unsupported Batch routes must not silently fall back to full-price Live translation.

The quote uses the same token/pricing helpers as the application, with a 2.5× source-token output allowance and no assumed cache savings.
It is a planning estimate, not a guaranteed bill or a spending cap.
Inspect the displayed rates: the application's pricing table may use configured or built-in fallbacks.
Output shape, provider tokenization, retries and billed reasoning can change the actual cost.
Image work, coding-assistant work, QA and provider queue time are excluded and must remain separately scoped.
The initial quote does not authorize an unlimited retry loop or changes in model, scope or output contract.

The estimate is invalidated by changed source inputs, compiled requests, shared guidance, references, compiler/templates, scope or API settings.
Revalidate before reusing a saved authorized quote; do not ask again solely because the session resumed when the user's authorization and all dependencies still match.
Old project.json GUI approvals are not imported as authorization for a new request set.
Keys and raw private endpoint configuration never belong in the handoff or request plan.
Pricing lookup can consult the application's public pricing catalog; it does not submit translation requests.

## Execution and progress

Reuse the app's supported Batch submission, persisted IDs, reconciliation, collection and Batches UI instead of creating an unrelated provider queue.
The actual engine adapter must consume every compiled context field and retain request/source fingerprints with results.
Historical `llm-pipeline.md` examples need adaptation to this contract and current live application code.
A transport success is not an accepted translation: validate and save the returned units before counting them.
Record submitted/completed/failed request counts and provider wait status separately from translated/reviewed source-unit counts.
Provider request counters can remain unchanged while work is running; they do not establish completion percentage or a delivery ETA.
Before provider waits, save progress and job IDs, explain the next checkpoint, and poll/resume within the assistant session's capabilities.
Reconcile usage after collection and estimate remaining retries before additional paid work; keep within the user's authorization.
