# Requirements Document

## Introduction

This feature adds standardized `%manual` / `%end` documentation blocks to ecFlow `.ecf` scripts in the global-workflow forked repository. The documentation content is sourced from a CSV reference file (`ecf_script_discriptions.txt`) containing job descriptions and troubleshooting guidance for approximately 81 scripts. A Python script will parse the CSV, resolve each entry to an on-disk `.ecf` file, and append (or update) a formatted `%manual` block after the `%include <tail.h>` directive.

## Glossary

- **ECF_Script**: An ecFlow task definition file (`.ecf` extension) containing PBS directives, module loads, environment setup, and a call to a J-Job script, bookended by `%include <head.h>` and `%include <tail.h>` directives
- **Manual_Block**: An ecFlow documentation section delimited by `%manual` and `%end` markers, placed after `%include <tail.h>`, containing structured task documentation visible to operators via the ecFlow GUI
- **CSV_Reference**: The file `ecf_script_discriptions.txt` containing comma-separated rows with columns: Job Name (relative `.ecf` file path), Description, and Troubleshooting
- **Task_Name**: The base filename of an `.ecf` script without the file extension and without the leading `j` prefix (e.g., `gfs_atmos_analysis_calc` derived from `jgfs_atmos_analysis_calc.ecf`)
- **Documentation_Generator**: The Python script that reads the CSV_Reference, resolves file paths, and writes Manual_Block content into ECF_Script files
- **Consolidated_Entry**: A single Manual_Block produced by merging multiple CSV_Reference rows that share the same Job Name path into one combined documentation block

## Requirements

### Requirement 1: CSV Parsing

**User Story:** As a developer, I want the Documentation_Generator to parse the CSV_Reference file, so that description and troubleshooting text is available for each ECF_Script.

#### Acceptance Criteria

1. WHEN the Documentation_Generator is invoked with a path to the CSV_Reference, THE Documentation_Generator SHALL parse all rows extracting the Job Name, Description, and Troubleshooting columns
2. WHEN a CSV row contains commas within quoted fields, THE Documentation_Generator SHALL correctly parse the full field content without splitting on embedded commas
3. WHEN the CSV_Reference contains multiple rows with the same Job Name, THE Documentation_Generator SHALL group those rows into a single Consolidated_Entry for that Job Name
4. IF the CSV_Reference file does not exist at the specified path, THEN THE Documentation_Generator SHALL exit with a non-zero return code and print a descriptive error message to stderr

### Requirement 2: File Path Resolution

**User Story:** As a developer, I want the Documentation_Generator to resolve CSV Job Name paths to actual on-disk file locations, so that documentation can be written to the correct ECF_Script files regardless of directory structure differences.

#### Acceptance Criteria

1. WHEN a Job Name path from the CSV_Reference corresponds to an existing file on disk at the expected location, THE Documentation_Generator SHALL resolve it to that file path
2. WHEN a Job Name path from the CSV_Reference does not exist at the literal path, THE Documentation_Generator SHALL search the `ecf/scripts/` directory tree for a file matching the base filename
3. IF a Job Name path cannot be resolved to any existing file on disk, THEN THE Documentation_Generator SHALL log a warning identifying the unresolved path and continue processing remaining entries
4. THE Documentation_Generator SHALL accept a configurable base directory parameter specifying the root of the `ecf/scripts/` tree

### Requirement 3: Manual Block Generation

**User Story:** As a developer, I want each ECF_Script to receive a properly formatted Manual_Block, so that operators can view structured task documentation through the ecFlow GUI.

#### Acceptance Criteria

1. THE Documentation_Generator SHALL produce a Manual_Block in the format: `%manual` line, blank line, `TASK <Task_Name>` line, blank line, `PURPOSE: <description text>` section, blank line, `TROUBLESHOOTING` heading line, blank line, `<troubleshooting text>` section, blank line, `%end` line
2. WHEN generating the Task_Name, THE Documentation_Generator SHALL derive it from the `.ecf` base filename by removing the file extension and stripping the leading `j` character
3. WHEN a Consolidated_Entry contains multiple descriptions from grouped CSV rows, THE Documentation_Generator SHALL include all descriptions in the PURPOSE section, separated by paragraph breaks with a sub-heading or numbered label for each distinct description
4. WHEN a Consolidated_Entry contains multiple troubleshooting texts from grouped CSV rows, THE Documentation_Generator SHALL include all troubleshooting texts in the TROUBLESHOOTING section, separated by paragraph breaks

