package dev.udak.observe;

import java.security.MessageDigest;
import java.util.Arrays;
import java.util.EnumMap;

import static dev.udak.observe.UnavailableReason.*;

/** Bounded lexical grouping for inventory. This is independent of exact-SQL rewrite approval. */
record SqlShape(String hash, StatementKind kind, UnavailableReason reason) {
    private static final int MAX_SQL_LENGTH = 16_384;
    private static final int MAX_COMMENT_DEPTH = 32;
    private static final int MAX_DOLLAR_TAG = 63;
    private static final EnumMap<UnavailableReason, SqlShape> UNAVAILABLE = unavailableShapes();

    private static EnumMap<UnavailableReason, SqlShape> unavailableShapes() {
        String digest = ObservationDigest.UNAVAILABLE.hash(ObservationDigest.newSha256(), "");
        EnumMap<UnavailableReason, SqlShape> shapes = new EnumMap<>(UnavailableReason.class);
        for (UnavailableReason reason : UnavailableReason.values()) {
            if (reason != NONE) shapes.put(reason, new SqlShape(digest, StatementKind.UNKNOWN, reason));
        }
        return shapes;
    }

    static SqlShape parse(String sql, MessageDigest digest) {
        if (sql == null || sql.isEmpty()) return UNAVAILABLE.get(EMPTY_SQL);
        if (sql.length() > MAX_SQL_LENGTH) return UNAVAILABLE.get(SQL_TOO_LONG);
        return new Lexer(sql).scan(digest);
    }

    FingerprintStatus status() {
        return reason == NONE ? FingerprintStatus.NORMALIZED : FingerprintStatus.UNAVAILABLE;
    }

    private static final class Lexer {
        private final String sql;
        private byte[] tokens;
        private int tokenBytes;
        private int pos;
        private int parentheses;
        private int previousStart;
        private StatementKind kind;
        private boolean terminated;
        private UnavailableReason tokenFailure;

        Lexer(String sql) {
            this.sql = sql;
            tokens = new byte[Math.min(sql.length() + 16, 128)];
        }

        SqlShape scan(MessageDigest digest) {
            while (pos < sql.length()) {
                char c = sql.charAt(pos);
                if (whitespace(c)) {
                    pos++;
                } else if (sql.startsWith("--", pos)) {
                    if (pos + 2 < sql.length() && !whitespace(at(pos + 2))) {
                        return UNAVAILABLE.get(AMBIGUOUS_SYNTAX);
                    }
                    pos += 2;
                    while (pos < sql.length() && at(pos) != '\n' && at(pos) != '\r') pos++;
                } else if (sql.startsWith("/*", pos)) {
                    UnavailableReason reason = blockComment();
                    if (reason != NONE) return UNAVAILABLE.get(reason);
                } else if (terminated) {
                    return UNAVAILABLE.get(MULTIPLE_STATEMENTS);
                } else if (c == ';') {
                    terminated = true;
                    pos++;
                } else {
                    if (c == '(') parentheses++;
                    if (c == ')' && --parentheses < 0) return UNAVAILABLE.get(MALFORMED_SYNTAX);
                    int start = tokenBytes;
                    if (letter(c) || c == '_') {
                        if (!word()) return UNAVAILABLE.get(tokenFailure);
                    } else {
                        String token = token();
                        if (token == null) return UNAVAILABLE.get(tokenFailure);
                        append(token);
                    }
                    if (kind == null || kind == StatementKind.UNKNOWN) return UNAVAILABLE.get(UNSUPPORTED_SYNTAX);
                    previousStart = start;
                }
            }
            if (kind == null) return UNAVAILABLE.get(EMPTY_SQL);
            if (parentheses != 0) return UNAVAILABLE.get(MALFORMED_SYNTAX);
            return new SqlShape(ObservationDigest.SQL_SHAPE.hash(digest, tokens, tokenBytes), kind, NONE);
        }

        private void reserveToken(int length) {
            int required = tokenBytes + length + 1;
            if (required > tokens.length) {
                tokens = Arrays.copyOf(tokens, Math.max(required, tokens.length * 2));
            }
        }

        private void append(String token) {
            reserveToken(token.length());
            for (int i = 0; i < token.length(); i++) {
                tokens[tokenBytes++] = (byte) token.charAt(i);
            }
            tokens[tokenBytes++] = ' ';
        }

