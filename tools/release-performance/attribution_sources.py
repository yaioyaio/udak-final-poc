"""Generate bounded, instrumented copies of the PostgreSQL diagnostic sources."""

import hashlib
import os
from pathlib import Path
import stat


MAX_SOURCE_BYTES = 1024**2
FIXTURE = 'tools/release-performance/ProductG5PerformanceMain.java'
OBSERVER = 'observe-core/src/main/java/dev/udak/observe/SqlObserver.java'
DATA_SOURCE = 'legacy-observe/src/main/java/dev/udak/observe/jdbc/ObserveDataSource.java'
PROBE_IMPORT = 'import dev.udak.diagnostic.AttributionProbe;\n'

REPLACEMENTS = {
    FIXTURE: (
        ('import dev.udak.observe.FingerprintStatus;\n',
         PROBE_IMPORT + 'import dev.udak.observe.FingerprintStatus;\n'),
        ('                trial = new Trial(connection);\n',
         '                trial = new Trial(AttributionProbe.wrap(connection));\n'),
        ('            long started = System.nanoTime();\n',
         '            AttributionProbe.begin(observe);\n'
         '            long started = System.nanoTime();\n'),
        ('            long elapsed = System.nanoTime() - started;\n',
         '            long elapsed = System.nanoTime() - started;\n'
         '            AttributionProbe.end(observe, index, elapsed);\n'),
        ('            report.println(observedLine);\n',
         '            report.println(observedLine);\n'
         '            AttributionProbe.report(report);\n'),
    ),
    OBSERVER: (
        ('import java.security.MessageDigest;\n',
         PROBE_IMPORT + 'import java.security.MessageDigest;\n'),
        ('            MessageDigest digest = ObservationDigest.newSha256();\n',
         '            long fingerprintStarted = AttributionProbe.start();\n'
         '            MessageDigest digest = ObservationDigest.newSha256();\n'),
        ('            sink.accept(new SqlObservation(framework, point, id, shape.hash(), shape.kind(), shape.status()));\n',
         '            AttributionProbe.finish("FINGERPRINT", fingerprintStarted);\n'
         '            long eventCreateStarted = AttributionProbe.start();\n'
         '            SqlObservation event = new SqlObservation(framework, point, id, shape.hash(),\n'
         '                    shape.kind(), shape.status());\n'
         '            AttributionProbe.finish("EVENT_CREATE", eventCreateStarted);\n'
         '            long eventSinkStarted = AttributionProbe.start();\n'
         '            sink.accept(event);\n'
         '            AttributionProbe.finish("EVENT_SINK", eventSinkStarted);\n'),
    ),
    DATA_SOURCE: (
        ('import dev.udak.observe.Framework;\n',
         PROBE_IMPORT + 'import dev.udak.observe.Framework;\n'),
        ('        return type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[] {type}, handler));\n',
         '        long proxyStarted = AttributionProbe.start();\n'
         '        T result = type.cast(Proxy.newProxyInstance(type.getClassLoader(), new Class<?>[] {type}, handler));\n'
         '        AttributionProbe.finish("OBSERVE_PROXY", proxyStarted);\n'
         '        return result;\n'),
    ),
}


def _instrument(source, name):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(source, flags), 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f'Diagnostic source is not a regular file: {name}')
        data = stream.read(MAX_SOURCE_BYTES + 1)
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError(f'Diagnostic source exceeds size limit: {name}')
    java = data.decode('utf-8')
    for anchor, replacement in REPLACEMENTS[name]:
        if java.count(anchor) != 1:
            raise ValueError(f'Diagnostic instrumentation anchor differs: {name}')
        java = java.replace(anchor, replacement, 1)
    data = java.encode('utf-8')
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError(f'Generated diagnostic source exceeds size limit: {name}')
    return data


def build_sources(root, work, original_sources):
    """Return the javac inputs and SHA-512 digests keyed by original source name."""
    root = Path(root).resolve(strict=True)
    work = Path(work).resolve(strict=True)
    originals = {}
    for original in original_sources:
        source = root / original
        if (not source.is_relative_to(root) or source.suffix != '.java'
                or source.resolve(strict=True) != source or not source.is_file()
                or source.stat().st_size > MAX_SOURCE_BYTES):
            raise ValueError('Invalid diagnostic compile source path')
        name = source.relative_to(root).as_posix()
        if name in originals:
            raise ValueError('Duplicate diagnostic compile source')
        originals[name] = source
    if not REPLACEMENTS.keys() <= originals.keys():
        raise ValueError('Diagnostic compile sources are incomplete')

    generated = {name: _instrument(originals[name], name) for name in REPLACEMENTS}
    scratch = work / 'attribution-sources'
    scratch.mkdir(mode=0o700)
    hashes = {}
    for name, data in generated.items():
        source = scratch / name
        source.parent.mkdir(parents=True, exist_ok=True)
        with source.open('xb') as stream:
            stream.write(data)
        originals[name] = source
        hashes[name] = hashlib.sha512(data).hexdigest()
    return list(originals.values()), hashes