### Requirement 4: Manual Block Insertion

**User Story:** As a developer, I want the Manual_Block to be placed at the correct location in each ECF_Script, so that ecFlow can parse it and existing script logic is not disrupted.

#### Acceptance Criteria

1. THE Documentation_Generator SHALL insert the Manual_Block after the `%include <tail.h>` line in each ECF_Script
2. WHEN an ECF_Script already contains an existing Manual_Block (text between `%manual` and `%end`), THE Documentation_Generator SHALL replace the existing Manual_Block with the newly generated content
3. WHEN an ECF_Script does not contain a `%include <tail.h>` line, THE Documentation_Generator SHALL append the Manual_Block at the end of the file
4. THE Documentation_Generator SHALL preserve all content above the Manual_Block insertion point without modification

### Requirement 5: Idempotent Execution

**User Story:** As a developer, I want to run the Documentation_Generator multiple times without producing duplicate or corrupted documentation, so that the tool is safe to re-run as the CSV_Reference is updated.

#### Acceptance Criteria

1. WHEN the Documentation_Generator is run on an ECF_Script that already has a Manual_Block generated by a previous run, THE Documentation_Generator SHALL produce output identical to a fresh single run
2. THE Documentation_Generator SHALL produce the same file content regardless of how many consecutive times it is executed with the same inputs
3. WHEN the CSV_Reference content changes between runs, THE Documentation_Generator SHALL update the Manual_Block to reflect the current CSV_Reference content

### Requirement 6: Skipped and Missing Script Handling

**User Story:** As a developer, I want scripts marked as SKIPPED or NOT ON DISK to still receive documentation noting their status, so that operators understand why those tasks may fail.

#### Acceptance Criteria

1. WHEN a CSV_Reference entry contains "SKIPPED" or "NOT ON DISK" in the Description or Troubleshooting column and the file exists on disk, THE Documentation_Generator SHALL generate a Manual_Block that includes the SKIPPED/NOT ON DISK notation in the PURPOSE section
2. WHEN a CSV_Reference entry references a file that does not exist on disk, THE Documentation_Generator SHALL log the entry as unresolved and skip writing a Manual_Block for that entry
3. THE Documentation_Generator SHALL include a summary report at the end of execution listing the count of files updated, files skipped due to non-existence, and files with errors

### Requirement 7: Output Reporting

**User Story:** As a developer, I want a clear summary of what the Documentation_Generator did, so that I can verify the run completed correctly and identify any issues.

#### Acceptance Criteria

1. WHEN the Documentation_Generator completes execution, THE Documentation_Generator SHALL print a summary to stdout containing: total CSV entries processed, files successfully updated, files with existing Manual_Blocks that were replaced, files not found on disk, and any errors encountered
2. WHEN the Documentation_Generator is invoked with a `--dry-run` flag, THE Documentation_Generator SHALL print the list of files that would be modified and the generated Manual_Block content without writing any changes to disk
3. WHEN the Documentation_Generator is invoked with a `--verbose` flag, THE Documentation_Generator SHALL print each file path and action taken (created, replaced, skipped) as it processes entries

### Requirement 8: Text Formatting

**User Story:** As a developer, I want the Manual_Block text to be cleanly formatted with appropriate line wrapping, so that the documentation is readable in terminal-width displays and the ecFlow GUI.

#### Acceptance Criteria

1. THE Documentation_Generator SHALL wrap description and troubleshooting text lines to a maximum of 72 characters
2. THE Documentation_Generator SHALL preserve paragraph structure from the original CSV text (sentences describing distinct concepts remain in separate paragraphs)
3. WHEN the CSV text contains em-dashes (—), THE Documentation_Generator SHALL convert them to standard ASCII double-dashes (--)
4. THE Documentation_Generator SHALL ensure a single trailing newline after the `%end` marker
