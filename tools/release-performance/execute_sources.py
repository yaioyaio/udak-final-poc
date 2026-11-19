"""Prepare the pinned current product sources for the PostgreSQL execute diagnostic."""

import hashlib
import importlib.util
from pathlib import Path


CURRENT_COMMIT = 'e1af76ce9e77ed743aef0522c008084441c51dfa'
_spec = importlib.util.spec_from_file_location(
    'execute_crossover_sources', Path(__file__).with_name('crossover_sources.py'),
)
_crossover = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_crossover)


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
    ('''    private static final int WARMUP = 8;
    private static final int MEASURED = 96;
    private static final int TOTAL = (WARMUP + MEASURED) * 2;
''', ''),
    ('    private static final long INTERVAL_NS = TimeUnit.MILLISECONDS.toNanos(125);\n', ''),
    ('            Trial trial;\n', '            ExecuteTrial trial;\n'),
    ('                trial = new Trial(connection);\n',
     '                trial = new ExecuteTrial(connection, SELECT, ROWS, TIMEOUT_SECONDS,\n'
     '                        ProductG5PerformanceMain::valueFor);\n'),
    ('            trial.report(engine, report);\n', '            trial.report(report);\n'),
    ('                properties.setProperty("ApplicationName", "udak-product-g5");\n',
     '                properties.setProperty("ApplicationName", "udak-product-g5");\n'
     '                properties.setProperty("socketFactory", "dev.udak.diagnostic.ExecuteSocketFactory");\n'),
)


def _fixture(original):
    java = original.decode('utf-8')
    start = '\n    private static final class EventCounter implements ObservationSink {\n'
    trial = '\n    private static final class Trial {\n'
    end = '\n    private static void require(boolean condition) {\n'
    if any(java.count(anchor) != 1 for anchor in (start, trial, end)):
        raise ValueError('Execute fixture trial anchors differ')
    prefix, _, old_trial = java.partition(start)
    removed, _, suffix = old_trial.partition(end)
    if trial not in removed or not removed.endswith('    }\n'):
        raise ValueError('Execute fixture trial boundary differs')
    return _crossover._replace(prefix + end + suffix, _crossover.FIXTURE, FIXTURE_REPLACEMENTS).encode('utf-8')


def build_sources(root, work):
    """Return the scratch javac paths and SHA-512 digests for the pinned originals and compile inputs."""
    root = Path(root).resolve(strict=True)
    work = Path(work).resolve(strict=True)
    if root == work or not work.is_dir():
        raise ValueError('Invalid execute source workspace')
    tree = _crossover._source_tree(root, CURRENT_COMMIT)
    scratch = work / 'execute-sources'
    scratch.mkdir(mode=0o700)
    sources = {
        'SHARED_FIXTURE': _crossover.FIXTURE,
        **{f'SHARED_{name}': path for name, path in _crossover.SHARED_SOURCES.items()},
        'CURRENT_SQL_OBSERVER': _crossover.OBSERVER,
        'CURRENT_OBSERVE_DATA_SOURCE': _crossover.DATA_SOURCE,
    }
    paths = []
    hashes = {}
    for name, path in sources.items():
        original = _crossover._blob(root, tree[path])
        generated = _fixture(original) if path == _crossover.FIXTURE else original
        if not 0 < len(generated) <= _crossover.MAX_SOURCE_BYTES:
            raise ValueError('Generated execute source exceeds size limit')
        destination = scratch / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream:
            stream.write(generated)
        paths.append(destination)
        hashes[f'ORIGINAL_{name}'] = hashlib.sha512(original).hexdigest()
        hashes[f'GENERATED_{name}'] = hashlib.sha512(generated).hexdigest()
    return paths, hashes
