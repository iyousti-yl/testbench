"""Command line interface: ``testbench <command>``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from testbench import __version__, demo
from testbench.config import ConfigError, expand_env, load_config
from testbench.connectors import ConnectorError, create_connector
from testbench.report import console_summary, write_report
from testbench.runner import Runner, save_run
from testbench.scenario import ScenarioError, list_suites, load_suite


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.directory)
    demo.create_example_project(target)
    print(f"Created an example project in {target.resolve()}")
    print("Next: cd into it, run 'testbench baseline hr-payroll', then 'testbench run hr-payroll'.")
    return 0


def cmd_connections(args: argparse.Namespace) -> int:
    config = load_config()
    if not config.connections:
        print("No connections configured in testbench.yaml.")
        return 0
    failed = False
    for name, conn in config.connections.items():
        label = f"{name} ({conn.type}{', sensitive' if conn.sensitive else ''})"
        try:
            connector = create_connector(
                conn.type, {**expand_env(conn.settings), "base_dir": config.root}
            )
            connector.test_connection()
            connector.close()
            print(f" ✓ {label}")
        except (ConnectorError, ConfigError) as exc:
            failed = True
            print(f" ✗ {label}: {exc}")
    return 1 if failed else 0


def cmd_objects(args: argparse.Namespace) -> int:
    config = load_config()
    conn = config.connection(args.connection)
    connector = create_connector(conn.type, {**expand_env(conn.settings), "base_dir": config.root})
    try:
        for obj in connector.list_objects(args.scope):
            print(f"{obj.kind:6} {obj.name}")
            if args.columns:
                for col in connector.describe(obj).columns:
                    print(f"         {col.name}  {col.type}{'  (key)' if col.key else ''}")
    finally:
        connector.close()
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    config = load_config()
    for suite_name in list_suites(config.suites_dir):
        suite = load_suite(config.suites_dir / suite_name)
        print(f"{suite.name}  ({len(suite.scenarios)} scenarios)")
        for s in suite.scenarios:
            tags = f"  [{', '.join(s.tags)}]" if s.tags else ""
            print(f"  - {s.name}{tags}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    config = load_config()
    names = [args.suite] if args.suite else list_suites(config.suites_dir)
    for name in names:
        suite = load_suite(config.suites_dir / name)
        print(f" ✓ {suite.name}: {len(suite.scenarios)} scenarios are valid")
    return 0


def _run(args: argparse.Namespace, mode: str) -> int:
    config = load_config()
    result = Runner(config).run_suite(args.suite, mode=mode, tags=args.tag, scenarios=args.scenario)
    if not result.scenarios:
        print("error: no scenario matches the filters", file=sys.stderr)
        return 2
    run_dir = save_run(result, config.output_dir)
    report = write_report(result, run_dir)
    print(console_summary(result))
    print(f"\nReport: {report}")
    return 0 if result.status in ("passed", "skipped") else 1


def cmd_demo(args: argparse.Namespace) -> int:
    config = load_config()
    demo.set_broken(config.root, broken=args.action == "break")
    if args.action == "break":
        print("Introduced a logic defect (contract changes mid-month) and a missing cost center.")
    else:
        print("Restored the demo to its correct state.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="testbench", description="Business-scenario regression testing for data landscapes."
    )
    parser.add_argument("--version", action="version", version=f"testbench {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create an example project with synthetic demo data")
    p.add_argument("directory", nargs="?", default=".")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("connections", help="test every configured connection")
    p.set_defaults(func=cmd_connections)

    p = sub.add_parser("objects", help="list tables and views of a connection")
    p.add_argument("connection")
    p.add_argument("--scope", help="schema or space to list")
    p.add_argument("--columns", action="store_true", help="also show columns")
    p.set_defaults(func=cmd_objects)

    p = sub.add_parser("list", help="list suites and scenarios")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("validate", help="check scenario files against the scenario format")
    p.add_argument("suite", nargs="?")
    p.set_defaults(func=cmd_validate)

    for name, mode, text in (
        ("run", "run", "run a suite and write a report"),
        ("baseline", "baseline", "capture baselines for regression checks"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("suite")
        p.add_argument("--tag", action="append", help="only scenarios with this tag")
        p.add_argument(
            "--scenario", action="append", help="only this scenario (file name without extension)"
        )
        p.set_defaults(func=lambda a, m=mode: _run(a, m))

    p = sub.add_parser("demo", help="break or fix the demo data to see failures")
    p.add_argument("action", choices=["break", "fix"])
    p.set_defaults(func=cmd_demo)

    try:
        from testbench.web.admin import add_parser as add_web_parser
    except ImportError:
        p = sub.add_parser("web", help="web app (needs: pip install 'testbench[web]')")
        p.set_defaults(func=lambda _: _missing_web())
    else:
        add_web_parser(sub)

    return parser


def _missing_web() -> int:
    print("error: the web app needs extra packages: pip install 'testbench[web]'", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (
        ConfigError,
        ScenarioError,
        ConnectorError,
        FileExistsError,
        FileNotFoundError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
