# Requirements Document

## Introduction

The Python ingestion scripts (`ingest_fortran_graph.py`, `ingest_shell_graph_v8.py`, `ingest_cross_language_bridges.py`, `ingest_code_v8.py`) in `mcp_server_node/scripts/` use `aws_backend.py` to connect to Neptune when `DB_BACKEND=aws`. The current `get_graph_driver()` creates a neo4j Bolt driver with `Auth("none", "", "")`, but Neptune has IAM auth enabled (`iamAuthEnabled: true`). The Bolt driver cannot perform SigV4 authentication, and no Python SigV4 Bolt package exists on PyPI.

The solution replaces the Bolt driver approach with Neptune's HTTP openCypher API (`https://<endpoint>:8182/opencypher`) using SigV4 request signing via `boto3`/`botocore`. This approach is already proven — the Track B ingestion script uses it for count queries. The HTTP adapter must provide a neo4j `Driver`-compatible interface (`session().run(query, **params)`) so the four ingestion scripts require zero code changes.

## Glossary

- **Ingestion_Script**: One of the four Python scripts that parse source code and write graph nodes/relationships to the graph database: `ingest_fortran_graph.py`, `ingest_shell_graph_v8.py`, `ingest_cross_language_bridges.py`, `ingest_code_v8.py`
- **Neptune_HTTP_Adapter**: A Python class that implements the neo4j `Driver` interface (`session().run()`) by sending SigV4-signed HTTP POST requests to Neptune's `/opencypher` endpoint
- **SigV4**: AWS Signature Version 4, the request signing protocol used to authenticate HTTP requests to AWS services including Neptune
- **openCypher_Endpoint**: Neptune's HTTP API at `https://<host>:8182/opencypher` that accepts Cypher queries via POST with `Content-Type: application/x-www-form-urlencoded`
- **Driver_Interface**: The neo4j Python driver API surface used by ingestion scripts: `driver.session()` returns a session, `session.run(query, **params)` executes a Cypher query, `session.close()` releases resources
- **MERGE_Operation**: An idempotent Cypher upsert operation (`MERGE (n:Label {key: value}) SET ...`) used by all ingestion scripts to create-or-update nodes and relationships
- **aws_backend**: The module `mcp_server_node/scripts/aws_backend.py` that provides `get_graph_driver()` and `get_vector_client()` functions, routing to legacy or AWS backends based on `DB_BACKEND`
- **Credential_Chain**: The boto3/botocore default credential resolution chain (environment variables, instance profile, config files) used to obtain AWS credentials for SigV4 signing

## Requirements

### Requirement 1: Neptune HTTP openCypher Adapter

**User Story:** As a developer running ingestion scripts with `DB_BACKEND=aws`, I want `get_graph_driver()` to return a Neptune-compatible client that uses SigV4-signed HTTP requests, so that the scripts can authenticate and write data to Neptune.

#### Acceptance Criteria

1. WHEN `DB_BACKEND` is set to `aws`, THE aws_backend `get_graph_driver()` function SHALL return a Neptune_HTTP_Adapter instance instead of a neo4j Bolt driver
2. THE Neptune_HTTP_Adapter SHALL send HTTP POST requests to the openCypher_Endpoint at `https://<host>:8182/opencypher`
3. THE Neptune_HTTP_Adapter SHALL sign each HTTP request using SigV4 with credentials obtained from the Credential_Chain
4. THE Neptune_HTTP_Adapter SHALL use the `neptune-db` service name and the configured AWS region for SigV4 signing
5. WHEN `NEPTUNE_ENDPOINT` is not set, THE aws_backend `get_graph_driver()` function SHALL print an error message to stderr and exit with a non-zero status code

### Requirement 2: neo4j Driver-Compatible Interface

**User Story:** As a developer, I want the Neptune_HTTP_Adapter to provide the same interface as the neo4j Python driver, so that existing ingestion scripts work without code changes.

#### Acceptance Criteria

1. THE Neptune_HTTP_Adapter SHALL provide a `session()` method that returns a context-manager-compatible session object
2. THE session object SHALL provide a `run(query, **params)` method that executes an openCypher query against Neptune
3. THE session object SHALL provide a `close()` method that releases resources
4. THE Neptune_HTTP_Adapter SHALL support the `with driver.session() as session:` context manager pattern used by all four Ingestion_Scripts
5. THE Neptune_HTTP_Adapter SHALL provide a `close()` method that performs cleanup
6. THE Neptune_HTTP_Adapter SHALL provide a `verify_connectivity()` method that executes `RETURN 1` against Neptune and raises an exception on failure

### Requirement 3: Query Parameter Serialization

**User Story:** As a developer, I want Cypher query parameters to be correctly serialized in HTTP requests, so that MERGE operations with parameterized values succeed on Neptune.

#### Acceptance Criteria

1. WHEN `session.run(query, **params)` is called with keyword parameters, THE Neptune_HTTP_Adapter SHALL serialize the parameters as a JSON object in the `parameters` field of the HTTP POST body
2. WHEN `session.run(query)` is called without parameters, THE Neptune_HTTP_Adapter SHALL send only the `query` field in the HTTP POST body
3. THE Neptune_HTTP_Adapter SHALL URL-encode the POST body with `Content-Type: application/x-www-form-urlencoded`
4. WHEN a parameter value is `None`, a string, an integer, a float, or a boolean, THE Neptune_HTTP_Adapter SHALL serialize the value correctly in the JSON parameters object
5. WHEN a parameter value is a list or dict, THE Neptune_HTTP_Adapter SHALL serialize the value as a JSON array or object respectively

