#!/usr/bin/env node

/**
 * generate_llm_summaries.js - Phase 24E-6 Step 2
 *
 * Reads community contexts from Step 1 and generates LLM summaries
 * using GitHub Models API (gpt-4o-mini). Processes bottom-up (L0 first)
 * so parent communities can reference child summaries.
 *
 * Resume-safe: writes after each batch. Skips communities with existing
 * summaries in the output file.
 *
 * Usage:
 *   node scripts/generate_llm_summaries.js
 *   node scripts/generate_llm_summaries.js --input data/community_contexts.json --output data/llm_summaries.json
 *   node scripts/generate_llm_summaries.js --dry-run        # process first 3 only
 *   node scripts/generate_llm_summaries.js --batch-size 10   # save every 10
 *
 * Requires: gh auth token (GitHub Copilot subscription)
 *
 * @phase Phase 24E-6
 * @author Terry McGuinness + AI Assistants
 * @date 2026-02-25
 */

import { readFileSync, writeFileSync, existsSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { execSync } from 'child_process';

const __dirname = dirname(fileURLToPath(import.meta.url));
const DATA_DIR = resolve(__dirname, '..', 'data');

const args = process.argv.slice(2);
function getArg(name, fallback) {
  const idx = args.indexOf(`--${name}`);
  return idx !== -1 && args[idx + 1] ? args[idx + 1] : fallback;
}

const inputPath = getArg('input', resolve(DATA_DIR, 'community_contexts.json'));
const outputPath = getArg('output', resolve(DATA_DIR, 'llm_summaries.json'));
const dryRun = args.includes('--dry-run');
const batchSize = parseInt(getArg('batch-size', '5'), 10);

const API_URL = 'https://models.inference.ai.azure.com/chat/completions';
const MODEL = 'gpt-4o-mini';
const DELAY_MS = 2500;
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 10000;

function getGitHubToken() {
  try {
    return execSync('gh auth token', { encoding: 'utf8' }).trim();
  } catch {
    console.error('[ERROR] Could not get GitHub auth token. Run: gh auth login');
    process.exit(1);
  }
}

function buildSystemPrompt(level) {
  const base = `You are an expert in NOAA's Global Workflow, a unified forecasting system for operational weather prediction (GFS, GEFS, GDAS, SFS). You analyze code communities — groups of related source files, modules, and scripts — within this scientific computing infrastructure.`;

  if (level === 0) {
    return `${base}

For each community you receive, produce a clear, technical summary (3-6 sentences) that covers:
1. The primary purpose of this group of files
2. Key functionalities and responsibilities
3. Important interfaces or data flows to other components
4. Relevant HPC/EE2 compliance patterns if visible

Be specific about file types, languages, and operational roles. Reference specific member names where helpful.`;
  }

  return `${base}

You are summarizing a HIGHER-LEVEL community (Level ${level}) composed of sub-communities. You will receive child community summaries. Produce a synthesis summary (4-8 sentences) that:
1. Describes the overarching function of this group
2. Explains how the sub-communities relate and interact
3. Identifies the data flow or workflow connections
4. Notes architectural patterns or operational significance

Focus on the forest, not the trees. Reference child community roles by name.`;
}

function buildUserPrompt(ctx) {
  const parts = [];

  parts.push(`Community: ${ctx.name || `L${ctx.level}-${ctx.communityId}`}`);
  parts.push(`Level: ${ctx.level} | Members: ${ctx.memberCount}`);

  if (ctx.languages && ctx.languages.length) {
    parts.push(`Languages: ${ctx.languages.join(', ')}`);
  }

  if (ctx.members && ctx.members.length > 0) {
    const memberList = ctx.members.slice(0, 30).map(m => `  - ${m.name} (${m.type})`).join('\n');
    parts.push(`\nMembers:\n${memberList}`);
    if (ctx.members.length > 30) {
      parts.push(`  ... and ${ctx.members.length - 30} more`);
    }
  }

  if (ctx.internalRelationships && ctx.internalRelationships.length > 0) {
    const rels = ctx.internalRelationships.slice(0, 20).map(r => `  - ${r.source} -[${r.rel}]-> ${r.target}`).join('\n');
    parts.push(`\nInternal Relationships:\n${rels}`);
  }

  if (ctx.externalRelationships && ctx.externalRelationships.length > 0) {
    const ext = ctx.externalRelationships.slice(0, 15).map(r => `  - ${r.source} -[${r.rel}]-> ${r.target} (community ${r.targetCommunity})`).join('\n');
    parts.push(`\nExternal Relationships:\n${ext}`);
  }

  if (ctx.childSummaries && ctx.childSummaries.length > 0) {
    const children = ctx.childSummaries.map(ch =>
      `  - ${ch.name || `community-${ch.communityId}`} (${ch.memberCount} members): ${ch.summary}`
    ).join('\n');
    parts.push(`\nChild Community Summaries:\n${children}`);
  }

  if (ctx.interactions && ctx.interactions.length > 0) {
    const inters = ctx.interactions.slice(0, 10).map(i => `  - ${i.name} (strength: ${i.strength})`).join('\n');
    parts.push(`\nInteracting Communities:\n${inters}`);
  }

  parts.push('\nProvide a concise technical summary for this community:');
  return parts.join('\n');
}

async function callGitHubModels(token, systemPrompt, userPrompt, retryCount = 0) {
  const body = JSON.stringify({
    model: MODEL,
    messages: [
      { role: 'system', content: systemPrompt },
      { role: 'user', content: userPrompt }
    ],
    temperature: 0.3,
    max_tokens: 500
  });

  const response = await fetch(API_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`
    },
    body
  });

  if (response.status === 429 || response.status >= 500) {
    if (retryCount < MAX_RETRIES) {
      const wait = RETRY_DELAY_MS * (retryCount + 1);
      console.log(`[WARN] ${response.status} — retrying in ${wait / 1000}s (attempt ${retryCount + 1}/${MAX_RETRIES})`);
      await new Promise(r => setTimeout(r, wait));
      return callGitHubModels(token, systemPrompt, userPrompt, retryCount + 1);
    }
    throw new Error(`API returned ${response.status} after ${MAX_RETRIES} retries`);
  }

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`API error ${response.status}: ${text.slice(0, 200)}`);
  }

  const data = await response.json();
  return data.choices[0].message.content.trim();
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

async function main() {
  console.log('============================================================');
  console.log('Phase 24E-6 Step 2: Generate LLM Summaries');
  console.log(`  Model: ${MODEL}`);
  console.log(`  API: ${API_URL}`);
  console.log(`  Dry run: ${dryRun}`);
  console.log(`  Batch save interval: ${batchSize}`);
  console.log('============================================================');

  if (!existsSync(inputPath)) {
    console.error(`[ERROR] Input not found: ${inputPath}`);
    console.error('       Run export_community_contexts.js first (Step 1).');
    process.exit(1);
  }

  const contexts = JSON.parse(readFileSync(inputPath, 'utf8'));
  console.log(`[INFO] Loaded ${contexts.length} community contexts`);

  // Load existing results for resume support
  let results = {};
  if (existsSync(outputPath)) {
    try {
      const existing = JSON.parse(readFileSync(outputPath, 'utf8'));
      if (Array.isArray(existing)) {
        for (const r of existing) {
          results[r.communityId] = r;
        }
      }
      console.log(`[INFO] Resuming — ${Object.keys(results).length} existing summaries found`);
    } catch {
      console.log('[WARN] Could not parse existing output, starting fresh');
    }
  }

  const token = getGitHubToken();
  console.log('[OK] GitHub auth token acquired');

  // Sort bottom-up: L0 first, then L1, L2, L3
  contexts.sort((a, b) => a.level - b.level);

  const toProcess = dryRun ? contexts.slice(0, 3) : contexts;
  let processed = 0;
  let skipped = 0;
  let errors = 0;
  const startTime = Date.now();

  for (const ctx of toProcess) {
    const key = ctx.communityId;

    // Skip if already done
    if (results[key] && results[key].summary) {
      skipped++;
      continue;
    }

    // For L1+ communities, inject any freshly generated child summaries
    if (ctx.level > 0 && ctx.childCommunityIds) {
      ctx.childSummaries = ctx.childCommunityIds
        .filter(cid => results[cid] && results[cid].summary)
        .map(cid => ({
          communityId: cid,
          name: results[cid].name || `community-${cid}`,
          memberCount: results[cid].memberCount || 0,
          summary: results[cid].summary
        }));
    }

    const systemPrompt = buildSystemPrompt(ctx.level);
    const userPrompt = buildUserPrompt(ctx);

    try {
      const summary = await callGitHubModels(token, systemPrompt, userPrompt);

      results[key] = {
        communityId: ctx.communityId,
        level: ctx.level,
        name: ctx.name,
        memberCount: ctx.memberCount,
        summary,
        model: MODEL,
        timestamp: new Date().toISOString()
      };

      processed++;

      if (processed % 50 === 0 || processed <= 3) {
        const elapsed = ((Date.now() - startTime) / 1000).toFixed(0);
        const rate = (processed / (elapsed / 60)).toFixed(1);
        console.log(`[INFO] ${processed} done, ${skipped} skipped, ${errors} errors | ${rate}/min | L${ctx.level} ${ctx.name || ctx.communityId}`);
      }

      // Save checkpoint
      if (processed % batchSize === 0) {
        writeFileSync(outputPath, JSON.stringify(Object.values(results), null, 2));
      }

      await sleep(DELAY_MS);

    } catch (err) {
      errors++;
      console.error(`[ERROR] L${ctx.level}-${ctx.communityId}: ${err.message}`);

      results[key] = {
        communityId: ctx.communityId,
        level: ctx.level,
        name: ctx.name,
        memberCount: ctx.memberCount,
        summary: null,
        error: err.message,
        model: MODEL,
        timestamp: new Date().toISOString()
      };
    }
  }

  // Final save
  const finalResults = Object.values(results);
  writeFileSync(outputPath, JSON.stringify(finalResults, null, 2));

  const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
  const successCount = finalResults.filter(r => r.summary).length;
  const failCount = finalResults.filter(r => !r.summary).length;

  console.log('');
  console.log('============================================================');
  console.log(`Phase 24E-6 Step 2 Complete: LLM Summaries`);
  console.log(`  Processed: ${processed}`);
  console.log(`  Skipped (resumed): ${skipped}`);
  console.log(`  Successful: ${successCount}`);
  console.log(`  Failed: ${failCount}`);
  console.log(`  Output: ${outputPath}`);
  console.log(`  Elapsed: ${elapsed}s`);
  console.log('============================================================');

  if (failCount > 0) {
    console.log(`[WARN] ${failCount} communities have no summary. Re-run to retry.`);
  }
}

main();
