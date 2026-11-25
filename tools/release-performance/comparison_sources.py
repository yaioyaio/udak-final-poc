"""Build instrumented copies of the two pinned diagnostic variants in private scratch."""
import hashlib
import subprocess

import attribution_sources as previous

SHAPE = 'observe-core/src/main/java/dev/udak/observe/SqlShape.java'
PROBE = 'tools/release-performance/AttributionProbe.java'


def replace(source, anchor, replacement):
    if source.count(anchor) != 1:
        raise ValueError('INSTRUMENTATION_ANCHOR')
    return source.replace(anchor, replacement, 1)


def instrument(name, java):
    if name == previous.OBSERVER:
        java = replace(java, 'import java.security.MessageDigest;',
                       previous.PROBE_IMPORT + 'import java.security.MessageDigest;')
        return replace(java, """            MessageDigest digest = ObservationDigest.newSha256();
            SqlShape shape = SqlShape.parse(sql, digest);
            String id = queryId == null || queryId.length() > MAX_QUERY_ID_LENGTH || queryId.isBlank()
                    ? sourceId(framework, shape.hash(), digest)
                    : ObservationDigest.QUERY_ID.hash(digest, queryId);
            sink.accept(new SqlObservation(framework, point, id, shape.hash(), shape.kind(), shape.status()),
                    shape.reason());""", """            AttributionProbe.start();
            MessageDigest digest = ObservationDigest.newSha256();
            AttributionProbe.transition("FINGERPRINT_AND_ID");
            SqlShape shape = SqlShape.parse(sql, digest);
            String id = queryId == null || queryId.length() > MAX_QUERY_ID_LENGTH || queryId.isBlank()
                    ? sourceId(framework, shape.hash(), digest)
                    : ObservationDigest.QUERY_ID.hash(digest, queryId);
            AttributionProbe.transition("FINGERPRINT_AND_ID");
            SqlObservation event = new SqlObservation(framework, point, id, shape.hash(), shape.kind(), shape.status());
            AttributionProbe.transition("EVENT_CREATE");
            sink.accept(event, shape.reason());
            AttributionProbe.finishCurrent("EVENT_SINK");""")
    if name == SHAPE:
        java = replace(java, 'import java.security.MessageDigest;',
                       previous.PROBE_IMPORT + 'import java.security.MessageDigest;')
        anchor = '            return new SqlShape(ObservationDigest.SQL_SHAPE.hash(digest, '
        if 'hash(digest, tokens.toString()), kind, NONE);' in java:
            return replace(java, anchor + 'tokens.toString()), kind, NONE);',
                           '            String normalized = tokens.toString();\n'
                           '            AttributionProbe.transition("SHAPE");\n'
                           + anchor + 'normalized), kind, NONE);')
        return replace(java, anchor + 'tokens, tokenBytes), kind, NONE);',
                       '            AttributionProbe.transition("SHAPE");\n'
                       + anchor + 'tokens, tokenBytes), kind, NONE);')
    if name == previous.DATA_SOURCE:
        for anchor, replacement in previous.REPLACEMENTS[name]:
            java = replace(java, anchor, replacement)
    if name in (previous.FIXTURE, PROBE):
        java = replace(java, 'int WARMUP = 8;', 'int WARMUP = 4;')
        java = replace(java, 'int MEASURED = 96;', 'int MEASURED = 16;')
    if name == PROBE:
        java = replace(java, 'JDBC_OTHER, FINGERPRINT,', 'JDBC_OTHER, SHAPE, FINGERPRINT_AND_ID,')
        java = replace(java, 'require(calls[Metric.FINGERPRINT.ordinal()] == expected &&',
                       'require(calls[Metric.SHAPE.ordinal()] == expected\n'
                       '                && calls[Metric.FINGERPRINT_AND_ID.ordinal()] == 2 * expected &&')
        java = replace(java, '    private static void record(Metric metric,',
                       """    public static void transition(String metric) {
        long boundary = System.nanoTime();
        record(Metric.valueOf(metric), timerStart, boundary);
        timing = true;
        timerStart = boundary;
    }

    public static void finishCurrent(String metric) {
        finish(metric, timerStart);
    }

    private static void record(Metric metric,""")
    if name == previous.FIXTURE:
        for anchor, replacement in previous.REPLACEMENTS[name]:
            java = replace(java, anchor, replacement)
        replacements = (
            ('import dev.udak.observe.SqlObserver;', 'import dev.udak.observe.SqlObserver;\n'
             'import dev.udak.observe.UnavailableReason;'),
            ('args.length == 2', 'args.length == 3 && args[0].equals("POSTGRESQL") && args[2].matches("[0-3]")'),
            ('                seed(connection, engine);', '                if (args[2].equals("0")) seed(connection, engine);'),
            ('                trial.run();', '                trial.run(Integer.parseInt(args[2]));'),
            ('        public void accept(SqlObservation event) {',
             '        public void accept(SqlObservation event) {\n            throw new AssertionError();\n        }\n'
             '\n        @Override\n        public void accept(SqlObservation event, UnavailableReason reason) {\n'
             '            require(reason == UnavailableReason.NONE);'),
            ('        private final long[] starts = new long[TOTAL];',
             '        private final long[] starts = new long[TOTAL];\n'
             '        private final StringJoiner schedule = new StringJoiner(",");'),
            ('void run() throws InterruptedException', 'void run(int block) throws InterruptedException'),
            ('int id = 1 + pair % ROWS;', 'int id = 1 + (pair + (block >= 2 ? 4 : 0)) % ROWS;'),
            ('boolean observedFirst = pair % 2 != 0;',
             'boolean observedFirst = ((pair ^ (pair >>> 3) ^ block) & 1) != 0;'),
            ('            starts[completed++] = started;',
             '            schedule.add(Integer.toString(id * 2 + (observe ? 1 : 0)));\n'
             '            starts[completed++] = started;'),
            ('            AttributionProbe.report(report);',
             '            AttributionProbe.report(report);\n'
             '            report.println("EVENT_KEY " + firstEvent.queryIdHash() + " "\n'
             '                    + firstEvent.fingerprintHash());\n'
             '            report.println("SCHEDULE " + schedule);\n'
             '            long[] gaps = new long[TOTAL - 1];\n'
             '            for (int i = 1; i < TOTAL; i++) gaps[i - 1] = starts[i] - starts[i - 1];\n'
             '            report.println(samplesLine("GAPS_NS", gaps));'),
        )
        for anchor, replacement in replacements:
            java = replace(java, anchor, replacement)
    return java


def materialize(root, work, revision, hashes, sources, probe):
    inputs = []
    generated = {}
    for name in (*sources, PROBE):
        if name == PROBE:
            data = probe
        else:
            data = subprocess.check_output(
                ['git', '--no-lazy-fetch', '--no-replace-objects', 'show', revision + ':' + name],
                cwd=root, timeout=5, stderr=subprocess.DEVNULL)
        if len(data) > previous.MAX_SOURCE_BYTES:
            raise ValueError('SOURCE_BOUND')
        if hashlib.sha512(data).hexdigest() != hashes[name]:
            raise ValueError('PINNED_SOURCE_MISMATCH')
        changed = instrument(name, data.decode('utf-8')).encode('utf-8')
        if len(changed) > previous.MAX_SOURCE_BYTES:
            raise ValueError('SOURCE_BOUND')
        source = work / name
        source.parent.mkdir(parents=True, exist_ok=True)
        with source.open('xb') as stream:
            stream.write(changed)
        inputs.append(source)
        if changed != data:
            generated[name] = hashlib.sha512(changed).hexdigest()
    return inputs, generated
