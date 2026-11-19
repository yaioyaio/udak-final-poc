"""Prepare the fixed prior and current crossover sources in a scratch directory."""

import hashlib
from pathlib import Path
import re
import subprocess


PRIOR_COMMIT = '21aeaf2b5e60637c6be3fb173923abfeb6b583f3'
CURRENT_COMMIT = '80090a180670f7d3b92022f885dfcdc74dcbc85d'
MAX_SOURCE_BYTES = 1024**2
OBSERVE = 'observe-core/src/main/java/dev/udak/observe/'
OBSERVER = OBSERVE + 'SqlObserver.java'
DATA_SOURCE = 'legacy-observe/src/main/java/dev/udak/observe/jdbc/ObserveDataSource.java'
FIXTURE = 'tools/release-performance/ProductG5PerformanceMain.java'
SHARED_SOURCES = {
    'FINGERPRINT_STATUS': OBSERVE + 'FingerprintStatus.java',
    'FRAMEWORK': OBSERVE + 'Framework.java',
    'OBSERVATION_DIGEST': OBSERVE + 'ObservationDigest.java',
    'OBSERVATION_POINT': OBSERVE + 'ObservationPoint.java',
    'OBSERVATION_SINK': OBSERVE + 'ObservationSink.java',
    'SQL_OBSERVATION': OBSERVE + 'SqlObservation.java',
    'SQL_SHAPE': OBSERVE + 'SqlShape.java',
    'STATEMENT_KIND': OBSERVE + 'StatementKind.java',
}
SOURCE_PATHS = (FIXTURE, OBSERVER, DATA_SOURCE, *SHARED_SOURCES.values())
GIT = ('git', '--no-lazy-fetch', '--no-replace-objects')
PROBE_IMPORT = 'import dev.udak.diagnostic.CrossoverProbe;\n'

FIXTURE_REPLACEMENTS = (
    ('''import dev.udak.observe.FingerprintStatus;
import dev.udak.observe.Framework;
import dev.udak.observe.ObservationPoint;
import dev.udak.observe.ObservationSink;
import dev.udak.observe.SqlObservation;
import dev.udak.observe.SqlObserver;
import dev.udak.observe.StatementKind;
import dev.udak.observe.jdbc.ObserveDataSource;
''', ''),
    ('import java.util.StringJoiner;\nimport java.util.concurrent.TimeUnit;\n', ''),
    ('''import javax.sql.DataSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DelegatingDataSource;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;
''', ''),
    ('/** Bounded paired JdbcTemplate SELECTs on a single connection to a fresh parent-owned fixture. */\n',
     '/** Bounded crossover SELECTs on a single connection to a fresh parent-owned fixture. */\n'),
    ('''    private static final int WARMUP = 8;
    private static final int MEASURED = 96;
    private static final int TOTAL = (WARMUP + MEASURED) * 2;
''', ''),
    ('    private static final long INTERVAL_NS = TimeUnit.MILLISECONDS.toNanos(125);\n', ''),
    ('            Trial trial;\n', '            CrossoverTrial trial;\n'),
    ('                trial = new Trial(connection);\n',
     '                trial = new CrossoverTrial(connection, SELECT, ROWS, TIMEOUT_SECONDS,\n'
     '                        ProductG5PerformanceMain::valueFor);\n'),
    ('            trial.report(engine, report);\n', '            trial.report(report);\n'),
)

OBSERVER_REPLACEMENTS = (
    ('package dev.udak.observe;\n\n', 'package dev.udak.observe;\n\n' + PROBE_IMPORT),
    ('            byte[] tag = jdbcReuseTag(sql);\n',
     '            long hmacStarted = CrossoverProbe.start();\n'
     '            byte[] tag = jdbcReuseTag(sql);\n'
     '            CrossoverProbe.finish("HMAC", hmacStarted);\n'),
    ('''            if (tag != null && cached != null && MessageDigest.isEqual(cached.tag(), tag)) {
                return cached.observation();
            }

            MessageDigest digest = ObservationDigest.newSha256();
''', '''            if (tag != null && cached != null && MessageDigest.isEqual(cached.tag(), tag)) {
                CrossoverProbe.recordCacheOutcome(true);
                return cached.observation();
            }

            CrossoverProbe.recordCacheOutcome(false);
            long fingerprintStarted = CrossoverProbe.start();
            MessageDigest digest = ObservationDigest.newSha256();
'''),
    ('                    shape);\n            if (tag != null) {\n',
     '                    shape);\n'
     '            CrossoverProbe.finish("FINGERPRINT", fingerprintStarted);\n'
     '            if (tag != null) {\n'),
    ('''            sink.accept(new SqlObservation(Framework.JDBC, ObservationPoint.JDBC_EXECUTE, prepared.queryIdHash,
                    prepared.fingerprintHash, prepared.statementKind, prepared.fingerprintStatus));
''', '''            long eventCreateStarted = CrossoverProbe.start();
            SqlObservation event = new SqlObservation(Framework.JDBC, ObservationPoint.JDBC_EXECUTE,
                    prepared.queryIdHash, prepared.fingerprintHash, prepared.statementKind,
                    prepared.fingerprintStatus);
            CrossoverProbe.finish("EVENT_CREATE", eventCreateStarted);
            long eventSinkStarted = CrossoverProbe.start();
            sink.accept(event);
            CrossoverProbe.finish("EVENT_SINK", eventSinkStarted);
'''),
)

DATA_SOURCE_REPLACEMENTS = (
    ('package dev.udak.observe.jdbc;\n\n', 'package dev.udak.observe.jdbc;\n\n' + PROBE_IMPORT),
    ('        return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[] {type}, handler));\n',
     '        long proxyStarted = CrossoverProbe.start();\n'
     '        T result = type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[] {type}, handler));\n'
     '        CrossoverProbe.finish("OBSERVE_PROXY", proxyStarted);\n'
     '        return result;\n'),
)


