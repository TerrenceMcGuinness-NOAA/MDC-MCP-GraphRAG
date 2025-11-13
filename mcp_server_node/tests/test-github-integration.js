#!/usr/bin/env node

/**
 * GitHub Integration Test Script
 * Tests GitHub API access and tool functionality
 */

import { Octokit } from '@octokit/rest';

const GITHUB_TOKEN = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;

async function testGitHubIntegration() {
  console.log('🔍 === GitHub Integration Test ===\n');

  // Check token availability
  if (!GITHUB_TOKEN) {
    console.log('❌ No GitHub token found');
    console.log('   Set GITHUB_TOKEN or GH_TOKEN environment variable');
    process.exit(1);
  }

  console.log(`✅ GitHub token found (${GITHUB_TOKEN.substring(0, 7)}...)`);
  console.log(`   Token length: ${GITHUB_TOKEN.length} characters\n`);

  // Initialize Octokit client
  const octokit = new Octokit({
    auth: GITHUB_TOKEN,
    userAgent: 'global-workflow-mcp-test/1.0.0'
  });

  try {
    // Test 1: Get authenticated user
    console.log('📝 Test 1: Get authenticated user info...');
    const { data: user } = await octokit.rest.users.getAuthenticated();
    console.log(`✅ Authenticated as: ${user.login}`);
    console.log(`   Name: ${user.name || 'N/A'}`);
    console.log(`   Plan: ${user.plan?.name || 'Free'}\n`);

    // Test 2: Get rate limit
    console.log('📊 Test 2: Check API rate limits...');
    const { data: rateLimit } = await octokit.rest.rateLimit.get();
    const core = rateLimit.resources.core;
    console.log(`✅ Rate limit: ${core.remaining}/${core.limit} requests remaining`);
    console.log(`   Resets at: ${new Date(core.reset * 1000).toLocaleString()}\n`);

    // Test 3: Access global-workflow repository
    console.log('📦 Test 3: Access NOAA-EMC/global-workflow repository...');
    const { data: repo } = await octokit.rest.repos.get({
      owner: 'NOAA-EMC',
      repo: 'global-workflow'
    });
    console.log(`✅ Repository: ${repo.full_name}`);
    console.log(`   Description: ${repo.description}`);
    console.log(`   Stars: ${repo.stargazers_count}`);
    console.log(`   Language: ${repo.language}\n`);

    // Test 4: Search recent issues
    console.log('🔍 Test 4: Search recent issues...');
    const { data: issues } = await octokit.rest.issues.listForRepo({
      owner: 'NOAA-EMC',
      repo: 'global-workflow',
      state: 'open',
      per_page: 3,
      sort: 'updated'
    });
    console.log(`✅ Found ${issues.length} recent open issues:`);
    issues.forEach((issue, idx) => {
      console.log(`   ${idx + 1}. #${issue.number}: ${issue.title}`);
      console.log(`      State: ${issue.state}, Comments: ${issue.comments}`);
    });
    console.log('');

    // Test 5: Get recent pull requests
    console.log('🔀 Test 5: Get recent pull requests...');
    const { data: prs } = await octokit.rest.pulls.list({
      owner: 'NOAA-EMC',
      repo: 'global-workflow',
      state: 'open',
      per_page: 3,
      sort: 'updated'
    });
    console.log(`✅ Found ${prs.length} recent open PRs:`);
    prs.forEach((pr, idx) => {
      console.log(`   ${idx + 1}. #${pr.number}: ${pr.title}`);
      console.log(`      Author: ${pr.user.login}, Reviews: ${pr.requested_reviewers?.length || 0}`);
    });
    console.log('');

    // Test 6: Search code
    console.log('🔎 Test 6: Search for "DATAROOT" in code...');
    const { data: codeResults } = await octokit.rest.search.code({
      q: 'DATAROOT in:file repo:NOAA-EMC/global-workflow',
      per_page: 3
    });
    console.log(`✅ Found ${codeResults.total_count} files containing "DATAROOT"`);
    codeResults.items.forEach((item, idx) => {
      console.log(`   ${idx + 1}. ${item.path}`);
      console.log(`      Repository: ${item.repository.name}`);
    });
    console.log('');

    // Final summary
    console.log('=' .repeat(60));
    console.log('✅ === ALL GITHUB INTEGRATION TESTS PASSED ===');
    console.log('=' .repeat(60));
    console.log('\n📋 Summary:');
    console.log('   ✅ Authentication successful');
    console.log(`   ✅ API access working (${core.remaining} requests remaining)`);
    console.log('   ✅ Repository access verified');
    console.log('   ✅ Issue search operational');
    console.log('   ✅ Pull request listing works');
    console.log('   ✅ Code search functional');
    console.log('\n🎯 GitHub tools are ready for MCP server integration!\n');

  } catch (error) {
    console.error('❌ Error during GitHub API test:', error.message);
    if (error.status) {
      console.error(`   HTTP Status: ${error.status}`);
    }
    if (error.response) {
      console.error(`   Response: ${JSON.stringify(error.response.data, null, 2)}`);
    }
    process.exit(1);
  }
}

// Run tests
testGitHubIntegration().catch(console.error);
