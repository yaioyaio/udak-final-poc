package dev.udak.rewrite;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFileAttributes;
import java.nio.file.attribute.PosixFilePermission;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.EnumSet;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Function;
import java.util.regex.Pattern;

/** Single-writer local journal in an existing, trusted POSIX directory. */
public final class ApprovalHistory implements AutoCloseable {
    public enum Kind { APPROVED, REVOKED }
    public record Event(long sequence, Kind kind, long generation, Instant recordedAt, Rewrite.Approval approval) {
        @Override public String toString() { return "Event[" + kind + ", sequence=" + sequence + "]"; }
    }

    private static final byte[] HEADER = {'U','D','A','K','A','H',0,1};
    private static final int MAX_EVENTS = 4096;
    private static final int MAX_PAYLOAD = 2048;
    private static final int HASH_BYTES = 32;
    private static final long MAX_BYTES = HEADER.length + (long) MAX_EVENTS * (4 + MAX_PAYLOAD + HASH_BYTES);
    private static final Set<PosixFilePermission> OWNER_RW = PosixFilePermissions.fromString("rw-------");
    private static final Set<Rewrite.Check> REQUIRED = Set.copyOf(EnumSet.allOf(Rewrite.Check.class));
    private static final Pattern QUERY_ID = Pattern.compile("[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}");
    // Avoid opening a second descriptor for a locked inode in this JVM.
    private static final Set<Object> OWNED = ConcurrentHashMap.newKeySet();

    private final FileChannel channel;
    private final FileLock lock;
    private final Object fileKey;
    private final Clock clock;
    private final Map<String, List<Event>> events = new HashMap<>();
    private final Map<String, Rewrite.Registry> active = new HashMap<>();
    private long sequence;
    private byte[] previous = digest().digest(HEADER);
    private boolean closed;

    private ApprovalHistory(FileChannel channel, FileLock lock, Object fileKey, Clock clock) {
        this.channel = channel;
        this.lock = lock;
        this.fileKey = fileKey;
        this.clock = clock;
    }

    public static synchronized ApprovalHistory open(Path journal, Clock clock) throws IOException {
        if (journal == null || clock == null) throw new Rewrite.Denied(Rewrite.Code.INVALID_INPUT);
        Object fileKey = null;
        boolean owned = false;
        FileChannel channel = null;
        try {
            Path requested = journal.toAbsolutePath();
            if (requested.getFileName() == null) throw storageError();
            Path parent = requested.getParent().toRealPath();
            PosixFileAttributes directory = Files.readAttributes(parent, PosixFileAttributes.class);
            if (!directory.isDirectory() || directory.permissions().contains(PosixFilePermission.GROUP_WRITE)
                    || directory.permissions().contains(PosixFilePermission.OTHERS_WRITE)) throw storageError();
            Path path = parent.resolve(requested.getFileName());

            boolean created;
            try {
                channel = FileChannel.open(path, Set.of(StandardOpenOption.READ, StandardOpenOption.WRITE,
                        StandardOpenOption.CREATE_NEW, LinkOption.NOFOLLOW_LINKS),
                        PosixFilePermissions.asFileAttribute(OWNER_RW));
                created = true;
            } catch (FileAlreadyExistsException exists) {
                fileKey = journalKey(path);
                if (OWNED.contains(fileKey)) throw storageError();
                channel = FileChannel.open(path, StandardOpenOption.READ, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS);
                created = false;
            }
            if (created) fileKey = journalKey(path);
            owned = OWNED.add(fileKey);
            if (!owned) throw storageError();
            FileLock lock = channel.tryLock();
            if (lock == null) throw storageError();
            ApprovalHistory store = new ApprovalHistory(channel, lock, fileKey, clock);
            if (created) {
                store.write(ByteBuffer.wrap(HEADER));
                channel.force(true);
            } else {
                store.replay();
            }
            try (FileChannel parentChannel = FileChannel.open(parent, StandardOpenOption.READ)) {
                parentChannel.force(true);
            }
            return store;
        } catch (IOException | RuntimeException failure) {
            if (channel != null) {
                try { channel.close(); } catch (IOException ignored) { /* Report a redacted storage failure. */ }
            }
            if (owned) OWNED.remove(fileKey);
            throw storageError();
        }
    }