        private String token() {
            char c = at(pos);
            if (digit(c) || c == '.' && digit(at(pos + 1))) return number();
            if ((c == '+' || c == '-') && signedNumberFollows()) {
                pos++;
                return number();
            }
            if (c == '\'') return quotedToken(quoted('\'', false), "?");
            if (c == '"' || c == '`' || c == '[') {
                return quotedToken(quoted(c == '[' ? ']' : c, false), "<id>");
            }
            if (c == '$') return dollar();
            if (sql.startsWith("::", pos)) {
                pos += 2;
                return "::";
            }
            if (c == ':' || c == '@') {
                if (!letter(at(pos + 1)) && at(pos + 1) != '_') return rejectToken(UNSUPPORTED_SYNTAX);
                pos += 2;
                while (wordPart(at(pos))) pos++;
                return "?";
            }
            if ("?,().=<>+-*/%!|&^~".indexOf(c) >= 0 && !sql.startsWith("*/", pos)) {
                pos++;
                return Character.toString(c);
            }
            return rejectToken(UNSUPPORTED_SYNTAX);
        }

        private String rejectToken(UnavailableReason reason) {
            tokenFailure = reason;
            return null;
        }

        private String quotedToken(UnavailableReason reason, String token) {
            return reason == NONE ? token : rejectToken(reason);
        }

        private boolean signedNumberFollows() {
            if (!digit(at(pos + 1)) && !(at(pos + 1) == '.' && digit(at(pos + 2)))) return false;
            return switch (tokenBytes - previousStart - 1) {
                case 1 -> "(,=<>!+-/*%".indexOf(tokens[previousStart]) >= 0;
                case 2 -> previousIs("or");
                case 3 -> previousIs("and");
                case 4 -> previousIs("when") || previousIs("then") || previousIs("else");
                case 6 -> previousIs("select");
                case 7 -> previousIs("between");
                case 9 -> previousIs("returning");
                default -> false;
            };
        }

        private boolean previousIs(String word) {
            for (int i = 0; i < word.length(); i++) {
                if (tokens[previousStart + i] != word.charAt(i)) return false;
            }
            return true;
        }

        private boolean word() {
            int start = pos++;
            while (wordPart(at(pos))) pos++;
            // Dollar tags must start a distinct token.
            if (at(pos) == '$') {
                tokenFailure = AMBIGUOUS_SYNTAX;
                return false;
            }
            // Administrative SQL and EXEC can accept unquoted credential or argument values.
            // Their boundaries cannot be inferred safely from framework-neutral SQL.
            if (blockedWord(start)) {
                tokenFailure = UNSUPPORTED_SYNTAX;
                return false;
            }
            if (at(pos) == '\'') {
                UnavailableReason reason = prefixedQuote(start);
                if (reason != null) {
                    if (reason != NONE) {
                        tokenFailure = reason;
                        return false;
                    }
                    append("?");
                    return true;
                }
            } else if (wordIs(start, "true") || wordIs(start, "false") || wordIs(start, "null")) {
                append("?");
                return true;
            }
            if (kind == null) kind = classifyWord(start);
            reserveToken(pos - start);
            for (int i = start; i < pos; i++) {
                char c = sql.charAt(i);
                tokens[tokenBytes++] = (byte) (c >= 'A' && c <= 'Z' ? c + ('a' - 'A') : c);
            }
            tokens[tokenBytes++] = ' ';
            return true;
        }

        private boolean wordIs(int start, String word) {
            return pos - start == word.length() && sql.regionMatches(true, start, word, 0, word.length());
        }

        private boolean blockedWord(int start) {
            return switch (pos - start) {
                case 4 -> wordIs(start, "exec");
                case 5 -> wordIs(start, "login");
                case 7 -> wordIs(start, "execute");
                case 8 -> wordIs(start, "password");
                case 10 -> wordIs(start, "identified") || wordIs(start, "credential");
                default -> false;
            };
        }

        // An ordinary word leaves the quote for the next token.
        private UnavailableReason prefixedQuote(int start) {
            if (wordIs(start, "nq")) return oracleQuoted();
            if (pos - start != 1) return null;
            return switch (sql.charAt(start)) {
                case 'q', 'Q' -> oracleQuoted();
                case 'e', 'E' -> quoted('\'', true);
                case 'n', 'N', 'x', 'X', 'b', 'B' -> quoted('\'', false);
                default -> null;
            };
        }

