# Configurable Report Templates - SDD Workflow

**Status:** Planned Enhancement  
**Priority:** Medium  
**Estimated Effort:** 8-12 hours  
**Target Release:** v3.1.0 or later

## Overview

Enable SME-driven report formatting through configuration files rather than hardcoded formatting instructions in MCP tools. This allows different stakeholders (EVS team, GFS ops, leadership) to define their preferred report formats without modifying code.

## Problem Statement

**Current State:**
- MCP tool `scan_repository_compliance` returns JSON data + hardcoded formatting instructions
- Report format is baked into JavaScript code
- Changing format requires code changes and MCP server restart
- Different audiences (technical vs executive) need different formats

**Desired State:**
- Report templates stored as configuration files (markdown)
- SMEs can modify templates without touching code
- Multiple templates available for different audiences
- Template selection via tool parameter

## Architecture

### Directory Structure
```
mcp_server_node/
├── report_templates/
│   ├── README.md                        # Template documentation
│   ├── default.md                       # Default format (current)
│   ├── evs_compliance_detailed.md       # EVS team preferred format
│   ├── global_workflow_operations.md    # GFS operations format
│   ├── executive_summary.md             # High-level for leadership
│   └── developer_technical.md           # Deep dive for developers
```

### Template File Format

Each template is a markdown file with:
1. **Metadata section** (YAML frontmatter)
2. **Formatting instructions** (for LLM)
3. **Structure requirements** (sections, tables, ordering)

**Example: `evs_compliance_detailed.md`**
```markdown
---
name: EVS Compliance Detailed Report
audience: EVS Development Team
description: Comprehensive compliance report with actionable fixes
version: 1.0.0
---

# Report Format Instructions for LLM

## Required Sections (in order)
1. Executive Summary
   - Compliance percentage
   - Files analyzed breakdown by type
   - Key metrics comparison (before/after if applicable)
   
2. Issue Categories
   - Present as TABLES, not lists or code blocks
   - Columns: #, File Path, Primary Issue, EE2 Reference
   - Show top 20 files + note about remainder
   
3. Detailed Findings
   - Group by issue type (missing set -x, no validation, shebang)
   - Include EE2 evidence citations (standards.rst line numbers)
   - Show code examples with before/after
   
4. Priority Action Plan
   - Phase 1: Quick wins (<1 hour)
   - Phase 2: High impact (1-4 hours)
   - Phase 3: Critical safety (4-8 hours)
   
5. Fix Code Examples
   - Bash examples with proper formatting
   - EE2 evidence citations
   - Phase 2 corrections where applicable
   
6. Appendix: Scan Metadata
   - JSON block with scan parameters

## Formatting Rules
- Use tables for file lists (NOT code blocks or plain lists)
- File paths in backticks: `path/to/file.sh`
- Issue counts in bold: **39 files**
- EE2 references: standards.rst lines 588-595
- Code blocks use triple backticks with language tags
- Phase 2 corrections in italics when noting exceptions

## Tone
- Professional and consultative
- Focus on actionable items, not theory
- Assume technical audience familiar with EE2
```

### Implementation Changes

**1. Tool Parameter Addition**
```javascript
async scan_repository_compliance({
  repository_path,
  categories = ['error_handling', 'environment_variables', 'file_naming'],
  file_patterns = ['**/*.sh', '**/*.py', '**/JEVS_*'],
  sample_size = 10000,
  template = 'default'  // NEW PARAMETER
})
```

**2. Template Loading Logic**
```javascript
// Load template from file system
const templatePath = path.join(__dirname, '../../report_templates', `${template}.md`);

let formatInstructions;
try {
  const templateContent = fs.readFileSync(templatePath, 'utf-8');
  
  // Parse YAML frontmatter (optional metadata)
  const frontmatterMatch = templateContent.match(/^---\n([\s\S]+?)\n---\n([\s\S]+)$/);
  if (frontmatterMatch) {
    const metadata = yaml.parse(frontmatterMatch[1]);
    formatInstructions = frontmatterMatch[2];
    console.error(`[INFO] Using template: ${metadata.name} v${metadata.version}`);
  } else {
    formatInstructions = templateContent;
  }
} catch (err) {
  console.error(`[WARN] Template '${template}' not found, using default`);
  formatInstructions = this.getDefaultFormatInstructions();
}
```