    private static Object journalKey(Path path) throws IOException {
        var attributes = Files.readAttributes(path, PosixFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
        if (!attributes.isRegularFile() || !OWNER_RW.equals(attributes.permissions()) || attributes.fileKey() == null
                || ((Number) Files.getAttribute(path, "unix:nlink", LinkOption.NOFOLLOW_LINKS)).longValue() != 1) {
            throw storageError();
        }
        return attributes.fileKey();
    }

    public synchronized long approve(Rewrite.Approval approval, Rewrite.Evidence proof) throws IOException {
        requireOpen();
        if (approval == null || proof == null) throw new Rewrite.Denied(Rewrite.Code.INVALID_INPUT);
        String queryId = approval.queryId();
        if (active.containsKey(queryId)) throw new Rewrite.Denied(Rewrite.Code.INVALID_INPUT);
        Instant now = clock.instant();
        validate(approval, proof, now);
        // Every active generation must still have space for its explicit revocation.
        if (sequence + active.size() + 2 > MAX_EVENTS) throw storageError();
        Event last = last(queryId);
        long generation = last == null ? 1 : last.generation() + 1;
        Event event = new Event(sequence + 1, Kind.APPROVED, generation, now, approval);
        Rewrite.Registry registry = registry(approval, proof);
        append(event, proof);
        active.put(queryId, registry);
        return generation;
    }

    public synchronized boolean revoke(String queryId, long generation) throws IOException {
        requireOpen();
        checkQueryId(queryId);
        Event last = last(queryId);
        if (last == null || last.kind() != Kind.APPROVED || last.generation() != generation) return false;
        Event event = new Event(sequence + 1, Kind.REVOKED, generation, clock.instant(), last.approval());
        active.get(queryId).revoke(queryId);
        append(event, null);
        active.remove(queryId);
        return true;
    }

    public synchronized List<Event> history(String queryId) {
        requireOpen();
        checkQueryId(queryId);
        return List.copyOf(events.getOrDefault(queryId, List.of()));
    }

    /** The selected registry keeps its generation identity across close, revoke and replacement. */
    public <T> T withRegistry(Rewrite.Template template, Function<Rewrite.Registry, T> action) {
        if (template == null || action == null) throw new Rewrite.Denied(Rewrite.Code.INVALID_INPUT);
        Rewrite.Registry registry;
        synchronized (this) {
            requireOpen();
            String queryId = template.queryId();
            registry = active.get(queryId);
            if (registry == null) {
                throw new Rewrite.Denied(events.containsKey(queryId) ? Rewrite.Code.REVOKED : Rewrite.Code.MISSING_APPROVAL);
            }
        }
        return action.apply(registry);
    }

    @Override public synchronized void close() throws IOException {
        if (closed) return;
        closed = true;
        active.forEach((id, registry) -> registry.revoke(id));
        active.clear();
        try {
            channel.close(); // Releases the exclusive FileLock as well.
        } catch (IOException failure) {
            throw storageError();
        } finally {
            OWNED.remove(fileKey);
        }
    }

    private static void validate(Rewrite.Approval a, Rewrite.Evidence e, Instant now) {
        if (!a.queryId().equals(e.queryId()) || !a.evidenceId().equals(e.id())
                || !a.evidenceDigest().equals(e.digest()) || !a.environment().equals(e.environment())
                || !a.sourceFingerprint().equals(e.sourceFingerprint()) || !a.targetFingerprint().equals(e.targetFingerprint())
                || !a.planFingerprint().equals(e.planFingerprint()) || !REQUIRED.equals(e.passed())
                || a.expiresAt().isAfter(e.validUntil()) || e.verifiedAt().isAfter(now)) {
            throw new Rewrite.Denied(Rewrite.Code.EVIDENCE_INVALID);
        }
        if (!now.isBefore(a.expiresAt()) || !now.isBefore(e.validUntil())) throw new Rewrite.Denied(Rewrite.Code.EXPIRED);
    }

    private Rewrite.Registry registry(Rewrite.Approval a, Rewrite.Evidence e) {
        return new Rewrite.Registry(Map.of(a.queryId(), a), Map.of(e.id(), e), clock);
    }

    private void append(Event event, Rewrite.Evidence evidence) throws IOException {
        try {
            byte[] payload = encode(event, evidence);
            if (!lock.isValid() || channel.position() != channel.size() || payload.length > MAX_PAYLOAD) throw storageError();
            byte[] hash = hash(payload);
            ByteBuffer frame = ByteBuffer.allocate(4 + payload.length + HASH_BYTES);
            frame.putInt(payload.length).put(payload).put(hash).flip();
            write(frame);
            channel.force(true);
            previous = hash;
            remember(event);
        } catch (IOException | RuntimeException failure) {
            close();
            throw storageError();
        }
    }

    private void replay() throws IOException {
        long size = channel.size();
        if (size < HEADER.length || size > MAX_BYTES || !Arrays.equals(read(HEADER.length), HEADER)) throw storageError();
        Map<String, Rewrite.Evidence> pending = new HashMap<>();
        while (channel.position() < size) {
            if (sequence == MAX_EVENTS) throw storageError();
            int length = ByteBuffer.wrap(read(4)).getInt();
            if (length <= 0 || length > MAX_PAYLOAD) throw storageError();
            byte[] payload = read(length);
            byte[] hash = hash(payload);
            if (!MessageDigest.isEqual(hash, read(HASH_BYTES))) throw storageError();
            restore(payload, pending);
            previous = hash;
        }
        for (var entry : pending.entrySet()) {
            String id = entry.getKey();
            active.put(id, registry(last(id).approval(), entry.getValue()));
        }
    }

    private void restore(byte[] payload, Map<String, Rewrite.Evidence> pending) throws IOException {
        var in = new DataInputStream(new ByteArrayInputStream(payload));
        long next = in.readLong();
        int kind = in.readUnsignedByte();
        long generation = in.readLong();
        Instant at = readTime(in);
        String id = in.readUTF();
        Event last = last(id);
        if (next != sequence + 1) throw storageError();
        Event event;
        if (kind == 1) {
            if (pending.containsKey(id) || generation != (last == null ? 1 : last.generation() + 1)
                    || next + pending.size() + 1 > MAX_EVENTS) throw storageError();
            String source = in.readUTF();
            var environment = new Rewrite.Environment(Rewrite.Dialect.valueOf(in.readUTF()), Rewrite.Dialect.valueOf(in.readUTF()),
                    in.readUTF(), in.readUTF(), in.readUTF(), in.readUTF(), in.readUTF(), in.readUTF());
            var approval = new Rewrite.Approval(id, source, environment, in.readUTF(), in.readUTF(),
                    in.readUTF(), in.readUTF(), readTime(in));
            Instant verifiedAt = readTime(in);
            Instant validUntil = readTime(in);
            int count = in.readUnsignedByte();
            if (count != REQUIRED.size()) throw storageError();
            var checks = EnumSet.noneOf(Rewrite.Check.class);
            for (int i = 0; i < count; i++) checks.add(Rewrite.Check.valueOf(in.readUTF()));
            var proof = new Rewrite.Evidence(approval.evidenceId(), approval.evidenceDigest(), id, source, environment,
                    approval.targetFingerprint(), approval.planFingerprint(), verifiedAt, validUntil, checks);
            validate(approval, proof, at); // Historical issuance time. Execution checks the current clock.
            pending.put(id, proof);
            event = new Event(next, Kind.APPROVED, generation, at, approval);
        } else if (kind == 2 && last != null && last.generation() == generation && pending.remove(id) != null) {
            event = new Event(next, Kind.REVOKED, generation, at, last.approval());
        } else {
            throw storageError();
        }
        if (in.available() != 0) throw storageError();
        remember(event);
    }

    private static byte[] encode(Event event, Rewrite.Evidence proof) throws IOException {
        var bytes = new ByteArrayOutputStream();
        var out = new DataOutputStream(bytes);
        out.writeLong(event.sequence());
        out.writeByte(event.kind() == Kind.APPROVED ? 1 : 2);
        out.writeLong(event.generation());
        writeTime(out, event.recordedAt());
        var a = event.approval();
        out.writeUTF(a.queryId());
        if (event.kind() == Kind.APPROVED) {
            out.writeUTF(a.sourceFingerprint());
            var e = a.environment();
            out.writeUTF(e.source().name());
            out.writeUTF(e.target().name());
            out.writeUTF(e.sourceVersion());
            out.writeUTF(e.targetVersion());
            out.writeUTF(e.driverVersion());
            out.writeUTF(e.schemaVersion());
            out.writeUTF(e.providerVersion());
            out.writeUTF(e.runtimeVersion());
            out.writeUTF(a.targetFingerprint());
            out.writeUTF(a.planFingerprint());
            out.writeUTF(a.evidenceId());
            out.writeUTF(a.evidenceDigest());
            writeTime(out, a.expiresAt());
            writeTime(out, proof.verifiedAt());
            writeTime(out, proof.validUntil());
            var checks = EnumSet.copyOf(proof.passed());
            out.writeByte(checks.size());
            for (var check : checks) out.writeUTF(check.name());
        }
        return bytes.toByteArray();
    }

    private void remember(Event event) {
        sequence = event.sequence();
        events.computeIfAbsent(event.approval().queryId(), ignored -> new ArrayList<>()).add(event);
    }

    private Event last(String id) {
        List<Event> entries = events.get(id);
        return entries == null ? null : entries.get(entries.size() - 1);
    }

    private byte[] hash(byte[] payload) {
        MessageDigest digest = digest();
        digest.update(previous);
        return digest.digest(payload);
    }

    private static MessageDigest digest() {
        try { return MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException impossible) { throw new IllegalStateException("SHA-256 unavailable"); }
    }

    private byte[] read(int count) throws IOException {
        ByteBuffer buffer = ByteBuffer.allocate(count);
        while (buffer.hasRemaining()) if (channel.read(buffer) <= 0) throw storageError();
        return buffer.array();
    }

    private void write(ByteBuffer buffer) throws IOException {
        while (buffer.hasRemaining()) if (channel.write(buffer) <= 0) throw storageError();
    }

    private static Instant readTime(DataInputStream in) throws IOException {
        long seconds = in.readLong();
        int nanos = in.readInt();
        if (nanos < 0 || nanos >= 1_000_000_000) throw storageError();
        return Instant.ofEpochSecond(seconds, nanos);
    }

    private static void writeTime(DataOutputStream out, Instant time) throws IOException {
        out.writeLong(time.getEpochSecond());
        out.writeInt(time.getNano());
    }

    private static void checkQueryId(String id) {
        if (id == null || !QUERY_ID.matcher(id).matches()) throw new Rewrite.Denied(Rewrite.Code.INVALID_INPUT);
    }

    private void requireOpen() {
        if (closed) throw new Rewrite.Denied(Rewrite.Code.REVOKED);
    }

    private static IOException storageError() { return new IOException("Approval history unavailable"); }
}
