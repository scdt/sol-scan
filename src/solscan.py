import glob
import os
import operator
import src.tools
import src.solidity
import src.tasks
import src.docker
import src.analysis
import src.colors
import src.logging
import src.cfg
import src.io
import src.settings
from src.exceptions import SolScanError


def collect_files(patterns):
    files = []
    for root, spec in patterns:
        if spec.endswith(".txt"):
            # No globbing, spec is a file specifying a 'dataset'
            contracts = src.io.read_lines(spec)
        else:
            try:
                if root:
                    contracts = glob.glob(spec, root_dir=root, recursive=True)
                else:
                    # avoid root_dir=... unless needed, for python<3.10
                    contracts = glob.glob(spec, recursive=True)
            except TypeError:
                raise SolScanError(f"{root}:{spec}: colons in file patterns only supported for python>=3.10")
        for relfn in contracts:
            root_relfn = os.path.join(root, relfn) if root else relfn
            absfn = os.path.normpath(os.path.abspath(root_relfn))
            if os.path.isfile(absfn) and absfn[-4:] in (".hex", ".sol"):
                files.append((absfn, relfn))
    return files


def collect_tasks(files, tools, settings):
    used_rdirs = set()
    rdir_collisions = 0

    def disambiguate(base):
        nonlocal rdir_collisions
        cnt = 1
        rdir = base
        collision = 0
        while rdir in used_rdirs:
            collision = 1
            cnt += 1
            rdir = f"{base}_{cnt}"
        used_rdirs.add(rdir)
        rdir_collisions += collision
        return rdir

    def report_collisions():
        if rdir_collisions > 0:
            src.logging.message(
                src.colors.warning(f"{rdir_collisions} collision(s) of result directories resolved."), "")
            if rdir_collisions > len(files) * 0.1:
                src.logging.message(src.colors.warning(
                    "    Consider using more of $TOOL, $MODE, $ABSDIR, $RELDIR, $FILENAME,\n"
                    "    $FILEBASE, $FILEEXT when specifying the 'results' directory."))

    def get_solc(pragma, fn, toolid):
        if not src.solidity.ensure_solc_versions_loaded():
            src.logging.message(src.colors.warning(
                "Failed to load list of solc versions; are we connected to the internet?\n"
                "    Proceeding with locally installed versions."),
                "")
        solc_version = src.solidity.get_solc_version(pragma)
        if not solc_version:
            raise SolScanError(
                "Cannot determine Solidity version\n"
                f"{fn}: {pragma}")
        solc_path = src.solidity.get_solc_path(solc_version)
        if not solc_path:
            raise SolScanError(
                f"Cannot load solc {solc_version}\n"
                f"required by {toolid} and {fn})")
        return solc_version, solc_path

    def ensure_loaded(image):
        if not src.docker.is_loaded(image):
            src.logging.message(f"Loading docker image {image}, may take a while ...")
            src.docker.load(image)

    tasks = []

    last_absfn = None
    for absfn, relfn in sorted(files):
        if absfn == last_absfn:
            # ignore duplicate contracts
            continue
        last_absfn = absfn

        is_sol = absfn[-4:] == ".sol"
        is_byc = absfn[-4:] == ".hex" and not (absfn[-7:-4] == ".rt" or settings.runtime)
        is_rtc = absfn[-4:] == ".hex" and (absfn[-7:-4] == ".rt" or settings.runtime)

        pragma = None
        if is_sol:
            prg = src.io.read_lines(absfn)
            pragma = src.solidity.get_pragma(prg)

        for tool in sorted(tools, key=operator.attrgetter("id", "mode")):
            if ((is_sol and tool.mode == "solidity") or
                (is_byc and tool.mode == "bytecode") or
                    (is_rtc and tool.mode == "runtime")):

                # find unique name for result dir
                # ought to be the same when rerunning SB with the same args,
                # due to sorting files and tools
                base = settings.resultdir(tool.id, tool.mode, absfn, relfn)
                rdir = disambiguate(base)

                # load resources
                solc_version, solc_path = None, None
                if tool.solc:
                    solc_version, solc_path = get_solc(pragma, absfn, tool.id)
                ensure_loaded(tool.image)

                task = src.tasks.Task(absfn, relfn, rdir, solc_version, solc_path, tool, settings)
                tasks.append(task)

    report_collisions()
    return tasks


def main(settings: src.settings.Settings):
    settings.freeze()
    src.logging.quiet = settings.quiet
    src.logging.message(
        src.colors.success(f"Welcome to SolScan {src.cfg.VERSION}"),
        f"Settings: {settings}")
    tools = src.tools.load(settings.tools)
    if not tools:
        src.logging.message(src.colors.warning("Warning: no tools selected!"))
    files = collect_files(settings.files)
    if not files:
        src.logging.message(src.colors.warning("Warning: no files selected!"))
    tasks = collect_tasks(files, tools, settings)
    if not tasks:
        raise SolScanError("No tasks to execute.")
    src.analysis.run(tasks, settings)
