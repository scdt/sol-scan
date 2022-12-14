#!/usr/bin/env python3

import docker, os, shutil, tempfile, requests
import src.io, io
from src.exceptions import SolScanError

_client = None

def client():
    global _client
    if not _client:
        try:    
            _client = docker.from_env()
            _client.info()
        except:
            raise SolScanError("Docker: Cannot connect to service. Is it installed and running?")
    return _client

images_loaded = set()

def is_loaded(image):
    try:
        return image in images_loaded or client().images.list(image)
    except Exception as e:
        raise SolScanError(f"Docker: checking for image {image} failed.\n{e}")

def load(image):
    try:
        client().images.pull(image)
        images_loaded.add(image)
    except Exception as e:
        raise SolScanError(f"Docker: Loading image {image} failed.\n{e}")

def __docker_volume(task):
    srcdir = tempfile.mkdtemp()
    srcdir_bin = os.path.join(srcdir, "bin")
    if task.tool.mode in ("bytecode","runtime"):
        # sanitize hex code
        code = src.io.read_lines(task.absfn)[0].strip()
        if code.startswith("0x"):
            code = code[2:]
        _,filename = os.path.split(task.absfn)
        src.io.write_txt(os.path.join(srcdir,filename), code)
    else:
        shutil.copy(task.absfn, srcdir)
    if task.tool.bin:
        shutil.copytree(task.tool.absrcin, srcdir_bin)
    else:
        os.mkdir(srcdir_bin)
    if task.solc_path:
        srcdir_bin_solc = os.path.join(srcdir_bin, "solc")
        shutil.copyfile(task.solc_path, srcdir_bin_solc)
    return srcdir

def __docker_args(task, srcdir):
    args = {
        "volumes": {srcdir: {"bind": "/src", "mode": "rw"}},
        "detach": True,
        "user": 0
    }
    for k in ("image","cpu_quota","mem_limit"):
        v = getattr(task.tool, k, None)
        if v is not None:
            args[k] = v
    for k in ("cpu_quota","mem_limit"):
        v = getattr(task.settings, k, None)
        if v is not None:
            args[k] = v
    _,filename = os.path.split(task.absfn)
    filename = f"/src/{filename}" # path in Linux Docker image
    timeout = task.settings.timeout or "0"
    args['command'] = task.tool.command(filename, timeout, "/src/bin")
    args['entrypoint'] = task.tool.entrypoint(filename, timeout, "/src/bin")
    return args

def execute(task):
    srcdir = __docker_volume(task)
    args = __docker_args(task, srcdir)
    exit_code,logs,output,container = None,[],None,None
    try:
        container = client().containers.run(**args)
        try:
            result = container.wait(timeout=task.settings.timeout)
            exit_code = result["StatusCode"]
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
            # The docs say that timeout raises ReadTimeout, but sometimes it is ConnectionError
            container.stop(timeout=0)
        logs = container.logs().decode("utf8").splitlines()
        if task.tool.output:
            output,_ = container.get_archive(task.tool.output)
            output = b''.join(output)
    finally:
        if container:
            container.stop(timeout=0)
            container.remove()
        shutil.rmtree(srcdir)
    return exit_code, logs, output, args
