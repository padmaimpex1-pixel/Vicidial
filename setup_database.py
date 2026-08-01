"""
setup_database.py
=================
One-shot setup script for VICIdial on Windows.

Steps performed:
  1. Install MySQL 8 via winget (if not already installed)
  2. Start the MySQL service
  3. Locate mysql.exe / mysqladmin.exe on PATH or known install dirs
  4. Discover / reset the root password from the MySQL error log
  5. Create database  : asterisk
  6. Create DB user   : cron  (password: 1234)
  7. Grant privileges
  8. Import schema    : extras/MySQL_AST_CREATE_tables.sql
  9. Import seed data : extras/first_server_install.sql
 10. Patch both www/agc/dbconnect.php and www/vicidial/dbconnect.php
     with the chosen credentials
 11. Verify the connection via PHP CLI

Run as Administrator for service management:
    python setup_database.py

Optional flags:
    --db-name   NAME     (default: asterisk)
    --db-user   USER     (default: cron)
    --db-pass   PASS     (default: 1234)
    --db-port   PORT     (default: 3306)
    --root-pass PASS     root password (auto-detected when omitted)
    --skip-install       skip winget install step
    --skip-import        skip SQL import step
"""

import argparse
import glob
import os
import re
import subprocess
import sys
import time
import winreg

# ── helpers ───────────────────────────────────────────────────────────────────

def log(msg):
    print(f"[setup] {msg}")

def run(cmd, *, check=True, capture=False, input_text=None, timeout=120):
    """Run a command; return CompletedProcess."""
    kwargs = dict(
        shell=True,
        capture_output=capture,
        text=True,
        timeout=timeout,
    )
    if input_text is not None:
        kwargs["input"] = input_text
    try:
        result = subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Command timed out ({timeout}s): {cmd}")
    if check and result.returncode != 0:
        # MySQL CLI exits 1 on warnings too; treat it as failure only when
        # stderr contains an actual ERROR line (not just a Warning).
        combined = (result.stderr or "") + (result.stdout or "")
        if result.returncode != 1 or re.search(r'\bERROR\b', combined):
            raise RuntimeError(
                f"Command failed (exit {result.returncode}):\n{cmd}\n"
                + combined
            )
    return result

def run_sql(mysql_bin, user, password, host, port, sql, database=""):
    """Execute a SQL string via mysql CLI."""
    db_arg = f' "{database}"' if database else ""
    cmd = (
        f'"{mysql_bin}" -h {host} -P {port} -u {user}'
        f' --password="{password}" --connect-timeout=10'
        f' -e "{sql}"{db_arg}'
    )
    return run(cmd, capture=True)

def run_sql_file(mysql_bin, user, password, host, port, sql_file, database=""):
    """Execute a SQL file via mysql CLI.

    Preprocesses the file to backtick-quote MySQL 8 reserved words used as
    column/index names (rank, groups, etc.) then imports with --force so that
    minor compatibility warnings don't abort the whole import.
    """
    # Reserved words that appear as bare identifiers in the legacy schema
    RESERVED = {"rank", "groups", "rows", "system", "interval", "function",
                "values", "leading", "condition", "release", "status"}

    with open(sql_file, "r", encoding="utf-8", errors="ignore") as f:
        sql_content = f.read()

    # Wrap bare reserved words that appear as column/index names.
    # Matches:  word<whitespace>  at start of a definition line, OR
    #           index (word)  patterns — only when not already backtick-quoted.
    def quote_reserved(text):
        for word in RESERVED:
            # column definition: "  rank SMALLINT" -> "  `rank` SMALLINT"
            text = re.sub(
                rf'(?<![`\w]){word}(?![`\w])',
                f'`{word}`',
                text,
                flags=re.IGNORECASE,
            )
        return text

    patched = quote_reserved(sql_content)

    # Write to a temp file
    import tempfile
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".sql", delete=False, encoding="utf-8"
    )
    tmp.write(patched)
    tmp.close()

    db_arg = f' "{database}"' if database else ""
    cmd = (
        f'"{mysql_bin}" -h {host} -P {port} -u {user}'
        f' --password="{password}" --connect-timeout=10 --force'
        f'{db_arg} < "{tmp.name}"'
    )
    try:
        return run(cmd, capture=True)
    finally:
        os.unlink(tmp.name)

# ── step 1: ensure MySQL is installed ─────────────────────────────────────────

MYSQL_WINGET_ID = "Oracle.MySQL"

def is_mysql_installed():
    """Return True if mysqld.exe is findable."""
    candidates = find_mysql_bin_dir()
    return candidates is not None

