#!/usr/bin/env python3
"""Verify the mixed Spring Boot demo in an isolated JDK 17 workspace."""
import argparse
from datetime import datetime, timezone
from functools import partial
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import time
import xml.etree.ElementTree as ET
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
REPORT = 'evidence/RELEASE-DEMO-VALIDATION.json'
DEMO = 'spring-boot-demo'
MODULES = (
    'core', DEMO, 'sql-jsqlparser', 'udak-api', 'jdbc-spring', 'db-testkit', 'observe-core',
    'legacy-observe', 'legacy-compat-testkit', 'consistency-core', 'consistency-spring',
    'consistency-testkit', 'rewrite-core', 'rewrite-jsqlparser', 'rewrite-jdbc', 'rewrite-testkit',
)
CONFIG = f'{DEMO}/src/main/resources/application.yml'
BUILD_FILES = ('settings.gradle.kts', 'build.gradle.kts', CONFIG) + tuple(
    f'{module}/build.gradle.kts' for module in MODULES
)
TEST_CLASS = 'dev.udak.demo.MixedUserServiceTest'
TESTS = {'visibilityAcrossJpaMybatisJdbc', 'rollbackAcrossJpaAndJdbc'}
BASELINES = ('evidence/PHASE5-GATE.json', 'evidence/PHASE6-VALIDATION.json', 'evidence/PHASE6-GATE.json')
JVM_LIMITS = ('-Xmx256m', '-XX:MaxMetaspaceSize=128m', '-XX:ActiveProcessorCount=2')
LIMITS = {
    'wall_seconds': 900, 'gradle_build_wall_seconds': 600, 'application_wall_seconds': 60,
    'child_cpu_seconds': 120, 'active_cpus': 2, 'gradle_workers': 1, 'junit_forks': 1,
    'gradle_heap_mib': 512, 'gradle_metaspace_mib': 256, 'test_and_application_heap_mib': 256,
    'test_and_application_metaspace_mib': 128, 'workspace_entries': 20000, 'workspace_bytes': 2 * 1024**3,
    'child_file_bytes': 256 * 1024**2, 'recorded_step_output_bytes': 1024**2,
}

