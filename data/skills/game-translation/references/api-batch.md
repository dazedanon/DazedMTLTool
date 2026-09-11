# API Batch Translation preflight

This mode is separate from Agent / Sub Direct Translation.
DazedTL's existing API Settings own provider/model/credentials, and Batches owns supported persisted jobs.
The Len tab adds preparation and a source-bound cost review; it does not automatically adapt an arbitrary engine to the Translation tab.

## Before paid translation

1. Select API Batch Translation and the task/image scope in Len's Method.
2. If the full request corpus does not exist, choose preparation only and copy its prompt.
   The assistant may inspect, extract, build shared guidance and compile a request plan locally using `direct-workflow.md`.
   It makes no translation API calls and stops after preparation.
   Show “estimate unavailable until preparation is complete”; missing corpus/pricing is not a $0 estimate.
3. Save a complete compiled plan at `.dazedtl/len-method/api-requests.json`.
   Include all scoped request sources, shared context, speakers and field instructions.
   Bind exact source inputs to the plan; do not substitute a small sample or successful responses for the full denominator.
4. In Len's Method, open **API Settings**, save the desired supported Batch provider/model, then use **Estimate prepared requests**.
   The quote displays model/provider, source units, requests, estimated tokens, Batch cost, Live comparison and rates.
   Review and accept it before copying the API translation prompt.
5. Reuse the existing compatible engine/API backend to collect actual provider requests, review their final estimate and submit within the user's authorization.
   If the engine needs an adapter, adapt the existing request builder and Batch lifecycle in the project workspace, preserving the same context and source identity contract.
   Do not assume the existing GUI's selected files are the Len game or that a saved Len plan can be submitted as an engine file.
   Unsupported Batch routes must stop with a clear explanation; do not silently fall back to full-price Live translation.

The quote uses the same token/pricing helpers as the application, with a 2.5× source-token output allowance and no assumed cache savings.
It is a planning estimate, not a guaranteed bill or a spending cap.
Inspect the displayed rates: the application's pricing table may use configured or built-in fallbacks.
Output shape, provider tokenization, retries and billed reasoning can change the actual cost.
Image work, coding-assistant work, QA and provider queue time are excluded and must remain separately scoped.
The initial quote does not authorize an unlimited retry loop or changes in model, scope or output contract.

The estimate is invalidated by changed source inputs, compiled requests, shared guidance, references, compiler/templates, scope or API settings.
Changing those requires recompilation and another review, even if the old dollar amount looks plausible.
Loading a saved quote requires accepting it again before copying the prompt.
Keys and raw private endpoint configuration never belong in the handoff or request plan.
Pricing lookup can consult the application's public pricing catalog; it does not submit translation requests.

## Execution and progress

Reuse the app's supported Batch submission, persisted IDs, reconciliation, collection and Batches UI instead of creating an unrelated provider queue.
The actual engine adapter must consume every compiled context field and retain request/source fingerprints with results.
Historical `llm-pipeline.md` examples need adaptation to this contract and current live application code.
A transport success is not an accepted translation: validate and save the returned units before counting them.
Record submitted/completed/failed request counts and provider wait status separately from translated/reviewed source-unit counts.
Provider request counters can remain unchanged while work is running; they do not establish completion percentage or a delivery ETA.
Resume known persisted jobs instead of submitting duplicates, reconcile usage after collection, and report any remaining retry estimate before additional paid work.
