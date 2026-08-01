<?php
/**
 * mysql_compat.php
 *
 * Compatibility shim for codebases written against the php5 mysql extension
 * (removed in PHP 7). Maps mysql_*() calls to mysqli_*() and adds polyfills
 * for ereg/eregi/ereg_replace/eregi_replace/split which were also removed.
 *
 * All functions that need a connection fall back to $GLOBALS['link'], which is
 * the variable name used by both dbconnect.php files in this project.
 */

// ── connection helpers ────────────────────────────────────────────────────────

if (!function_exists('mysql_connect')) {
    function mysql_connect($server, $user, $pass, $new_link = false, $client_flags = 0) {
        // Old extension accepted "host:port" as a single string
        $host = $server;
        $port = 3306;
        if (strpos($server, ':') !== false) {
            list($host, $port) = explode(':', $server, 2);
        }
        $conn = mysqli_connect($host, $user, $pass, '', (int)$port);
        return $conn ?: false;
    }
}

if (!function_exists('mysql_pconnect')) {
    function mysql_pconnect($server, $user, $pass) {
        return mysql_connect($server, $user, $pass);
    }
}

if (!function_exists('mysql_select_db')) {
    function mysql_select_db($db, $conn = null) {
        if ($conn === null) $conn = $GLOBALS['link'];
        return mysqli_select_db($conn, $db);
    }
}

if (!function_exists('mysql_close')) {
    function mysql_close($conn = null) {
        if ($conn === null) $conn = $GLOBALS['link'];
        return mysqli_close($conn);
    }
}

// ── error reporting ───────────────────────────────────────────────────────────

if (!function_exists('mysql_error')) {
    function mysql_error($conn = null) {
        if ($conn === null) $conn = isset($GLOBALS['link']) ? $GLOBALS['link'] : null;
        if (!$conn) return mysqli_connect_error() ?: '';
        return mysqli_error($conn);
    }
}

if (!function_exists('mysql_errno')) {
    function mysql_errno($conn = null) {
        if ($conn === null) $conn = isset($GLOBALS['link']) ? $GLOBALS['link'] : null;
        if (!$conn) return mysqli_connect_errno() ?: 0;
        return mysqli_errno($conn);
    }
}

// ── queries ───────────────────────────────────────────────────────────────────

if (!function_exists('mysql_query')) {
    function mysql_query($sql, $conn = null) {
        if ($conn === null) $conn = $GLOBALS['link'];
        return mysqli_query($conn, $sql);
    }
}

if (!function_exists('mysql_unbuffered_query')) {
    function mysql_unbuffered_query($sql, $conn = null) {
        if ($conn === null) $conn = $GLOBALS['link'];
        return mysqli_query($conn, $sql, MYSQLI_USE_RESULT);
    }
}

// ── result fetch ──────────────────────────────────────────────────────────────

if (!function_exists('mysql_fetch_array')) {
    function mysql_fetch_array($result, $type = MYSQLI_BOTH) {
        return mysqli_fetch_array($result, $type);
    }
}

if (!function_exists('mysql_fetch_row')) {
    function mysql_fetch_row($result) {
        return mysqli_fetch_row($result);
    }
}

if (!function_exists('mysql_fetch_assoc')) {
    function mysql_fetch_assoc($result) {
        return mysqli_fetch_assoc($result);
    }
}

if (!function_exists('mysql_fetch_object')) {
    function mysql_fetch_object($result) {
        return mysqli_fetch_object($result);
    }
}

// ── result metadata ───────────────────────────────────────────────────────────

if (!function_exists('mysql_num_rows')) {
    function mysql_num_rows($result) {
        return mysqli_num_rows($result);
    }
}

if (!function_exists('mysql_num_fields')) {
    function mysql_num_fields($result) {
        return mysqli_num_fields($result);
    }
}

if (!function_exists('mysql_field_name')) {
    function mysql_field_name($result, $field_offset) {
        $fields = mysqli_fetch_fields($result);
        return isset($fields[$field_offset]) ? $fields[$field_offset]->name : false;
    }
}

