import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';

/**
 * FeedbackLogger — Anonymized query-result pair logging to S3
 * 
 * Logs query text, result doc IDs, scores, collection, model profile, and tool name
 * to S3 in JSON Lines format for downstream fine-tuning and quality analysis.
 * 
 * Opt-in via FEEDBACK_LOGGING=true env var. No PII or raw user prompts.
 */
export class FeedbackLogger {
  constructor() {
    this.enabled = process.env.FEEDBACK_LOGGING === 'true';
    this.bucket = process.env.FEEDBACK_S3_BUCKET || 'mdc-mcp-rag-feedback';
    this.region = process.env.AWS_REGION || 'us-east-1';
    
    if (this.enabled) {
      this.s3 = new S3Client({ region: this.region });
    }
  }

  /**
   * Log anonymized query-result pair to S3.
   * @param {string} queryText - User query text (no PII)
   * @param {Array} results - Search results with id and score
   * @param {string} toolName - MCP tool name that generated the query
   * @param {string} collection - Collection name (includes model profile)
   * @param {string} modelProfile - Model short name (e.g., "mpnet768")
   */
  async log(queryText, results, toolName, collection, modelProfile) {
    if (!this.enabled) return;

    const entry = {
      timestamp: new Date().toISOString(),
      tool_name: toolName,
      query_text: queryText,
      result_ids: results.map(r => r.id || r.chunk_id),
      result_scores: results.map(r => r.score || r.similarity),
      collection,
      model_profile: modelProfile
    };

    const key = `feedback/${new Date().toISOString().split('T')[0]}/${Date.now()}.jsonl`;
    
    try {
      await this.s3.send(new PutObjectCommand({
        Bucket: this.bucket,
        Key: key,
        Body: JSON.stringify(entry) + '\n',
        ContentType: 'application/x-ndjson'
      }));
    } catch (error) {
      console.error(`[WARN] FeedbackLogger failed to write to S3: ${error.message}`);
    }
  }
}