**3. Output Construction**
```javascript
const output = `# EE2 Compliance Scan - Action Items

\`\`\`json
${JSON.stringify(scanResult, null, 2)}
\`\`\`

${formatInstructions}`;

return { content: [{ type: 'text', text: output }] };
```

## Usage Examples

### EVS Team (Detailed Technical Report)
```javascript
mcp_eib-mcp-rag-f_scan_repository_compliance({
  repository_path: '/mcp_rag_eib/eib-mcp-rag-server/supported_repos/EVS',
  categories: ['error_handling'],
  template: 'evs_compliance_detailed'
})
```

### Leadership (Executive Summary)
```javascript
mcp_eib-mcp-rag-f_scan_repository_compliance({
  repository_path: '/mcp_rag_eib/eib-mcp-rag-server/supported_repos/EVS',
  categories: ['error_handling'],
  template: 'executive_summary'
})
```

### Operations Team (Action-Oriented)
```javascript
mcp_eib-mcp-rag-f_scan_repository_compliance({
  repository_path: '/mcp_rag_eib/supported_repos/global-workflow',
  categories: ['error_handling', 'file_naming'],
  template: 'global_workflow_operations'
})
```

## Benefits

1. **SME Control**
   - Teams define their own report formats
   - No code changes required for format updates
   - Version control for format evolution

2. **Consistency**
   - Same format every time for given template
   - Institutional knowledge captured in templates
   - Onboarding new team members easier

3. **Flexibility**
   - Multiple audiences supported
   - Context-appropriate detail levels
   - Custom formats for special cases

4. **Maintainability**
   - Templates separate from business logic
   - Easier testing (compare against template)
   - Format changes don't require code review

## Implementation Plan

### Phase 1: Infrastructure (4 hours)
- [ ] Create `report_templates/` directory
- [ ] Implement template loading logic in `SemanticSearchTools.js`
- [ ] Add `template` parameter to `scan_repository_compliance` tool
- [ ] Handle template not found error (fallback to default)
- [ ] Add YAML frontmatter parsing support

### Phase 2: Initial Templates (2 hours)
- [ ] Create `default.md` (current hardcoded format)
- [ ] Create `evs_compliance_detailed.md` (based on current report)
- [ ] Create `executive_summary.md` (high-level format)
- [ ] Create `report_templates/README.md` (documentation)

### Phase 3: Testing (2-3 hours)
- [ ] Test default template matches current behavior
- [ ] Test EVS detailed template produces expected format
- [ ] Test executive summary template for leadership
- [ ] Test template not found fallback
- [ ] Verify all templates with actual scans

### Phase 4: Documentation (1 hour)
- [ ] Update MCP tool documentation with template parameter
- [ ] Document template file format in README
- [ ] Provide template creation guide for SMEs
- [ ] Update CHANGELOG.md for v3.1.0

## Template Variables (Future Enhancement)

Consider adding template variable substitution:
```markdown
Report generated for: {{repository_name}}
Scan date: {{scan_date}}
Total files: {{statistics.total_files}}
Compliance rate: {{compliance_rate}}%
```

This would allow more dynamic content without LLM interpretation.

## Success Criteria

- [ ] SMEs can modify report format without code changes
- [ ] Multiple templates coexist and are selectable
- [ ] Template changes don't require MCP server restart (if hot-reload added)
- [ ] All existing reports continue to work with default template
- [ ] Template format is documented and easy to create

## Related Work

- **Phase 2 Compliance Architecture** - Template system follows same configuration-driven approach
- **SDD Methodology** - Specifications (templates) drive behavior
- **MCP Tool Design** - Data separation from presentation

## Open Questions

1. Should templates support variable substitution (Jinja2-style)?
2. Should templates be hot-reloadable or require server restart?
3. Should we support template inheritance (base template + overrides)?
4. Should templates validate against JSON schema for data structure?

## Notes

This enhancement aligns with the Phase 2 compliance fix philosophy:
- **Configuration over code** - Templates are configuration
- **Evidence-based** - Templates document format requirements
- **SME-driven** - Domain experts control presentation
- **Single source of truth** - Template file is authoritative

---
**Document Status:** Living document - update as requirements evolve  
**Last Updated:** November 20, 2025  
**Next Review:** After v3.1.0 planning
