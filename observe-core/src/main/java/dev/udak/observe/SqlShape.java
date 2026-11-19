package dev.udak.observe;

import java.security.MessageDigest;
import java.util.Locale;

/** Bounded lexical grouping for inventory. This is independent of exact-SQL rewrite approval. */
record SqlShape(String hash, StatementKind kind, FingerprintStatus status) {
    private static final int MAX_SQL_LENGTH = 16_384;
    private static final int MAX_COMMENT_DEPTH = 32;
    private static final int MAX_DOLLAR_TAG = 63;
    private static final SqlShape UNAVAILABLE = new SqlShape(
            ObservationDigest.UNAVAILABLE.hash(ObservationDigest.newSha256(), ""),
            StatementKind.UNKNOWN, FingerprintStatus.UNAVAILABLE);

    static SqlShape parse(String sql, MessageDigest digest) {
        if (sql == null || sql.isEmpty() || sql.length() > MAX_SQL_LENGTH) return UNAVAILABLE;
        return new Lexer(sql).scan(digest);
    }

    private static final class Lexer {
        private final String sql;
        private final StringBuilder tokens = new StringBuilder();
        private int pos;
        private int parentheses;
        private String previous = "";
        private StatementKind kind;
        private boolean terminated;

        Lexer(String sql) {
            this.sql = sql;
        }

        SqlShape scan(MessageDigest digest) {
            while (pos < sql.length()) {
                char c = sql.charAt(pos);
                if (whitespace(c)) {
                    pos++;
                } else if (sql.startsWith("--", pos)) {
                    if (pos + 2 < sql.length() && !whitespace(at(pos + 2))) return UNAVAILABLE;
                    pos += 2;
                    while (pos < sql.length() && at(pos) != '\n' && at(pos) != '\r') pos++;
                } else if (sql.startsWith("/*", pos)) {
                    if (!blockComment()) return UNAVAILABLE;
                } else if (terminated) {
                    return UNAVAILABLE;
                } else if (c == ';') {
                    terminated = true;
                    pos++;
                } else {
                    if (c == '(') parentheses++;
                    if (c == ')' && --parentheses < 0) return UNAVAILABLE;
                    String token = token();
                    if (token == null) return UNAVAILABLE;
                    if (kind == null) {
                        kind = classify(token);
                        if (kind == StatementKind.UNKNOWN) return UNAVAILABLE;
                    }
                    tokens.append(token).append(' ');
                    previous = token;
                }
            }
            if (kind == null || parentheses != 0) return UNAVAILABLE;
            return new SqlShape(ObservationDigest.SQL_SHAPE.hash(digest, tokens.toString()), kind,
                    FingerprintStatus.NORMALIZED);
        }

        private String token() {
            char c = at(pos);
            if (letter(c) || c == '_') return word();
            if (digit(c) || c == '.' && digit(at(pos + 1))) return number();
            if ((c == '+' || c == '-') && signedNumberFollows()) {
                pos++;
                return number();
            }
            if (c == '\'') return quoted('\'', false) ? "?" : null;
            if (c == '"' || c == '`' || c == '[') return quoted(c == '[' ? ']' : c, false) ? "<id>" : null;
            if (c == '$') return dollar();
            if (sql.startsWith("::", pos)) {
                pos += 2;
                return "::";
            }
            if (c == ':' || c == '@') {
                if (!letter(at(pos + 1)) && at(pos + 1) != '_') return null;
                pos += 2;
                while (wordPart(at(pos))) pos++;
                return "?";
            }
            if ("?,().=<>+-*/%!|&^~".indexOf(c) >= 0 && !sql.startsWith("*/", pos)) {
                pos++;
                return Character.toString(c);
            }
            return null;
        }

        private boolean signedNumberFollows() {
            if (!digit(at(pos + 1)) && !(at(pos + 1) == '.' && digit(at(pos + 2)))) return false;
            return switch (previous) {
                case "select", "returning", "when", "then", "else", "between", "and", "or",
                        "(", ",", "=", "<", ">", "!", "+", "-", "/", "*", "%" -> true;
                default -> false;
            };
        }

        private String word() {
            int start = pos++;
            while (wordPart(at(pos))) pos++;
            if (at(pos) == '$') return null; // Dollar tags must start a distinct token.
            String word = sql.substring(start, pos).toLowerCase(Locale.ROOT);
            // Administrative SQL and EXEC can accept unquoted credential or argument values.
            // Their boundaries cannot be inferred safely from framework-neutral SQL.
            switch (word) {
                case "identified", "password", "credential", "login", "exec", "execute" -> { return null; }
                default -> { }
            }
            if (at(pos) == '\'') {
                return switch (word) {
                    case "q", "nq" -> oracleQuoted() ? "?" : null;
                    case "e" -> quoted('\'', true) ? "?" : null;
                    case "n", "x", "b" -> quoted('\'', false) ? "?" : null;
                    default -> word; // The next token will consume the ordinary quoted literal.
                };
            }
            return switch (word) {
                case "true", "false", "null" -> "?";
                default -> word;
            };
        }