        private StatementKind classifyWord(int start) {
            if (wordIs(start, "select")) return StatementKind.SELECT;
            if (wordIs(start, "insert")) return StatementKind.INSERT;
            if (wordIs(start, "update")) return StatementKind.UPDATE;
            if (wordIs(start, "delete")) return StatementKind.DELETE;
            if (wordIs(start, "merge")) return StatementKind.MERGE;
            if (wordIs(start, "call")) return StatementKind.CALL;
            if (wordIs(start, "create") || wordIs(start, "alter") || wordIs(start, "drop")
                    || wordIs(start, "truncate") || wordIs(start, "rename")) return StatementKind.DDL;
            if (wordIs(start, "with") || wordIs(start, "explain") || wordIs(start, "values")) return StatementKind.OTHER;
            return StatementKind.UNKNOWN;
        }

        private String number() {
            if (sql.regionMatches(true, pos, "0x", 0, 2) || sql.regionMatches(true, pos, "0b", 0, 2)) {
                boolean binary = Character.toLowerCase(at(pos + 1)) == 'b';
                pos += 2;
                int start = pos;
                while (binary ? at(pos) == '0' || at(pos) == '1' : hex(at(pos))) pos++;
                if (start == pos) return rejectToken(MALFORMED_SYNTAX);
            } else {
                while (digit(at(pos))) pos++;
                if (at(pos) == '.') {
                    pos++;
                    while (digit(at(pos))) pos++;
                }
                if (at(pos) == 'e' || at(pos) == 'E') {
                    pos++;
                    if (at(pos) == '+' || at(pos) == '-') pos++;
                    if (!digit(at(pos))) return rejectToken(MALFORMED_SYNTAX);
                    while (digit(at(pos))) pos++;
                }
            }
            return wordPart(at(pos)) || at(pos) == '$' ? rejectToken(MALFORMED_SYNTAX) : "?";
        }

        private UnavailableReason quoted(char close, boolean backslashEscapes) {
            pos++;
            while (pos < sql.length()) {
                char c = sql.charAt(pos++);
                // '[' may also open a subscript expression containing its own quoted tokens.
                if (close == ']' && !wordPart(c) && c != ' ' && c != ']') return AMBIGUOUS_SYNTAX;
                if (c == '\\' && close != ']') {
                    // In an ordinary quoted token, an odd backslash before its delimiter is
                    // mode-dependent. Discard the entire shape instead of guessing its end.
                    if (backslashEscapes || at(pos) == '\\') {
                        if (pos == sql.length()) return MALFORMED_SYNTAX;
                        pos++;
                    } else if (at(pos) == close) {
                        return AMBIGUOUS_SYNTAX;
                    }
                } else if (c == close) {
                    if (at(pos) != close) return NONE;
                    pos++;
                }
            }
            return MALFORMED_SYNTAX;
        }

        private UnavailableReason oracleQuoted() {
            char open = at(pos + 1);
            if (open <= ' ' || open > '~' || open == '\'') return MALFORMED_SYNTAX;
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
                    return NONE;
                }
            }
            return MALFORMED_SYNTAX;
        }

        private String dollar() {
            int start = pos++;
            if (digit(at(pos))) {
                while (digit(at(pos))) pos++;
                return wordPart(at(pos)) || at(pos) == '$' ? rejectToken(AMBIGUOUS_SYNTAX) : "?";
            }
            while (wordPart(at(pos))) {
                if (pos - start > MAX_DOLLAR_TAG) return rejectToken(LEXER_LIMIT);
                pos++;
            }
            if (at(pos) != '$') return rejectToken(UNSUPPORTED_SYNTAX);
            String delimiter = sql.substring(start, ++pos);
            int end = sql.indexOf(delimiter, pos);
            if (end < 0) return rejectToken(MALFORMED_SYNTAX);
            pos = end + delimiter.length();
            return "?";
        }

        private UnavailableReason blockComment() {
            int depth = 0;
            while (pos < sql.length()) {
                if (sql.startsWith("/*", pos)) {
                    pos += 2;
                    if (++depth > MAX_COMMENT_DEPTH) return LEXER_LIMIT;
                    // MySQL and MariaDB executable comments can change what is executed.
                    if (at(pos) == '!' || sql.regionMatches(true, pos, "M!", 0, 2)) return UNSUPPORTED_SYNTAX;
                } else if (sql.startsWith("*/", pos)) {
                    pos += 2;
                    if (--depth == 0) return NONE;
                } else {
                    pos++;
                }
            }
            return MALFORMED_SYNTAX;
        }

        private char at(int index) {
            return index < sql.length() ? sql.charAt(index) : '\0';
        }
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
