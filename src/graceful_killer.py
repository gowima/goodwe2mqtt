# -*- coding: utf-8 -*-
"""
Found in the net.

If GracefulKiller.kill_now is True, then a signal has been catched.
How to use e.g.:
    killer = GracefulKiller()
    while not killer.kill_now:
        ... do something
    tidy up and exit
"""
import signal


# -- signal handling ----------------------------------------------------------
class GracefulKiller:
    kill_now = False

    def __init__(self):
        # catch these signals and set kill_now to True
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, *args):
        self.kill_now = True
