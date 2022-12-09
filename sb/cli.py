import argparse
import sys
import os
import sb.cfg
import sb.colors
import sb.solscan
import sb.logging
import sb.settings
from sb.exceptions import SolScanError


def cli_args(defaults):

    def fmt_default(defval):
        formatted = (
            "yes" if isinstance(defval, bool) and defval else
            "no" if isinstance(defval, bool) and not defval else
            str(defval) if isinstance(defval, int) else
            "none" if not defval else
            " ".join([str(dv) for dv in defval])
            if isinstance(defval, list) or isinstance(defval, tuple) or isinstance(defval, set) else
            str(defval))
        return f" [default: {formatted}]"

    parser = argparse.ArgumentParser(
        description="Automated analysis of Ethereum smart contracts",
        add_help=False,
        prog="solscan")

    input = parser.add_argument_group("input options")
    input.add_argument("-c", "--configuration",
                       metavar="FILE",
                       type=str,
                       help=f"settings to be processed before command line args{fmt_default(None)}")
    input.add_argument("-t", "--tools",
                       metavar="TOOL",
                       nargs="+",
                       type=str,
                       help=f"tools to run on the contracts{fmt_default(defaults.tools)}")
    input.add_argument("-f", "--files",
                       metavar="PATTERN",
                       nargs="+",
                       type=str,
                       help=f"glob pattern specifying the files to analyse{fmt_default(defaults.files)}"
                       "; may be prefixed by 'DIR:' for search relative to DIR")
    input.add_argument("--runtime",
                       action="store_true",
                       default=None,
                       help=f"analyse the deployed, not the deployment code{fmt_default(defaults.runtime)}")

    exec = parser.add_argument_group("execution options")
    exec.add_argument("--processes",
                      type=int,
                      metavar="N",
                      help=f"number of parallel processes{fmt_default(defaults.processes)}")
    exec.add_argument("--timeout",
                      type=int,
                      metavar="N",
                      help=f"timeout for each task in seconds{fmt_default(defaults.timeout)}")
    exec.add_argument("--cpu-quota",
                      type=int,
                      metavar="N",
                      help=f"cpu quota for docker containers{fmt_default(defaults.cpu_quota)}")
    exec.add_argument("--mem-limit",
                      type=str,
                      metavar="MEM",
                      help=f"memory quota for docker containers, like 512m or 1g{fmt_default(defaults.mem_limit)}")

    output = parser.add_argument_group("output options")
    output.add_argument("--runid",
                        type=str,
                        metavar="ID",
                        help=f"string identifying the run{fmt_default(defaults.runid)}")
    output.add_argument("--results",
                        type=str,
                        metavar="DIR",
                        help=f"folder for the results{fmt_default(defaults.results)}")
    output.add_argument("--log",
                        type=str,
                        metavar="FILE",
                        help=f"file for log messages{fmt_default(defaults.log)}")
    output.add_argument("--overwrite",
                        action="store_true",
                        default=None,
                        help=f"delete old result and rerun the analysis{fmt_default(defaults.overwrite)}")
    output.add_argument("--json",
                        action="store_true",
                        default=None,
                        help=f"parse output and write it to {sb.cfg.PARSER_OUTPUT}{fmt_default(defaults.json)}")
    output.add_argument("--sarif",
                        action="store_true",
                        default=None,
                        help=f"parse output and write it to {sb.cfg.PARSER_OUTPUT} as well as {sb.cfg.SARIF_OUTPUT}{fmt_default(defaults.sarif)}")
    output.add_argument("--quiet",
                        action="store_true",
                        default=None,
                        help=f"suppress output to console (stdout){fmt_default(defaults.quiet)}")

    info = parser.add_argument_group("information options")
    info.add_argument("--version",
                      action="version",
                      version=f"solscan {sb.cfg.VERSION}",
                      help="show version number and exit")
    info.add_argument("-h", "--help",
                      action="help",
                      default=argparse.SUPPRESS,
                      help="show this help message and exit")

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    return vars(parser.parse_args())


def cli(site_cfg=sb.cfg.SITE_CFG):
    settings = sb.settings.Settings()
    # add site settings
    if os.path.exists(site_cfg):
        settings.update(site_cfg)
    # parse command line
    cli_settings = cli_args(settings)
    # add settings from config file specified on command line
    if cli_settings["configuration"]:
        settings.update(cli_settings["configuration"])
    # add settings from command line
    del cli_settings["configuration"]
    for k in [k for k, v in cli_settings.items() if v is None]:
        del cli_settings[k]
    settings.update(cli_settings)
    return settings


def main():
    try:
        settings = cli()
        sb.logging.message(None, f"Arguments passed: {sys.argv}")
        sb.solscan.main(settings)
    except SolScanError as e:
        sb.logging.message(sb.colors.error(e))
        sys.exit(1)
