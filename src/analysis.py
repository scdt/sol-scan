import multiprocessing
import random
import time
import datetime
import os
import cpuinfo
import platform
import src.logging
import src.colors
import src.docker
import src.cfg
import src.io
import src.parsing
import src.sarif
from src.exceptions import SolScanError


cpu = cpuinfo.get_cpu_info()
uname = platform.uname()
SYSTEM_INFO = {
    "solscan": {
        "version": src.cfg.VERSION,
        "python": cpu.get("python_version")
    },
    "platform": {
        "system": uname.system,
        "release": uname.release,
        "version": uname.version,
    },
    "cpu_info": {
        "arch_string_raw": cpu.get("arch_string_raw"),
        "bits": cpu.get("bits"),
        "brand_raw": cpu.get("brand_raw"),
        "hz_actual_friendly": cpu.get("hz_actual_friendly"),
        "hz_advertised_friendly": cpu.get("hz_advertised_friendly"),
        "model": cpu.get("model"),
        "stepping": cpu.get("stepping"),
        "vendor_id_raw": cpu.get("vendor_id_raw"),
    }
}


def task_log_dict(task, start_time, duration, exit_code, log, output, docker_args):
    task_log = {
        "filename": task.relfn,
        "runid": task.settings.runid,
        "result": {
            "start": start_time,
            "duration": duration,
            "exit_code": exit_code,
            "logs": src.cfg.TOOL_LOG if log else None,
            "output": src.cfg.TOOL_OUTPUT if output else None},
        "solc": str(task.solc_version) if task.solc_version else None,
        "tool": task.tool.dict(),
        "docker": docker_args,
    }
    task_log.update(SYSTEM_INFO)
    return task_log


def execute(task):

    # create result dir if it doesn't exist
    os.makedirs(task.rdir, exist_ok=True)
    if not os.path.isdir(task.rdir):
        raise SolScanError(f"Cannot create result directory {task.rdir}")

    # check whether result dir is empty,
    # and if not, whether we are going to overwrite it
    fn_task_log = os.path.join(task.rdir, src.cfg.TASK_LOG)
    if os.path.exists(fn_task_log):
        old = src.io.read_json(fn_task_log)
        old_fn = old["filename"]
        old_toolid = old["tool"]["id"]
        old_mode = old["tool"]["mode"]
        if task.relfn != old_fn or task.tool.id != old_toolid or task.tool.mode != old_mode:
            raise SolScanError(
                f"Result directory {task.rdir} occupied by another task"
                f" ({old_toolid}/{old_mode}, {old_fn})")
        if not task.settings.overwrite:
            return 0.0

    # remove any leftovers from a previous analysis
    fn_tool_log = os.path.join(task.rdir, src.cfg.TOOL_LOG)
    fn_tool_output = os.path.join(task.rdir, src.cfg.TOOL_OUTPUT)
    fn_parser_output = os.path.join(task.rdir, src.cfg.PARSER_OUTPUT)
    fn_sarif_output = os.path.join(task.rdir, src.cfg.SARIF_OUTPUT)
    for fn in (fn_task_log, fn_tool_log, fn_tool_output, fn_parser_output, fn_sarif_output):
        try:
            os.remove(fn)
        except:
            pass
        if os.path.exists(fn):
            raise SolScanError(f"Cannot clear old output {fn}")

    # perform analysis
    start_time = time.time()
    exit_code, tool_log, tool_output, docker_args = src.docker.execute(task)
    duration = time.time() - start_time

    # write result to files
    task_log = task_log_dict(task, start_time, duration, exit_code, tool_log, tool_output, docker_args)
    src.io.write_json(fn_task_log, task_log)
    if tool_log:
        src.io.write_txt(fn_tool_log, tool_log)
    if tool_output:
        src.io.write_bin(fn_tool_output, tool_output)

    # Parse output of tool
    if task.settings.json or task.settings.sarif:
        parsed_result = src.parsing.parse(task_log, tool_log, tool_output)
        src.io.write_json(fn_parser_output, parsed_result)

        # Format parsed result as sarif
        if task.settings.sarif:
            sarif_result = src.sarif.sarify(task_log["tool"], parsed_result["findings"])
            src.io.write_json(fn_sarif_output, sarif_result)

    return duration


def analyser(logqueue, taskqueue, tasks_total, tasks_started, tasks_completed, time_completed):

    def pre_analysis():
        with tasks_started.get_lock():
            tasks_started.value += 1
            started = tasks_started.value
        src.logging.message(
            f"{started}/{tasks_total}: {src.colors.tool(task.tool.id)} and {src.colors.file(task.relfn)}",
            "", logqueue)

    def post_analysis(duration):
        with tasks_completed.get_lock(), time_completed.get_lock():
            tasks_completed.value += 1
            time_completed.value += duration
            elapsed = time_completed.value
            completed = tasks_completed.value
        # estimated time to completion = avg.time per task * remaining tasks / no.processes
        etc = elapsed / completed * (tasks_total - completed) / task.settings.processes
        etc_fmt = datetime.timedelta(seconds=round(etc))
        duration_fmt = datetime.timedelta(seconds=round(duration))
        #src.logging.message(f"{completed}/{tasks_total} completed, ETC {etc_fmt}")

    while True:
        task = taskqueue.get()
        if task is None:
            return
        src.logging.quiet = task.settings.quiet
        pre_analysis()
        try:
            duration = execute(task)
        except SolScanError as e:
            duration = 0
            src.logging.message(src.colors.error(f"Analysis of {task.absfn} with {task.tool.id} failed.\n{e}"), "", logqueue)
        post_analysis(duration)


def run(tasks, settings):
    # spawn processes (instead of forking), for identical behavior on Linux and MacOS
    mp = multiprocessing.get_context("spawn")

    # start shared logging
    logqueue = mp.Queue()
    src.logging.start(settings.log, settings.overwrite, logqueue)
    try:
        start_time = time.time()

        # fill task queue
        taskqueue = mp.Queue()
        random.shuffle(tasks)
        for task in tasks:
            taskqueue.put(task)
        for _ in range(settings.processes):
            taskqueue.put(None)

        # accounting
        tasks_total = len(tasks)
        tasks_started = mp.Value('L', 0)
        tasks_completed = mp.Value('L', 0)
        time_completed = mp.Value('f', 0.0)

        # start analysers
        shared = (logqueue, taskqueue, tasks_total, tasks_started, tasks_completed, time_completed)
        analysers = [mp.Process(target=analyser, args=shared) for _ in range(settings.processes)]
        for a in analysers:
            a.start()

        # wait for analysers to finish
        for a in analysers:
            a.join()

        # good bye
        duration = datetime.timedelta(seconds=round(time.time() - start_time))
        src.logging.message(f"{duration}", "", logqueue)

    finally:
        src.logging.stop(logqueue)
