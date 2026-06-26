# NIH AWS Sandbox — OMD AI Assistance Platform Extension Proposal

**Date:** June 25, 2026
**Author:** Terry McGuinness, NOAA NWS POCAI Software Engineering — Office of Mission Delivery (OMD), Computing & Advanced Technologies (CAT) Unit
**Audience:** NIH AWS Sandbox sponsors, NOAA OMD management
**Status:** Prototype complete — requesting extension to operationalize external access

---

## Executive Summary

Under the NIH AWS Sandbox funding envelope, the OMD CAT Unit has delivered a
**fully operational AWS-based AI assistance platform** for the NOAA Global
Workflow. The platform gives developers and forecasters an AI coding partner
that already understands the entire Global Forecast System (GFS) codebase, its
documentation, and the operational standards it must meet. The initial
prototype is production-quality on AWS and serves OMD developers from their
editors today.

We are requesting an extension of the NIH AWS Sandbox engagement to complete
the one remaining piece of unfinished work: opening the platform up to two
additional groups of NOAA users who were always part of the vision but out of
scope for the prototype — **GitHub continuous-integration (CI) pipelines** and
**researchers working on RDHPCS systems** (Hera, Orion, Hercules, Gaea, and
Ursa). The design is already complete; this proposal funds the build-out,
hardening, and rollout.

---

## What We Built (Prototype Accomplishments)

The OMD AI assistance platform answers the kinds of questions that used to
require senior engineers and full days of investigation: *"What does this
script depend on?"*, *"Which jobs read this environment variable?"*, *"Does
this Pull Request meet NCEP operational standards?"*, *"Show me similar code
across the workflow."* It does this by combining a complete map of the Global
Workflow source code with the project's documentation set, then exposing the
result as a small set of AI-assistant tools that work directly inside the
developer's editor.

Headline accomplishments:

- **A focused set of AI assistant tools** organized into nine topical areas:
  workflow architecture, code analysis, knowledge-base search, NCEP
  operational-standards compliance, operational guidance, architectural
  reasoning, GitHub integration, spec-driven design tracking, and platform
  health.
- **A code knowledge graph** that captures roughly 148,000 source-code
  entities (Fortran subroutines, Python modules, Shell scripts, job scripts,
  environment variables, configuration files) and 2.8 million relationships
  between them across all three languages.
- **A documentation knowledge base** of roughly 206,000 indexed documents
  drawn from 35 sources, including ESMF, NUOPC, MOM6, CICE, WW3, CCPP,
  METplus, and NCEPLIBS.
- **Multi-program support** — the same platform serves the Global Workflow
  develop branch, the v17 coupled DA branch, the Sub-seasonal Forecast System,
  and GEFS, with strict separation so answers about one program never
  cross-contaminate another.
- **Infrastructure managed entirely as code** — every AWS resource is defined
  in version-controlled templates with automatic data-safety guardrails added
  after our April post-mortem; no production change is ever made by hand.
- **Measured quality** — answer-relevance and coverage metrics are tracked
  continuously, all platform health checks are green, and end-to-end response
  times are well under one second.

### AWS Services in Use (Prototype)

| Role | AWS Service |
|------|-------------|
| Hosting the AI assistant | **Amazon Bedrock AgentCore Runtime** |
| AI model access (embeddings) | **Amazon Bedrock** (Titan, Nova foundation models) |
| Code knowledge graph | **Amazon Neptune** |
| Documentation knowledge base | **Amazon OpenSearch Service** |
| Developer and ingestion workstation | **Amazon EC2** |
| Container hosting | **Amazon Elastic Container Registry (ECR)** |
| Shared file storage | **Amazon EFS** |
| Long-term storage and backups | **Amazon S3** |
| Configuration and secret management | **AWS Secrets Manager** and **AWS Systems Manager Parameter Store** |
| Identity, access, and inter-service authentication | **AWS Identity and Access Management (IAM)** |
| Private network | **Amazon Virtual Private Cloud (VPC)** with 10 service endpoints (no internet exposure) |
| Monitoring, logging, and alerting | **Amazon CloudWatch** |
| Infrastructure as code | **AWS CloudFormation**, deployed via **AWS Cloud Development Kit (CDK)** |
| Future capability (built, currently dormant) | **Amazon SageMaker** for automated quality monitoring and model fine-tuning |