        private String number() {
            if (sql.regionMatches(true, pos, "0x", 0, 2) || sql.regionMatches(true, pos, "0b", 0, 2)) {
                boolean binary = Character.toLowerCase(at(pos + 1)) == 'b';
                pos += 2;
                int start = pos;
                while (binary ? at(pos) == '0' || at(pos) == '1' : hex(at(pos))) pos++;
                if (start == pos) return null;
            } else {
                while (digit(at(pos))) pos++;
                if (at(pos) == '.') {
                    pos++;
                    while (digit(at(pos))) pos++;
                }
                if (at(pos) == 'e' || at(pos) == 'E') {
                    pos++;
                    if (at(pos) == '+' || at(pos) == '-') pos++;
                    if (!digit(at(pos))) return null;
                    while (digit(at(pos))) pos++;
                }
            }
            return wordPart(at(pos)) || at(pos) == '$' ? null : "?";
        }

        private boolean quoted(char close, boolean backslashEscapes) {
            pos++;
            while (pos < sql.length()) {
                char c = sql.charAt(pos++);
                // '[' may also open a subscript expression containing its own quoted tokens.
                if (close == ']' && !wordPart(c) && c != ' ' && c != ']') return false;
                if (c == '\\' && close != ']') {
                    // In an ordinary quoted token, an odd backslash before its delimiter is
                    // mode-dependent. Discard the entire shape instead of guessing its end.
                    if (backslashEscapes || at(pos) == '\\') {
                        if (pos == sql.length()) return false;
                        pos++;
                    } else if (at(pos) == close) {
                        return false;
                    }
                } else if (c == close) {
                    if (at(pos) != close) return true;
                    pos++;
                }
            }
            return false;
        }

        private boolean oracleQuoted() {
            char open = at(pos + 1);
            if (open <= ' ' || open > '~' || open == '\'') return false;
            char close = switch (open) {
                case '[' -> ']';
                case '(' -> ')';
                case '{' -> '}';
                case '<' -> '>';
                default -> open;
            };
            pos += 2;
            while (pos < sql.length()) {
                if (sql.charAt(pos++) == close && at(pos) == '\'') {
                    pos++;
                    return true;
                }
            }
            return false;
        }

        private String dollar() {
            int start = pos++;
            if (digit(at(pos))) {
                while (digit(at(pos))) pos++;
                return wordPart(at(pos)) || at(pos) == '$' ? null : "?";
            }
            while (wordPart(at(pos))) {
                if (pos - start > MAX_DOLLAR_TAG) return null;
                pos++;
            }
            if (at(pos) != '$') return null;
            String delimiter = sql.substring(start, ++pos);
            int end = sql.indexOf(delimiter, pos);
            if (end < 0) return null;
            pos = end + delimiter.length();
            return "?";
        }

        private boolean blockComment() {
            int depth = 0;
            while (pos < sql.length()) {
                if (sql.startsWith("/*", pos)) {
                    pos += 2;
                    if (++depth > MAX_COMMENT_DEPTH) return false;
                    // MySQL and MariaDB executable comments can change what is executed.
                    if (at(pos) == '!' || sql.regionMatches(true, pos, "M!", 0, 2)) return false;
                } else if (sql.startsWith("*/", pos)) {
                    pos += 2;
                    if (--depth == 0) return true;
                } else {
                    pos++;
                }
            }
            return false;
        }

        private char at(int index) {
            return index < sql.length() ? sql.charAt(index) : '\0';
        }
    }

    private static StatementKind classify(String word) {
        return switch (word) {
            case "select" -> StatementKind.SELECT;
            case "insert" -> StatementKind.INSERT;
            case "update" -> StatementKind.UPDATE;
            case "delete" -> StatementKind.DELETE;
            case "merge" -> StatementKind.MERGE;
            case "call" -> StatementKind.CALL;
            case "create", "alter", "drop", "truncate", "rename" -> StatementKind.DDL;
            case "with", "explain", "values" -> StatementKind.OTHER;
            default -> StatementKind.UNKNOWN;
        };
    }

    private static boolean whitespace(char c) {
        return c == ' ' || c == '\t' || c == '\r' || c == '\n' || c == '\f';
    }

    private static boolean letter(char c) {
        return c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z';
    }

    private static boolean digit(char c) {
        return c >= '0' && c <= '9';
    }

    private static boolean hex(char c) {
        return digit(c) || c >= 'a' && c <= 'f' || c >= 'A' && c <= 'F';
    }

    private static boolean wordPart(char c) {
        return letter(c) || digit(c) || c == '_';
    }
}
