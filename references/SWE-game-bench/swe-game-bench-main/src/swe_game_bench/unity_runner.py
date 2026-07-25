"""Run the Unity test runner headlessly and interpret its NUnit XML results.

If Unity dies before writing results (compile error, license failure, timeout),
a synthetic failing XML is written so downstream tooling always has a parseable
result with the relevant log excerpt embedded.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

UNITY = os.getenv("UNITY", "/opt/unity/Editor/Unity")
UNITY_TIMEOUT_SEC = int(os.getenv("UNITY_TIMEOUT_SEC", "2400"))


UNITY_EDITOR_DIR = str(PurePosixPath(UNITY).parent)
_STRAY_NEEDLES = (UNITY_EDITOR_DIR, "VBCSCompiler", "xvfb-run")


def kill_stray_unity() -> None:
    """Kill leftover Unity/Xvfb processes from an interrupted or timed-out run.

    docker exec does not forward Ctrl+C into the container, and a timeout kill
    only reaches the xvfb-run wrapper — either way a surviving Unity keeps the
    project open and corrupts the next run's asset import.
    """
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return
    me = os.getpid()
    for piddir in proc_root.iterdir():
        if not piddir.name.isdigit() or int(piddir.name) == me:
            continue
        try:
            cmdline = (piddir / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if any(n in cmdline for n in _STRAY_NEEDLES) or cmdline.lstrip().startswith("Xvfb"):
            try:
                os.kill(int(piddir.name), signal.SIGKILL)
                print(f"[unity] Killed stray process {piddir.name}: {cmdline[:100]}")
            except OSError:
                pass


def _run_unity_process(cmd: list[str], cwd: Path) -> tuple[int, str]:
    """Run Unity in its own process group so a timeout kills the whole tree."""
    print("CMD:", " ".join(map(str, cmd)))
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=UNITY_TIMEOUT_SEC)
        print(out)
        return proc.returncode, out
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, AttributeError):
            proc.kill()
        try:
            out, _ = proc.communicate(timeout=30)
        except Exception:
            out = ""
        print(out)
        print("[HARNESS] TIMEOUT — Unity process tree killed")
        return 124, out


def ensure_results_xml(xml_path: Path, label: str, log_path: Path, extra_msg: str = "") -> None:
    if xml_path.exists() and xml_path.stat().st_size > 0:
        return
    msg = "Unity exited before producing test results."
    if extra_msg:
        msg = extra_msg.strip() + "\n" + msg
    if log_path.exists():
        txt = log_path.read_text(encoding="utf-8", errors="replace")
        lines = []
        for line in txt.splitlines():
            if "not supported" in line and "Platform name" in line:
                lines.append(line)
            if re.search(r"error\s*CS[0-9]{4}", line, re.IGNORECASE):
                lines.append(line)
            if re.search(r"Assets/.*\.cs\([0-9]+,[0-9]+\):\s*error", line, re.IGNORECASE):
                lines.append(line)
            if "Scripts have compiler errors" in line:
                lines.append(line)
            if "License" in line and ("error" in line.lower() or "failed" in line.lower()):
                lines.append(line)
        if lines:
            msg = "\n".join(lines[:300])
        else:
            tail = "\n".join(txt.splitlines()[-200:])
            if tail.strip():
                msg = tail
    xml_path.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<test-run id="1" name="{label}" total="1" passed="0" failed="1" inconclusive="0" skipped="0" result="Failed">
  <test-suite type="Assembly" name="{label}" executed="True" result="Failed">
    <test-case name="UNITY_COMPILATION_OR_SETUP" executed="True" result="Failed">
      <failure>
        <message><![CDATA[{msg}]]></message>
      </failure>
    </test-case>
  </test-suite>
</test-run>
""",
        encoding="utf-8",
    )


def run_unity_test(
    workdir: Path,
    label: str,
    outdir: Path,
    test_platform: str,
    test_class: str,
) -> tuple[int, Path, Path]:
    xml = outdir / f"{label}_results.xml"
    log = outdir / f"{label}_unity.log"
    # Remove stale results so ensure_results_xml writes a fresh FAIL if Unity crashes.
    xml.unlink(missing_ok=True)
    kill_stray_unity()
    cmd = [
        "xvfb-run", "-a",
        UNITY,
        "-batchmode",
        "-nographics",
        "-projectPath", str(workdir),
        "-runTests",
        "-testPlatform", test_platform,
        "-testResults", str(xml),
        "-logFile", str(log),
        "-testFilter", test_class,
    ]
    code, _ = _run_unity_process(cmd, cwd=workdir)
    extra = f"[HARNESS] Unity timeout after {UNITY_TIMEOUT_SEC}s" if code == 124 else ""
    ensure_results_xml(xml, label, log, extra_msg=extra)
    print(f"[{label}] unity exit code = {code}")
    print(f"[{label}] xml  = {xml}")
    print(f"[{label}] log  = {log}")
    return code, xml, log


def _int_attr(root: ET.Element, name: str) -> int:
    try:
        return int(root.get(name, "0"))
    except ValueError:
        return 0