---

## What Is Unfinished — The Extension Request

The prototype validated the platform on the **developer-workstation path**:
a developer working in their editor gets immediate AI assistance against the
Global Workflow. The two remaining user groups that unlock the full return on
the NIH investment are out of scope of the prototype:

1. **GitHub continuous-integration pipelines** — two automatic services
   attached to every Pull Request:
   - **Real-time NCEP operational-standards (EE2) compliance review.** The
     moment a Pull Request is opened or updated, the platform reviews the
     changed code against the NCEP EE2 operational coding standards and
     posts a pass/fail summary directly in the PR. Reviewers and
     configuration managers see — in seconds, not days — exactly which
     standards are at risk, with line-level pointers to the offending
     code and a recommendation for each finding. This shifts EE2
     compliance from a late, manual gate before the operational handoff
     into a continuous check that every contributor sees on every commit.
   - **AI-assisted failure diagnosis.** When a Pull Request build fails,
     the platform automatically attaches a probable-root-cause analysis
     and the relevant code references to the PR thread before a human
     ever opens the log file.
2. **RDHPCS researcher sessions** — meteorologists working on Hera, Orion,
   Hercules, Gaea, and Ursa get the same AI assistance directly from their
   HPC login node, without having to run the platform locally and without
   storing long-lived passwords or tokens on shared filesystems.

### Proposed Work

| Workstream | What it Delivers |
|------------|------------------|
| Short-lived sign-in service (**Amazon Cognito**) | Replaces long-lived passwords with short-lived, attributable access tokens for the two new user groups; the existing developer path is left untouched. |
| GitHub federated trust + **AWS Lambda** token broker | Lets a GitHub workflow obtain a one-time access token automatically, so no credentials are ever stored in a GitHub repository. |
| Real-time EE2 compliance GitHub Action | A reusable workflow, dropped into the Global Workflow repository and any partner repository, that runs on every Pull Request, calls the platform's NCEP operational-standards review, and posts the findings as a PR review comment. |
| HPC login helper | A small one-line command researchers run on their HPC node to obtain a short-lived token for the rest of their work session. |
| Per-user-group permissions inside the platform | CI pipelines get read-only analysis and compliance tools; researchers get the broader analysis and search toolset; developers continue to get everything. |
| Audit logging in **Amazon CloudWatch** | Every AI assistant call is attributable to a specific GitHub workflow run or a specific HPC user, supporting incident review and oversight. |
| Onboarding documentation | One short guide per user group, written for non-developers, ready to hand to new teams. |

All new infrastructure stays under the same code-managed deployment process,
and the existing developer experience is unaffected during rollout.

### Cost Posture

The extension adds only the Amazon Cognito sign-in service (free for the
expected number of users) and a small, lightly used AWS Lambda function. In
parallel, we are landing an **operator-driven hibernation system** in the
same funding window: with a single command, all of the platform's billable
compute (the AI assistant host, the graph database, the documentation search
service, and the developer workstation) goes to sleep, preserving every byte
of ingested data, and wakes back up just as easily. This extends the
operational lifetime of every NIH dollar by ensuring the platform does not
accrue compute charges during nights, weekends, and the long stretches
between research bursts.

---

## Why This Matters

The prototype proved the technology. The extension converts a single-user
demonstration into a shared NOAA capability. Meteorologists across five HPC
systems and every Pull Request submitted to the Global Workflow organization
will receive the same kind of AI assistance that has accelerated OMD CAT Unit
development for the last six months. In particular, real-time EE2 compliance
review on every Pull Request moves NCEP operational-standards enforcement
from a late, expensive, end-of-cycle review into a routine check that runs
on every commit — reducing rework, shortening the path to operational
handoff, and giving NCO and EMC clearer evidence of compliance throughout
the development cycle. The architecture is deliberately layered, so each
new user group plugs in without changes to the underlying platform — which
is exactly the property a long-lived NOAA capability needs.
