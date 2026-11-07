"""Launch the backend-owned API command, once its implementation is available."""
import os
import shlex


def main():
    command = shlex.split(os.environ.get('STEPMETER_API_COMMAND', ''))
    if not command:
        raise SystemExit('API implementation is not supplied: set STEPMETER_API_COMMAND to the backend launch command (bind 0.0.0.0:8000). See infra/m2.md.')
    os.execvpe(command[0], command, os.environ)


if __name__ == '__main__':
    main()