def merge_test_results(xml_paths: list[Path], aggregate_path: Path, label: str) -> bool:
    """Merge multiple Unity platform runs into the standard per-label XML."""
    aggregate_path.parent.mkdir(parents=True, exist_ok=True)
    total = passed = failed = inconclusive = skipped = 0
    roots: list[ET.Element] = []
    any_failed = False

    for xml_path in xml_paths:
        try:
            root = ET.parse(xml_path).getroot()
        except Exception as exc:
            root = ET.Element(
                "test-run",
                {
                    "name": xml_path.name,
                    "total": "1",
                    "passed": "0",
                    "failed": "1",
                    "result": "Failed",
                },
            )
            case = ET.SubElement(
                root,
                "test-case",
                {"name": f"UNREADABLE_XML_{xml_path.name}", "result": "Failed"},
            )
            failure = ET.SubElement(case, "failure")
            ET.SubElement(failure, "message").text = str(exc)

        total += _int_attr(root, "total")
        passed += _int_attr(root, "passed")
        failed += _int_attr(root, "failed")
        inconclusive += _int_attr(root, "inconclusive")
        skipped += _int_attr(root, "skipped")
        any_failed = any_failed or str(root.get("result", "")).lower() != "passed"
        roots.append(root)

    if not roots:
        ensure_results_xml(aggregate_path, label, aggregate_path)
        return False

    result = "Failed" if any_failed or failed else "Passed"
    aggregate = ET.Element(
        "test-run",
        {
            "id": "1",
            "name": label,
            "total": str(total or len(roots)),
            "passed": str(passed),
            "failed": str(failed if failed or result == "Passed" else 1),
            "inconclusive": str(inconclusive),
            "skipped": str(skipped),
            "result": result,
        },
    )
    suite = ET.SubElement(
        aggregate,
        "test-suite",
        {"type": "Assembly", "name": label, "executed": "True", "result": result},
    )
    for root in roots:
        suite.append(root)
    ET.ElementTree(aggregate).write(aggregate_path, encoding="utf-8", xml_declaration=True)
    return result == "Passed"


def run_unity_suites(
    workdir: Path,
    label: str,
    outdir: Path,
    suites: list[dict],
) -> tuple[int, Path, Path]:
    """Run one or more platform/filter suites and return one aggregate result."""
    if not suites:
        raise ValueError("At least one Unity test suite is required.")
    if len(suites) == 1:
        suite = suites[0]
        return run_unity_test(
            workdir=workdir,
            label=label,
            outdir=outdir,
            test_platform=suite["test_platform"],
            test_class=suite["test_class"],
        )

    xml_paths: list[Path] = []
    log_parts: list[str] = []
    exit_codes: list[int] = []
    for index, suite in enumerate(suites, start=1):
        platform = suite["test_platform"]
        suite_label = f"{label}_{platform.lower()}_{index}"
        code, xml_path, log_path = run_unity_test(
            workdir=workdir,
            label=suite_label,
            outdir=outdir,
            test_platform=platform,
            test_class=suite["test_class"],
        )
        exit_codes.append(code)
        xml_paths.append(xml_path)
        if log_path.exists():
            log_parts.append(
                f"=== {platform} suite {index} ===\n"
                + log_path.read_text(encoding="utf-8", errors="replace")
            )

    aggregate_xml = outdir / f"{label}_results.xml"
    aggregate_log = outdir / f"{label}_unity.log"
    passed = merge_test_results(xml_paths, aggregate_xml, label)
    aggregate_log.write_text("\n\n".join(log_parts), encoding="utf-8")
    code = 0 if passed else next((value for value in exit_codes if value != 0), 1)
    return code, aggregate_xml, aggregate_log


def xml_says_passed(xml_path: Path) -> bool | None:
    """True if the results XML reports a pass, False if a fail, None if unreadable."""
    if not xml_path.exists() or xml_path.stat().st_size == 0:
        return None
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError:
        return None
    root = tree.getroot()
    result = root.get("result")
    if result is None:
        return None
    try:
        passed_n = int(root.get("passed", "0"))
        failed_n = int(root.get("failed", "0"))
    except ValueError:
        return result.lower() == "passed"
    if failed_n > 0:
        return False
    if passed_n > 0 and result.lower() == "passed":
        return True
    return result.lower() == "passed"


def parse_test_cases(xml_path: Path) -> list[dict]:
    """Return [{name, classname, fullname, result, label, duration, message?}, ...]."""
    if not xml_path.exists() or xml_path.stat().st_size == 0:
        return []
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError:
        return []
    cases: list[dict] = []
    for tc in tree.getroot().iter("test-case"):
        attrs = tc.attrib
        entry = {
            "name": attrs.get("name", ""),
            "classname": attrs.get("classname", ""),
            "fullname": attrs.get("fullname", ""),
            "result": attrs.get("result", ""),
            "label": attrs.get("label"),
            "duration": attrs.get("duration"),
        }
        failure = tc.find("failure")
        if failure is not None:
            msg = failure.findtext("message")
            if msg:
                entry["message"] = msg.strip()
        cases.append(entry)
    return cases