def _git(root, *args):
    result = subprocess.run(
        (*GIT, *args), cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, timeout=3,
    )
    if result.returncode != 0:
        raise ValueError('Pinned crossover sources are unavailable')
    return result.stdout


def _source_tree(root, commit):
    # Each literal path selects a single tree entry. Reject symlinks, submodules, and large blobs.
    entries = _git(root, 'ls-tree', '-zl', '--full-tree', commit, '--', *SOURCE_PATHS)
    sources = {}
    for entry in entries.split(b'\0')[:-1]:
        match = re.fullmatch(rb'100644 blob ([0-9a-f]{40}) +([0-9]+)\t([A-Za-z0-9./-]+)', entry)
        if match is None:
            raise ValueError('Invalid pinned crossover source entry')
        oid, size, name = match.groups()
        name = name.decode('ascii')
        size = int(size)
        if name not in SOURCE_PATHS or name in sources or not 0 < size <= MAX_SOURCE_BYTES:
            raise ValueError('Invalid pinned crossover source path or size')
        sources[name] = (oid.decode('ascii'), size)
    if sources.keys() != set(SOURCE_PATHS):
        raise ValueError('Pinned crossover source list is incomplete')
    return sources


def _blob(root, entry):
    oid, size = entry
    # The immutable object size was checked before reading content.
    data = _git(root, 'cat-file', 'blob', oid)
    if len(data) != size:
        raise ValueError('Pinned crossover source size differs')
    return data


def _replace(java, path, replacements):
    for anchor, replacement in replacements:
        if java.count(anchor) != 1:
            raise ValueError(f'Crossover instrumentation anchor differs: {path}')
        java = java.replace(anchor, replacement, 1)
    return java


def _fixture(java):
    start = '\n    private static final class EventCounter implements ObservationSink {\n'
    trial = '\n    private static final class Trial {\n'
    end = '\n    private static void require(boolean condition) {\n'
    if any(java.count(anchor) != 1 for anchor in (start, trial, end)):
        raise ValueError('Crossover fixture trial anchors differ')
    prefix, _, old_trial = java.partition(start)
    removed, _, suffix = old_trial.partition(end)
    if trial not in removed or not removed.endswith('    }\n'):
        raise ValueError('Crossover fixture trial boundary differs')
    return _replace(prefix + end + suffix, FIXTURE, FIXTURE_REPLACEMENTS)


def _prior_type(java, old, expected_count):
    renamed, count = re.subn(rf'\b{old}\b', f'Prior{old}', java)
    if count != expected_count:
        raise ValueError(f'Crossover prior type anchors differ: {old}')
    return renamed


def build_sources(root, work):
    """Return scratch javac paths and the SHA-512 digests of original and compiled sources."""
    root = Path(root).resolve(strict=True)
    work = Path(work).resolve(strict=True)
    if root == work or not work.is_dir():
        raise ValueError('Invalid crossover source workspace')
    prior = _source_tree(root, PRIOR_COMMIT)
    current = _source_tree(root, CURRENT_COMMIT)
    if any(prior[path] != current[path] for path in (FIXTURE, *SHARED_SOURCES.values())):
        raise ValueError('Shared crossover sources differ between pinned commits')
    if prior[OBSERVER] == current[OBSERVER]:
        raise ValueError('Pinned crossover observer sources are identical')

    scratch = work / 'crossover-sources'
    scratch.mkdir(mode=0o700)
    paths = []
    hashes = {}

    def emit(name, path, original, generated):
        if not 0 < len(generated) <= MAX_SOURCE_BYTES:
            raise ValueError('Generated crossover source exceeds size limit')
        source = scratch / path
        source.parent.mkdir(parents=True, exist_ok=True)
        with source.open('xb') as stream:
            stream.write(generated)
        paths.append(source)
        hashes[f'ORIGINAL_{name}'] = hashlib.sha512(original).hexdigest()
        hashes[f'GENERATED_{name}'] = hashlib.sha512(generated).hexdigest()

    fixture = _blob(root, current[FIXTURE])
    emit('SHARED_FIXTURE', FIXTURE, fixture, _fixture(fixture.decode('utf-8')).encode('utf-8'))
    for name, path in SHARED_SOURCES.items():
        original = _blob(root, current[path])
        emit(f'SHARED_{name}', path, original, original)

    for arm, tree in (('PRIOR', prior), ('CURRENT', current)):
        observer = _blob(root, tree[OBSERVER])
        data_source = _blob(root, tree[DATA_SOURCE])
        observer_java = _replace(observer.decode('utf-8'), OBSERVER, OBSERVER_REPLACEMENTS)
        data_source_java = _replace(data_source.decode('utf-8'), DATA_SOURCE, DATA_SOURCE_REPLACEMENTS)
        observer_path = Path(OBSERVER)
        data_source_path = Path(DATA_SOURCE)
        if arm == 'PRIOR':
            observer_java = _prior_type(observer_java, 'SqlObserver', 2)
            data_source_java = _prior_type(data_source_java, 'SqlObserver', 4)
            data_source_java = _prior_type(data_source_java, 'ObserveDataSource', 2)
            observer_path = observer_path.with_name('PriorSqlObserver.java')
            data_source_path = data_source_path.with_name('PriorObserveDataSource.java')
        emit(f'{arm}_SQL_OBSERVER', observer_path, observer, observer_java.encode('utf-8'))
        emit(f'{arm}_OBSERVE_DATA_SOURCE', data_source_path, data_source, data_source_java.encode('utf-8'))

    return paths, hashes