def find_mysql_bin_dir():
    """Search registry + common paths for MySQL bin dir. Returns path or None."""
    # Registry search
    for hive in (winreg.HKEY_LOCAL_MACHINE,):
        for subkey in (
            r"SOFTWARE\MySQL AB",
            r"SOFTWARE\WOW6432Node\MySQL AB",
            r"SOFTWARE\Oracle\MySQL Server 8.0",
            r"SOFTWARE\Oracle\MySQL Server 8.4",
            r"SOFTWARE\WOW6432Node\Oracle\MySQL Server 8.0",
            r"SOFTWARE\WOW6432Node\Oracle\MySQL Server 8.4",
        ):
            try:
                key = winreg.OpenKey(hive, subkey)
                loc, _ = winreg.QueryValueEx(key, "Location")
                candidate = os.path.join(loc, "bin")
                if os.path.isfile(os.path.join(candidate, "mysql.exe")):
                    return candidate
            except (FileNotFoundError, OSError):
                pass

    # Common filesystem locations
    for base in (
        r"C:\Program Files\MySQL",
        r"C:\Program Files (x86)\MySQL",
        r"C:\MySQL",
    ):
        for entry in sorted(glob.glob(os.path.join(base, "MySQL Server *")), reverse=True):
            candidate = os.path.join(entry, "bin")
            if os.path.isfile(os.path.join(candidate, "mysql.exe")):
                return candidate

    # PATH
    result = subprocess.run("where mysql.exe", shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        return os.path.dirname(result.stdout.strip().splitlines()[0])

    return None

def install_mysql_via_winget():
    log("Installing MySQL 8 via winget (this may take a few minutes)…")
    run(
        f'winget install --id {MYSQL_WINGET_ID} --silent --accept-package-agreements'
        ' --accept-source-agreements',
        timeout=600,
    )
    log("winget install finished.")

# ── step 2: start service ─────────────────────────────────────────────────────

def get_mysql_service_name():
    result = subprocess.run(
        'sc query type= all state= all | findstr /i "mysql"',
        shell=True, capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        m = re.search(r"SERVICE_NAME:\s*(\S+)", line, re.IGNORECASE)
        if m:
            return m.group(1)
    return None

def ensure_mysql_service_running():
    svc = get_mysql_service_name()
    if not svc:
        log("No MySQL service found; MySQL may have been installed without a service. Continuing.")
        return
    result = subprocess.run(f'sc query "{svc}"', shell=True, capture_output=True, text=True)
    if "RUNNING" in result.stdout:
        log(f"MySQL service '{svc}' is already running.")
        return
    log(f"Starting MySQL service '{svc}'…")
    run(f'net start "{svc}"')
    for _ in range(30):
        time.sleep(2)
        r = subprocess.run(f'sc query "{svc}"', shell=True, capture_output=True, text=True)
        if "RUNNING" in r.stdout:
            log("MySQL service is running.")
            return
    raise RuntimeError("MySQL service did not reach RUNNING state within 60 seconds.")

# ── step 3 & 4: locate binaries & discover root password ──────────────────────

def find_mysql_error_log():
    """Find the MySQL error log that contains the temporary root password."""
    data_dirs = []
    # Registry
    for hive in (winreg.HKEY_LOCAL_MACHINE,):
        for subkey in (
            r"SOFTWARE\Oracle\MySQL Server 8.0",
            r"SOFTWARE\Oracle\MySQL Server 8.4",
            r"SOFTWARE\WOW6432Node\Oracle\MySQL Server 8.0",
            r"SOFTWARE\WOW6432Node\Oracle\MySQL Server 8.4",
        ):
            try:
                key = winreg.OpenKey(hive, subkey)
                datadir, _ = winreg.QueryValueEx(key, "DataLocation")
                data_dirs.append(datadir)
            except (FileNotFoundError, OSError):
                pass
    # Common defaults
    programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    for pattern in (
        os.path.join(programdata, "MySQL", "MySQL Server *", "Data"),
        r"C:\ProgramData\MySQL\MySQL Server *\Data",
    ):
        data_dirs.extend(glob.glob(pattern))
    for data_dir in data_dirs:
        for fname in glob.glob(os.path.join(data_dir, "*.err")):
            return fname
    return None

def read_temp_root_password(log_path):
    """Parse the temporary root password from the MySQL error log."""
    try:
        with open(log_path, "r", errors="ignore") as f:
            for line in f:
                m = re.search(r"temporary password.*root@localhost:\s*(\S+)", line, re.IGNORECASE)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return None

def probe_root_password(mysql_bin, host, port, candidates):
    """Try each password candidate; return the first that connects."""
    for pwd in candidates:
        result = subprocess.run(
            f'"{mysql_bin}" -h {host} -P {port} -u root --password="{pwd}"'
            ' --connect-timeout=5 -e "SELECT 1;" mysql',
            shell=True, capture_output=True, text=True
        )
        if result.returncode == 0:
            return pwd
    return None

# ── step 5-7: database + user ─────────────────────────────────────────────────

def setup_database(mysql_bin, root_pass, host, port, db_name, db_user, db_pass):
    log(f"Creating database '{db_name}' and user '{db_user}'…")
    sql = (
        f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
        f"CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci; "
        f"CREATE USER IF NOT EXISTS '{db_user}'@'{host}' IDENTIFIED BY '{db_pass}'; "
        f"CREATE USER IF NOT EXISTS '{db_user}'@'localhost' IDENTIFIED BY '{db_pass}'; "
        f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'{host}'; "
        f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'localhost'; "
        f"FLUSH PRIVILEGES;"
    )
    run_sql(mysql_bin, "root", root_pass, host, port, sql)
    log("Database and user created.")

# ── steps 8-9: import SQL ──────────────────────────────────────────────────────

def import_sql_files(mysql_bin, db_user, db_pass, host, port, db_name, repo_root):
    schema_file = os.path.join(repo_root, "extras", "MySQL_AST_CREATE_tables.sql")
    seed_file   = os.path.join(repo_root, "extras", "first_server_install.sql")

    log(f"Importing schema: {schema_file}")
    run_sql_file(mysql_bin, db_user, db_pass, host, port, schema_file, db_name)
    log("Schema imported.")

    log(f"Importing seed data: {seed_file}")
    run_sql_file(mysql_bin, db_user, db_pass, host, port, seed_file, db_name)
    log("Seed data imported.")

# ── step 10: patch dbconnect.php files ────────────────────────────────────────

DBCONNECT_FILES = [
    os.path.join("www", "agc", "dbconnect.php"),
    os.path.join("www", "vicidial", "dbconnect.php"),
]

def patch_dbconnect(repo_root, host, port, db_name, db_user, db_pass):
    replacements = {
        r"(\$VARDB_server\s*=\s*')[^']*(')"  : rf"\g<1>{host}\g<2>",
        r"(\$VARDB_port\s*=\s*')[^']*(')"    : rf"\g<1>{port}\g<2>",
        r"(\$VARDB_user\s*=\s*')[^']*(')"    : rf"\g<1>{db_user}\g<2>",
        r"(\$VARDB_pass\s*=\s*')[^']*(')"    : rf"\g<1>{db_pass}\g<2>",
        r"(\$VARDB_database\s*=\s*')[^']*(')" : rf"\g<1>{db_name}\g<2>",
    }
    for rel_path in DBCONNECT_FILES:
        full_path = os.path.join(repo_root, rel_path)
        if not os.path.isfile(full_path):
            log(f"  WARNING: {full_path} not found, skipping.")
            continue
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        patched = content
        for pattern, repl in replacements.items():
            patched = re.sub(pattern, repl, patched)
        if patched != content:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(patched)
            log(f"  Patched: {full_path}")
        else:
            log(f"  Already correct (or no defaults block found): {full_path}")

# ── step 11: verify via PHP CLI ───────────────────────────────────────────────

def verify_php_connection(repo_root, host, port, db_name, db_user, db_pass):
    php_snippet = (
        "<?php "
        f"$c = mysqli_connect('{host}', '{db_user}', '{db_pass}', '{db_name}', {port}); "
        "if (!$c) { echo 'FAIL: '.mysqli_connect_error(); exit(1); } "
        "$r = mysqli_query($c, 'SHOW TABLES'); "
        "echo 'OK: '.mysqli_num_rows($r).' tables found.'; "
        "?>"
    )
    tmp = os.path.join(repo_root, "_db_verify.php")
    with open(tmp, "w") as f:
        f.write(php_snippet)
    try:
        result = subprocess.run(f'php "{tmp}"', shell=True, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            log(f"PHP verification: {result.stdout.strip()}")
        else:
            log(f"PHP verification FAILED: {result.stdout.strip()} {result.stderr.strip()}")
    finally:
        os.remove(tmp)

# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="VICIdial database setup script")
    parser.add_argument("--db-name",      default="asterisk",  help="Database name (default: asterisk)")
    parser.add_argument("--db-user",      default="cron",      help="DB username   (default: cron)")
    parser.add_argument("--db-pass",      default="1234",      help="DB password   (default: 1234)")
    parser.add_argument("--db-port",      default="3306",      help="MySQL port    (default: 3306)")
    parser.add_argument("--db-host",      default="localhost", help="MySQL host    (default: localhost)")
    parser.add_argument("--root-pass",    default=None,        help="MySQL root password (auto-detected)")
    parser.add_argument("--skip-install", action="store_true", help="Skip winget install")
    parser.add_argument("--skip-import",  action="store_true", help="Skip SQL import")
    args = parser.parse_args()

    repo_root = os.path.dirname(os.path.abspath(__file__))
    log(f"Repository root: {repo_root}")

    # ── 1. Install MySQL ──────────────────────────────────────────────────────
    if args.skip_install:
        log("Skipping MySQL installation (--skip-install).")
    elif is_mysql_installed():
        log("MySQL binaries already detected; skipping install.")
    else:
        install_mysql_via_winget()
        # Give the installer a moment to register paths
        time.sleep(5)

    # ── 2. Locate binaries ────────────────────────────────────────────────────
    bin_dir = find_mysql_bin_dir()
    if not bin_dir:
        sys.exit(
            "[setup] ERROR: Could not locate mysql.exe. "
            "Ensure MySQL is installed and its bin directory is on PATH."
        )
    mysql_bin   = os.path.join(bin_dir, "mysql.exe")
    mysqladmin  = os.path.join(bin_dir, "mysqladmin.exe")
    log(f"MySQL binaries: {bin_dir}")

    # ── 3. Start service ──────────────────────────────────────────────────────
    ensure_mysql_service_running()
    # Brief pause for socket readiness
    time.sleep(2)

    # ── 4. Discover root password ─────────────────────────────────────────────
    root_pass = args.root_pass
    if root_pass is None:
        log("Attempting to auto-detect MySQL root password…")
        candidates = [""]  # try blank first (already-configured installs)
        err_log = find_mysql_error_log()
        if err_log:
            log(f"  Found error log: {err_log}")
            tmp_pwd = read_temp_root_password(err_log)
            if tmp_pwd:
                log("  Found temporary root password in error log.")
                candidates.insert(0, tmp_pwd)
        root_pass = probe_root_password(mysql_bin, args.db_host, args.db_port, candidates)
        if root_pass is None:
            sys.exit(
                "[setup] ERROR: Could not connect as root with any detected password.\n"
                "Re-run with:  python setup_database.py --root-pass YOUR_PASSWORD\n"
                "Or if this is a fresh winget install, check the MySQL error log for\n"
                "the temporary password (search for 'temporary password' in the log)."
            )
        if root_pass == "":
            log("  Connected with empty root password.")
        else:
            log("  Root password resolved.")

        # If connected with temp password, reset it to something we know
        if root_pass and root_pass != (args.root_pass or ""):
            new_root = "ViciAdmin2024!"
            log(f"  Resetting temporary root password to '{new_root}'…")
            reset_sql = (
                f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{new_root}'; "
                f"FLUSH PRIVILEGES;"
            )
            # Use --connect-expired-password so ALTER USER works on expired creds
            reset_cmd = (
                f'"{mysql_bin}" -h {args.db_host} -P {args.db_port} -u root '
                f'--password="{root_pass}" --connect-expired-password '
                f'-e "{reset_sql}" mysql'
            )
            r = subprocess.run(reset_cmd, shell=True, capture_output=True, text=True)
            if r.returncode == 0:
                root_pass = new_root
                log(f"  Root password is now: {new_root}")
            else:
                log(f"  Could not reset root password (may already be valid): {r.stderr.strip()}")

    # ── 5-7. Create database and user ─────────────────────────────────────────
    setup_database(
        mysql_bin, root_pass,
        args.db_host, args.db_port,
        args.db_name, args.db_user, args.db_pass,
    )

    # ── 8-9. Import SQL files ─────────────────────────────────────────────────
    if args.skip_import:
        log("Skipping SQL import (--skip-import).")
    else:
        import_sql_files(
            mysql_bin, args.db_user, args.db_pass,
            args.db_host, args.db_port,
            args.db_name, repo_root,
        )

    # ── 10. Patch dbconnect.php ───────────────────────────────────────────────
    log("Patching dbconnect.php files…")
    patch_dbconnect(
        repo_root,
        args.db_host, args.db_port,
        args.db_name, args.db_user, args.db_pass,
    )

    # ── 11. PHP sanity check ──────────────────────────────────────────────────
    log("Running PHP connection verification…")
    verify_php_connection(
        repo_root,
        args.db_host, args.db_port,
        args.db_name, args.db_user, args.db_pass,
    )

    log("")
    log("=" * 60)
    log("Setup complete!")
    log(f"  Database : {args.db_name}")
    log(f"  User     : {args.db_user} / {args.db_pass}")
    log(f"  Host     : {args.db_host}:{args.db_port}")
    log("")
    log("Start the PHP server (if not already running):")
    log(f'  php -S 127.0.0.1:8000 -t "{os.path.join(repo_root, "www")}"')
    log("")
    log("Then open:  http://127.0.0.1:8000/vicidial/welcome.php")
    log("  Agent login: http://127.0.0.1:8000/agc/vicidial.php")
    log("  Admin:       http://127.0.0.1:8000/vicidial/admin.php")
    log("  Default admin credentials: user=6666  pass=1234")
    log("=" * 60)

if __name__ == "__main__":
    main()
