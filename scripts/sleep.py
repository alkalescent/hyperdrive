import sys

from hyperdrive.TimeMachine import TimeTraveller

time = sys.argv[1] or "00:00"
traveller = TimeTraveller()

traveller.sleep_until(time)
