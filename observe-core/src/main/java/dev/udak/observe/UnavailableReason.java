package dev.udak.observe;

/** Fixed, SQL-free diagnostic codes for shape normalization coverage. */
public enum UnavailableReason {
    /** The observation has a normalized shape. */
    NONE,
    /** An unavailable observation was supplied without a reason. */
    UNSPECIFIED,
    /** No statement tokens were found. */
    EMPTY_SQL,
    /** The SQL exceeds the length limit. */
    SQL_TOO_LONG,
    /** A statement terminator was followed by more statement input. */
    MULTIPLE_STATEMENTS,
    /** The lexer cannot safely determine a token boundary across dialects. */
    AMBIGUOUS_SYNTAX,
    /** The lexer does not cover a statement or token form. */
    UNSUPPORTED_SYNTAX,
    /** The lexer could not complete a recognized token or balance parentheses. */
    MALFORMED_SYNTAX,
    /** A lexical bound on a delimiter or comment nesting was exceeded. */
    LEXER_LIMIT
}
