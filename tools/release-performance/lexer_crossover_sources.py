"""Generate one fixture classpath with both pinned lexer implementations."""
import hashlib
import subprocess

from comparison_sources import SHAPE, replace
from attribution_sources import DATA_SOURCE, FIXTURE, MAX_SOURCE_BYTES, OBSERVER

PROBE = 'tools/release-performance/LexerCrossoverProbe.java'
PROBE_IMPORT = 'import dev.udak.diagnostic.LexerCrossoverProbe;\n'
RECORD = 'record SqlShape(String hash, StatementKind kind, UnavailableReason reason) {'
SHAPE_RETURN = '            return new SqlShape(ObservationDigest.SQL_SHAPE.hash(digest, tokens, tokenBytes), kind, NONE);'


def pinned_source(root, revision, path, sha512):
    data = subprocess.check_output(['git', '--no-lazy-fetch', '--no-replace-objects', 'show', revision + ':' + path],
                                   cwd=root, timeout=5, stderr=subprocess.DEVNULL)
    if len(data) > MAX_SOURCE_BYTES or hashlib.sha512(data).hexdigest() != sha512:
        raise ValueError('PINNED_SOURCE_MISMATCH')
    return data.decode('utf-8')


def shape(java, older):
    if older:
        java = replace(java, RECORD, 'final class PreviousSqlShape {')
        java = replace(java, '''    FingerprintStatus status() {
        return reason == NONE ? FingerprintStatus.NORMALIZED : FingerprintStatus.UNAVAILABLE;
    }

''', '')
    java = replace(java, 'import java.security.MessageDigest;', PROBE_IMPORT + 'import java.security.MessageDigest;')
    java = replace(java, '        return new Lexer(sql).scan(digest);',
                   '        LexerCrossoverProbe.startNormalization();\n        return new Lexer(sql).scan(digest);')
    return replace(java, SHAPE_RETURN, '            LexerCrossoverProbe.finishNormalization();\n' + SHAPE_RETURN)


def fixture(java):
    replacements = (
        ('import dev.udak.observe.FingerprintStatus;', PROBE_IMPORT + 'import dev.udak.observe.FingerprintStatus;'),
        ('import dev.udak.observe.SqlObserver;',
         'import dev.udak.observe.SqlObserver;\nimport dev.udak.observe.UnavailableReason;'),
        ('int WARMUP = 8;', 'int WARMUP = 16;'),
        ('int MEASURED = 96;', 'int MEASURED = 64;'),
        ('            String secret = privateInput();',
         '            LexerCrossoverProbe.initialize();\n            String secret = privateInput();'),
        ('        public void accept(SqlObservation event) {',
         '        public void accept(SqlObservation event) {\n            throw new AssertionError();\n        }\n'
         '\n        @Override\n        public void accept(SqlObservation event, UnavailableReason reason) {\n'
         '            require(reason == UnavailableReason.NONE);'),
        ('        private final JdbcTemplate plain;\n', ''),
        ('        private final long[] plainSamples = new long[MEASURED];\n'
         '        private final long[] observedSamples = new long[MEASURED];',
         '        private final long[][] shapeBytes = new long[2][MEASURED];\n'
         '        private final long[][] jdbcNanos = new long[2][MEASURED];\n'
         '        private final StringJoiner schedule = new StringJoiner(",");'),
        ('            // Both arms borrow and logically close the same close-suppressed physical connection.\n'
         '            // The delegate gives both templates the same ordinary (non-SmartDataSource) release path.',
         '            // The two lexers share the same wrapper, template and physical connection.'),
        ('            plain = new JdbcTemplate(shared);\n', ''),
        ('            plain.setQueryTimeout(TIMEOUT_SECONDS);\n', ''),
        ('''                int id = 1 + pair % ROWS;
                boolean observedFirst = pair % 2 != 0;
                sample(observedFirst, id, pair - WARMUP);
                sample(!observedFirst, id, pair - WARMUP);''', '''                int block = pair / 20;
                int slot = pair % 20;
                int id = 1 + (slot + (block >= 2 ? 4 : 0)) % ROWS;
                boolean candidateFirst = ((slot ^ (slot >>> 3) ^ block) & 1) != 0;
                int index = slot < 4 ? -1 : block * 16 + slot - 4;
                sample(candidateFirst, id, index);
                sample(!candidateFirst, id, index);'''),
        ('boolean observe, int id, int index', 'boolean candidate, int id, int index'),
        ('            JdbcTemplate template = observe ? observed : plain;\n', ''),
        ('            long started = System.nanoTime();\n            template.query(',
         '            LexerCrossoverProbe.begin(candidate);\n'
         '            long started = System.nanoTime();\n            observed.query('),
        ('''            require(elapsed > 0 && events.count == previousEvents + (observe ? 1 : 0));
            if (observe) {
                SqlObservation event = events.last;
                require(event.framework() == Framework.JDBC && event.point() == ObservationPoint.JDBC_EXECUTE);
                require(event.statementKind() == StatementKind.SELECT && event.fingerprintStatus() == FingerprintStatus.NORMALIZED);
                if (firstEvent == null) firstEvent = event;
                require(firstEvent.equals(event));
            }
            if (index >= 0) {
                long[] samples = observe ? observedSamples : plainSamples;
                samples[index] = elapsed;
            }
            starts[completed++] = started;''', '''            var result = LexerCrossoverProbe.end(elapsed);
            require(elapsed > 0 && events.count == previousEvents + 1);
            SqlObservation event = events.last;
            require(event.framework() == Framework.JDBC && event.point() == ObservationPoint.JDBC_EXECUTE);
            require(event.statementKind() == StatementKind.SELECT && event.fingerprintStatus() == FingerprintStatus.NORMALIZED);
            if (firstEvent == null) firstEvent = event;
            require(firstEvent.equals(event));
            if (index >= 0) {
                int arm = candidate ? 1 : 0;
                shapeBytes[arm][index] = result.shapeAllocatedBytes();
                jdbcNanos[arm][index] = result.jdbcExecuteNanos();
            }
            schedule.add(Integer.toString(2 * id + (candidate ? 1 : 0)));
            starts[completed++] = started;'''),
        ('events.count == WARMUP + MEASURED', 'events.count == TOTAL'),
        ('            String plainLine = samplesLine("PLAIN_NS", plainSamples);\n'
         '            String observedLine = samplesLine("OBSERVE_NS", observedSamples);\n', ''),
        ('"PRODUCT_PERF profile="', '"LEXER_CROSSOVER profile="'),
        ('''            report.println(plainLine);
            report.println(observedLine);''', '''            report.println("EVENT_KEY " + firstEvent.queryIdHash() + " " + firstEvent.fingerprintHash());
            report.println("SCHEDULE " + schedule);
            long[] gaps = new long[TOTAL - 1];
            for (int i = 1; i < TOTAL; i++) gaps[i - 1] = starts[i] - starts[i - 1];
            report.println(samplesLine("GAPS_NS", gaps));
            report.println(samplesLine("BEFORE_SHAPE_BYTES", shapeBytes[0]));
            report.println(samplesLine("AFTER_SHAPE_BYTES", shapeBytes[1]));
            report.println(samplesLine("BEFORE_JDBC_EXECUTE_NS", jdbcNanos[0]));
            report.println(samplesLine("AFTER_JDBC_EXECUTE_NS", jdbcNanos[1]));'''),
        ('                require(nanos > 0);', '                require(nanos >= 0);'),
    )
    for anchor, replacement in replacements:
        java = replace(java, anchor, replacement)
    return java


