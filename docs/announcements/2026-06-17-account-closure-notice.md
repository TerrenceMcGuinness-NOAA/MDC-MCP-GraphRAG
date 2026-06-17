# Notice: NIH AWS POC Account Shutdown — June 17, 2026

**To:** All MDC MCP-RAG Platform Users  
**From:** Terry Latanville, EIB Development Lead  
**Date:** June 17, 2026  
**Subject:** AWS account services stopping today; project data preserved

---

Team,

Per direction from the NIH program office, all processing servers in the AWS POC account are being **stopped today at 5:00 PM EDT (June 17, 2026)**. The account will be permanently closed by June 20 — it will not remain available in any hibernated or reduced-cost state after that date.

## What this means for you

- The MCP-RAG server (AgentCore runtime), OpenSearch, and Neptune will no longer be reachable after 5:00 PM today.
- The `agentcore-mcp-rag` tools in your IDE will stop responding.
- No new queries, ingestion runs, or deployments can be performed against this account.

## Your data is safe

All project artifacts have been exported and preserved outside the NIH account:

- **Full knowledge base export** (2.1 GB) — vector embeddings, Neptune graph data, and dedupe registry for both `gw` and `gw_v17` tenants — synced to external S3 storage (`s3://omdmcpdata`).
- **All source code** pushed to GitLab (`develop_aws` branch) including the complete portable export pipeline, ingestion tooling, specs, and operational runbooks.
- **Ingestion reports** and configuration artifacts committed for reproducibility.

The export is in an engine-neutral format (gzipped JSONL + Neptune-loader CSV) that can restore into either AWS (OpenSearch + Neptune) or the original open-source stack (ChromaDB + Neo4j) without any re-ingestion or re-embedding.

## What's next

We are exploring **Google Gemini Code Assist** as an alternative development platform while we work to secure funding for a new AWS account (earliest availability: after July 6, 2026). If funding is allocated, we will stand up a fresh account and reimport from the preserved export — the round-trip tooling is built and tested for exactly this scenario.

More details on the transition plan will follow once the next platform is confirmed.

## Questions?

Reach out to Terry or J if you have questions about accessing preserved artifacts or the timeline for resuming services.

---

*This notice is archived at `docs/announcements/2026-06-17-account-closure-notice.md` in the project repository.*
