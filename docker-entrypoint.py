import os
import pwd
import sys
from pathlib import Path


data_directory = Path("/app/data")
data_directory.mkdir(parents=True, exist_ok=True)
if os.getuid() == 0:
    user = pwd.getpwnam("planner")
    # Bind mounts may be root-owned on first run; only adjust this app's files.
    for path in [data_directory, *(data_directory / name for name in (
        "holidays.db", "holidays.db-wal", "holidays.db-shm", "holidays.db-journal",
    ))]:
        if path.exists():
            os.chown(path, user.pw_uid, user.pw_gid, follow_symlinks=False)
    os.setgroups([])
    os.setgid(user.pw_gid)
    os.setuid(user.pw_uid)
os.umask(0o077)
os.execvp(sys.argv[1], sys.argv[1:])