if (!function_exists('mysql_field_type')) {
    function mysql_field_type($result, $field_offset) {
        $fields = mysqli_fetch_fields($result);
        if (!isset($fields[$field_offset])) return false;
        $type_map = [
            MYSQLI_TYPE_DECIMAL     => 'real',
            MYSQLI_TYPE_TINY        => 'int',
            MYSQLI_TYPE_SHORT       => 'int',
            MYSQLI_TYPE_LONG        => 'int',
            MYSQLI_TYPE_FLOAT       => 'real',
            MYSQLI_TYPE_DOUBLE      => 'real',
            MYSQLI_TYPE_TIMESTAMP   => 'timestamp',
            MYSQLI_TYPE_LONGLONG    => 'int',
            MYSQLI_TYPE_INT24       => 'int',
            MYSQLI_TYPE_DATE        => 'date',
            MYSQLI_TYPE_TIME        => 'time',
            MYSQLI_TYPE_DATETIME    => 'datetime',
            MYSQLI_TYPE_YEAR        => 'year',
            MYSQLI_TYPE_NEWDATE     => 'date',
            MYSQLI_TYPE_ENUM        => 'unknown',
            MYSQLI_TYPE_SET         => 'unknown',
            MYSQLI_TYPE_TINY_BLOB   => 'blob',
            MYSQLI_TYPE_MEDIUM_BLOB => 'blob',
            MYSQLI_TYPE_LONG_BLOB   => 'blob',
            MYSQLI_TYPE_BLOB        => 'blob',
            MYSQLI_TYPE_VAR_STRING  => 'string',
            MYSQLI_TYPE_STRING      => 'string',
            MYSQLI_TYPE_CHAR        => 'string',
            MYSQLI_TYPE_GEOMETRY    => 'unknown',
            MYSQLI_TYPE_NULL        => 'null',
        ];
        return $type_map[$fields[$field_offset]->type] ?? 'unknown';
    }
}

if (!function_exists('mysql_field_len')) {
    function mysql_field_len($result, $field_offset) {
        $fields = mysqli_fetch_fields($result);
        return isset($fields[$field_offset]) ? $fields[$field_offset]->length : false;
    }
}

if (!function_exists('mysql_result')) {
    function mysql_result($result, $row, $field = 0) {
        mysqli_data_seek($result, $row);
        $data = mysqli_fetch_array($result);
        return isset($data[$field]) ? $data[$field] : null;
    }
}

if (!function_exists('mysql_data_seek')) {
    function mysql_data_seek($result, $row) {
        return mysqli_data_seek($result, $row);
    }
}

if (!function_exists('mysql_free_result')) {
    function mysql_free_result($result) {
        return mysqli_free_result($result);
    }
}

// ── write helpers ─────────────────────────────────────────────────────────────

if (!function_exists('mysql_affected_rows')) {
    function mysql_affected_rows($conn = null) {
        if ($conn === null) $conn = $GLOBALS['link'];
        return mysqli_affected_rows($conn);
    }
}

if (!function_exists('mysql_insert_id')) {
    function mysql_insert_id($conn = null) {
        if ($conn === null) $conn = $GLOBALS['link'];
        return mysqli_insert_id($conn);
    }
}

if (!function_exists('mysql_real_escape_string')) {
    function mysql_real_escape_string($str, $conn = null) {
        if ($conn === null) $conn = $GLOBALS['link'];
        return mysqli_real_escape_string($conn, $str);
    }
}

if (!function_exists('mysql_escape_string')) {
    function mysql_escape_string($str) {
        return mysql_real_escape_string($str);
    }
}

// ── database/table listing ────────────────────────────────────────────────────

if (!function_exists('mysql_list_tables')) {
    function mysql_list_tables($db, $conn = null) {
        if ($conn === null) $conn = $GLOBALS['link'];
        return mysqli_query($conn, "SHOW TABLES FROM `" . mysqli_real_escape_string($conn, $db) . "`");
    }
}

if (!function_exists('mysql_list_dbs')) {
    function mysql_list_dbs($conn = null) {
        if ($conn === null) $conn = $GLOBALS['link'];
        return mysqli_query($conn, "SHOW DATABASES");
    }
}

if (!function_exists('mysql_get_server_info')) {
    function mysql_get_server_info($conn = null) {
        if ($conn === null) $conn = $GLOBALS['link'];
        return mysqli_get_server_info($conn);
    }
}

if (!function_exists('mysql_get_client_info')) {
    function mysql_get_client_info() {
        return mysqli_get_client_info();
    }
}

// ── POSIX regex functions removed in PHP 7 ────────────────────────────────────

if (!function_exists('ereg')) {
    function ereg($pattern, $string, &$regs = null) {
        $pattern = '/' . str_replace('/', '\\/', $pattern) . '/';
        $result  = preg_match($pattern, $string, $matches);
        if ($regs !== null) $regs = $matches;
        return $result ? strlen($matches[0]) : false;
    }
}

if (!function_exists('eregi')) {
    function eregi($pattern, $string, &$regs = null) {
        $pattern = '/' . str_replace('/', '\\/', $pattern) . '/i';
        $result  = preg_match($pattern, $string, $matches);
        if ($regs !== null) $regs = $matches;
        return $result ? strlen($matches[0]) : false;
    }
}

if (!function_exists('ereg_replace')) {
    function ereg_replace($pattern, $replacement, $string) {
        return preg_replace('/' . str_replace('/', '\\/', $pattern) . '/', $replacement, $string);
    }
}

if (!function_exists('eregi_replace')) {
    function eregi_replace($pattern, $replacement, $string) {
        return preg_replace('/' . str_replace('/', '\\/', $pattern) . '/i', $replacement, $string);
    }
}

if (!function_exists('split')) {
    function split($pattern, $string, $limit = -1) {
        return preg_split('/' . str_replace('/', '\\/', $pattern) . '/', $string, $limit);
    }
}
