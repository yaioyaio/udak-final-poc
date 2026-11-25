"""Create a private one-JVM fixture from two pinned Observe revisions."""
import hashlib
import re

from attribution_sources import DATA_SOURCE, FIXTURE, MAX_SOURCE_BYTES, OBSERVER
from comparison_sources import replace
from lexer_crossover_sources import pinned_source

TRIAL = 'tools/release-performance/PgHotPathTrial.java'
METRIC = 'PgHotPathTrial.Metric.'
IMPORT = 'import dev.udak.diagnostic.PgHotPathTrial;\n'


def wrap(before):
    return f"""        long started = PgHotPathTrial.start();
        try {{
            {before}
        }} finally {{
            PgHotPathTrial.finish(type == Connection.class ? {METRIC}CONNECTION_WRAP
                    : {METRIC}STATEMENT_WRAP, started);
        }}"""


def observer(java, old):
    java = replace(java, 'import java.security.MessageDigest;', IMPORT + 'import java.security.MessageDigest;')
    java = replace(java, '            MessageDigest digest = ObservationDigest.newSha256();',
                   '            long metadataStarted = PgHotPathTrial.start();\n'
                   '            MessageDigest digest = ObservationDigest.newSha256();')
    call = '            sink.accept(event, shape.reason());'
    if old:
        java = replace(java, '''            sink.accept(new SqlObservation(framework, point, id, shape.hash(), shape.kind(), shape.status()),
                    shape.reason());''',
                       '            var event = new SqlObservation(framework, point, id, shape.hash(), shape.kind(), shape.status());\n'
                       + call)
        java = re.sub(r'\bSqlObserver\b', 'PreviousSqlObserver', java)
    return replace(java, call,
                   f'            PgHotPathTrial.finish({METRIC}METADATA, metadataStarted);\n'
                   '            long sinkStarted = PgHotPathTrial.start();\n'
                   '            try {\n'
                   '                sink.accept(event, shape.reason());\n'
                   '            } finally {\n'
                   f'                PgHotPathTrial.finish({METRIC}EVENT_SINK, sinkStarted);\n'
                   '            }')


def data_source(java, old):
    java = replace(java, 'import dev.udak.observe.Framework;', IMPORT + 'import dev.udak.observe.Framework;')
    java = replace(java, 'yield ((PreparedStatement) target).executeQuery();',
                   'yield PgHotPathTrial.execute((PreparedStatement) target);')
    java = replace(java, 'args.length == 1 ? target.prepareStatement(sql)',
                   'args.length == 1 ? PgHotPathTrial.prepare(target, sql)')
    if old:
        java = re.sub(r'\bSqlObserver\b', 'PreviousSqlObserver', java)
        java = re.sub(r'\bObserveDataSource\b', 'PreviousObserveDataSource', java)
        anchor = 'return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[] {type}, handler));'
        return replace(java, '        ' + anchor, wrap(anchor))
    anchor = 'return type.cast(Proxy.newProxyInstance(loader, interfaces, handler));'
    return replace(java, '            ' + anchor, '\n'.join('    ' + line for line in wrap(anchor).splitlines()))


def fixture(java):
    java = IMPORT + java
    java = replace(java, '            require(args.length == 2 &&',
                   '            require(args.length == 2 && args[0].equals("POSTGRESQL") &&')
    java = replace(java, '            Trial trial;', '            PgHotPathTrial trial;')
    java = replace(java, '                trial = new Trial(connection);',
                   '                trial = new PgHotPathTrial(connection);')
    java = replace(java, '            trial.report(engine, report);', '            trial.report(report);')
    start = '    private static final class EventCounter implements ObservationSink {'
    end = '    private static void require(boolean condition) {'
    if java.count(start) != 1 or java.count(end) != 1 or java.index(start) >= java.index(end):
        raise ValueError('FIXTURE_ANCHOR')
    return java[:java.index(start)] + java[java.index(end):]


def materialize(root, work, variants, pinned, inputs, trial_sha):
    shared = {}
    for name in inputs:
        original = pinned_source(root, variants['before'], name, pinned['before'][name])
        candidate = pinned_source(root, variants['after'], name, pinned['after'][name])
        if name == OBSERVER:
            shared[name] = observer(candidate, False)
            shared[name.replace('SqlObserver.java', 'PreviousSqlObserver.java')] = observer(original, True)
        elif name == DATA_SOURCE:
            shared[name] = data_source(candidate, False)
            shared[name.replace('ObserveDataSource.java', 'PreviousObserveDataSource.java')] = data_source(original, True)
        elif original != candidate:
            raise ValueError('COMMON_JAVA_SOURCE_CHANGED')
        else:
            shared[name] = fixture(candidate) if name == FIXTURE else candidate
    data = (root / TRIAL).read_bytes()
    if len(data) > MAX_SOURCE_BYTES or hashlib.sha512(data).hexdigest() != trial_sha:
        raise ValueError('TRIAL_SOURCE_CHANGED')
    shared[TRIAL] = data.decode('utf-8')
    paths = []
    digests = {}
    for name, java in shared.items():
        data = java.encode('utf-8')
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(data)
        paths.append(path)
        digests[name] = hashlib.sha512(data).hexdigest()
    return paths, digests