### Requirement 4: Query Result Handling

**User Story:** As a developer, I want query results from Neptune's HTTP API to be accessible in the same way as neo4j driver results, so that ingestion scripts that read query results continue to work.

#### Acceptance Criteria

1. WHEN Neptune returns a successful response, THE `session.run()` method SHALL return a result object that supports iteration over records
2. WHEN a result record is accessed by column name (e.g., `record["count"]`), THE result object SHALL return the corresponding value from Neptune's JSON response
3. WHEN `result.single()` is called, THE result object SHALL return the first record or `None` if no records exist
4. WHEN Neptune returns an HTTP error status (4xx or 5xx), THE `session.run()` method SHALL raise an exception containing the HTTP status code and Neptune's error message
5. WHEN Neptune returns a response with zero result rows, THE result object SHALL behave as an empty iterable

### Requirement 5: Ingestion Script Compatibility

**User Story:** As a developer, I want all four ingestion scripts to successfully ingest data into Neptune using the new adapter, so that Phase 53 Track B re-ingestion is unblocked.

#### Acceptance Criteria

1. WHEN `ingest_fortran_graph.py` runs with `DB_BACKEND=aws`, THE Ingestion_Script SHALL successfully MERGE FortranModule, FortranSubroutine, FortranFunction, and FortranProgram nodes into Neptune
2. WHEN `ingest_shell_graph_v8.py` runs with `DB_BACKEND=aws`, THE Ingestion_Script SHALL successfully MERGE ShellScript, EnvironmentVariable, and ConfigFile nodes and their relationships into Neptune
3. WHEN `ingest_cross_language_bridges.py` runs with `DB_BACKEND=aws`, THE Ingestion_Script SHALL successfully MERGE EXECUTES and INVOKES relationships into Neptune
4. WHEN `ingest_code_v8.py` runs with `DB_BACKEND=aws`, THE Ingestion_Script SHALL successfully MERGE File, Function, Class, and Module nodes into Neptune
5. THE four Ingestion_Scripts SHALL require zero source code modifications to work with the Neptune_HTTP_Adapter

### Requirement 6: Error Handling and Resilience

**User Story:** As a developer running long-running ingestion jobs, I want the adapter to handle transient errors gracefully, so that ingestion does not fail due to temporary network issues or credential expiry.

#### Acceptance Criteria

1. WHEN a Neptune HTTP request fails with a retryable error (HTTP 429, 500, 503), THE Neptune_HTTP_Adapter SHALL retry the request up to 3 times with exponential backoff
2. WHEN all retry attempts are exhausted, THE Neptune_HTTP_Adapter SHALL raise an exception with the final error details
3. WHEN AWS credentials expire during a long-running ingestion, THE Neptune_HTTP_Adapter SHALL refresh credentials from the Credential_Chain before the next request
4. IF a network timeout occurs, THEN THE Neptune_HTTP_Adapter SHALL raise a descriptive exception indicating the timeout duration and Neptune endpoint
5. THE Neptune_HTTP_Adapter SHALL set a per-request timeout of 30 seconds for individual openCypher queries

### Requirement 7: Endpoint Configuration

**User Story:** As a developer, I want the adapter to accept Neptune endpoint configuration from environment variables, so that it works with the existing `DB_BACKEND=aws` routing in `aws_backend.py`.

#### Acceptance Criteria

1. THE Neptune_HTTP_Adapter SHALL derive the HTTPS endpoint from the `NEPTUNE_ENDPOINT` environment variable
2. WHEN `NEPTUNE_ENDPOINT` contains a `wss://` prefix, THE Neptune_HTTP_Adapter SHALL convert the prefix to `https://` for HTTP API access
3. WHEN `NEPTUNE_ENDPOINT` contains a `bolt+s://` prefix, THE Neptune_HTTP_Adapter SHALL convert the prefix to `https://` for HTTP API access
4. WHEN `NEPTUNE_ENDPOINT` contains a bare hostname (no scheme), THE Neptune_HTTP_Adapter SHALL prepend `https://` and append port `8182`
5. THE Neptune_HTTP_Adapter SHALL read the AWS region from the `AWS_REGION` environment variable, defaulting to `us-east-1`

### Requirement 8: Logging and Observability

**User Story:** As a developer monitoring ingestion progress, I want the adapter to log connection status and errors, so that I can diagnose issues during Track B re-ingestion.

#### Acceptance Criteria

1. WHEN the Neptune_HTTP_Adapter successfully connects (via `verify_connectivity()`), THE Neptune_HTTP_Adapter SHALL print `[OK] Connected to Neptune (HTTP/SigV4): <endpoint>` to stderr
2. WHEN a query fails after all retries, THE Neptune_HTTP_Adapter SHALL print `[ERROR] Neptune query failed: <status_code> <error_message>` to stderr
3. WHEN a retry is attempted, THE Neptune_HTTP_Adapter SHALL print `[WARN] Neptune request retry <attempt>/<max>: <reason>` to stderr
4. THE Neptune_HTTP_Adapter SHALL use the `[OK]`, `[ERROR]`, `[WARN]` ASCII prefix convention consistent with the existing ingestion scripts
