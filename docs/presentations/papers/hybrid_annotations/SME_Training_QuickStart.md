# SME Training Quick-Start Guide
**Getting Subject Matter Experts Up to Speed on Semantic Annotation Review**

**Version:** 1.1  
**Date:** December 4, 2025  
**Audience:** Domain experts, operations staff, senior developers, **technical translators**  
**Time Required:** 2-hour training session + 4-hour hands-on practice

---

## A Note for Language-Minded Experts

If you have a background in **linguistics, translation, or language learning**, you bring unique strengths to this work. Semantic annotation is fundamentally a **translation task**—you're translating *implicit operational knowledge* into *explicit machine-readable statements*.

**Your linguistic skills transfer directly:**

| Linguistic Concept | Semantic Annotation Equivalent |
|-------------------|--------------------------------|
| **Denotation vs. Connotation** | Literal text vs. Intent/Rationale |
| **Register** (formal/informal) | Priority/Severity levels |
| **Pragmatics** (context-dependent meaning) | `:context:` and `:scope:` attributes |
| **Semantic fields** | MCP directive categories |
| **Collocations** | `:related:` relationships |
| **Translation equivalence** | `:alternatives:` for similar utilities |

Think of MCP directives as **glosses**—annotations that capture meaning the surface text alone cannot convey.

---

## Table of Contents