spec = importlib.util.spec_from_file_location('release_demo_guard', ROOT / 'tools/run-phase6.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)

INIT_SCRIPT = """
gradle.projectsEvaluated {
    def installation = new File(System.getProperty('udak.release.jdk17')).canonicalFile
    if (JavaVersion.current() != JavaVersion.VERSION_17 ||
        new File(System.getProperty('java.home')).canonicalFile != installation) {
        throw new GradleException('RELEASE_DEMO_GRADLE_JDK_MISMATCH')
    }
    println 'RELEASE_DEMO_GRADLE_JDK_17'
    def demo = gradle.rootProject.project(':spring-boot-demo')
    demo.tasks.named('test', org.gradle.api.tasks.testing.Test).configure {
        maxHeapSize = '256m'
        maxParallelForks = 1
        jvmArgs '-XX:MaxMetaspaceSize=128m', '-XX:ActiveProcessorCount=2'
        systemProperty 'user.home', System.getProperty('user.home')
        systemProperty 'java.io.tmpdir', System.getenv('TMPDIR')
        systemProperty 'spring.config.location', 'classpath:/application.yml'
        systemProperty 'logging.level.dev.udak.demo.MixedUserServiceTest', 'INFO'
        doFirst {
            def launcher = javaLauncher.get().metadata
            if (launcher.languageVersion.asInt() != 17 ||
                launcher.installationPath.asFile.canonicalFile != installation) {
                throw new GradleException('RELEASE_DEMO_TEST_JDK_MISMATCH')
            }
            println 'RELEASE_DEMO_TEST_JDK_17'
        }
    }
}
"""


def source_paths():
    return set(BUILD_FILES) | {
        str(source.relative_to(ROOT))
        for module in ('core', DEMO)
        for directory in ('main', 'test')
        for source in (ROOT / module / 'src' / directory / 'java/dev/udak').rglob('*.java')
    }


def stage_project(project, inputs):
    for name, source in h.p5.p4.approved_paths(inputs):
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    if any(h.guard.digest((project / name).read_bytes()) != digest for name, digest in inputs.items()):
        raise ValueError('Staged source changed')


def child_environment(work, jdk):
    return {
        'PATH': os.pathsep.join((str(jdk / 'bin'), '/usr/bin', '/bin', '/usr/sbin', '/sbin')),
        'JAVA_HOME': str(jdk), 'TMPDIR': str(work),
        'GRADLE_USER_HOME': str(work / 'home'), 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
        'JAVA_OPTS': f'-Duser.home={work / "user-home"} -Djava.io.tmpdir={work}',
    }


def verify_jdk(jdk, work, result):
    for binary in ('java', 'javac'):
        path = jdk / 'bin' / binary
        if not path.is_file() or not os.access(path, os.X_OK) or not path.resolve().is_relative_to(jdk):
            raise ValueError('JDK launcher missing or outside selected installation')
        result['steps'].append(h.step(binary + '-version', [str(path), '-version'], work, timeout=10))
    java = re.search(r'(?m)^(?:openjdk|java) version "(17(?:\.[0-9]+){0,3})"', (work / 'java-version.output').read_text())
    javac = re.fullmatch(r'javac (17(?:\.[0-9]+){0,3})\s*', (work / 'javac-version.output').read_text())
    if not java or not javac or java[1] != javac[1]:
        raise ValueError('Selected runtime and compiler did not report the same JDK 17 version')
    return java[1]


def verify_tests(work, project, version):
    output = (work / 'gradle-build.output').read_text(errors='replace').splitlines()
    for marker in ('RELEASE_DEMO_GRADLE_JDK_17', 'RELEASE_DEMO_TEST_JDK_17'):
        if output.count(marker) != 1:
            raise ValueError('Gradle and test launcher identity markers incomplete')
    directory = project / DEMO / 'build/test-results/test'
    reports = list(directory.glob('TEST-*.xml'))
    if len(reports) != 1 or reports[0].stat().st_size > 1024**2:
        raise ValueError('Unexpected JUnit report inventory')
    suite = ET.parse(reports[0]).getroot()
    cases = suite.findall('testcase')
    if (suite.tag != 'testsuite' or suite.get('name') != TEST_CLASS or len(cases) != len(TESTS)
            or suite.get('tests') != str(len(TESTS))
            or any(suite.get(counter) != '0' for counter in ('failures', 'errors', 'skipped'))
            or {case.get('name', '').removesuffix('()') for case in cases} != TESTS
            or any(case.get('classname') != TEST_CLASS or len(case) for case in cases)):
        raise ValueError('The fixed mixed demo JUnit cases did not all pass')
    runtime = re.search(r'Starting MixedUserServiceTest using Java ([\d.]+) with PID \d+',
                        suite.findtext('system-out', ''))
    if not runtime or runtime[1] != version:
        raise ValueError('Actual JUnit runtime did not report the selected JDK 17 version')
    return {
        'status': 'PASS', 'test_count': len(cases), 'failures': 0, 'errors': 0, 'skipped': 0,
        'cases': sorted(TESTS), 'junit_java_version': runtime[1], 'gradle_java_major': 17,
        'xml_sha512': h.guard.digest(reports[0].read_bytes()),
    }


def packaged_jar(project, inputs):
    jars = list((project / DEMO / 'build/libs').glob('*.jar'))
    jars = [jar for jar in jars if not jar.name.endswith('-plain.jar')]
    if len(jars) != 1 or jars[0].stat().st_size > 96 * 1024**2:
        raise ValueError('Unexpected packaged demo artifact inventory')
    jar = jars[0]
    with zipfile.ZipFile(jar) as archive:
        if (not archive.getinfo('BOOT-INF/classes/dev/udak/demo/DemoApplication.class').file_size
                or archive.getinfo('BOOT-INF/classes/application.yml').file_size > 32 * 1024
                or h.guard.digest(archive.read('BOOT-INF/classes/application.yml')) != inputs[CONFIG]):
            raise ValueError('Packaged demo inputs incomplete')
        runtime = {}
        for name in ('spring-boot', 'hibernate-core', 'mybatis-spring-boot-starter', 'spring-jdbc', 'h2'):
            versions = [
                match[1] for entry in archive.namelist()
                if (match := re.fullmatch(rf'BOOT-INF/lib/{re.escape(name)}-([0-9][A-Za-z0-9.\-]*)\.jar', entry))
            ]
            if len(versions) != 1:
                raise ValueError('Packaged demo runtime components incomplete')
            runtime[name] = versions[0]
    return jar, {
        'file': jar.name, 'bytes': jar.stat().st_size, 'sha512': h.guard.digest(jar.read_bytes()),
        'runtime_components': runtime,
    }


def verify_startup(work, version, result):
    output = (work / 'packaged-startup.output').read_text(errors='replace')
    runtime = re.findall(r'Starting DemoApplication(?: v0\.1\.0-poc)? using Java ([\d.]+) with PID \d+', output)
    mixed_reads = re.findall(r'(?m)^UDAK demo: inserted and read ID=[1-9]\d*$', output)
    rollback_paths = re.findall(r'(?m)^UDAK demo: rollback path executed$', output)
    shutdowns = re.findall(r'HikariPool-\d+ - Shutdown completed\.', output)
    result['startup_marker_counts'] = {
        'java_identity': len(runtime), 'mixed_read': len(mixed_reads),
        'rollback': len(rollback_paths), 'pool_shutdown': len(shutdowns),
    }
    if runtime != [version] or len(mixed_reads) != 1 or len(rollback_paths) != 1 or len(shutdowns) != 1:
        raise ValueError('Packaged demo startup, mixed read, rollback or H2 shutdown evidence incomplete')
    return {
        'status': 'PASS', 'application_started': True, 'application_closed': True,
        'java_version': runtime[0], 'mixed_read_markers': len(mixed_reads),
        'rollback_markers': len(rollback_paths), 'pool_shutdown_markers': len(shutdowns),
    }


def validate_demo(jdk, result):
    if shutil.disk_usage(Path('/tmp').resolve()).free < 4 * 1024**3:
        raise ValueError('Insufficient workspace disk headroom')
    result['inputs_sha512'] = h.hashes(source_paths())
    result['harness_sha512'] = h.hashes(('tools/run-release-demo.py', 'tools/run-phase6.py'))
    result['prior_evidence_sha512'] = h.hashes(BASELINES)
    h.child_environment = partial(child_environment, jdk=jdk)
    try:
        with h.workspace() as (work, cleanup):
            result['cleanup'] = cleanup
            result['failed_check'] = 'stage-project'
            project = work / 'project'
            stage_project(project, result['inputs_sha512'])
            (work / 'user-home').mkdir()
            h.ROOT = project
            result['failed_check'] = 'jdk17-preflight'
            version = verify_jdk(jdk, work, result)
            result['java_version'] = version
            result['failed_check'] = 'gradle-distribution'
            binary = h.gradle_distribution(work)
            result['gradle_version'] = h.GRADLE_VERSION
            result['gradle_distribution_sha256'] = h.GRADLE_SHA256
            init = work / 'release-demo.init.gradle'
            init.write_text(INIT_SCRIPT)
            result['failed_check'] = 'gradle-build'
            command = [
                binary, '--no-daemon', '--console=plain', '--max-workers=1', '--no-watch-fs',
                '--configure-on-demand', '--gradle-user-home', str(work / 'home'), '--init-script', str(init),
                f'-Dudak.release.jdk17={jdk}', f'-Dorg.gradle.java.home={jdk}',
                '-Dorg.gradle.jvmargs=-Xmx512m -XX:MaxMetaspaceSize=256m -XX:ActiveProcessorCount=2 '
                f'-Duser.home={work / "user-home"} -Djava.io.tmpdir={work}',
                '-Porg.gradle.java.installations.auto-download=false',
                '-Porg.gradle.java.installations.auto-detect=false',
                f'-Porg.gradle.java.installations.paths={jdk}', f':{DEMO}:build',
            ]
            result['steps'].append(h.step('gradle-build', command, work, timeout=LIMITS['gradle_build_wall_seconds']))
            result['failed_check'] = 'junit-results'
            result['junit'] = verify_tests(work, project, version)
            result['failed_check'] = 'packaged-artifact'
            jar, result['packaged_jar'] = packaged_jar(project, result['inputs_sha512'])
            result['failed_check'] = 'packaged-startup'
            command = [
                str(jdk / 'bin/java'), *JVM_LIMITS,
                f'-Duser.home={work / "user-home"}', f'-Djava.io.tmpdir={work}',
                '-jar', str(jar), '--spring.config.location=classpath:/application.yml',
                '--spring.main.web-application-type=none', '--logging.level.dev.udak.demo.DemoApplication=INFO',
                '--logging.level.com.zaxxer.hikari.HikariDataSource=INFO',
            ]
            result['steps'].append(h.step('packaged-startup', command, work, timeout=LIMITS['application_wall_seconds']))
            result['startup'] = verify_startup(work, version, result)
            result['failed_check'] = 'execution-inputs'
            if result['inputs_sha512'] != h.hashes(source_paths()) or result['prior_evidence_sha512'] != h.hashes(BASELINES):
                raise ValueError('Repository inputs or prior evidence changed during validation')
            result['failed_check'] = 'automatic-cleanup'
    finally:
        h.ROOT = ROOT
    del result['failed_check']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jdk17', required=True, type=Path, metavar='PATH', help='JDK 17 installation directory')
    args = parser.parse_args()
    start = time.monotonic()
    result = {
        'schema_version': 1, 'requirement': 'RELEASE-001', 'status': 'FAIL',
        'started_at_utc': datetime.now(timezone.utc).isoformat(), 'steps': [], 'limits': LIMITS,
        'scope': 'Spring Boot mixed access demo on embedded H2 with JDK 17',
        'containers_started': 0, 'external_database_processes_started': 0,
        'not_run': ['real database coverage', 'performance/load', 'external publication'],
        'failed_check': 'preflight',
    }
    for event in (signal.SIGINT, signal.SIGTERM, signal.SIGALRM):
        signal.signal(event, h.guard.interrupted)
    signal.alarm(LIMITS['wall_seconds'])
    try:
        validate_demo(args.jdk17.expanduser().resolve(strict=True), result)
        result['status'] = 'PASS'
    except Exception as error:
        result['failure_type'] = type(error).__name__
        if isinstance(error, RuntimeError):
            try:
                step = json.loads(str(error))
            except ValueError:
                pass
            else:
                if isinstance(step, dict) and 'exit_code' in step:
                    result['failed_step'] = step
    finally:
        signal.alarm(0)
        result['elapsed_seconds'] = round(time.monotonic() - start, 3)
        h.save(REPORT, result)
    print(json.dumps({key: value for key, value in result.items() if not key.endswith('_sha512')}))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
