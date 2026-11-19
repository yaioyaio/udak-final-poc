package dev.udak.diagnostic;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.Socket;
import javax.net.SocketFactory;

/** Plain socket instrumentation for the diagnostic's owned loopback fixture. */
public final class ExecuteSocketFactory extends SocketFactory {
    public ExecuteSocketFactory() {}

    @Override
    public Socket createSocket() {
        return new MeasuredSocket();
    }

    @Override
    public Socket createSocket(String host, int port) throws IOException {
        return new MeasuredSocket(host, port);
    }

    @Override
    public Socket createSocket(InetAddress address, int port) throws IOException {
        return new MeasuredSocket(address, port);
    }

    @Override
    public Socket createSocket(String host, int port, InetAddress localAddress, int localPort) throws IOException {
        return new MeasuredSocket(host, port, localAddress, localPort);
    }

    @Override
    public Socket createSocket(InetAddress address, int port, InetAddress localAddress, int localPort)
            throws IOException {
        return new MeasuredSocket(address, port, localAddress, localPort);
    }

    private static final class MeasuredSocket extends Socket {
        private InputStream input;
        private OutputStream output;

        private MeasuredSocket() {}

        private MeasuredSocket(String host, int port) throws IOException {
            super(host, port);
        }

        private MeasuredSocket(InetAddress address, int port) throws IOException {
            super(address, port);
        }

        private MeasuredSocket(String host, int port, InetAddress localAddress, int localPort) throws IOException {
            super(host, port, localAddress, localPort);
        }

        private MeasuredSocket(InetAddress address, int port, InetAddress localAddress, int localPort)
                throws IOException {
            super(address, port, localAddress, localPort);
        }

        @Override
        public synchronized InputStream getInputStream() throws IOException {
            InputStream delegate = super.getInputStream();
            if (input == null) input = new MeasuredInput(delegate);
            return input;
        }

        @Override
        public synchronized OutputStream getOutputStream() throws IOException {
            OutputStream delegate = super.getOutputStream();
            if (output == null) output = new MeasuredOutput(delegate);
            return output;
        }
    }

    // The inherited bulk helpers use these reads without counting the outer helper again.
    private static final class MeasuredInput extends InputStream {
        private final InputStream delegate;

        private MeasuredInput(InputStream delegate) {
            this.delegate = delegate;
        }

        @Override
        public int read() throws IOException {
            ExecuteIntervals.Measurement measurement = ExecuteIntervals.activeSocketCapture();
            if (measurement == null) return delegate.read();
            long start = System.nanoTime();
            int bytes = 0;
            try {
                int value = delegate.read();
                if (value != -1) bytes = 1;
                return value;
            } finally {
                measurement.recordRead(start, bytes);
            }
        }

        @Override
        public int read(byte[] buffer, int offset, int length) throws IOException {
            ExecuteIntervals.Measurement measurement = ExecuteIntervals.activeSocketCapture();
            if (measurement == null) return delegate.read(buffer, offset, length);
            long start = System.nanoTime();
            int bytes = 0;
            try {
                bytes = delegate.read(buffer, offset, length);
                return bytes;
            } finally {
                measurement.recordRead(start, bytes);
            }
        }

        @Override
        public int available() throws IOException {
            return delegate.available();
        }

        @Override
        public void close() throws IOException {
            delegate.close();
        }
    }

    private static final class MeasuredOutput extends OutputStream {
        private final OutputStream delegate;

        private MeasuredOutput(OutputStream delegate) {
            this.delegate = delegate;
        }

        @Override
        public void write(int value) throws IOException {
            ExecuteIntervals.Measurement measurement = ExecuteIntervals.activeSocketCapture();
            if (measurement == null) {
                delegate.write(value);
                return;
            }
            long start = System.nanoTime();
            int bytes = 0;
            try {
                delegate.write(value);
                bytes = 1;
            } finally {
                measurement.recordWrite(start, bytes);
            }
        }

        @Override
        public void write(byte[] buffer, int offset, int length) throws IOException {
            ExecuteIntervals.Measurement measurement = ExecuteIntervals.activeSocketCapture();
            if (measurement == null) {
                delegate.write(buffer, offset, length);
                return;
            }
            long start = System.nanoTime();
            int bytes = 0;
            try {
                delegate.write(buffer, offset, length);
                bytes = length;
            } finally {
                measurement.recordWrite(start, bytes);
            }
        }

        @Override
        public void flush() throws IOException {
            delegate.flush();
        }

        @Override
        public void close() throws IOException {
            delegate.close();
        }
    }
}
