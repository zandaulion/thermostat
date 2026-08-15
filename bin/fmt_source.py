"""Render a newly registered push source. Reads JSON on stdin.

The token is shown once -- only its hash is stored -- so it is printed with
the URL already assembled.
"""
import json
import sys

d = json.load(sys.stdin)
print()
print(f"  source #{d['id']}  {d['name']}  ->  {d['location']}")
print(f"  token: {d['token']}")
print()
print("  Point the sensor at this URL. On a Shelly, Settings -> Actions,")
print("  and substitute its own placeholders for the values:")
print()
print(f"    {d['example_url']}")
print()
print("  The token is a bearer secret for this one sensor: it can be revoked")
print("  on its own, and it is shown here once only.")