def instrument(name, source):
    if name == SHAPE:
        return shape(source, False)
    if name == FIXTURE:
        return fixture(source)
    if name == OBSERVER:
        source = replace(source, 'import java.security.MessageDigest;', PROBE_IMPORT + 'import java.security.MessageDigest;')
        return replace(source, '            SqlShape shape = SqlShape.parse(sql, digest);',
                       '            SqlShape shape = LexerCrossoverProbe.useCandidate() ? SqlShape.parse(sql, digest)\n'
                       '                    : PreviousSqlShape.parse(sql, digest);')
    if name == DATA_SOURCE:
        source = replace(source, 'import dev.udak.observe.Framework;', PROBE_IMPORT + 'import dev.udak.observe.Framework;')
        return replace(source, 'yield ((PreparedStatement) target).executeQuery();',
                       'yield LexerCrossoverProbe.execute((PreparedStatement) target);')
    return source


def materialize(root, work, variants, signed, names, probe_sha512):
    generated = {}
    paths = []
    for name in names:
        before = pinned_source(root, variants['before'], name, signed['before'][name])
        after = pinned_source(root, variants['after'], name, signed['after'][name])
        if name == SHAPE:
            generated[name.replace('SqlShape.java', 'PreviousSqlShape.java')] = shape(before, True)
        elif before != after:
            raise ValueError('COMMON_JAVA_INPUT_CHANGED')
        generated[name] = instrument(name, after)
    probe = (root / PROBE).read_bytes()
    if len(probe) > MAX_SOURCE_BYTES or hashlib.sha512(probe).hexdigest() != probe_sha512:
        raise ValueError('PROBE_INPUT_CHANGED')
    generated[PROBE] = probe.decode('utf-8')
    hashes = {}
    for name, src in generated.items():
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = src.encode('utf-8')
        if len(data) > MAX_SOURCE_BYTES:
            raise ValueError('SOURCE_BOUND')
        with path.open('xb') as stream:
            stream.write(data)
        hashes[name] = hashlib.sha512(data).hexdigest()
        paths.append(path)
    return paths, hashes
