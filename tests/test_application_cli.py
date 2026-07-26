import unittest
from types import SimpleNamespace
from unittest.mock import Mock


class CLIApplicationTests(unittest.TestCase):
    def _cli(self, *, config=None):
        from trendradar.application.cli import CLIApplication

        analyzer = SimpleNamespace(
            is_github_actions=False,
            update_info=None,
            ctx=SimpleNamespace(config={"DEBUG": False}),
            run=Mock(),
        )
        dependencies = {
            "load_config": Mock(
                return_value=config
                or {
                    "VERSION_CHECK_URL": "",
                    "CONFIGS_VERSION_CHECK_URL": "",
                }
            ),
            "analyzer_factory": Mock(return_value=analyzer),
            "check_versions": Mock(return_value=(False, None)),
            "run_doctor": Mock(return_value=True),
            "show_schedule": Mock(),
            "version": "test",
        }
        return CLIApplication(**dependencies), dependencies, analyzer

    def test_normal_run_loads_once_and_runs_analyzer(self):
        cli, dependencies, analyzer = self._cli()

        code = cli.run([])

        self.assertEqual(code, 0)
        dependencies["load_config"].assert_called_once_with()
        dependencies["analyzer_factory"].assert_called_once_with(
            config=dependencies["load_config"].return_value
        )
        analyzer.run.assert_called_once_with()

    def test_doctor_is_a_separate_command_without_loading_config(self):
        cli, dependencies, analyzer = self._cli()

        code = cli.run(["--doctor"])

        self.assertEqual(code, 0)
        dependencies["run_doctor"].assert_called_once_with()
        dependencies["load_config"].assert_not_called()
        analyzer.run.assert_not_called()

    def test_show_schedule_closes_over_loaded_config_without_analyzer(self):
        cli, dependencies, analyzer = self._cli()

        code = cli.run(["--show-schedule"])

        self.assertEqual(code, 0)
        dependencies["show_schedule"].assert_called_once_with(
            dependencies["load_config"].return_value
        )
        dependencies["analyzer_factory"].assert_not_called()
        analyzer.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
