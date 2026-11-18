"""Export-only child: run the real read-only UI at a fixed fictional time."""
import argparse
import json
import runpy
import subprocess
import sys
import time
from pathlib import Path

from freezegun import freeze_time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--factory', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--at', required=True)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    time.tzset()
    entry = args.factory / 'bin/factory'
    sys.argv = [str(entry), 'serve', '--bind', '127.0.0.1', '--port', str(args.port)]
    timers = {name: getattr(time, name) for name in
              ('monotonic', 'monotonic_ns', 'perf_counter', 'perf_counter_ns')}
    wait_clock = subprocess._time
    # Keep this clock inside the isolated child; build timeouts use the real clock.
    with freeze_time(args.at):
        for name, fn in timers.items():
            setattr(time, name, fn)
        subprocess._time = wait_clock
        sys.path.insert(0, str(args.factory))
        from web.tokens import TokenIndex
        from web.views import agents, home, resources
        # A fixed sample needs one complete scan before the first HTTP response.
        TokenIndex.start_background = lambda self, interval=60: self.refresh()
        # Host telemetry must describe the fictional sample, not the CI runner.
        machine = json.loads(args.config.read_text())['machine']
        resources.machine = lambda: dict(machine)
        home.machine = resources.machine
        agents.proc_snapshot = lambda: None
        runpy.run_path(str(entry), run_name='__main__')


if __name__ == '__main__':
    main()