1. [Training Objectives](#training-objectives)
2. [Prerequisites](#prerequisites)
3. [Linguistic Framework for Annotation](#linguistic-framework-for-annotation)
4. [Session 1: Introduction (30 minutes)](#session-1-introduction-30-minutes)
5. [Session 2: Hands-On Review (60 minutes)](#session-2-hands-on-review-60-minutes)
6. [Session 3: Practice Session (30 minutes)](#session-3-practice-session-30-minutes)
7. [Post-Training: Independent Review (4 hours)](#post-training-independent-review-4-hours)
8. [Certification Checklist](#certification-checklist)
9. [Quick Reference Card](#quick-reference-card)

---

## Linguistic Framework for Annotation

Before diving into the mechanics, understand the **ontological structure** we're building:

### The Three Layers of Meaning

Every EE2 requirement has three layers—like any natural language utterance:

```
┌─────────────────────────────────────────────────────────────┐
│ LAYER 1: SURFACE FORM (What the text says)                  │
│ "Jobs should fail with err_chk or err_exit"                 │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ LAYER 2: SEMANTIC CONTENT (What it means)                   │
│ - Requirement type: error handling                          │
│ - Modality: should (recommendation, not mandate)            │
│ - Entities: err_chk, err_exit (specific utilities)          │
│ - Temporal: immediately upon error                          │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│ LAYER 3: PRAGMATIC INTENT (Why it exists)                   │
│ - Operational context: 6-hour forecast windows              │
│ - Consequence of violation: cascade failures                │
│ - SLA requirement: 99% on-time delivery                     │
│ - Historical motivation: post-mortem from 2019 outage       │
└─────────────────────────────────────────────────────────────┘
```

**Your job as an annotator**: Capture Layers 2 and 3 so AI can "understand" requirements the way you do.

### Semantic Relations (Familiar Territory)

If you've studied linguistics, you'll recognize these relations:

| Semantic Relation | MCP Equivalent | Example |
|------------------|----------------|---------|
| **Hyponymy** (is-a-kind-of) | `:category:` | err_chk IS-A error-handling utility |
| **Meronymy** (part-of) | `:module:` | err_chk PART-OF prod_util |
| **Synonymy** (same meaning) | `:alternatives:` | err_chk ≈ err_exit (similar purpose) |
| **Antonymy** (opposite) | `:anti-pattern:` | silent_failure OPPOSITE-OF fail_fast |
| **Collocation** (co-occurrence) | `:related:`, `:see-also:` | err_chk COLLOCATES-WITH `export err=$?` |
| **Causation** | `:rationale:` | set -x ENABLES debug logging |

### Modal Logic (Priority/Severity)

EE2 uses RFC 2119 terminology—essentially a **modal logic system**:

| RFC 2119 Term | Modal Logic | Deontic Meaning | MCP `:severity:` |
|---------------|-------------|-----------------|------------------|
| MUST | □P (necessarily P) | Obligation | `must` |
| MUST NOT | □¬P (necessarily not P) | Prohibition | `must_not` |
| SHOULD | ◇P (possibly P, recommended) | Strong recommendation | `should` |
| SHOULD NOT | ◇¬P (possibly not P) | Discouraged | `should_not` |
| MAY | ◇P ∧ ◇¬P (either permissible) | Permission | `may` |

**Linguistic insight**: Notice how "should" in EE2 documents is **normative**, not predictive. Annotating severity captures this **illocutionary force**.

---

## Training Objectives

By the end of this training, SMEs will be able to:

✅ **Understand** the purpose of semantic annotations in AI knowledge bases  
✅ **Identify** the 7 types of MCP directives and their fields  
✅ **Evaluate** annotation quality across 7 review dimensions  
✅ **Provide** structured feedback using the SME Review Guide  
✅ **Recognize** common annotation errors and anti-patterns  
✅ **Complete** an independent review of 1-2 documentation sections

---

## Prerequisites

**Required Knowledge:**
- Expert-level understanding of your domain (e.g., GFS operations, error handling, data assimilation)
- Familiarity with NCEP production standards (EE2 compliance)
- Basic understanding of reStructuredText (RST) format

**Especially Valuable (Not Required):**
- Background in linguistics, translation, or language pedagogy
- Experience with controlled vocabularies, taxonomies, or ontologies
- Familiarity with markup languages (XML, HTML, LaTeX)
- Understanding of technical writing or documentation systems

**Not Required:**
- AI/ML expertise
- Programming in Python/JavaScript
- Vector database knowledge
- Graph database experience

**Materials Provided:**
- This training guide
- SME Review Guide (complete reference)
- Pilot annotation examples (error_handling section)
- Review feedback template

### RST Syntax in 5 Minutes (For Non-Programmers)

RST (reStructuredText) is a **human-readable markup language**—think of it as a more structured version of Markdown. Here's all you need to know:

```rst
# This is a comment (invisible in rendered docs)
.. This is also a comment (RST's native comment syntax)

.. mcp:directive_name:: identifier
   :attribute: value
   :another_attribute: another value
   
   Body text goes here, indented with 3 spaces.
   Multiple lines are fine.
```

**Key rules:**
1. **Indentation matters** (like Python, use 3 spaces)
2. **Double colon** `::` introduces a directive
3. **Attributes** use `:name: value` format
4. **Blank lines** separate elements

That's it. If you can write a structured email, you can write RST annotations.

---

## Session 1: Introduction (30 minutes)

### 1.1 The Problem AI Solves (10 minutes)

**Scenario:** New developer asks: "How do I check for errors in production scripts?"

**Traditional Approach (Text Search):**
```
Search: "error checking"
Results: 347 documents containing "error"
  - Error message format guidelines
  - Error code reference table
  - Error handling overview
  - Historical error analysis
  - ...
Time to find answer: 15-30 minutes
Confidence: Low (which approach is correct?)
```

**SDD Framework Approach (Intent-Aware):**
```
Query: "How do I check for errors?"
AI Understanding:
  - Intent: rapid_error_detection
  - Priority: critical
  - Utility: err_chk
  - Examples: err_chk_usage (with context)
  - Alternatives: err_exit (for immediate abort)
Time to answer: 15 seconds
Confidence: High (operational rationale provided)
```

**Key Insight:** AI can "understand" *why* requirements exist, not just match keywords—**if** we capture that knowledge correctly.

### 1.2 What Are Semantic Annotations? (10 minutes)

**Simple Definition:** Invisible "tags" embedded in documentation that capture:
- **Why** requirements exist (intent, rationale)
- **How critical** they are (priority, severity)
- **What** they prevent or enable (operational impact)
- **How** they relate to each other (relationships)

**A Linguistic Analogy:**

Think of annotations as **interlinear glosses** in linguistics—the hidden layer between surface text and deep meaning:

```
Surface:    err_chk   must   be used   after   commands
           ─────────────────────────────────────────────
Gloss:      [UTIL]   [OBL]  [PASSIVE] [TEMP]  [ENTITY]
           prod_util  must   required   immed.  shell_cmd
           ─────────────────────────────────────────────
Deep:      For operational reliability, immediately invoke
           the err_chk utility after any command that might fail
```

Without annotations, AI sees only the surface. With annotations, AI "reads" all three levels.

**Example (Before Annotation):**
```rst
C. Production Utilities

err_chk / err_exit
  It is imperative that all production code employ error checking.
  Jobs should fail with err_chk or err_exit as soon as an error is encountered.
```

**After Annotation (Your Role to Review):**
```rst
C. Production Utilities

.. mcp:intent:: rapid_error_detection
   :description: Enable immediate error detection and recovery
   :enforcement: runtime_check
   :rationale: 99% on-time delivery SLA requires detection within 5 minutes

.. mcp:compliance:: error_handling
   :priority: critical
   :type: mandatory
   :scope: global

err_chk / err_exit
  It is imperative that all production code employ error checking.
  Jobs should fail with err_chk or err_exit as soon as an error is encountered.
  
.. mcp:utility:: err_chk
   :module: prod_util
   :category: error-handling
   :required: yes
   :deprecated: no
```

**Question to Consider:** Does this capture what YOU know about why err_chk exists?

### 1.3 Your Role as SME Reviewer (10 minutes)

**You Are NOT Expected To:**
- Understand vector embeddings or AI mathematics
- Write code or modify the RAG system
- Learn new programming languages
- Become an AI expert

**You ARE Expected To:**
- Validate that annotations capture YOUR expert knowledge
- Identify missing context or incorrect rationale
- Flag examples that don't match real operational usage
- Suggest additional examples for common scenarios

**Impact of Your Work:**

| Without SME Review | With SME Review |
|-------------------|----------------|
| AI returns generic text | AI provides operational context |
| 45% retrieval accuracy | **87% retrieval accuracy** |
| 35% false positives | **8% false positives** |
| 8-week developer onboarding | **3-week onboarding** |

**Your domain expertise is the secret ingredient that makes AI effective.**

---

## Session 2: Hands-On Review (60 minutes)

### 2.1 The 7 MCP Directive Types (20 minutes)

We'll review each directive type with examples from YOUR domain.

#### Directive 1: `mcp:compliance` - Priority and Scope

**Purpose:** Specify how critical a requirement is.

**Fields:**
- `:priority:` → critical | high | medium | low
- `:type:` → mandatory | recommended | optional
- `:scope:` → global | system-specific | component-specific

**Example:**
```rst
.. mcp:compliance:: error_handling
   :priority: critical
   :type: mandatory
   :scope: global
```

**Your Review Question:** "Is this really CRITICAL, or should it be HIGH?"

**Decision Framework:**
- **critical** = System fails / operational delivery at risk if violated
- **high** = Data quality/reliability significantly impacted
- **medium** = Maintainability/efficiency affected
- **low** = Stylistic/convenience

**Exercise:** Review 3 compliance directives, identify any mis-prioritized items.

---

#### Directive 2: `mcp:intent` - The "Why" Behind Requirements

**Purpose:** Capture WHY a requirement exists (most important directive!).

**Fields:**
- `:description:` → High-level purpose
- `:enforcement:` → runtime_check | compile_check | manual_review
- `:rationale:` → Operational justification (this is YOUR expertise!)

**Example:**
```rst
.. mcp:intent:: rapid_error_detection
   :description: Enable immediate error detection and recovery
   :enforcement: runtime_check
   :rationale: Operational reliability requires catching failures at earliest point
```

**Your Review Question:** "Is this the REAL reason we do this?"

**Common Issue - Circular Reasoning:**
```rst
❌ BAD:
   :rationale: We use err_chk to check errors

✅ GOOD:
   :rationale: 99% on-time delivery SLA requires detection within 5 minutes
               to prevent cascade failures across 6-hour forecast window
```

**Linguistic Note:** The BAD example is **tautological**—it restates the description, adding no semantic content. The GOOD example provides **explanatory adequacy**—it answers "why?" with causal reasoning.

**The Rationale Litmus Test:**

A good `:rationale:` should pass this test: *"If someone asks 'but why?' after reading it, the answer is NOT simply a restatement."*

- "We check errors to catch errors" → FAILS (circular)
- "We catch errors to prevent downstream failures" → PASSES (causal)
- "We prevent downstream failures to maintain SLA" → PASSES (teleological)

**Exercise:** Rewrite 2 rationale statements to include operational context.

---

#### Directive 3: `mcp:severity` - RFC 2119 Compliance Levels

**Purpose:** Specify requirement strength (must/should/may).

**Fields:**
- `:severity:` → must | must-not | should | should-not | may
- `:rationale:` → Why this level?
- `:exceptions:` → Documented exceptions

**Linguistic Context:** RFC 2119 creates a **deontic modality system** for technical specifications. These aren't just English words—they're defined terms with precise meanings:

| Term | Linguistic Force | Pragmatic Effect |
|------|-----------------|------------------|
| MUST | Obligation | Violation = non-conformance |
| SHOULD | Strong recommendation | Violation = acceptable with justification |
| MAY | Permission | Choice with no preference |

**Example:**
```rst
.. mcp:severity:: must
   :rationale: Critical for operational stability and rapid troubleshooting
   :exceptions: None
```

**Your Review Question:** "Does the text say 'must' but we actually mean 'should'?"

**Watch for Modal Inflation:** Technical writers often use "must" for emphasis when "should" is more accurate. Your job is to calibrate the actual requirement strength.

**Exercise:** Identify 2 cases where severity doesn't match standard language.

---

#### Directive 4: `mcp:utility` - Tool Metadata

**Purpose:** Document production utilities with structured metadata.

**Fields:**
- `:module:` → Which module provides it (e.g., prod_util)
- `:category:` → error-handling | data-management | messaging | initialization
- `:required:` → yes | no
- `:deprecated:` → yes | no | partial

**Example:**
```rst
.. mcp:utility:: err_chk
   :module: prod_util
   :category: error-handling
   :required: yes
   :deprecated: no
```

**Your Review Question:** "Is this utility truly REQUIRED or just RECOMMENDED?"

**Exercise:** Verify module names and categories for 3 utilities.

---

#### Directive 5: `mcp:example` - Context-Aware Code Examples

**Purpose:** Show the RIGHT way with clear context.

**Fields:**
- `:language:` → bash | python | yaml
- `:context:` → When to use this
- `:demonstrates:` → What pattern it shows

**Example:**
```rst
.. mcp:example:: err_chk_usage
   :language: bash
   :context: error_checking_after_command
   :demonstrates: Standard error checking pattern

   .. code-block:: bash
   
      critical_command arg1 arg2
      export err=$?
      err_chk
```

**Your Review Question:** "Is this example what we ACTUALLY do in production?"

**Exercise:** Identify 2 missing examples that would help new developers.

---

#### Directive 6: `mcp:pattern` - Design Patterns and Anti-Patterns

**Purpose:** Recognize good and bad code patterns.

**Fields:**
- `:category:` → error-handling | data-management | etc.
- `:anti-pattern:` → yes | no
- `:alternatives:` → List of better approaches

**Example:**
```rst
.. mcp:pattern:: fail_fast_pattern
   :category: error-handling
   :anti-pattern: no
   :alternatives: []

   Failures must not be allowed to propagate downstream.
   Jobs should fail with err_chk or err_exit immediately.
```

**Your Review Question:** "Should AI flag code that does the OPPOSITE of this?"

**Linguistic Note on Anti-Patterns:**

Anti-patterns are essentially **negative exemplars**—they define a concept by exclusion. In lexical semantics, we call this **sense disambiguation through contrast**:

- "fast" only makes sense in contrast to "slow"
- `fail_fast_pattern` only makes sense in contrast to `silent_failure`

By explicitly annotating what NOT to do, we give the AI **contrastive semantics**—the ability to distinguish good from bad by seeing both sides.

**Exercise:** Define 1 anti-pattern AI should detect.

---

#### Directive 7: `mcp:see-also` - Relationship Mapping

**Purpose:** Connect related concepts explicitly.

**Fields:**
- `:related:` → List of related items
- `:type:` → prerequisite | reference | alternative | example

**Example:**
```rst
.. mcp:see-also:: production_utilities
   :related: [err_exit, err_trap]
   :type: alternative
```

**Your Review Question:** "Are these items REALLY related? How?"

**Types:**
- **prerequisite** = Must understand/have this first (logical dependence)
- **reference** = Related concept for more info (topical association)
- **alternative** = Different approach to same goal (functional equivalence)
- **example** = Concrete usage example (instantiation)

**Linguistic Framework (Sense Relations):**

The `:type:` attribute captures **semantic relations** you may recognize:

| `:type:` | Semantic Relation | Example |
|---------|-------------------|---------|
| prerequisite | Presupposition | `err_chk` PRESUPPOSES `export err=$?` |
| reference | Topical cohesion | `err_chk` TOPIC-RELATED-TO `error_handling` |
| alternative | Near-synonymy | `err_chk` ≈ `err_exit` (same domain, different use) |
| example | Instantiation | `err_chk_usage` INSTANCE-OF `err_chk` |

**Exercise:** Identify 2 missing relationships.

---

### 2.2 Live Review Exercise (40 minutes)

**Scenario:** We'll review the pilot annotation for Error Handling section together.

**Materials:** 
- `pilot_annotation_error_handling.md` (provided)
- Review feedback template (provided)

**Process:**
1. Read original text (5 min)
2. Review annotations (10 min)
3. Group discussion: What's good? What's wrong? What's missing? (15 min)
4. Fill out feedback template (10 min)

**Sample Feedback Entry:**

```markdown
## Section: Error Handling

### Intent Accuracy
- ✅ rapid_error_detection - rationale captures operational SLA
- ⚠️ descriptive_error_messages - add "enables automated log parsing"
- ❌ atomic_file_operations - enforcement should be "automated" not "manual"

### Priority/Severity
- ✅ error_handling: critical priority appropriate
- ⚠️ messaging: should be "low" not "medium" - not production-critical

### Examples
- ✅ err_chk_usage - good basic example
- ⚠️ Missing: err_chk inside loop (common use case)
- ⚠️ Missing: pipeline error handling (command1 | command2)

### Questions
1. Is prep_step truly "required: yes" or just recommended?
2. Should we mark getsystem as "deprecated: yes"?
```

---

## Session 3: Practice Session (30 minutes)

### 3.1 Independent Review Task

**Assignment:** Review one of the following sections (your choice):

1. **Production Utilities** (prod_util module)
2. **Environment Variables** (PDY, cyc, COMROOT)
3. **File Handling** (cpreq, cpfs)

**Time Limit:** 20 minutes

**Deliverable:** Completed feedback template

### 3.2 Group Review and Discussion (10 minutes)

Share findings:
- What did you discover?
- What patterns emerged?
- What questions do you have?

---

## Post-Training: Independent Review (4 hours)

### Task Breakdown

**Week 1 Assignment (4 hours):**

1. **Review Assigned Section (2 hours)**
   - Read original documentation
   - Review all annotations
   - Fill out feedback template

2. **Identify Gaps (1 hour)**
   - Missing examples?
   - Missing relationships?
   - Incomplete rationale?

3. **Write Recommendations (1 hour)**
   - Specific text changes
   - New examples to add
   - Priority adjustments

**Submission:**
- Email completed feedback template
- Schedule 30-minute follow-up discussion

---

## Certification Checklist

You are certified to perform independent SME reviews when you can:

- [ ] Identify all 7 MCP directive types from examples
- [ ] Evaluate intent accuracy (does rationale capture operational context?)
- [ ] Assess priority/severity correctness
- [ ] Validate utility metadata (module, category, required)
- [ ] Review code examples for correctness and completeness
- [ ] Identify missing relationships
- [ ] Provide structured feedback using template
- [ ] Complete independent review in 2-4 hours per section

**Sign-off:** _____________________________ Date: ___________

---

## Quick Reference Card

### The 7 Review Dimensions (Memory Aid: "I-P-U-E-R-P-G")

1. **I**ntent Accuracy - Does rationale capture WHY?
2. **P**riority/Severity - Does priority match operational impact?
3. **U**tility Metadata - Are module/category/required correct?
4. **E**xamples - Do they show the RIGHT way?
5. **R**elationships - Are connections accurate?
6. **P**atterns - Should AI recognize this?
7. **G**ap Analysis - What's missing?

### Annotation as Translation: A Mental Model

Think of each annotation as translating from **operational knowledge** to **machine-readable semantics**:

```
SOURCE (Your Expert Knowledge):
   "We use err_chk because back in 2019 we had a cascade failure
    that cost us 3 forecast cycles when a data copy failed silently."
                              ↓
TARGET (MCP Directive):
   .. mcp:intent:: rapid_error_detection
      :description: Detect failures immediately to prevent cascade
      :rationale: Silent failures can cost 3+ forecast cycles (historical incident)
      :enforcement: runtime_check
```

**Translation Strategy:**
1. Identify the **illocutionary force** (what is the text trying to DO?)
2. Extract the **propositional content** (what facts are being asserted?)
3. Capture the **pragmatic context** (why does this matter HERE and NOW?)

### Priority Decision Tree

```
Is violation a production failure risk?
├─ Yes → CRITICAL
└─ No
   ├─ Does it significantly impact data quality?
   │  ├─ Yes → HIGH
   │  └─ No
   │     ├─ Does it affect maintainability?
   │     │  ├─ Yes → MEDIUM
   │     │  └─ No → LOW
```

### Severity Levels (RFC 2119)

- **must** / **must-not** → Absolute requirement (deontic necessity)
- **should** / **should-not** → Strong recommendation, exceptions allowed (defeasible)
- **may** → Optional, discretionary (permission)

### Common Review Flags

🚩 **Circular Reasoning (Tautology)**
```
❌ "We use err_chk to check errors"    [Says nothing new]
✅ "99% delivery SLA requires 5-minute error detection"    [Explains WHY]
```

🚩 **Severity Inflation (Modal Overstatement)**
```
❌ Everything marked "critical"    [If everything is critical, nothing is]
✅ Only production-failure risks are "critical"    [Meaningful differentiation]
```

🚩 **Missing Examples (Underspecification)**
```
❌ Only basic usage shown    [Learner can't generalize]
✅ Common scenarios covered (loops, pipelines, error recovery)    [Comprehensive]
```

🚩 **Wrong Relationships (Semantic Error)**
```
❌ err_exit marked as "reference"    [Wrong relation type]
✅ err_exit is "alternative" (different approach to same goal)    [Correct]
```

### Glossary for Language-Minded Annotators

| Term | Definition | Linguistic Analogue |
|------|------------|---------------------|
| **MCP Directive** | Machine-readable annotation in RST format | Gloss, interlinear annotation |
| **Intent** | The purpose or goal behind a requirement | Illocutionary force |
| **Rationale** | Explanation of WHY something is required | Presupposition, pragmatic implicature |
| **Severity** | Strength of obligation (must/should/may) | Deontic modality |
| **Priority** | Operational importance (critical/high/medium/low) | Information structure (focus) |
| **Anti-pattern** | What NOT to do; negative exemplar | Antonymy, contrast |
| **Context** | Where/when a pattern applies | Register, domain restriction |
| **Scope** | How broadly a rule applies | Quantifier scope |
| **Evidence** | Citation proving the requirement exists | Source attribution |
| **Enforcement** | How compliance is verified | Felicity conditions |

---

## Support Resources

**During Training:**
- Instructor: Available for questions
- Pilot annotations: `sdd_framework/templates/pilot_annotation_error_handling.md`
- Complete guide: `sdd_framework/templates/sme_review_guide.md`

**Post-Training:**
- Email: Terry.McGuinness@noaa.gov
- Office hours: Tuesdays 2-3pm
- Slack channel: #sdd-framework-sme-reviews

**Feedback on This Training:**
Please provide feedback to help us improve:
- What was most helpful?
- What needs more explanation?
- What additional examples would help?

---

## Training Success Metrics

**Target Outcomes:**
- 100% of SMEs can identify directive types after training
- 90%+ agreement between SME reviews on priority/severity
- 80%+ of identified gaps lead to annotation improvements
- 4-hour average time per section review (down from 8+ hours without training)

**Your feedback shapes the future of this training!**

---

**End of Quick-Start Guide**

**Next Steps:**
1. Complete certification checklist
2. Review assigned documentation section
3. Submit feedback within 1 week
4. Attend follow-up discussion session

**Thank you for contributing your domain expertise to make AI assistance more effective!**
