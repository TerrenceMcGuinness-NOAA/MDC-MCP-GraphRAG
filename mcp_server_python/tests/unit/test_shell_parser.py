"""Unit tests for ShellScriptParser.

Validates: R2.1–R2.8 (extraction), R1.3–R1.4 (type/category classification).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from scripts._shell_parser import EXTERNAL_PACKAGES, ShellParseResult, ShellScriptParser


class TestSourceExtraction:
    """R2.1: `. path` and `source path` → SOURCES."""

    def setup_method(self):
        self.parser = ShellScriptParser()

    def test_dot_source(self):
        content = ". ${USHgfs}/preamble.sh\necho hello"
        r = self.parser.parse("dev/jobs/JGFS_FORECAST", content)
        assert len(r.sources) == 1
        assert r.sources[0]["path"] == "${USHgfs}/preamble.sh"
        assert r.sources[0]["line"] == 1
        assert r.sources[0]["resolved"] == "ush/preamble.sh"

    def test_source_keyword(self):
        content = 'source "${HOMEgfs}/ush/load_fv3.sh"'
        r = self.parser.parse("ush/test.sh", content)
        assert len(r.sources) == 1
        assert r.sources[0]["path"] == "${HOMEgfs}/ush/load_fv3.sh"

    def test_source_with_extension_no_slash(self):
        content = ". machine.sh\necho done"
        r = self.parser.parse("ush/test.sh", content)
        assert len(r.sources) == 1
        assert r.sources[0]["path"] == "machine.sh"

    def test_comment_lines_skipped(self):
        content = "# . ${USHgfs}/preamble.sh\necho hello"
        r = self.parser.parse("ush/test.sh", content)
        assert len(r.sources) == 0

    def test_post_filter_rejects_flags(self):
        content = ". -e something"
        r = self.parser.parse("ush/test.sh", content)
        assert len(r.sources) == 0


class TestInvokeExtraction:
    """R2.2: ${VAR}/script.sh and ./script.sh → INVOKES."""

    def setup_method(self):
        self.parser = ShellScriptParser()

    def test_variable_invoke(self):
        content = "${SCRIPTSgfs}/exglobal_fcst.sh\necho done"
        r = self.parser.parse("dev/jobs/JGLOBAL_FORECAST", content)
        assert len(r.invokes) == 1
        assert r.invokes[0]["script"] == "exglobal_fcst.sh"
        assert r.invokes[0]["variable"] == "SCRIPTSgfs"

    def test_direct_invoke(self):
        content = "bash run_post.sh\necho done"
        r = self.parser.parse("ush/test.sh", content)
        assert len(r.invokes) == 1
        assert r.invokes[0]["script"] == "run_post.sh"
        assert r.invokes[0]["variable"] is None

    def test_dollar_prefix_filtered(self):
        """Direct invokes starting with $ are skipped (handled by var pattern)."""
        content = " $HOME/run.sh\necho done"
        r = self.parser.parse("ush/test.sh", content)
        # The _INVOKE_VAR pattern catches this, not _INVOKE_DIRECT
        # $HOME/run.sh won't match direct invoke (starts with $)
        assert all(inv["variable"] is not None or not inv["script"].startswith("$")
                   for inv in r.invokes)

    def test_external_package_detection(self):
        content = "${HOMEgfs}/scripts/run.sh"
        r = self.parser.parse("ush/test.sh", content)
        for inv in r.invokes:
            if inv["variable"] == "HOMEgfs":
                assert inv["package"] == "GFS"


class TestExportExtraction:
    """R2.3: export VAR=value → EXPORTS."""

    def setup_method(self):
        self.parser = ShellScriptParser()

    def test_simple_export(self):
        content = "export CDATE=2024010100\necho done"
        r = self.parser.parse("ush/test.sh", content)
        assert len(r.exports) == 1
        assert r.exports[0]["name"] == "CDATE"
        assert r.exports[0]["value"] == "2024010100"
        assert r.exports[0]["line"] == 1

    def test_quoted_export(self):
        content = 'export DATA="${DATAROOT}/${job}"'
        r = self.parser.parse("ush/test.sh", content)
        assert r.exports[0]["name"] == "DATA"
        assert r.exports[0]["value"] == "${DATAROOT}/${job}"

    def test_value_truncated_at_200(self):
        content = f"export LONGVAR={'x' * 300}"
        r = self.parser.parse("ush/test.sh", content)
        assert len(r.exports[0]["value"]) == 200


class TestEnvDepsExtraction:
    """R2.4: $VAR / ${VAR} → DEPENDS_ON_ENV (filtered)."""

    def setup_method(self):
        self.parser = ShellScriptParser()

    def test_basic_env_dep(self):
        content = "cd ${DATAROOT}/work\nls $COMOUT"
        r = self.parser.parse("ush/test.sh", content)
        assert "DATAROOT" in r.env_deps
        assert "COMOUT" in r.env_deps

    def test_builtins_filtered(self):
        content = "cd $HOME\necho $PATH $PWD $i $j"
        r = self.parser.parse("ush/test.sh", content)
        assert "HOME" not in r.env_deps
        assert "PATH" not in r.env_deps
        assert "PWD" not in r.env_deps
        assert "i" not in r.env_deps
        assert "j" not in r.env_deps

    def test_env_deps_sorted_unique(self):
        content = "$FOO $BAR $FOO $BAR $ZED"
        r = self.parser.parse("ush/test.sh", content)
        assert r.env_deps == sorted(set(r.env_deps))


class TestConfigExtraction:
    """R2.5: config.<name> → READS_CONFIG."""

    def setup_method(self):
        self.parser = ShellScriptParser()

    def test_config_ref(self):
        content = ". config.base\n. config.fcst"
        r = self.parser.parse("ush/test.sh", content)
        assert len(r.configs) == 2
        assert r.configs[0]["name"] == "base"
        assert r.configs[1]["name"] == "fcst"

    def test_config_deduped(self):
        content = "config.base\nconfig.base\nconfig.base"
        r = self.parser.parse("ush/test.sh", content)
        assert len(r.configs) == 1


class TestFunctionExtraction:
    """R2.6: function definitions → DEFINES."""

    def setup_method(self):
        self.parser = ShellScriptParser()

    def test_function_keyword(self):
        content = "function cleanup() {\n  rm -rf tmp\n}"
        r = self.parser.parse("ush/test.sh", content)
        assert len(r.functions) == 1
        assert r.functions[0]["name"] == "cleanup"
        assert r.functions[0]["line"] == 1

    def test_posix_syntax(self):
        content = "setup_env() {\n  export A=1\n}"
        r = self.parser.parse("ush/test.sh", content)
        assert len(r.functions) == 1
        assert r.functions[0]["name"] == "setup_env"

    def test_builtin_keywords_filtered(self):
        """Shell keywords like if/while/for are NOT functions."""
        content = "if () {\n  true\n}\nwhile () {\n  true\n}"
        r = self.parser.parse("ush/test.sh", content)
        assert all(f["name"] not in ("if", "while", "for") for f in r.functions)


class TestTypeClassification:
    """R1.3: type from path."""

    def setup_method(self):
        self.parser = ShellScriptParser()

    def test_jjob_from_path(self):
        r = self.parser.parse("dev/jobs/JGFS_ATMOS_ANALYSIS", "echo hi")
        assert r.type == "jjob"

    def test_exscript_from_path(self):
        r = self.parser.parse("dev/scripts/exglobal_fcst.sh", "echo hi")
        assert r.type == "exscript"

    def test_ush_from_path(self):
        r = self.parser.parse("ush/load_fv3.sh", "echo hi")
        assert r.type == "ush"

    def test_config_from_path(self):
        r = self.parser.parse("parm/config/config.base", "echo hi")
        assert r.type == "config"

    def test_other_script(self):
        r = self.parser.parse("workflow/startup.sh", "echo hi")
        assert r.type == "script"


class TestCategoryClassification:
    """R1.4: category from filename patterns."""

    def setup_method(self):
        self.parser = ShellScriptParser()

    def test_forecast(self):
        r = self.parser.parse("dev/jobs/JGFS_FORECAST", "echo hi")
        assert r.category == "forecast"

    def test_analysis(self):
        r = self.parser.parse("dev/jobs/JGDAS_ATMOS_ANALYSIS", "echo hi")
        assert r.category == "analysis"

    def test_archive(self):
        r = self.parser.parse("dev/scripts/exgfs_archive.sh", "echo hi")
        assert r.category == "archive"

    def test_post(self):
        r = self.parser.parse("dev/scripts/exgfs_atmos_post.sh", "echo hi")
        assert r.category == "post"

    def test_general_fallback(self):
        r = self.parser.parse("ush/helper.sh", "echo hi")
        assert r.category == "general"
