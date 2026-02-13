**Scaling AI-Assisted Software Engineering for Scientific Software Development**

Engineering and Implementation Branch (EIB)

**Executive Summary**

The NOAA Environmental Modeling Center (EMC) faces increasing complexity in maintaining and evolving the critical scientific software infrastructure that underpins our application suite, such as the Global Workflow (GFS, GEFS, GDAS, etc.). To address this, we propose scaling our pilot AI-assisted software engineering platform to a "beta" cohort of 10-15 scientific developers. This platform leverages the **Model Context Protocol (MCP)** and **Retrieval-Augmented Generation (RAG)** to provide deep, context-aware coding assistance that goes far beyond standard autocomplete. By integrating directly with our specific HPC environments (Ursa, Hercules, Orion) and enforcing EE2 compliance standards, this system promises to reduce debugging time, ensure architectural integrity, and accelerate scientific innovation.

All proposed services are **FedRAMP-authorized** at the Moderate or High baseline, ensuring compliance with federal security requirements. Service authorization status is verified against the [AWS FedRAMP Services in Scope](https://aws.amazon.com/compliance/services-in-scope/FedRAMP/) listing (last updated December 4, 2025).

**The Solution: A Context-Aware MCP-RAG System on AWS**

Standard AI coding tools lack knowledge of NOAA's specific infrastructure, coding standards, and the intricate nature of our dependencies, like those of the Global Workflow. Our solution bridges this gap using a specialized architecture built entirely on FedRAMP-authorized AWS services:

**• Model Context Protocol (MCP):** A standardized way to fold in AI models into the software development process by enabling them with specific instructions via "tools" with context from all of our documentation and code bases (see RAG below) which creates an "understanding" of our specific workflow structures.

**• Hybrid RAG Engine:** We utilize a dual-database approach for unmatched accuracy:

– **Vector Search (Amazon OpenSearch Service)**: Provides semantic vector search (k-NN) over our documentation and code comments, enabling natural-language queries such as "How do I validate environment variables?" OpenSearch Service is FedRAMP-authorized at both Moderate and High baselines.

– **Graph Database (Amazon Neptune)**: Understands the *structural relationships* of our code *(e.g., "Which scripts call* exglobal forecast.py *and what dependencies do they share?").* Neptune is FedRAMP-authorized at both Moderate and High baselines.

**• Foundation Models (Amazon Bedrock):** Provides managed access to state-of-the-art foundation models (Claude, Llama, Titan, etc.) for document ingestion, embedding generation, and knowledge base maintenance — all within a FedRAMP-authorized boundary (Moderate + High). Bedrock eliminates the need for standalone LLM API keys by providing a unified, secure API gateway to multiple model families.

**• IDE AI Assistant (Amazon Q Developer):** Replaces third-party AI coding assistants with AWS's native, FedRAMP-authorized (Moderate) IDE integration. Amazon Q Developer provides in-editor code completion, chat-based assistance, code generation, and code transformation — fully integrated with the AWS ecosystem and our MCP-RAG backend.

This system allows a developer to ask complex questions like, *"How does the C48 ATM test case interact with the GSI data assimilation step on Hera?"* and receive an answer grounded in our actual codebase and operational procedures, not just general programming knowledge.

**Value Proposition**

This infrastructure converts hours of manual debugging and compliance checking into automated, instantaneous tasks:

**• Accelerated Software Development Time:** By automating routine lookups, boilerplate generation, and compliance checking, we drastically shorten the development lifecycle. This allows high-cost scientific staff to focus on solving complex modeling problems rather than wrestling with syntax, effectively multiplying our workforce's output without adding headcount.

**• Cost Avoidance via Automated Compliance:** The system proactively enforces NWS/HPC EE2 standards, preventing the accumulation of technical debt. This eliminates the need for costly "compliance cleanup" sprints and reduces the risk of delayed operational implementations.

**• Reduced Operational Risk & Downtime:** By validating scripts against platform-specific configurations (e.g., WCOSS2 vs. Orion paths) during development, we minimize runtime failures in production, protecting valuable HPC allocations and ensuring timely forecast delivery.

**• Faster Onboarding & Knowledge Retention:** The system effectively creates an up-to-date knowledge base expert system that allows new staff to use natural language to immediately get relevant information, reducing the training burden on senior engineers and preserving institutional knowledge that might otherwise be lost.

**• Unified Security Posture:** By consolidating on the AWS ecosystem, all services operate within a single FedRAMP-authorized boundary with unified IAM, encryption (KMS), audit logging (CloudTrail), and network controls (VPC). This simplifies Authority to Operate (ATO) documentation and ongoing compliance monitoring.

**Resource Requirements for Beta Rollout (20 Users)**

To scale from our current prototype to a robust beta environment for 10-15 users, we require specific AWS infrastructure and services. We propose a tiered deployment leveraging AWS-native orchestration for secure, scalable management.

**Infrastructure Needs**

**• Compute Environment:** A shared AWS instance (e.g., **m7i.4xlarge**, 16 vCPUs) hosted within a dedicated VPC to run the MCP servers and serve as the orchestration layer for the beta cohort. Individual user clusters are not required. (FedRAMP: EC2 — Moderate + High)

**• Vector Search:** Amazon OpenSearch Service domain with k-NN plugin enabled for semantic vector search across ingested documentation, code-with-context embeddings, and EE2 standards. (FedRAMP: Moderate + High)

**• Graph Database:** Amazon Neptune instance for code relationship graph — call trees, dependency mapping, import chains, and environment variable lineage across the Global Workflow codebase. (FedRAMP: Moderate + High)

**• Foundation Models:** Amazon Bedrock for all LLM interactions — document ingestion, embedding generation, knowledge base maintenance, and programmatic model calls for the MCP-RAG pipeline. Pay-per-use pricing eliminates the need for per-user API keys. (FedRAMP: Moderate + High)

**• IDE AI Assistant:** Amazon Q Developer licenses for all beta users, providing in-editor code completion, chat, and code generation integrated with the MCP-RAG backend. (FedRAMP: Moderate)

**• Orchestration & Security:** AWS-native services for session management, identity (IAM/IAM Identity Center), secrets management (Secrets Manager), audit logging (CloudTrail), and infrastructure-as-code (CloudFormation). All FedRAMP-authorized at Moderate + High.

**FedRAMP Authorization Summary**

All services in this proposal are verified as FedRAMP-authorized:

| AWS Service | Role in Architecture | FedRAMP Moderate | FedRAMP High |
| ----- | ----- | :-----: | :-----: |
| Amazon EC2 | MCP Server hosting | ✓ | ✓ |
| Amazon OpenSearch Service | Vector search (replaces ChromaDB) | ✓ | ✓ |
| Amazon Neptune | Graph database (replaces Neo4j) | ✓ | ✓ |
| Amazon Bedrock | Foundation models & embeddings | ✓ | ✓ |
| Amazon Q Developer | IDE AI coding assistant | ✓ | — |
| Amazon S3 | Document & artifact storage | ✓ | ✓ |
| AWS IAM / IAM Identity Center | Identity & access management | ✓ | ✓ |
| AWS KMS | Encryption key management | ✓ | ✓ |
| AWS CloudTrail | Audit logging | ✓ | ✓ |
| Amazon VPC | Network isolation | ✓ | ✓ |
| Amazon ECS | Container orchestration | ✓ | ✓ |

**Cost Estimates (Annualized)**

| Component | Tier 1 (Pilot — 1 User) | Tier 2 (Beta — 20 Users) |
| ----- | ----- | ----- |
| AWS Compute (EC2) | ~$4,000 | ~$6,000 |
| Amazon OpenSearch Service | ~$3,600 | ~$7,200 |
| Amazon Neptune | ~$3,600 | ~$5,400 |
| Amazon Bedrock (inference + embeddings) | ~$1,200 | ~$3,600 |
| Amazon Q Developer | ~$228 ($19/mo) | ~$4,560 (20 users) |
| Supporting Services (S3, VPC, IAM, etc.) | ~$600 | ~$1,200 |
| **Total Estimated** | **~$13,228** | **~$27,960** |

Table 1: Estimated costs for pilot vs. scaled beta deployment. All services FedRAMP-authorized. Costs are approximate and based on published AWS pricing as of February 2026. Actual costs will depend on usage patterns, instance sizing, and negotiated rates.

**Conclusion**

The MCP-RAG system, deployed on a fully FedRAMP-authorized AWS stack, represents a transformative step for NOAA's software engineering capability. By embedding our institutional knowledge into an intelligent assistant built on Amazon Bedrock, Neptune, and OpenSearch Service — with Amazon Q Developer as the developer-facing interface — we empower our scientists to build better, compliant, and more robust forecasting systems faster. We request support and approval to proceed with the Tier 2 procurement to enable this capability for our core development team.
